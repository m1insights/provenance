"""The convergence gate decides whether a production algorithm gets touched.

It runs before any model is consulted, so it is testable in full.
"""

from __future__ import annotations

from provenance.agents.synthesist import (
    MIN_CHALLENGERS,
    gate,
)
from provenance.models import Alignment, Appraisal, Claim, EvidenceTier

QUOTE = "bout duration did not modify the mortality benefit of activity"


def _appraisal(
    paper_id: str,
    *,
    tier: EvidenceTier = EvidenceTier.B,
    alignment: Alignment = Alignment.CHALLENGES,
    component: str = "mvpa",
) -> Appraisal:
    return Appraisal(
        paper_id=paper_id,
        tier=tier,
        design="prospective cohort",
        component_ids=[component],
        alignment=alignment,
        claims=[Claim(claim_id="c1", statement="x", quote=QUOTE)],
    )


def _distinct(n: int, **kwargs) -> list[Appraisal]:
    """n challengers from n different DOI registrants."""
    return [_appraisal(f"doi:10.{1000 + i}_study{i}", **kwargs) for i in range(n)]


class TestConvergenceCount:
    def test_single_paper_never_opens_a_finding(self):
        """The headline discipline: one study does not move an algorithm."""
        challengers, blocked = gate("mvpa", _distinct(1))
        assert challengers == []
        assert blocked is not None
        assert blocked.reason_code == "insufficient_convergence"

    def test_below_threshold_is_blocked(self):
        _, blocked = gate("mvpa", _distinct(MIN_CHALLENGERS - 1))
        assert blocked is not None and blocked.reason_code == "insufficient_convergence"

    def test_at_threshold_passes(self):
        challengers, blocked = gate("mvpa", _distinct(MIN_CHALLENGERS))
        assert blocked is None
        assert len(challengers) == MIN_CHALLENGERS

    def test_supporting_papers_do_not_count_toward_convergence(self):
        """Agreement with the status quo is not a reason to change it."""
        appraisals = _distinct(MIN_CHALLENGERS, alignment=Alignment.SUPPORTS)
        _, blocked = gate("mvpa", appraisals)
        assert blocked is not None and blocked.reason_code == "insufficient_convergence"

    def test_other_components_do_not_count(self):
        appraisals = _distinct(MIN_CHALLENGERS, component="sleepBehavior")
        _, blocked = gate("mvpa", appraisals)
        assert blocked is not None


class TestEvidenceStrength:
    def test_all_weak_evidence_is_blocked(self):
        """Three tier-C studies are a hypothesis, not a mandate."""
        _, blocked = gate("mvpa", _distinct(MIN_CHALLENGERS, tier=EvidenceTier.C))
        assert blocked is not None and blocked.reason_code == "no_strong_evidence"

    def test_one_strong_among_weak_passes(self):
        appraisals = _distinct(MIN_CHALLENGERS, tier=EvidenceTier.C)
        appraisals[0] = _appraisal("doi:10.9999_strong", tier=EvidenceTier.A)
        challengers, blocked = gate("mvpa", appraisals)
        assert blocked is None and len(challengers) == MIN_CHALLENGERS

    def test_tier_d_does_not_count_as_strong(self):
        _, blocked = gate("mvpa", _distinct(MIN_CHALLENGERS, tier=EvidenceTier.D))
        assert blocked is not None and blocked.reason_code == "no_strong_evidence"


class TestIndependence:
    def test_same_registrant_is_blocked(self):
        """Three papers from one consortium are one finding reported thrice."""
        appraisals = [_appraisal(f"doi:10.1001_study{i}") for i in range(MIN_CHALLENGERS)]
        _, blocked = gate("mvpa", appraisals)
        assert blocked is not None and blocked.reason_code == "single_source"
        assert "10.1001" in blocked.reason

    def test_two_registrants_pass(self):
        appraisals = [
            _appraisal("doi:10.1001_a"),
            _appraisal("doi:10.1001_b"),
            _appraisal("doi:10.2002_c"),
        ]
        challengers, blocked = gate("mvpa", appraisals)
        assert blocked is None and len(challengers) == 3


class TestGateOrdering:
    def test_count_is_checked_before_strength(self):
        """Reason codes must name the first unmet condition, not the last.

        A log that reports 'no strong evidence' for a component with one paper
        misdescribes why nothing happened.
        """
        _, blocked = gate("mvpa", _distinct(1, tier=EvidenceTier.D))
        assert blocked.reason_code == "insufficient_convergence"

    def test_empty_input_reports_zero(self):
        _, blocked = gate("mvpa", [])
        assert blocked is not None and "0 challenging paper" in blocked.reason
