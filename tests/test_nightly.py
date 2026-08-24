"""The morning briefing is the only place a night's reading is visible outside
Cloud Run logs. If the kept papers never reach the email template, "kept one
paper" is all the reader gets -- exactly the regression this pins.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

from provenance.agents.scout import SweepResult
from provenance.config import SUBJECTS
from provenance.models import (
    Appraisal,
    Claim,
    EvidenceTier,
    Paper,
    ResearchAgenda,
    SourceName,
)
from provenance.nightly import _notify, run


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


class _StubDb:
    """Enough Firestore to satisfy the Sunday digest.

    Without it this test passes six days a week and fails on the seventh: the
    digest branch only runs on a Sunday, and it is the only part of ``_notify``
    that touches the database.
    """

    class _Collection:
        def stream(self):
            return iter(())

        def select(self, _fields):
            return self

    def collection(self, _name):
        return self._Collection()


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
                db=_StubDb(), subject=None, fresh=[], prior=[],
                run={}, appraisals=[appraisal], rejections=[],
                papers={"doi:10.1_x": paper},
            )

            (_run, pairs, *_rest), _kwargs = briefing_email.call_args
            assert pairs == [(paper, appraisal)]


class _RunDb:
    """Firestore boundary for a complete run with an empty stored corpus."""

    def __init__(self):
        self.saved_run = None

    class _Collection:
        def __init__(self, owner, name):
            self.owner = owner
            self.name = name

        def stream(self):
            return iter(())

        def document(self, _doc_id):
            owner = self.owner
            name = self.name

            class _Document:
                def set(self, payload):
                    if name == "provenance_runs":
                        owner.saved_run = dict(payload)

            return _Document()

    def collection(self, name):
        return self._Collection(self, name)


class TestSynthesisFailureIsFailSoft:
    def test_quota_failure_still_sends_briefing_and_records_run(self):
        """A model quota error must not make a completed reading night invisible."""
        db = _RunDb()
        agenda = ResearchAgenda(
            subject_key="synqology", algorithm_version="VI test",
            source_digest="digest", items=[],
        )
        result = SweepResult(agenda=agenda)

        async def failed_synthesis(*_args, **_kwargs):
            raise RuntimeError("429 RESOURCE_EXHAUSTED")

        with patch("provenance.nightly.store.client", return_value=db), \
             patch("provenance.nightly.store.known_paper_ids", return_value=set()), \
             patch("provenance.nightly.store.save_agenda"), \
             patch("provenance.nightly.store.save_papers"), \
             patch("provenance.nightly.store.save_rejections"), \
             patch("provenance.nightly.sweep", return_value=result), \
             patch("provenance.nightly.synthesise", side_effect=failed_synthesis), \
             patch("provenance.nightly.pr_health.sweep", return_value={}), \
             patch("provenance.nightly._notify", return_value={"sent": ["briefing"]}):
            summary = asyncio.run(run(SUBJECTS["synqology"]))

        assert summary["synthesis_error"] == {
            "type": "RuntimeError", "message": "429 RESOURCE_EXHAUSTED",
        }
        assert summary["findings_new"] == 0
        assert summary["notified"] == {"sent": ["briefing"]}
        assert db.saved_run == summary
