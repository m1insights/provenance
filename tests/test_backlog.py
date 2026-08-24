from __future__ import annotations

from datetime import datetime, timedelta, timezone
from enum import Enum

import pytest

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


def paper_doc(doc_id: str) -> QueueDocument:
    return doc(doc_id, {
        "doc_id": doc_id,
        "source": "pubmed",
        "title": doc_id,
    })


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


class StatusCode(Enum):
    RESOURCE_EXHAUSTED = "RESOURCE_EXHAUSTED"


class CodeError(Exception):
    def __init__(self, code: str | StatusCode):
        self._code = code

    def code(self) -> str | StatusCode:
        return self._code


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


def test_selection_lends_unused_new_slots_to_backlog():
    """Unused new-work capacity is available to an existing backlog."""
    old = papers("old", 12, start_day=1)

    assert len(select_for_appraisal(old, new_ids=set(), limit=10)) == 10


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
    RuntimeError("429 RESOURCE_EXHAUSTED"),
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
