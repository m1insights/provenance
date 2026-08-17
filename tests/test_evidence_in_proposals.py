"""No proposal may leave this system without its evidence attached.

That is a property of the code path, not a habit of the model, so it is
asserted here: whatever else changes, a pull request body that omits the
studies -- or the links to them -- fails this suite.
"""

from __future__ import annotations

from datetime import date

import pytest

from provenance.agents import engineer
from provenance.agents.engineer import EngineeringPlan, _cohort_overlap, _evidence_markdown
from provenance.config import SYNQOLOGY
from provenance.models import (
    Alignment,
    Appraisal,
    Claim,
    EvidenceTier,
    Finding,
    Paper,
    ProposedChange,
    SourceName,
)

QUOTE = "weekend warriors had lower all-cause mortality than inactive participants"


def _paper(index: int, *, cohort: str = "", title: str = "") -> Paper:
    return Paper(
        doc_id=f"doi:10.{1000 + index}_study{index}",
        source=SourceName.PUBMED,
        title=title or f"Weekend warrior activity and mortality, study {index}",
        abstract=f"We analysed {cohort} participants. {QUOTE}.",
        journal="Ann Intern Med",
        published=date(2025, 6, 1),
        pmid=f"4000000{index}",
        authors=[f"Author{index} X"],
        url=f"https://pubmed.ncbi.nlm.nih.gov/4000000{index}/",
    )


def _appraisal(index: int, *, tier: EvidenceTier = EvidenceTier.B, n: int = 50_000) -> Appraisal:
    return Appraisal(
        paper_id=f"doi:10.{1000 + index}_study{index}",
        tier=tier,
        design="prospective cohort study",
        sample_size=n,
        follow_up="9.5 years",
        component_ids=["mvpa"],
        alignment=Alignment.CHALLENGES,
        claims=[Claim(claim_id="c1", statement="Comparable benefit", quote=QUOTE)],
    )


def _finding(count: int = 3) -> Finding:
    return Finding(
        finding_id="synqology__mvpa__abc123",
        subject_key="synqology",
        component_id="mvpa",
        statement="Concentrated activity gives comparable mortality benefit.",
        current_behavior="Day factor denominator is 3.",
        supporting_paper_ids=[f"doi:10.{1000 + i}_study{i}" for i in range(count)],
        tier_counts={"B": count},
        proposed_changes=[
            ProposedChange(
                file_path="tapntrack/Services/ShiftWorkAdjuster.swift",
                symbol="mvpaDayFactorDenominator",
                current_value="3.0",
                proposed_value="2.0",
                rationale="Weekend warrior evidence",
            )
        ],
        confidence=0.7,
    )


def _corpus(count: int = 3, *, cohort: str = "") -> tuple[dict, dict]:
    appraisals = {f"doi:10.{1000 + i}_study{i}": _appraisal(i) for i in range(count)}
    papers = {f"doi:10.{1000 + i}_study{i}": _paper(i, cohort=cohort) for i in range(count)}
    return appraisals, papers


class TestEvidenceMarkdown:
    def test_every_supporting_study_appears(self):
        appraisals, papers = _corpus(5)
        rendered = _evidence_markdown(_finding(5), appraisals, papers)
        for paper in papers.values():
            assert paper.title in rendered

    def test_every_study_is_linked(self):
        """A citation a reviewer cannot click is a citation they will not check."""
        appraisals, papers = _corpus(4)
        rendered = _evidence_markdown(_finding(4), appraisals, papers)
        for paper in papers.values():
            assert paper.url in rendered
        assert rendered.count("pubmed.ncbi.nlm.nih.gov") >= 4

    def test_tier_sample_size_and_follow_up_are_shown(self):
        appraisals, papers = _corpus(3)
        rendered = _evidence_markdown(_finding(3), appraisals, papers)
        assert "50,000" in rendered
        assert "9.5 years" in rendered
        assert "prospective cohort study" in rendered

    def test_verified_quotes_are_included(self):
        appraisals, papers = _corpus(3)
        rendered = _evidence_markdown(_finding(3), appraisals, papers)
        assert QUOTE in rendered
        assert "<details>" in rendered

    def test_pipes_in_titles_do_not_break_the_table(self):
        """An unescaped pipe silently splits a row into the wrong columns."""
        appraisals, papers = _corpus(1)
        key = "doi:10.1000_study0"
        papers[key] = _paper(0, title="Activity | mortality: a cohort")
        rendered = _evidence_markdown(_finding(1), appraisals, papers)
        assert "Activity \\| mortality" in rendered

    def test_strongest_evidence_is_listed_first(self):
        appraisals, papers = _corpus(3)
        appraisals["doi:10.1002_study2"] = _appraisal(2, tier=EvidenceTier.C, n=300)
        rendered = _evidence_markdown(_finding(3), appraisals, papers)
        assert rendered.index("| B |") < rendered.index("| C |")

    def test_missing_records_are_skipped_not_fabricated(self):
        appraisals, papers = _corpus(3)
        del papers["doi:10.1001_study1"]
        rendered = _evidence_markdown(_finding(3), appraisals, papers)
        assert "study 1" not in rendered
        assert "2 appraised studies" in rendered


