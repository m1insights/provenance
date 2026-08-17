"""The last check before a number is printed over a citation.

The Storyteller has no field in which to write a figure, but it writes prose,
and prose is where a fabricated number would hide. These tests are the
adversarial ones: each imagines a plausible sentence a model might produce and
asserts the gate refuses it.
"""

from __future__ import annotations

from provenance.creative import (
    ChartPlan,
    ChartType,
    SlidePlan,
    StoryPlan,
    check_copy,
    resolve,
)
from provenance.models import Appraisal, Claim, EvidenceTier, Finding, Paper, SourceName

CLAIMS = {
    "c1": Claim(
        claim_id="c1",
        statement="Weekend warriors had lower mortality",
        quote="weekend warriors had a hazard ratio of 0.65 (95% CI 0.48-0.87)",
        value=0.65, ci_low=0.48, ci_high=0.87,
    ),
    "c2": Claim(
        claim_id="c2",
        statement="Guideline volume",
        quote="participants accumulating at least 150 minutes per week of activity",
        value=150, unit="minutes",
    ),
}


def _plan(**slide) -> StoryPlan:
    base = {"kicker": "NEW EVIDENCE", "headline": "Pace didn't matter", "body": ""}
    return StoryPlan(slides=[SlidePlan(**(base | slide))])


class TestFabricatedNumbers:
    def test_invented_percentage_is_refused(self):
        """The archetypal failure: a confident figure from nowhere."""
        failures = check_copy(_plan(headline="Cuts your risk by 43%"), CLAIMS)
        assert failures and "43" in failures[0].detail

    def test_invented_sample_size_is_refused(self):
        failures = check_copy(_plan(body="Across 400,000 adults over 20 years."), CLAIMS)
        assert any("400000" in f.detail or "400,000" in f.detail for f in failures)

    def test_number_in_the_kicker_is_checked_too(self):
        """Every text field, not just the headline."""
        failures = check_copy(_plan(kicker="THE 37% FINDING"), CLAIMS)
        assert failures and failures[0].field == "kicker"

    def test_axis_labels_are_checked(self):
        plan = _plan(chart=ChartPlan(type=ChartType.BAR, claim_ids=["c1"],
                                     point_labels=["up to 9,500 steps"]))
        failures = check_copy(plan, CLAIMS)
        assert any(f.field == "chart.point_labels" for f in failures)


class TestGroundedNumbersPass:
    def test_exact_claim_value_passes(self):
        assert check_copy(_plan(body="150 minutes a week."), CLAIMS) == []

    def test_confidence_bounds_pass(self):
        assert check_copy(_plan(body="0.48 to 0.87, adjusted."), CLAIMS) == []

    def test_hazard_ratio_expressed_as_percent_passes(self):
        """A hazard ratio of 0.65 honestly reads as '35% lower risk'.

        That is arithmetic on a verified number, not an invention, so both
        renderings are allowed. Refusing it would push writers toward vaguer,
        less useful copy.
        """
        assert check_copy(_plan(headline="*35%* lower risk of dying"), CLAIMS) == []

    def test_ratio_itself_passes(self):
        assert check_copy(_plan(body="A hazard ratio of 0.65."), CLAIMS) == []

    def test_slide_indices_and_years_are_not_treated_as_claims(self):
        """'1 of 4' and '2025' must not require an appraisal to support them."""
        assert check_copy(_plan(body="In 2025, 3 of 4 analyses agreed."), CLAIMS) == []

    def test_prose_without_numbers_passes(self):
        assert check_copy(_plan(headline="Volume did the work, not pace"), CLAIMS) == []


class TestReferentialIntegrity:
    def test_unknown_feature_claim_is_refused(self):
        failures = check_copy(_plan(feature_claim_id="c99"), CLAIMS)
        assert failures and "c99" in failures[0].detail

    def test_unknown_chart_claim_is_refused(self):
        plan = _plan(chart=ChartPlan(type=ChartType.BAR, claim_ids=["c1", "c404"]))
        failures = check_copy(plan, CLAIMS)
        assert any("c404" in f.detail for f in failures)

    def test_every_slide_is_reported_by_index(self):
        plan = StoryPlan(slides=[
            SlidePlan(kicker="A", headline="fine"),
            SlidePlan(kicker="B", headline="Risk fell 88%"),
        ])
        failures = check_copy(plan, CLAIMS)
        assert failures and failures[0].slide == 2


