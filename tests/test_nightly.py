"""The morning briefing is the only place a night's reading is visible outside
Cloud Run logs. If the kept papers never reach the email template, "kept one
paper" is all the reader gets -- exactly the regression this pins.
"""

from __future__ import annotations

from unittest.mock import patch

from provenance.models import Appraisal, Claim, EvidenceTier, Paper, SourceName
from provenance.nightly import _notify


def _fixtures():
    paper = Paper(
        doc_id="doi:10.1_x", source=SourceName.PUBMED,
        title="Weekend warrior activity and mortality",
        journal="Ann Intern Med", url="https://pubmed.ncbi.nlm.nih.gov/1/",
    )
    appraisal = Appraisal(
        paper_id="doi:10.1_x", tier=EvidenceTier.B,
        design="prospective cohort study", sample_size=51650,
        claims=[Claim(claim_id="c1", statement="x",
                      quote="weekend warriors had lower all-cause mortality")],
    )
    return paper, appraisal


class TestBriefingCarriesTheNightsPapers:
    def test_kept_papers_reach_briefing_email(self):
        """A regression test for nightly.py shadowing appraisals/papers with
        empty dicts before building the (paper, appraisal) pairs -- which made
        "What it kept" render nothing no matter how much the night kept."""
        paper, appraisal = _fixtures()

        with patch("provenance.nightly.notify.mail_config") as mail_config, \
             patch("provenance.nightly.notify.briefing_email") as briefing_email, \
             patch("provenance.nightly.notify.send", return_value="email-id"):
            mail_config.return_value.configured = True
            briefing_email.return_value = ("subject", "<html></html>")

            _notify(
                db=None, subject=None, fresh=[], prior=[],
                run={}, appraisals=[appraisal], rejections=[],
                papers={"doi:10.1_x": paper},
            )

            (_run, pairs, *_rest), _kwargs = briefing_email.call_args
            assert pairs == [(paper, appraisal)]
