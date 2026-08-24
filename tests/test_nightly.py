"""Nightly orchestration keeps its queue durable and its briefing honest."""

from __future__ import annotations

import asyncio
from contextlib import ExitStack, contextmanager
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from provenance.agents.appraiser import AppraisalBatch, TriageBatch
from provenance.agents.scout import SweepResult
from provenance.config import SUBJECTS
from provenance.models import (
    Appraisal,
    Claim,
    EvidenceTier,
    Finding,
    Paper,
    Rejection,
    ResearchAgenda,
    SourceName,
)
from provenance.nightly import _notify, run
from provenance.store import firestore as store

_DEFAULT_SYNTHESIS = object()


def _agenda() -> ResearchAgenda:
    return ResearchAgenda(
        subject_key="synqology",
        algorithm_version="VI test",
        source_digest="digest",
        items=[],
    )


def _paper(
    doc_id: str,
    *,
    retrieved_at: datetime | None = None,
    triaged: bool = False,
) -> Paper:
    return Paper(
        doc_id=doc_id,
        source=SourceName.PUBMED,
        title=f"Paper {doc_id}",
        abstract="A sufficiently complete abstract for an appraisal.",
        journal="Ann Intern Med",
        url=f"https://example.test/{doc_id}",
        retrieved_at=retrieved_at or datetime(2026, 8, 1, tzinfo=timezone.utc),
        triaged_at=(datetime(2026, 8, 2, tzinfo=timezone.utc) if triaged else None),
        triage_agenda_digest="digest" if triaged else "",
    )


def _appraisal(paper_id: str) -> Appraisal:
    return Appraisal(
        paper_id=paper_id,
        tier=EvidenceTier.B,
        design="prospective cohort study",
        sample_size=51_650,
        claims=[
            Claim(
                claim_id="c1",
                statement="The measured outcome was lower.",
                quote="weekend warriors had lower all-cause mortality",
            )
        ],
    )


def _rejection(paper: Paper, *, reason_code: str = "not_relevant") -> Rejection:
    return Rejection(
        paper_id=paper.doc_id,
        title=paper.title,
        stage="appraiser",
        reason_code=reason_code,
        reason="Does not bear on a scoring component.",
    )


def _finding() -> Finding:
    return Finding(
        finding_id="synqology__mvpa__test",
        subject_key="synqology",
        component_id="mvpa",
        statement="The rule should change.",
        current_behavior="The current rule.",
    )


def _fixtures() -> tuple[Paper, Appraisal]:
    paper = _paper("doi:10.1_x")
    return paper, _appraisal(paper.doc_id)


class _Snapshot:
    def __init__(self, doc_id: str, payload: dict | None):
        self.id = doc_id
        self._payload = payload
        self.exists = payload is not None

    def to_dict(self) -> dict | None:
        return dict(self._payload) if self._payload is not None else None


class _Document:
    def __init__(self, owner: "_StatefulDb", collection: str, doc_id: str):
        self.owner = owner
        self.collection = collection
        self.id = doc_id

    def get(self) -> _Snapshot:
        return _Snapshot(self.id, self.owner._collections[self.collection].get(self.id))

    def set(self, payload: dict, merge: bool = False) -> None:
        target = self.owner._collections[self.collection]
        if merge and self.id in target:
            target[self.id] = {**target[self.id], **dict(payload)}
        else:
            target[self.id] = dict(payload)


class _Collection:
    def __init__(self, owner: "_StatefulDb", name: str):
        self.owner = owner
        self.name = name

    def stream(self):
        return iter(
            _Snapshot(doc_id, payload)
            for doc_id, payload in sorted(self.owner._collections[self.name].items())
        )

    def select(self, _fields):
        return self

    def document(self, doc_id: str) -> _Document:
        return _Document(self.owner, self.name, doc_id)


