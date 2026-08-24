"""The appraisal CLI shares nightly's queue and atomic persistence contracts."""

from __future__ import annotations

from types import SimpleNamespace

from provenance import cli
from provenance.agents import appraiser
from provenance import content_agenda
from provenance.models import Appraisal, EvidenceTier, Paper, Rejection, SourceName
from provenance.store import firestore as store


class _Snapshot:
    def __init__(self, paper: Paper):
        self.id = paper.doc_id
        self._payload = paper.model_dump(mode="json")

    def to_dict(self) -> dict:
        return dict(self._payload)


class _PaperCollection:
    def __init__(self, papers: list[Paper]):
        self.papers = papers

    def stream(self):
        return iter(_Snapshot(paper) for paper in self.papers)


class _CliDb:
    def __init__(self, papers: list[Paper] | None = None):
        self.papers = list(papers or [])

    def collection(self, name: str) -> _PaperCollection:
        if name != store.PAPERS:
            raise AssertionError(f"unexpected collection scan: {name}")
        return _PaperCollection(self.papers)


def _paper(doc_id: str) -> Paper:
    return Paper(doc_id=doc_id, source=SourceName.PUBMED, title=doc_id)


def _appraisal(paper_id: str) -> Appraisal:
    return Appraisal(
        paper_id=paper_id,
        tier=EvidenceTier.B,
        design="prospective cohort study",
    )


def _rejection(paper_id: str) -> Rejection:
    return Rejection(
        paper_id=paper_id,
        stage="grounding",
        reason_code="unsupported_quote",
        reason="Claim failed grounding.",
    )


def _configure_appraisal_cli(monkeypatch, db: _CliDb):
    selected: list[list[str]] = []
    persisted = {"appraisals": {}, "rejections": {}}

    async def triage(papers, _agenda):
        selected.append([paper.doc_id for paper in papers])
        return list(papers), []

    async def appraise(papers, _agenda):
        return (
            [_appraisal(paper.doc_id) for paper in papers],
            [_rejection(papers[0].doc_id)] if papers else [],
        )

    def save_wave(appraisals, rejections, *, db):
        persisted["appraisals"].update(
            {appraisal.paper_id: appraisal for appraisal in appraisals}
        )
        persisted["rejections"].update(
            {f"{rejection.paper_id}__{rejection.stage}": rejection for rejection in rejections}
        )

    def divergent_write(*_args, **_kwargs):
        raise AssertionError("CLI used split appraisal persistence")

    monkeypatch.setattr(store, "client", lambda: db)
    monkeypatch.setattr(cli, "build_agenda", lambda _subject: object())
    monkeypatch.setattr(content_agenda, "with_lane", lambda agenda: agenda)
    monkeypatch.setattr(appraiser, "triage", triage)
    monkeypatch.setattr(appraiser, "appraise", appraise)
    monkeypatch.setattr(store, "save_appraisal_wave", save_wave, raising=False)
    monkeypatch.setattr(store, "save_appraisals", divergent_write)
    monkeypatch.setattr(store, "save_rejections", divergent_write)
    return selected, persisted


def test_appraise_normal_mode_selects_the_canonical_pending_queue(monkeypatch):
    pending = [_paper("pending-b"), _paper("pending-a")]
    db = _CliDb()
    selected, persisted = _configure_appraisal_cli(monkeypatch, db)
    monkeypatch.setattr(store, "pending_papers", lambda *, db: list(pending))

    result = cli.cmd_appraise(
        SimpleNamespace(subject="synqology", redo=[], limit_papers=None)
    )

    assert result == 0
    assert selected == [["pending-b", "pending-a"]]
    assert list(persisted["appraisals"]) == ["pending-b", "pending-a"]
    assert list(persisted["rejections"]) == ["pending-b__grounding"]


def test_appraise_redo_selects_only_explicit_document_ids(monkeypatch):
    db = _CliDb([_paper("redo-me"), _paper("leave-alone")])
    selected, persisted = _configure_appraisal_cli(monkeypatch, db)

    def unexpected_pending_lookup(*, db):
        raise AssertionError("--redo must not use the pending queue")

    monkeypatch.setattr(store, "pending_papers", unexpected_pending_lookup)

    result = cli.cmd_appraise(
        SimpleNamespace(subject="synqology", redo=["redo-me"], limit_papers=None)
    )

    assert result == 0
    assert selected == [["redo-me"]]
    assert list(persisted["appraisals"]) == ["redo-me"]
    assert list(persisted["rejections"]) == ["redo-me__grounding"]
