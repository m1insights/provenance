from __future__ import annotations

from datetime import datetime, timedelta, timezone
from enum import Enum

import pytest
from google.genai.errors import ClientError
from pydantic import BaseModel, ValidationError

from provenance.backlog import select_for_appraisal
from provenance.llm import is_quota_error
from provenance.models import Paper
from provenance.store import firestore as store


class QueueDocument:
    def __init__(self, doc_id: str, payload: dict):
        self.id = doc_id
        self._payload = payload

    def to_dict(self) -> dict:
        return self._payload


class QueueCollection:
    def __init__(self, documents: list[QueueDocument]):
        self._documents = documents

    def select(self, _fields: list) -> QueueCollection:
        return self

    def stream(self):
        return iter(self._documents)


class QueueDb:
    def __init__(
        self,
        *,
        papers: list[QueueDocument],
        appraisals: list[QueueDocument],
        rejections: list[QueueDocument],
    ):
        self._collections = {
            store.PAPERS: QueueCollection(papers),
            store.APPRAISALS: QueueCollection(appraisals),
            store.REJECTIONS: QueueCollection(rejections),
        }

    def collection(self, name: str) -> QueueCollection:
        return self._collections[name]


def doc(doc_id: str, payload: dict) -> QueueDocument:
    return QueueDocument(doc_id, payload)


def paper_doc(
    doc_id: str, *, retrieved_at: datetime | None = None
) -> QueueDocument:
    payload = {
        "doc_id": doc_id,
        "source": "pubmed",
        "title": doc_id,
    }
    if retrieved_at is not None:
        payload["retrieved_at"] = retrieved_at.isoformat()
    return doc(doc_id, payload)


def papers(prefix: str, count: int, *, start_day: int) -> list[Paper]:
    return [
        Paper(
            doc_id=f"{prefix}-{index}",
            source="pubmed",
            title=f"{prefix} paper {index}",
            retrieved_at=datetime(2026, 1, start_day, tzinfo=timezone.utc)
            + timedelta(minutes=index),
        )
        for index in range(count)
    ]


class StatusError(Exception):
    def __init__(self, status_code: int):
        self.status_code = status_code

    def __str__(self) -> str:
        return "provider request failed"


class StatusCode(Enum):
    RESOURCE_EXHAUSTED = "RESOURCE_EXHAUSTED"


class CodeError(Exception):
    def __init__(self, code: str | StatusCode):
        self._code = code

    def code(self) -> str | StatusCode:
        return self._code

    def __str__(self) -> str:
        return "provider request failed"


class DirectCodeError(Exception):
    def __init__(self, code: int | str):
        self.code = code

    def __str__(self) -> str:
        return "provider request failed"


class StatusValueError(Exception):
    def __init__(self, status: str | StatusCode):
        self.status = status

    def __str__(self) -> str:
        return "provider request failed"


class ParticipantRecord(BaseModel):
    participants: int


def test_old_paper_documents_default_to_untriaged():
    """Legacy Firestore documents retain a usable untriaged queue state."""
    paper = Paper.model_validate({
        "doc_id": "paper-1", "source": "pubmed", "title": "Old record"
    })

    assert paper.triaged_at is None
    assert paper.triage_agenda_digest == ""


def test_pending_papers_exclude_appraised_and_rejected_records():
    """Only records without an appraisal or rejection payload remain pending."""
    db = QueueDb(
        papers=[paper_doc("pending"), paper_doc("appraised"), paper_doc("rejected")],
        appraisals=[doc("appraised", {})],
        rejections=[doc("opaque-firestore-id", {"paper_id": "rejected"})],
    )

    assert [paper.doc_id for paper in store.pending_papers(db=db)] == ["pending"]


def test_pending_papers_order_by_retrieval_time_then_document_id():
    """Queue order is stable even when Firestore streams documents arbitrarily."""
    early = datetime(2026, 1, 1, tzinfo=timezone.utc)
    tied = datetime(2026, 1, 2, tzinfo=timezone.utc)
    late = datetime(2026, 1, 3, tzinfo=timezone.utc)
    db = QueueDb(
        papers=[
            paper_doc("late", retrieved_at=late),
            paper_doc("tie-b", retrieved_at=tied),
            paper_doc("early", retrieved_at=early),
            paper_doc("tie-a", retrieved_at=tied),
        ],
        appraisals=[],
        rejections=[],
    )

    assert [paper.doc_id for paper in store.pending_papers(db=db)] == [
        "early",
        "tie-a",
        "tie-b",
        "late",
    ]


def test_selection_shares_ten_slots_between_new_and_old():
    """A sustained backlog cannot be starved by a busy retrieval day."""
    old = papers("old", 8, start_day=1)
    new = papers("new", 8, start_day=20)

    selected = select_for_appraisal(
        old + new, new_ids={paper.doc_id for paper in new}, limit=10
    )

    assert len(selected) == 10
    assert sum(paper.doc_id.startswith("new") for paper in selected) == 5
    assert [paper.doc_id for paper in selected if paper.doc_id.startswith("old")] == [
        "old-0", "old-1", "old-2", "old-3", "old-4"
    ]


