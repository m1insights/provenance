"""Sweepability -- finding the papers whose data can be SHOWN, not just cited.

The one breakout this account has (10k-steps, 84K views) was a dose-response
curve animated so the number arrives with the motion. These tests pin the
detector that hunts for that shape, and the boundary that keeps the content
lane out of the algorithm.
"""

from __future__ import annotations

from provenance import content
from provenance.content_agenda import ITEMS, PREFIX, is_content_component, lane_items
from provenance.models import Alignment, Appraisal, Claim, EvidenceTier


def _claim(claim_id: str, statement: str, quote: str, value: float | None = None) -> Claim:
    return Claim(claim_id=claim_id, statement=statement, quote=quote, value=value)


def _appraisal(claims: list[Claim], *, tier=EvidenceTier.B, design="prospective cohort",
               reasoning="") -> Appraisal:
    return Appraisal(
        paper_id="doi:10.1000_test",
        tier=tier,
        design=design,
        component_ids=["steps"],
        alignment=Alignment.CHALLENGES,
        claims=claims,
        reasoning=reasoning,
    )


SWEEP_QUOTE = (
    "we observed a nonlinear dose-response association between daily step "
    "count and all-cause mortality, with risk reduction reaching a plateau"
)
FLAT_QUOTE = (
    "mortality risk was similar between weekend warriors and regularly "
    "active participants across the follow-up period"
)
PLAIN_QUOTE = (
    "participants in the intervention group lost more weight than controls "
    "at twelve months of follow-up in this trial"
)


class TestSweepSignals:
    def test_dose_response_language_is_a_signal(self):
        a = _appraisal([_claim("c1", "risk falls with steps", SWEEP_QUOTE, 0.60)])
        assert "dose-response" in content.sweep_signals(a)

    def test_plain_endpoint_paper_has_no_signal(self):
        a = _appraisal([_claim("c1", "lost more weight", PLAIN_QUOTE, 3.2)])
        assert content.sweep_signals(a) == []

    def test_graded_markers_need_enough_points_to_draw(self):
        """A reference quartile is in every cohort; alone it is not a curve."""
        quote = "compared with the lowest quartile of activity, hazard was lower " \
                "in every higher quartile of measured activity"
        two = _appraisal([
            _claim("c1", "q4 lower", quote, 0.70),
            _claim("c2", "q3 lower", quote, 0.80),
        ])
        assert content.sweep_signals(two) == []
        three = _appraisal([
            _claim("c1", "q4 lower", quote, 0.70),
            _claim("c2", "q3 lower", quote, 0.80),
            _claim("c3", "q2 lower", quote, 0.90),
        ])
        assert "quartile" in content.sweep_signals(three)


class TestMotionPrecedence:
    def test_sweep_needs_two_values_to_travel(self):
        one = _appraisal([_claim("c1", "risk falls", SWEEP_QUOTE, 0.60)])
        assert content.pick_motion(one) != "sweep"

    def test_dose_response_with_values_is_a_sweep(self):
        a = _appraisal([
            _claim("c1", "risk at 5,800 steps", SWEEP_QUOTE, 0.60),
            _claim("c2", "risk at 10,000 steps", SWEEP_QUOTE, 0.55),
        ])
        assert content.pick_motion(a) == "sweep"

    def test_equivalence_outranks_sweep(self):
        """A flat line must never be animated as a curve."""
        a = _appraisal([
            _claim("c1", "similar risk", FLAT_QUOTE, 0.76),
            _claim("c2", "similar risk", FLAT_QUOTE, 0.77),
        ], reasoning="reports a dose-response analysis as secondary")
        assert content.pick_motion(a) == "hold"


class TestRanking:
    def test_sweep_shape_earns_the_bonus(self):
        a = _appraisal([
            _claim("c1", "risk falls", SWEEP_QUOTE, 0.60),
            _claim("c2", "risk falls further", SWEEP_QUOTE, 0.55),
        ])
        _, reasons = content.score(a, None, posted=set())
        assert any("sweep-shaped" in r for r in reasons)

    def test_sweepable_filter_narrows_the_pool(self):
        sweep = _appraisal([
            _claim("c1", "risk falls", SWEEP_QUOTE, 0.60),
            _claim("c2", "risk falls further", SWEEP_QUOTE, 0.55),
        ])
        flat = _appraisal([_claim("c1", "lost weight", PLAIN_QUOTE, 3.2)])
        flat = flat.model_copy(update={"paper_id": "doi:10.2000_other"})
        picks = content.candidates([sweep, flat], {}, sweepable=True)
        assert [c.paper_id for c in picks] == ["doi:10.1000_test"]
        assert picks[0].sweep_signals


class TestContentLane:
    def test_every_lane_item_carries_the_guard_prefix(self):
        """The prefix IS the synthesist's guard key; an item without it could
        converge into a pull request for an algorithm rule that does not exist."""
        assert all(item.component_id.startswith(PREFIX) for item in ITEMS)
        assert all(is_content_component(item.component_id) for item in ITEMS)

    def test_lane_items_deduplicate_against_a_stored_agenda(self):
        existing = {ITEMS[0].component_id}
        remaining = lane_items(existing)
        assert ITEMS[0].component_id not in {i.component_id for i in remaining}
        assert len(remaining) == len(ITEMS) - 1

    def test_lane_rules_state_the_belief_not_an_algorithm(self):
        """`current_rule` holds the folk number under test, flagged as such,
        so an appraiser reading it cannot mistake it for a scoring rule."""
        assert all("CONTENT LANE" in item.current_rule for item in ITEMS)
        assert all(item.weight == 0.0 for item in ITEMS)

    def test_lane_queries_hunt_the_sweep_shape(self):
        assert all(
            any("dose-response" in c or "dose response" in c for c in item.search_concepts)
            for item in ITEMS
        )
