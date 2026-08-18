"""Firestore persistence.

Collections
-----------
``provenance_papers``      retrieved records, keyed by DOI-first identity
``provenance_appraisals``  one per appraised paper
``provenance_rejections``  everything that did not survive, and why
``provenance_findings``    converged evidence with a proposed change
``provenance_agendas``     cached research agendas, keyed by source digest

Every collection carries a ``provenance_`` prefix. This project may later share
a Firestore database with the subject application's production data, and an
unprefixed ``papers`` collection is exactly the kind of thing that quietly
collides with something important.
"""

from __future__ import annotations

import logging
from typing import Iterable

from google.cloud import firestore

from .. import auth
from ..config import settings
from ..models import (
    Appraisal,
    Finding,
    Paper,
    Rejection,
    ResearchAgenda,
)

log = logging.getLogger(__name__)

PAPERS = "provenance_papers"
APPRAISALS = "provenance_appraisals"
REJECTIONS = "provenance_rejections"
FINDINGS = "provenance_findings"
AGENDAS = "provenance_agendas"

#: Firestore commits at most 500 writes per batch.
_BATCH_LIMIT = 450


def client() -> firestore.Client:
    cfg = settings()
    return firestore.Client(
        project=cfg.gcp_project,
        database=cfg.firestore_database,
        credentials=auth.credentials(cfg.gcp_project),
    )


def _serialise(model) -> dict:
    """Pydantic -> Firestore-safe dict.

    ``mode="json"`` converts enums to their values and dates to ISO strings;
    Firestore rejects both raw ``Enum`` and ``datetime.date``.
    """
    return model.model_dump(mode="json")


def _commit_in_batches(db: firestore.Client, collection: str, docs: Iterable[tuple[str, dict]]) -> int:
    written = 0
    batch = db.batch()
    pending = 0
    for doc_id, payload in docs:
        batch.set(db.collection(collection).document(doc_id), payload, merge=True)
        pending += 1
        written += 1
        if pending >= _BATCH_LIMIT:
            batch.commit()
            batch = db.batch()
            pending = 0
    if pending:
        batch.commit()
    return written


def save_papers(papers: list[Paper], *, db: firestore.Client | None = None) -> int:
    db = db or client()
    return _commit_in_batches(db, PAPERS, ((p.doc_id, _serialise(p)) for p in papers))


def save_rejections(rejections: list[Rejection], *, db: firestore.Client | None = None) -> int:
    db = db or client()
    # A paper can be rejected at more than one stage across runs; key by both so
    # a later grounding failure does not overwrite an earlier screening reason.
    return _commit_in_batches(
        db,
        REJECTIONS,
        ((f"{r.paper_id}__{r.stage}", _serialise(r)) for r in rejections),
    )


def save_appraisals(appraisals: list[Appraisal], *, db: firestore.Client | None = None) -> int:
    db = db or client()
    return _commit_in_batches(
        db, APPRAISALS, ((a.paper_id, _serialise(a)) for a in appraisals)
    )


def save_finding(finding: Finding, *, db: firestore.Client | None = None) -> None:
    db = db or client()
    db.collection(FINDINGS).document(finding.finding_id).set(_serialise(finding), merge=True)


def save_agenda(agenda: ResearchAgenda, *, db: firestore.Client | None = None) -> None:
    db = db or client()
    doc_id = f"{agenda.subject_key}__{agenda.source_digest}"
    db.collection(AGENDAS).document(doc_id).set(_serialise(agenda), merge=True)


def latest_agenda(
    subject_key: str, *, db: firestore.Client | None = None
) -> ResearchAgenda | None:
    """The most recently published agenda for a subject.

    The agenda is derived from source files that live in a private repository
    on a developer machine. A scheduled cloud run has no checkout of them and
    no business cloning one, so it reads the agenda the last local run
    published instead. That is not a staleness compromise: the agenda only
    changes when the algorithm changes, and the algorithm changes where the
    code is.
    """
    db = db or client()
    docs = [
        doc.to_dict()
        for doc in db.collection(AGENDAS).stream()
        if doc.id.startswith(f"{subject_key}__")
    ]
    if not docs:
        return None
    docs.sort(key=lambda d: d.get("generated_at", ""), reverse=True)
    return ResearchAgenda.model_validate(docs[0])


def known_paper_ids(*, db: firestore.Client | None = None, limit: int | None = None) -> set[str]:
    """Identifiers already retrieved, so a sweep only surfaces what is new.

    Reads document names only -- the payload is never fetched, which keeps this
    cheap as the corpus grows.
    """
    db = db or client()
    query = db.collection(PAPERS).select([])
    if limit is not None:
        query = query.limit(limit)
    return {doc.id for doc in query.stream()}


def load_appraisals_for_component(
    component_id: str, *, db: firestore.Client | None = None
) -> list[Appraisal]:
    """Every appraisal bearing on one scoring component.

    This is what convergence is judged over -- the Synthesist needs the whole
    accumulated history for a component, not just tonight's batch.
    """
    db = db or client()
    docs = (
        db.collection(APPRAISALS)
        .where(filter=firestore.FieldFilter("component_ids", "array_contains", component_id))
        .stream()
    )
    return [Appraisal.model_validate(doc.to_dict()) for doc in docs]