class TestResolve:
    """Figures reach the canvas from the record, never from the plan."""

    def _fixtures(self):
        paper = Paper(
            doc_id="doi:10.1_x", source=SourceName.PUBMED,
            title="Weekend warrior activity and mortality",
            journal="Ann Intern Med", authors=["Xu Y"],
            url="https://pubmed.ncbi.nlm.nih.gov/1/",
        )
        appraisal = Appraisal(
            paper_id="doi:10.1_x", tier=EvidenceTier.B,
            design="prospective cohort study", sample_size=51650,
            claims=list(CLAIMS.values()),
        )
        finding = Finding(
            finding_id="f1", subject_key="synqology", component_id="mvpa",
            statement="s", current_behavior="c", supporting_paper_ids=["doi:10.1_x"],
        )
        return finding, {"doi:10.1_x": paper}, {"doi:10.1_x": appraisal}

    def test_figure_comes_from_the_claim(self):
        finding, papers, appraisals = self._fixtures()
        plan = _plan(feature_claim_id="c1")
        payload = resolve(plan, finding, CLAIMS, papers, appraisals)
        # 0.65 hazard ratio renders as the 35% reduction a reader can act on.
        assert payload["slides"][0]["figure"]["value"] == "35%"

    def test_bar_values_come_from_claims(self):
        finding, papers, appraisals = self._fixtures()
        plan = _plan(chart=ChartPlan(type=ChartType.BAR, claim_ids=["c1", "c2"],
                                     point_labels=["ratio", "minutes"]))
        payload = resolve(plan, finding, CLAIMS, papers, appraisals)
        assert [b["value"] for b in payload["slides"][0]["chart"]["bars"]] == [0.65, 150]

    def test_source_line_is_built_from_the_record(self):
        finding, papers, appraisals = self._fixtures()
        payload = resolve(_plan(), finding, CLAIMS, papers, appraisals)
        source = payload["slides"][0]["source"]
        assert source["journal"] == "Ann Intern Med"
        assert source["sample"] == "n=51,650"

    def test_chart_is_omitted_when_no_claim_supplies_a_value(self):
        """Better no chart than an empty one implying missing data."""
        finding, papers, appraisals = self._fixtures()
        plan = _plan(chart=ChartPlan(type=ChartType.BAR, claim_ids=["c404"]))
        payload = resolve(plan, finding, CLAIMS, papers, appraisals)
        assert "chart" not in payload["slides"][0]


class TestCausalLanguage:
    """A cohort study shows association. Copy that says otherwise is the most
    common way health content overstates its evidence — and unlike a fabricated
    figure, nothing about it looks wrong."""

    def test_causal_verb_on_observational_evidence_is_refused(self):
        from provenance.creative import check_language
        plan = _plan(headline="Concentrated training *reduces* cardiovascular risk")
        failures = check_language(plan, observational=True)
        assert failures and "causation" in failures[0].detail

    def test_association_phrasing_passes(self):
        from provenance.creative import check_language
        plan = _plan(headline="Concentrated training was *linked to* lower risk")
        assert check_language(plan, observational=True) == []

    def test_causal_verb_is_allowed_on_trial_evidence(self):
        from provenance.creative import check_language
        plan = _plan(headline="Training *reduces* resting heart rate")
        assert check_language(plan, observational=False) == []

    def test_intensifiers_are_refused_regardless_of_design(self):
        from provenance.creative import check_language
        for observational in (True, False):
            plan = _plan(headline="A *dramatically* lower risk")
            failures = check_language(plan, observational=observational)
            assert failures and "overstates" in failures[0].detail

    def test_hype_words_are_refused(self):
        from provenance.creative import check_language
        plan = _plan(body="A groundbreaking result that is nothing short of a miracle.")
        assert len(check_language(plan, observational=False)) >= 2

    def test_design_detection_reads_the_appraisals(self):
        from provenance.creative import _is_observational
        from provenance.models import Appraisal, EvidenceTier
        cohort = Appraisal(paper_id="a", tier=EvidenceTier.B, design="prospective cohort study")
        trial = Appraisal(paper_id="b", tier=EvidenceTier.A, design="randomised controlled trial")
        assert _is_observational({"a": cohort}, ["a"]) is True
        assert _is_observational({"a": cohort, "b": trial}, ["a", "b"]) is False

    def test_no_evidence_is_treated_as_observational(self):
        """The cautious default when design is unknown."""
        from provenance.creative import _is_observational
        assert _is_observational({}, []) is True

    def test_meta_analysis_of_cohorts_stays_observational(self):
        """Pooling cohort studies buys precision, not causal warrant."""
        from provenance.creative import _is_observational
        from provenance.models import Appraisal, EvidenceTier
        meta = Appraisal(paper_id="m", tier=EvidenceTier.B,
                         design="systematic review and meta-analysis of cohort studies")
        assert _is_observational({"m": meta}, ["m"]) is True

    def test_meta_analysis_of_trials_licenses_causation(self):
        from provenance.creative import _is_observational
        from provenance.models import Appraisal, EvidenceTier
        meta = Appraisal(paper_id="m", tier=EvidenceTier.A,
                         design="meta-analysis of randomised controlled trials")
        assert _is_observational({"m": meta}, ["m"]) is False

    def test_one_cohort_among_trials_does_not_block_causation(self):
        from provenance.creative import _is_observational
        from provenance.models import Appraisal, EvidenceTier
        cohort = Appraisal(paper_id="a", tier=EvidenceTier.B, design="prospective cohort study")
        trial = Appraisal(paper_id="b", tier=EvidenceTier.A, design="randomised controlled trial")
        assert _is_observational({"a": cohort, "b": trial}, ["a", "b"]) is False
