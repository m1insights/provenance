"""The only checks in this system that run AFTER a proposal exists.

Both of the worst bugs this project hit were the same shape: something true
when written that quietly stopped being true. These are the checks that would
have caught them.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

from provenance.health import (
    STALE_AFTER_DAYS,
    _decision_problems,
    _merge_problems,
    _staleness_problems,
)
from provenance.models import Finding, FindingStatus

NOW = datetime(2026, 8, 18, 12, 0, tzinfo=timezone.utc)


def _finding(status: FindingStatus = FindingStatus.OPEN) -> Finding:
    return Finding(
        finding_id="f1", subject_key="synqology", component_id="mvpa",
        statement="s", current_behavior="c",
        pr_url="https://github.com/o/r/pull/2", status=status,
    )


def _pull(**kw) -> dict:
    base = {
        "state": "open", "draft": False, "mergeable": True,
        "base": {"ref": "launch"},
        "created_at": NOW.strftime("%Y-%m-%dT%H:%M:%SZ"),
    }
    return base | kw


class TestMergeability:
    def test_conflict_is_reported(self):
        problems = _merge_problems(_pull(mergeable=False))
        assert problems and "no longer applies" in problems[0]
        assert "launch" in problems[0]

    def test_clean_merge_is_silent(self):
        assert _merge_problems(_pull(mergeable=True)) == []

    def test_unknown_mergeability_is_not_an_alarm(self):
        """GitHub reports null while it computes. Null is not a conflict, and
        treating it as one fires on every freshly opened pull request."""
        assert _merge_problems(_pull(mergeable=None)) == []


class TestDecisionMatchesGitHub:
    def test_approved_but_still_draft_is_caught(self):
        """This exact state shipped: an approval that never reached GitHub."""
        problems = _decision_problems(_finding(FindingStatus.APPROVED), _pull(draft=True))
        assert problems and "never reached GitHub" in problems[0]

    def test_approved_and_undrafted_is_silent(self):
        assert _decision_problems(_finding(FindingStatus.APPROVED), _pull(draft=False)) == []

    def test_rejected_but_open_for_review_is_caught(self):
        problems = _decision_problems(_finding(FindingStatus.REJECTED), _pull(draft=False))
        assert problems and "rejected" in problems[0].lower()

    def test_undecided_is_silent_either_way(self):
        for draft in (True, False):
            assert _decision_problems(_finding(FindingStatus.OPEN), _pull(draft=draft)) == []


class TestStaleness:
    def _aged(self, days: int) -> dict:
        opened = NOW - timedelta(days=days)
        return _pull(created_at=opened.strftime("%Y-%m-%dT%H:%M:%SZ"))

    def test_forgotten_proposal_is_reported(self):
        problems = _staleness_problems(_finding(), self._aged(STALE_AFTER_DAYS + 1), NOW)
        assert problems and "undecided" in problems[0]

    def test_recent_proposal_is_silent(self):
        assert _staleness_problems(_finding(), self._aged(2), NOW) == []

    def test_a_decided_proposal_is_never_stale(self):
        """Age only matters while nobody has decided."""
        old = self._aged(90)
        assert _staleness_problems(_finding(FindingStatus.APPROVED), old, NOW) == []
        assert _staleness_problems(_finding(FindingStatus.REJECTED), old, NOW) == []
