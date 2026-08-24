from __future__ import annotations

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
