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


class TestReviewerDecisionsHold:
    """A rejection must survive the arrival of one more paper.

    Findings are keyed by a hash of their supporting set, so without this a
    single new study reopens a question the reviewer already answered — and a
    system that re-asks nightly teaches its reviewer to stop reading it.
    """

    def _rejected(self, component: str, n: int) -> Appraisal:
        from provenance.models import Finding, FindingStatus
        return Finding(
            finding_id=f"synqology__{component}__abc",
            subject_key="synqology",
            component_id=component,
            statement="s", current_behavior="c",
            supporting_paper_ids=[f"doi:10.{1000+i}_p{i}" for i in range(n)],
            status=FindingStatus.REJECTED,
        )

    def test_rejected_component_is_suppressed(self):
        from provenance.agents.synthesist import _settled_components, _suppressed
        settled = _settled_components([self._rejected("mvpa", 22)])
        blocked = _suppressed("mvpa", _distinct(23), settled)
        assert blocked is not None
        assert blocked.reason_code == "settled_by_reviewer"

    def test_materially_more_evidence_reopens_it(self):
        from provenance.agents.synthesist import (
            REPROPOSE_AFTER_NEW_PAPERS, _settled_components, _suppressed,
        )
        settled = _settled_components([self._rejected("mvpa", 22)])
        grown = _distinct(22 + REPROPOSE_AFTER_NEW_PAPERS)
        assert _suppressed("mvpa", grown, settled) is None

    def test_untouched_components_are_unaffected(self):
        from provenance.agents.synthesist import _settled_components, _suppressed
        settled = _settled_components([self._rejected("mvpa", 22)])
        assert _suppressed("sleepBehavior", _distinct(5), settled) is None

    def test_approved_findings_do_not_suppress(self):
        """Approval is not a reason to stop looking at a component."""
        from provenance.models import Finding, FindingStatus
        from provenance.agents.synthesist import _settled_components
        approved = Finding(
            finding_id="f", subject_key="synqology", component_id="mvpa",
            statement="s", current_behavior="c",
            supporting_paper_ids=["doi:10.1_a"], status=FindingStatus.APPROVED,
        )
        assert _settled_components([approved]) == {}

    def test_growth_is_measured_against_the_strongest_rejection(self):
        from provenance.agents.synthesist import _settled_components
        settled = _settled_components([
            self._rejected("mvpa", 8), self._rejected("mvpa", 22),
        ])
        assert settled["mvpa"] == 22


class TestHumanDecisionsSurviveTheFleet:
    """The nightly run may recompute a Finding. It may not un-decide it.

    A freshly synthesised Finding carries status=open and empty urls as
    defaults. Merging those over an existing document reverts an approval and
    drops the pull request link — which is the worst available failure for a
    system whose whole claim is that a human stays in the loop. It happened in
    production: a run erased an approval made an hour earlier.
    """

    def test_human_owned_fields_are_listed(self):
        from provenance.store.firestore import _HUMAN_OWNED
        assert set(_HUMAN_OWNED) == {"status", "issue_url", "pr_url"}

    def test_fleet_write_preserves_a_decision(self):
        from provenance.models import FindingStatus
        from provenance.store.firestore import _HUMAN_OWNED

        prior = {
            "status": FindingStatus.APPROVED.value,
            "pr_url": "https://github.com/o/r/pull/2",
            "issue_url": "https://github.com/o/r/issues/1",
            "confidence": 0.7,
        }
        payload = {"status": "open", "pr_url": "", "issue_url": "", "confidence": 0.8}

        for field in _HUMAN_OWNED:
            if prior.get(field):
                payload[field] = prior[field]

        assert payload["status"] == "approved"
        assert payload["pr_url"].endswith("/pull/2")
        # Everything the fleet legitimately owns still updates.
        assert payload["confidence"] == 0.8

    def test_empty_prior_does_not_block_a_first_write(self):
        from provenance.store.firestore import _HUMAN_OWNED
        prior = {"status": "", "pr_url": "", "issue_url": ""}
        payload = {"status": "open", "pr_url": "", "issue_url": ""}
        for field in _HUMAN_OWNED:
            if prior.get(field):
                payload[field] = prior[field]
        assert payload["status"] == "open"


class TestOneRunDoesNotFloodTheReviewer:
    """Eleven proposals on a Tuesday is not eleven times the value of one.

    It is zero: nobody reviews eleven changes to a health algorithm, and the
    twelfth gets skimmed along with them.
    """

    def _finding(self, component: str, confidence: float):
        from provenance.models import Finding
        return Finding(
            finding_id=f"f-{component}", subject_key="synqology",
            component_id=component, statement="s", current_behavior="c",
            confidence=confidence,
        )

    def test_only_one_change_per_pillar(self):
        """mvpa and strength both feed the behavior score."""
        from provenance.agents.synthesist import _separate_colliding
        kept, deferred = _separate_colliding([
            self._finding("mvpa", 0.8), self._finding("strength", 0.7),
        ])
        assert [f.component_id for f in kept] == ["mvpa"]
        assert len(deferred) == 1
        assert deferred[0].reason_code == "pillar_collision"
        assert "behavior" in deferred[0].reason

    def test_different_pillars_both_proceed(self):
        from provenance.agents.synthesist import _separate_colliding
        kept, deferred = _separate_colliding([
            self._finding("mvpa", 0.8), self._finding("autonomic", 0.7),
        ])
        assert len(kept) == 2 and deferred == []

    def test_the_stronger_finding_is_the_one_kept(self):
        from provenance.agents.synthesist import _separate_colliding
        kept, _ = _separate_colliding([
            self._finding("mvpa", 0.9), self._finding("steps", 0.4),
        ])
        assert kept[0].component_id == "mvpa"

    def test_deferral_names_what_it_is_waiting_on(self):
        """A held proposal has to say what would unblock it."""
        from provenance.agents.synthesist import _separate_colliding
        _, deferred = _separate_colliding([
            self._finding("mvpa", 0.8), self._finding("steps", 0.5),
        ])
        assert "mvpa" in deferred[0].reason

    def test_the_cap_is_small_enough_to_be_read(self):
        from provenance.agents.synthesist import MAX_FINDINGS_PER_RUN
        assert 1 <= MAX_FINDINGS_PER_RUN <= 3
