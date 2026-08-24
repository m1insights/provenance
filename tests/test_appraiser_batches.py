"""Partial appraiser batches preserve completed work across quota failures."""

from __future__ import annotations

import asyncio

import pytest

from provenance.agents import appraiser
from provenance.agents.appraiser import appraise, appraise_batch, triage, triage_batch
from provenance.llm import is_quota_error
from provenance.models import AgendaItem, Paper, ResearchAgenda, SourceName


QUOTE = "Participants had a hazard ratio of 0.82 for all-cause mortality."


def _paper(doc_id: str) -> Paper:
    return Paper(
        doc_id=doc_id,
        source=SourceName.PUBMED,
        title=doc_id,
        abstract=f"{doc_id}: {QUOTE}",
        matched_components=["activity"],
    )


def _agenda() -> ResearchAgenda:
    return ResearchAgenda(
        subject_key="test",
        algorithm_version="v1",
        source_digest="digest",
        items=[
            AgendaItem(
                component_id="activity",
                display_name="Activity",
                weight=10,
                current_rule="Awards points for weekly activity.",
            )
        ],
    )


def _appraisal_payload() -> dict:
    return {
        "tier": "B",
        "design": "prospective cohort",
        "sample_size": 12_345,
        "component_ids": ["activity"],
        "alignment": "supports",
        "claims": [
            {
                "claim_id": "c1",
                "statement": "Activity was associated with lower mortality.",
                "quote": QUOTE,
                "value": 0.82,
            }
        ],
        "reasoning": "Reports a quantitative result.",
    }