class TestCohortOverlap:
    def test_shared_cohort_is_flagged(self):
        """Nine re-analyses of one biobank are not nine replications."""
        appraisals, papers = _corpus(4, cohort="UK Biobank")
        rows = [(appraisals[k], papers[k]) for k in papers]
        warning = _cohort_overlap(rows)
        assert "UK Biobank" in warning and "4 of 4" in warning

    def test_below_threshold_is_not_flagged(self):
        appraisals, papers = _corpus(5)
        papers["doi:10.1000_study0"] = _paper(0, cohort="UK Biobank")
        rows = [(appraisals[k], papers[k]) for k in papers]
        assert _cohort_overlap(rows) == ""

    def test_independent_studies_produce_no_warning(self):
        appraisals, papers = _corpus(5)
        rows = [(appraisals[k], papers[k]) for k in papers]
        assert _cohort_overlap(rows) == ""


class TestProposalsAlwaysCarryEvidence:
    """The guarantee itself: no PR or issue body escapes without the studies."""

    @pytest.fixture
    def captured(self, monkeypatch):
        seen: dict[str, str] = {}

        def fake_issue(*, repo, title, body, labels=None):
            seen["issue"] = body
            return "https://github.com/x/y/issues/1"

        def fake_pr(subject, *, repo, branch, base, title, body, edits, commit_message, draft=True):
            seen["pr"] = body
            return "https://github.com/x/y/pull/2"

        monkeypatch.setattr(engineer.github, "open_issue", fake_issue)
        monkeypatch.setattr(engineer.github, "open_pull_request", fake_pr)
        return seen

    def _plan(self) -> EngineeringPlan:
        return EngineeringPlan(
            resolved_symbol="mvpaDayFactorDenominator",
            symbol_location="tapntrack/Services/ShiftWorkAdjuster.swift:56",
            edits=[{"path": "a.swift", "old": "3.0", "new": "2.0", "why": "lower target"}],
            issue_title="Lower the MVPA credit-day target",
            issue_body="Body.",
            pr_title="fix: lower MVPA day factor denominator",
            pr_body="Body.",
            commit_message="fix: lower denominator",
            dissent="Healthy-user confounding.",
        )

    def test_pull_request_body_carries_the_evidence(self, captured):
        appraisals, papers = _corpus(3)
        engineer.execute(
            SYNQOLOGY, _finding(3), self._plan(), appraisals, papers,
            repo="x/y", base="launch", run_tests=False,
        )
        body = captured["pr"]
        assert "## Evidence" in body
        assert "pubmed.ncbi.nlm.nih.gov" in body
        assert QUOTE in body

    def test_issue_body_carries_the_evidence(self, captured):
        appraisals, papers = _corpus(3)
        engineer.execute(
            SYNQOLOGY, _finding(3), self._plan(), appraisals, papers,
            repo="x/y", base="launch", run_tests=False,
        )
        assert "## Evidence" in captured["issue"]
        assert "pubmed.ncbi.nlm.nih.gov" in captured["issue"]

    def test_cross_repo_obligation_is_stated(self, captured):
        """A change that cannot be made here must still be recorded here."""
        appraisals, papers = _corpus(3)
        engineer.execute(
            SYNQOLOGY, _finding(3), self._plan(), appraisals, papers,
            repo="x/y", base="launch", run_tests=False,
        )
        assert "vi_system_explainer.py" in captured["pr"]
        assert "synq_insights" in captured["pr"]

    def test_dissent_survives_into_the_body(self, captured):
        appraisals, papers = _corpus(3)
        engineer.execute(
            SYNQOLOGY, _finding(3), self._plan(), appraisals, papers,
            repo="x/y", base="launch", run_tests=False,
        )
        assert "Healthy-user confounding." in captured["pr"]