class _Batch:
    def __init__(self, owner: "_StatefulDb"):
        self.owner = owner
        self.writes: list[tuple[_Document, dict, bool]] = []

    def set(self, document: _Document, payload: dict, merge: bool = False) -> None:
        self.writes.append((document, payload, merge))

    def commit(self) -> None:
        collections = {document.collection for document, _payload, _merge in self.writes}
        paper_ids = {
            payload.get("paper_id")
            for _document, payload, _merge in self.writes
            if payload.get("paper_id")
        }
        target = self.owner.fail_appraisal_wave_for
        if (
            target is not None
            and target in paper_ids
            and store.REJECTIONS in collections
            and (store.APPRAISALS in collections or collections == {store.REJECTIONS})
        ):
            self.owner.fail_appraisal_wave_for = None
            raise RuntimeError("appraisal wave commit failed")
        for document, payload, merge in self.writes:
            document.set(payload, merge=merge)


class _StatefulDb:
    """Small Firestore double whose streams reflect every persisted write."""

    def __init__(
        self,
        papers: list[Paper] | None = None,
        *,
        fail_appraisal_wave_for: str | None = None,
    ):
        self._collections: dict[str, dict[str, dict]] = {
            store.PAPERS: {},
            store.APPRAISALS: {},
            store.REJECTIONS: {},
            store.FINDINGS: {},
            store.AGENDAS: {},
            "provenance_runs": {},
        }
        self.notification: dict | None = None
        self.fail_appraisal_wave_for = fail_appraisal_wave_for
        for paper in papers or []:
            self.papers[paper.doc_id] = paper.model_dump(mode="json")

    @property
    def papers(self) -> dict[str, dict]:
        return self._collections[store.PAPERS]

    @property
    def appraisals(self) -> dict[str, dict]:
        return self._collections[store.APPRAISALS]

    @property
    def rejections(self) -> dict[str, dict]:
        return self._collections[store.REJECTIONS]

    @property
    def findings(self) -> dict[str, dict]:
        return self._collections[store.FINDINGS]

    @property
    def runs(self) -> dict[str, dict]:
        return self._collections["provenance_runs"]

    @property
    def saved_run(self) -> dict | None:
        return next(reversed(self.runs.values()), None)

    def collection(self, name: str) -> _Collection:
        self._collections.setdefault(name, {})
        return _Collection(self, name)

    def batch(self) -> _Batch:
        return _Batch(self)


class _StubDb:
    """Enough Firestore to satisfy the Sunday digest in the direct notify test."""

    class _Collection:
        def stream(self):
            return iter(())

        def select(self, _fields):
            return self

    def collection(self, _name):
        return self._Collection()


async def _triage_all(
    papers: list[Paper],
    _agenda: ResearchAgenda,
    *,
    max_concurrent: int = 6,
) -> TriageBatch:
    assert max_concurrent == 6
    return TriageBatch(list(papers), [], [], None)


async def _appraise_all(
    papers: list[Paper],
    _agenda: ResearchAgenda,
    *,
    max_concurrent: int = 3,
) -> AppraisalBatch:
    assert max_concurrent == 3
    return AppraisalBatch([_appraisal(paper.doc_id) for paper in papers], [], [], None)


@contextmanager
def _pipeline(
    db: _StatefulDb,
    result: SweepResult,
    *,
    triage_side_effect=_triage_all,
    appraisal_side_effect=_appraise_all,
    synthesis_side_effect=None,
    synthesis_return=_DEFAULT_SYNTHESIS,
):
    """Patch only external/model boundaries; persistence remains real."""
    if synthesis_return is _DEFAULT_SYNTHESIS:
        synthesis_return = ([], [])

    def capture_notification(
        _db,
        _subject,
        _fresh,
        _prior,
        *,
        run,
        appraisals,
        rejections,
        **_kwargs,
    ):
        db.notification = {
            "run": dict(run),
            "appraisals": list(appraisals),
            "rejections": list(rejections),
        }
        return {"sent": ["briefing"]}

    with ExitStack() as stack:
        stack.enter_context(patch("provenance.nightly.store.client", return_value=db))
        stack.enter_context(patch("provenance.nightly.sweep", return_value=result))
        triage_batch = stack.enter_context(
            patch("provenance.nightly.triage_batch", side_effect=triage_side_effect,
                  create=True)
        )
        appraise_batch = stack.enter_context(
            patch(
                "provenance.nightly.appraise_batch",
                side_effect=appraisal_side_effect,
            )
        )
        synthesise_kwargs = (
            {"side_effect": synthesis_side_effect}
            if synthesis_side_effect is not None
            else {"return_value": synthesis_return}
        )
        synthesise = stack.enter_context(
            patch("provenance.nightly.synthesise", **synthesise_kwargs)
        )
        stack.enter_context(patch("provenance.nightly.pr_health.sweep", return_value={}))
        notify = stack.enter_context(
            patch("provenance.nightly._notify", side_effect=capture_notification)
        )
        engineer_plan = stack.enter_context(
            patch("provenance.agents.engineer.plan", return_value=None)
        )
        yield SimpleNamespace(
            triage_batch=triage_batch,
            appraise_batch=appraise_batch,
            synthesise=synthesise,
            notify=notify,
            engineer_plan=engineer_plan,
        )


