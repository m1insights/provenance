"""Firestore appraisal waves persist their complete audit trail atomically."""

from __future__ import annotations

import pytest

from provenance.models import Appraisal, EvidenceTier, Rejection, ResearchAgenda
from provenance.store import firestore as store


class _Document:
    def __init__(self, db: "_AtomicDb", collection: str, doc_id: str):
        self.db = db
        self.collection = collection
        self.id = doc_id


class _Collection:
    def __init__(self, db: "_AtomicDb", name: str):
        self.db = db
        self.name = name

    def document(self, doc_id: str) -> _Document:
        return _Document(self.db, self.name, doc_id)


class _Batch:
    def __init__(self, db: "_AtomicDb"):
        self.db = db
        self.writes: list[tuple[_Document, dict, bool]] = []
        self.paths: set[tuple[str, str]] = set()

    def set(self, document: _Document, payload: dict, merge: bool = False) -> None:
        path = (document.collection, document.id)
        if path in self.paths:
            raise AssertionError(f"duplicate write for {path}")
        self.paths.add(path)
        self.writes.append((document, dict(payload), merge))

    def commit(self) -> None:
        self.db.commit_attempts += 1
        if self.db.fail_next_commit:
            self.db.fail_next_commit = False
            raise RuntimeError("atomic commit failed")

        staged = {
            name: {doc_id: dict(payload) for doc_id, payload in documents.items()}
            for name, documents in self.db.documents.items()
        }
        for document, payload, merge in self.writes:
            collection = staged.setdefault(document.collection, {})
            if merge and document.id in collection:
                collection[document.id] = {**collection[document.id], **payload}
            else:
                collection[document.id] = payload
        self.db.documents = staged


class _AtomicDb:
    def __init__(self, *, fail_next_commit: bool = False):
        self.documents: dict[str, dict[str, dict]] = {
            store.APPRAISALS: {},
            store.REJECTIONS: {},
        }
        self.fail_next_commit = fail_next_commit
        self.commit_attempts = 0

    def collection(self, name: str) -> _Collection:
        self.documents.setdefault(name, {})
        return _Collection(self, name)

    def batch(self) -> _Batch:
        return _Batch(self)


def _appraisal(paper_id: str) -> Appraisal:
    return Appraisal(
        paper_id=paper_id,
        tier=EvidenceTier.B,
        design="prospective cohort study",
    )


def _rejection(paper_id: str, reason: str) -> Rejection:
    return Rejection(
        paper_id=paper_id,
        stage="grounding",
        reason_code="unsupported_quote",
        reason=reason,
    )


def test_save_appraisal_wave_commits_both_collections_and_coalesces_rejections():
    """One commit contains the appraisal and one write per rejection identity."""
    db = _AtomicDb()

    written = store.save_appraisal_wave(
        [_appraisal("paper-1")],
        [
            _rejection("paper-1", "First claim failed."),
            _rejection("paper-1", "Second claim failed."),
        ],
        db=db,
    )

    assert written == 2
    assert db.commit_attempts == 1
    assert set(db.documents[store.APPRAISALS]) == {"paper-1"}
    assert set(db.documents[store.REJECTIONS]) == {"paper-1__grounding"}
    assert (
        db.documents[store.REJECTIONS]["paper-1__grounding"]["reason"]
        == "Second claim failed."
    )


def test_save_appraisal_wave_commit_failure_persists_neither_collection():
    """A failed Firestore commit cannot make a paper terminal without its audit."""
    db = _AtomicDb(fail_next_commit=True)

    with pytest.raises(RuntimeError, match="atomic commit failed"):
        store.save_appraisal_wave(
            [_appraisal("paper-1")],
            [_rejection("paper-1", "Claim failed.")],
            db=db,
        )

    assert db.documents[store.APPRAISALS] == {}
    assert db.documents[store.REJECTIONS] == {}


class _LookupSnapshot:
    def __init__(self, payload: dict | None):
        self.exists = payload is not None
        self._payload = payload

    def to_dict(self) -> dict | None:
        return self._payload


class _LookupDocument:
    def __init__(self, db: "_LookupDb", doc_id: str):
        self.db = db
        self.doc_id = doc_id

    def get(self) -> _LookupSnapshot:
        self.db.requested.append(self.doc_id)
        return _LookupSnapshot(self.db.documents.get(self.doc_id))


class _LookupCollection:
    def __init__(self, db: "_LookupDb"):
        self.db = db

    def document(self, doc_id: str) -> _LookupDocument:
        return _LookupDocument(self.db, doc_id)

    def stream(self):
        raise AssertionError("exact lookup must not scan the collection")


class _LookupDb:
    def __init__(self, documents: dict[str, dict] | None = None):
        self.documents = dict(documents or {})
        self.requested: list[str] = []

    def collection(self, name: str) -> _LookupCollection:
        assert name == store.AGENDAS
        return _LookupCollection(self)


def _stored_agenda() -> ResearchAgenda:
    return ResearchAgenda(
        subject_key="synqology",
        algorithm_version="VI test",
        source_digest="abc123",
        items=[],
    )


def test_agenda_for_digest_reads_only_the_deterministic_document():
    agenda = _stored_agenda()
    doc_id = "synqology__abc123"
    db = _LookupDb({doc_id: agenda.model_dump(mode="json")})
    assert store.agenda_for_digest("synqology", "abc123", db=db) == agenda
    assert db.requested == [doc_id]


def test_agenda_for_digest_returns_none_when_document_is_absent():
    db = _LookupDb()
    assert store.agenda_for_digest("synqology", "missing", db=db) is None
    assert db.requested == ["synqology__missing"]