def _stub_agent(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(appraiser, "_agent", lambda *args, **kwargs: object())


def test_triage_batch_preserves_partial_results_on_quota(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_agent(monkeypatch)
    papers = [_paper("relevant"), _paper("irrelevant"), _paper("quota")]

    async def fake_run(agent, prompt):
        if "TITLE: relevant\n" in prompt:
            return {"relevant": True, "component_ids": ["activity"]}
        if "TITLE: irrelevant\n" in prompt:
            return {"relevant": False, "reason": "Different organ system."}
        raise RuntimeError("429 RESOURCE_EXHAUSTED")

    monkeypatch.setattr(appraiser, "_run", fake_run)

    result = asyncio.run(triage_batch(papers, _agenda(), max_concurrent=3))

    assert [paper.doc_id for paper in result.kept] == ["relevant"]
    assert [rejection.paper_id for rejection in result.rejections] == ["irrelevant"]
    assert [paper.doc_id for paper in result.deferred] == ["quota"]
    assert is_quota_error(result.quota_error)


def test_triage_batch_reraises_unexpected_errors(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_agent(monkeypatch)

    async def fake_run(agent, prompt):
        raise TypeError("bad test payload")

    monkeypatch.setattr(appraiser, "_run", fake_run)

    with pytest.raises(TypeError, match="bad test payload"):
        asyncio.run(triage_batch([_paper("broken")], _agenda()))


def test_triage_batch_stops_waiters_after_first_quota_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Only calls already inside the concurrency gate may finish after quota."""
    _stub_agent(monkeypatch)
    paper_ids = ["quota", "in-flight", "waiting-1", "waiting-2"]
    entered: list[str] = []

    async def exercise():
        both_in_flight = asyncio.Event()
        quota_observed = asyncio.Event()

        async def fake_run(agent, prompt):
            paper_id = next(
                candidate
                for candidate in paper_ids
                if f"TITLE: {candidate}\n" in prompt
            )
            entered.append(paper_id)
            if len(entered) == 2:
                both_in_flight.set()
            await both_in_flight.wait()
            if paper_id == "quota":
                quota_observed.set()
                raise RuntimeError("HTTP 429 RESOURCE_EXHAUSTED")
            await quota_observed.wait()
            return {"relevant": True, "component_ids": ["activity"]}

        monkeypatch.setattr(appraiser, "_run", fake_run)
        return await asyncio.wait_for(
            triage_batch([_paper(paper_id) for paper_id in paper_ids], _agenda(), max_concurrent=2),
            timeout=1,
        )

    result = asyncio.run(exercise())

    assert entered == ["quota", "in-flight"]
    assert [paper.doc_id for paper in result.kept] == ["in-flight"]
    assert [paper.doc_id for paper in result.deferred] == [
        "quota",
        "waiting-1",
        "waiting-2",
    ]


def test_appraise_batch_preserves_success_and_rejection_on_quota(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_agent(monkeypatch)
    papers = [_paper("valid"), _paper("no-result"), _paper("quota")]

    async def fake_run(agent, prompt):
        if "TITLE: valid\n" in prompt:
            return _appraisal_payload()
        if "TITLE: no-result\n" in prompt:
            return None
        raise RuntimeError("429 RESOURCE_EXHAUSTED")

    monkeypatch.setattr(appraiser, "_run", fake_run)
    monkeypatch.setattr(
        appraiser.grounding,
        "verify",
        lambda appraisal, paper: (appraisal, []),
    )

    result = asyncio.run(appraise_batch(papers, _agenda(), max_concurrent=3))

    assert [appraisal.paper_id for appraisal in result.appraisals] == ["valid"]
    assert [rejection.paper_id for rejection in result.rejections] == ["no-result"]
    assert result.rejections[0].reason_code == "no_appraisal"
    assert [paper.doc_id for paper in result.deferred] == ["quota"]
    assert is_quota_error(result.quota_error)


def test_appraise_batch_reraises_unexpected_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Programming failures remain fatal in the appraisal batch API."""
    _stub_agent(monkeypatch)

    async def fake_run(agent, prompt):
        raise TypeError("bad appraisal payload")

    monkeypatch.setattr(appraiser, "_run", fake_run)

    with pytest.raises(TypeError, match="bad appraisal payload"):
        asyncio.run(appraise_batch([_paper("broken")], _agenda()))


def test_appraise_batch_honours_max_concurrent(monkeypatch: pytest.MonkeyPatch) -> None:
    _stub_agent(monkeypatch)
    active = 0
    max_active = 0

    async def fake_run(agent, prompt):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        active -= 1
        return _appraisal_payload()

    monkeypatch.setattr(appraiser, "_run", fake_run)
    monkeypatch.setattr(
        appraiser.grounding,
        "verify",
        lambda appraisal, paper: (appraisal, []),
    )

    result = asyncio.run(
        appraise_batch([_paper(f"paper-{index}") for index in range(7)], _agenda(), max_concurrent=3)
    )

    assert len(result.appraisals) == 7
    assert max_active == 3


def test_appraise_batch_caps_caller_concurrency_at_three(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _stub_agent(monkeypatch)
    active = 0
    max_active = 0

    async def fake_run(agent, prompt):
        nonlocal active, max_active
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0)
        await asyncio.sleep(0)
        active -= 1
        return _appraisal_payload()

    monkeypatch.setattr(appraiser, "_run", fake_run)
    monkeypatch.setattr(
        appraiser.grounding,
        "verify",
        lambda appraisal, paper: (appraisal, []),
    )

    result = asyncio.run(
        appraise_batch(
            [_paper(f"paper-{index}") for index in range(8)],
            _agenda(),
            max_concurrent=4,
        )
    )

    assert len(result.appraisals) == 8
    assert max_active == 3


def test_appraise_batch_stops_waiters_after_first_quota_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The hard three-call wave preserves in-flight work and skips its waiters."""
    _stub_agent(monkeypatch)
    paper_ids = [
        "quota",
        "in-flight-1",
        "in-flight-2",
        "waiting-1",
        "waiting-2",
    ]
    entered: list[str] = []

    async def exercise():
        wave_in_flight = asyncio.Event()
        quota_observed = asyncio.Event()

        async def fake_run(agent, prompt):
            paper_id = next(
                candidate
                for candidate in paper_ids
                if f"TITLE: {candidate}\n" in prompt
            )
            entered.append(paper_id)
            if len(entered) == 3:
                wave_in_flight.set()
            await wave_in_flight.wait()
            if paper_id == "quota":
                quota_observed.set()
                raise RuntimeError("HTTP 429 RESOURCE_EXHAUSTED")
            await quota_observed.wait()
            return _appraisal_payload()

        monkeypatch.setattr(appraiser, "_run", fake_run)
        monkeypatch.setattr(
            appraiser.grounding,
            "verify",
            lambda appraisal, paper: (appraisal, []),
        )
        return await asyncio.wait_for(
            appraise_batch([_paper(paper_id) for paper_id in paper_ids], _agenda(), max_concurrent=3),
            timeout=1,
        )

    result = asyncio.run(exercise())

    assert entered == ["quota", "in-flight-1", "in-flight-2"]
    assert [appraisal.paper_id for appraisal in result.appraisals] == [
        "in-flight-1",
        "in-flight-2",
    ]
    assert [paper.doc_id for paper in result.deferred] == [
        "quota",
        "waiting-1",
        "waiting-2",
    ]


@pytest.mark.parametrize(
    ("wrapper", "paper_id"),
    [(triage, "triage-quota"), (appraise, "appraise-quota")],
)
def test_legacy_wrappers_reraise_quota_errors(
    monkeypatch: pytest.MonkeyPatch,
    wrapper,
    paper_id: str,
) -> None:
    _stub_agent(monkeypatch)

    async def fake_run(agent, prompt):
        raise RuntimeError("429 RESOURCE_EXHAUSTED")

    monkeypatch.setattr(appraiser, "_run", fake_run)

    with pytest.raises(RuntimeError, match="RESOURCE_EXHAUSTED"):
        asyncio.run(wrapper([_paper(paper_id)], _agenda()))