class _QuotaError(RuntimeError):
    status_code = 429


class TestBriefingCarriesTheNightsPapers:
    def test_kept_papers_reach_briefing_email(self):
        paper, appraisal = _fixtures()

        with patch("provenance.nightly.notify.mail_config") as mail_config, \
             patch("provenance.nightly.notify.briefing_email") as briefing_email, \
             patch("provenance.nightly.notify.send", return_value="email-id"):
            mail_config.return_value.configured = True
            briefing_email.return_value = ("subject", "<html></html>")

            _notify(
                db=_StubDb(), subject=None, fresh=[], prior=[],
                run={}, appraisals=[appraisal], rejections=[],
                papers={paper.doc_id: paper},
            )

            (_run, pairs, *_rest), _kwargs = briefing_email.call_args
            assert pairs == [(paper, appraisal)]


class TestNightlyQueue:
    def test_recovers_stored_pending_papers_in_a_capped_batch(self):
        papers = [_paper(f"old-{index:02d}") for index in range(33)]
        db = _StatefulDb(papers)
        result = SweepResult(agenda=_agenda())

        with _pipeline(db, result) as calls:
            summary = asyncio.run(run(SUBJECTS["synqology"]))

        selected = [
            paper.doc_id
            for call in calls.appraise_batch.await_args_list
            for paper in call.args[0]
        ]
        assert summary["pending_before"] == 33
        assert summary["triaged"] == 33
        assert summary["appraisal_selected"] == 10
        assert summary["appraised"] == 10
        assert summary["appraisal_pending"] == 23
        assert [
            len(call.args[0]) for call in calls.appraise_batch.await_args_list
        ] == [3, 3, 3, 1]
        assert set(db.appraisals) == set(selected)
        assert [a.paper_id for a in db.notification["appraisals"]] == selected
        calls.synthesise.assert_awaited_once()

    def test_reserves_five_slots_each_for_old_and_new_papers(self):
        base = datetime(2026, 7, 1, tzinfo=timezone.utc)
        old = [
            _paper(f"old-{index}", retrieved_at=base + timedelta(days=index), triaged=True)
            for index in range(7)
        ]
        new = [
            _paper(f"new-{index}", retrieved_at=base + timedelta(days=20 + index))
            for index in range(7)
        ]
        db = _StatefulDb(old)
        result = SweepResult(agenda=_agenda(), papers=new)

        with _pipeline(db, result) as calls:
            asyncio.run(run(SUBJECTS["synqology"]))

        selected = [
            paper.doc_id
            for call in calls.appraise_batch.await_args_list
            for paper in call.args[0]
        ]
        assert selected == [
            "old-0", "new-0", "old-1", "new-1", "old-2",
            "new-2", "old-3", "new-3", "old-4", "new-4",
        ]

    def test_honours_the_configured_appraisal_limit(self):
        papers = [_paper(f"paper-{index:02d}", triaged=True) for index in range(10)]
        db = _StatefulDb(papers)
        result = SweepResult(agenda=_agenda())

        with patch.dict("os.environ", {"PROVENANCE_APPRAISAL_LIMIT": "4"}):
            with _pipeline(db, result) as calls:
                summary = asyncio.run(run(SUBJECTS["synqology"]))

        assert summary["appraisal_selected"] == 4
        assert summary["appraisal_pending"] == 6
        assert [
            len(call.args[0]) for call in calls.appraise_batch.await_args_list
        ] == [3, 1]

    def test_retriages_only_papers_without_current_agenda_metadata(self):
        current = _paper("current", triaged=True)
        stale = _paper("stale", triaged=True)
        stale.triage_agenda_digest = "old-digest"
        db = _StatefulDb([current, stale])
        result = SweepResult(agenda=_agenda())

        with _pipeline(db, result) as calls:
            summary = asyncio.run(run(SUBJECTS["synqology"]))

        assert [paper.doc_id for paper in calls.triage_batch.await_args.args[0]] == [
            "stale"
        ]
        assert summary["triaged"] == 1
        assert db.papers["stale"]["triage_agenda_digest"] == "digest"

    def test_persists_each_triage_and_appraisal_wave_before_starting_the_next(self):
        papers = [_paper(f"paper-{index:02d}") for index in range(25)]
        db = _StatefulDb(papers)
        result = SweepResult(agenda=_agenda())
        triage_waves: list[list[str]] = []
        appraisal_waves: list[list[str]] = []
        rejected = _rejection(papers[23])
        appraisal_rejection = _rejection(papers[2], reason_code="no_appraisal")

        async def triage_wave(batch, _agenda, *, max_concurrent):
            assert max_concurrent == 6
            if triage_waves:
                assert all(
                    db.papers[paper_id]["triage_agenda_digest"] == "digest"
                    for paper_id in triage_waves[-1]
                    if paper_id != rejected.paper_id
                )
                assert f"{rejected.paper_id}__appraiser" in db.rejections
            ids = [paper.doc_id for paper in batch]
            triage_waves.append(ids)
            if len(triage_waves) == 1:
                return TriageBatch(list(batch[:-1]), [rejected], [], None)
            return TriageBatch(list(batch), [], [], None)

        async def appraisal_wave(batch, _agenda, *, max_concurrent):
            assert max_concurrent == 3
            assert f"{rejected.paper_id}__appraiser" in db.rejections
            assert all(
                payload["triage_agenda_digest"] == "digest"
                for paper_id, payload in db.papers.items()
                if paper_id != rejected.paper_id
            )
            if appraisal_waves:
                previous = appraisal_waves[-1]
                if len(appraisal_waves) == 1:
                    assert all(paper_id in db.appraisals for paper_id in previous[:2])
                    assert f"{previous[2]}__appraiser" in db.rejections
                else:
                    assert all(paper_id in db.appraisals for paper_id in previous)
            ids = [paper.doc_id for paper in batch]
            appraisal_waves.append(ids)
            if len(appraisal_waves) == 1:
                return AppraisalBatch(
                    [_appraisal(paper_id) for paper_id in ids[:2]],
                    [appraisal_rejection],
                    [],
                    None,
                )
            return AppraisalBatch([_appraisal(paper_id) for paper_id in ids], [], [], None)

        with _pipeline(
            db,
            result,
            triage_side_effect=triage_wave,
            appraisal_side_effect=appraisal_wave,
        ) as calls:
            asyncio.run(run(SUBJECTS["synqology"]))

        assert [len(wave) for wave in triage_waves] == [24, 1]
        assert [len(wave) for wave in appraisal_waves] == [3, 3, 3, 1]
        assert [
            rejection.paper_id for rejection in db.notification["rejections"]
        ] == [rejected.paper_id, appraisal_rejection.paper_id]
        assert {
            appraisal.paper_id for appraisal in db.notification["appraisals"]
        } == set(db.appraisals)
        calls.notify.assert_called_once()

    def test_triage_quota_preserves_partial_wave_and_stops_model_stages(self):
        papers = [_paper(f"paper-{index:02d}") for index in range(33)]
        db = _StatefulDb(papers)
        result = SweepResult(agenda=_agenda())
        rejection = _rejection(papers[1])
        quota = _QuotaError("429 RESOURCE_EXHAUSTED during triage")

        async def partial_triage(batch, _agenda, *, max_concurrent):
            assert max_concurrent == 6
            return TriageBatch([batch[0]], [rejection], list(batch[2:]), quota)

        with _pipeline(db, result, triage_side_effect=partial_triage) as calls:
            summary = asyncio.run(run(SUBJECTS["synqology"], engineer=True))

        assert summary["triaged"] == 2
        assert summary["appraisal_selected"] == 0
        assert summary["appraised"] == 0
        assert summary["appraisal_pending"] == 32
        assert summary["pipeline_error"] == {
            "stage": "triage",
            "type": "_QuotaError",
            "message": "Model quota exhausted (HTTP 429).",
        }
        assert db.papers[papers[0].doc_id]["triage_agenda_digest"] == "digest"
        assert f"{rejection.paper_id}__appraiser" in db.rejections
        calls.triage_batch.assert_awaited_once()
        calls.appraise_batch.assert_not_awaited()
        calls.synthesise.assert_not_awaited()
        calls.engineer_plan.assert_not_called()
        assert summary["notified"] == {"sent": ["briefing"]}
        assert [
            item.paper_id for item in db.notification["rejections"]
        ] == [rejection.paper_id]
        assert db.saved_run == summary

    def test_appraisal_quota_preserves_partial_wave_and_stops_model_stages(self):
        papers = [_paper(f"paper-{index:02d}", triaged=True) for index in range(33)]
        db = _StatefulDb(papers)
        result = SweepResult(agenda=_agenda())
        quota = _QuotaError("429 RESOURCE_EXHAUSTED during appraisal")

        async def partial_appraisal(batch, _agenda, *, max_concurrent):
            assert max_concurrent == 3
            return AppraisalBatch(
                [_appraisal(batch[0].doc_id), _appraisal(batch[1].doc_id)],
                [],
                [batch[2]],
                quota,
            )

        with _pipeline(db, result, appraisal_side_effect=partial_appraisal) as calls:
            summary = asyncio.run(run(SUBJECTS["synqology"], engineer=True))

        assert summary["appraised"] == 2
        assert summary["appraisal_selected"] == 10
        assert summary["appraisal_pending"] == 31
        assert summary["pipeline_error"] == {
            "stage": "appraisal",
            "type": "_QuotaError",
            "message": "Model quota exhausted (HTTP 429).",
        }
        calls.appraise_batch.assert_awaited_once()
        calls.synthesise.assert_not_awaited()
        calls.engineer_plan.assert_not_called()
        assert summary["notified"] == {"sent": ["briefing"]}
        assert {
            item.paper_id for item in db.notification["appraisals"]
        } == set(db.appraisals)
        assert db.saved_run == summary

    def test_failed_first_appraisal_wave_remains_reproducible_on_retry(self):
        paper = _paper("paper-0", triaged=True)
        db = _StatefulDb(
            [paper], fail_appraisal_wave_for=paper.doc_id
        )
        result = SweepResult(agenda=_agenda())
        audit = Rejection(
            paper_id=paper.doc_id,
            title=paper.title,
            stage="grounding",
            reason_code="unsupported_quote",
            reason="One claim failed source verification.",
        )
        attempts: list[list[str]] = []

        async def appraise_with_audit(batch, _agenda, *, max_concurrent):
            assert max_concurrent == 3
            attempts.append([item.doc_id for item in batch])
            return AppraisalBatch([_appraisal(batch[0].doc_id)], [audit], [], None)

        with _pipeline(db, result, appraisal_side_effect=appraise_with_audit):
            with pytest.raises(RuntimeError, match="appraisal wave commit failed"):
                asyncio.run(run(SUBJECTS["synqology"]))

        assert db.appraisals == {}
        assert db.rejections == {}
        assert [item.doc_id for item in store.pending_papers(db=db)] == [paper.doc_id]
        assert db.notification is None
        assert db.saved_run is None

        with _pipeline(db, result, appraisal_side_effect=appraise_with_audit):
            summary = asyncio.run(run(SUBJECTS["synqology"]))

        assert attempts == [[paper.doc_id], [paper.doc_id]]
        assert set(db.appraisals) == {paper.doc_id}
        assert set(db.rejections) == {f"{paper.doc_id}__grounding"}
        assert summary["appraisal_pending"] == 0
        assert [item.paper_id for item in db.notification["appraisals"]] == [
            paper.doc_id
        ]
        assert [item.paper_id for item in db.notification["rejections"]] == [
            paper.doc_id
        ]

    def test_failed_later_appraisal_wave_leaves_only_that_wave_pending(self):
        papers = [_paper(f"paper-{index}", triaged=True) for index in range(6)]
        failed_wave_first = papers[3]
        db = _StatefulDb(
            papers, fail_appraisal_wave_for=failed_wave_first.doc_id
        )
        result = SweepResult(agenda=_agenda())
        audit = Rejection(
            paper_id=failed_wave_first.doc_id,
            title=failed_wave_first.title,
            stage="grounding",
            reason_code="unsupported_quote",
            reason="One claim failed source verification.",
        )
        attempts: list[list[str]] = []

        async def appraise_with_later_audit(batch, _agenda, *, max_concurrent):
            assert max_concurrent == 3
            ids = [item.doc_id for item in batch]
            attempts.append(ids)
            rejections = [audit] if failed_wave_first.doc_id in ids else []
            return AppraisalBatch(
                [_appraisal(paper_id) for paper_id in ids], rejections, [], None
            )

        with _pipeline(db, result, appraisal_side_effect=appraise_with_later_audit):
            with pytest.raises(RuntimeError, match="appraisal wave commit failed"):
                asyncio.run(run(SUBJECTS["synqology"]))

        assert set(db.appraisals) == {paper.doc_id for paper in papers[:3]}
        assert db.rejections == {}
        assert [item.doc_id for item in store.pending_papers(db=db)] == [
            paper.doc_id for paper in papers[3:]
        ]
        assert db.notification is None

        with _pipeline(db, result, appraisal_side_effect=appraise_with_later_audit):
            summary = asyncio.run(run(SUBJECTS["synqology"]))

        assert attempts == [
            [paper.doc_id for paper in papers[:3]],
            [paper.doc_id for paper in papers[3:]],
            [paper.doc_id for paper in papers[3:]],
        ]
        assert set(db.appraisals) == {paper.doc_id for paper in papers}
        assert set(db.rejections) == {f"{failed_wave_first.doc_id}__grounding"}
        assert summary["appraisal_pending"] == 0
        assert [item.paper_id for item in db.notification["appraisals"]] == [
            paper.doc_id for paper in papers[3:]
        ]