def test_selection_interleaves_old_and_new_in_the_first_appraisal_wave():
    """A quota failure in wave one cannot repeatedly starve all new work."""
    old = papers("old", 8, start_day=1)
    new = papers("new", 8, start_day=20)

    selected = select_for_appraisal(
        old + new, new_ids={paper.doc_id for paper in new}, limit=10
    )

    assert [paper.doc_id for paper in selected[:3]] == ["old-0", "new-0", "old-1"]
    assert any(paper.doc_id.startswith("old") for paper in selected[:3])
    assert any(paper.doc_id.startswith("new") for paper in selected[:3])


def test_selection_lends_unused_new_slots_to_backlog():
    """Unused new-work capacity is available to an existing backlog."""
    old = papers("old", 12, start_day=1)

    assert len(select_for_appraisal(old, new_ids=set(), limit=10)) == 10


def test_selection_lends_unused_backlog_slots_to_new_papers():
    """A small backlog does not strand capacity needed by fresh retrievals."""
    old = papers("old", 2, start_day=1)
    new = papers("new", 12, start_day=20)

    selected = select_for_appraisal(
        old + new, new_ids={paper.doc_id for paper in new}, limit=10
    )

    assert len(selected) == 10
    assert sum(paper.doc_id.startswith("old") for paper in selected) == 2
    assert sum(paper.doc_id.startswith("new") for paper in selected) == 8


def test_selection_deduplicates_papers_without_changing_cohort_order():
    """Duplicate candidates cannot consume more than one appraisal slot."""
    old = papers("old", 2, start_day=1)
    new = papers("new", 2, start_day=20)

    selected = select_for_appraisal(
        [old[0], new[0], old[0], new[1], old[1]],
        new_ids={paper.doc_id for paper in new},
        limit=10,
    )

    assert [paper.doc_id for paper in selected] == [
        "old-0",
        "new-0",
        "old-1",
        "new-1",
    ]


def test_selection_returns_nothing_when_limit_is_zero():
    """The cap is strict even when papers are available."""
    assert select_for_appraisal(papers("old", 1, start_day=1), new_ids=set(), limit=0) == []


def test_selection_resolves_retrieval_ties_by_document_id():
    """Equivalent timestamps retain a reproducible ordering."""
    retrieved_at = datetime(2026, 1, 1, tzinfo=timezone.utc)
    papers_with_tie = [
        Paper(doc_id="paper-b", source="pubmed", title="B", retrieved_at=retrieved_at),
        Paper(doc_id="paper-a", source="pubmed", title="A", retrieved_at=retrieved_at),
    ]

    selected = select_for_appraisal(papers_with_tie, new_ids=set(), limit=2)

    assert [paper.doc_id for paper in selected] == ["paper-a", "paper-b"]


@pytest.mark.parametrize("exc", [
    StatusError(429),
    DirectCodeError(429),
    DirectCodeError("429"),
    StatusValueError("RESOURCE_EXHAUSTED"),
    StatusValueError(StatusCode.RESOURCE_EXHAUSTED),
    RuntimeError("429 RESOURCE_EXHAUSTED"),
    RuntimeError("HTTP 429: too many requests"),
    RuntimeError("status code: 429"),
    RuntimeError("ResourceExhausted: quota exceeded"),
    CodeError("RESOURCE_EXHAUSTED"),
    CodeError(StatusCode.RESOURCE_EXHAUSTED),
])
def test_quota_errors_are_recognized(exc):
    """Provider quota failures are distinguishable from ordinary failures."""
    assert is_quota_error(exc)


def test_programming_errors_are_not_quota_errors():
    """Local validation failures must continue to surface normally."""
    assert not is_quota_error(TypeError("bad payload"))


def test_pydantic_error_with_incidental_429_payload_is_not_quota():
    """Digits in rejected model data cannot turn validation into fail-soft."""
    with pytest.raises(ValidationError) as caught:
        ParticipantRecord.model_validate({"participants": "429 participants"})

    assert not is_quota_error(caught.value)


def test_real_google_genai_429_client_error_is_quota():
    """The installed Google GenAI error shape is recognized structurally."""
    exc = ClientError(
        429,
        {
            "error": {
                "code": 429,
                "status": "RESOURCE_EXHAUSTED",
                "message": "Quota exhausted.",
            }
        },
    )

    assert is_quota_error(exc)


@pytest.mark.parametrize(
    "exc",
    [
        ValueError("429 participants were enrolled"),
        RuntimeError("paper 429 could not be parsed"),
        TypeError("resource 429 has the wrong shape"),
    ],
)
def test_incidental_429_text_is_not_quota(exc):
    """An arbitrary identifier or value containing 429 remains fatal."""
    assert not is_quota_error(exc)