class TestPipelineFailures:
    def test_synthesis_quota_is_fail_soft_but_uses_the_common_error_shape(self):
        db = _StatefulDb()
        result = SweepResult(agenda=_agenda())
        quota = _QuotaError(
            "429 RESOURCE_EXHAUSTED project=private-project resource=secret-resource"
        )

        with _pipeline(db, result, synthesis_side_effect=quota):
            summary = asyncio.run(run(SUBJECTS["synqology"]))

        assert summary["pipeline_error"] == {
            "stage": "synthesis",
            "type": "_QuotaError",
            "message": "Model quota exhausted (HTTP 429).",
        }
        assert "private-project" not in str(summary)
        assert "secret-resource" not in str(summary)
        assert summary["findings_new"] == 0
        assert summary["notified"] == {"sent": ["briefing"]}
        assert db.notification["run"]["pipeline_error"] == summary["pipeline_error"]
        assert db.saved_run == summary

    def test_non_quota_synthesis_failure_remains_fatal(self):
        db = _StatefulDb()
        result = SweepResult(agenda=_agenda())

        with _pipeline(db, result, synthesis_side_effect=RuntimeError("bad response")):
            with pytest.raises(RuntimeError, match="bad response"):
                asyncio.run(run(SUBJECTS["synqology"]))

        assert db.notification is None
        assert db.saved_run is None

    @pytest.mark.parametrize(
        ("target", "seed_papers", "synthesis_return"),
        [
            ("save_papers", [], ([], [])),
            ("save_rejections", [], ([], [])),
            ("save_appraisal_wave", [_paper("ready", triaged=True)], ([], [])),
            ("save_finding", [], ([_finding()], [])),
        ],
    )
    def test_persistence_failures_remain_fatal(
        self,
        target: str,
        seed_papers: list[Paper],
        synthesis_return,
    ):
        db = _StatefulDb(seed_papers)
        result = SweepResult(agenda=_agenda())

        with _pipeline(db, result, synthesis_return=synthesis_return):
            with patch(
                f"provenance.nightly.store.{target}",
                side_effect=RuntimeError(f"{target} failed"),
            ):
                with pytest.raises(RuntimeError, match=f"{target} failed"):
                    asyncio.run(run(SUBJECTS["synqology"]))

        assert db.saved_run is None
