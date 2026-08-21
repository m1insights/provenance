"""A review link is a credential that arrives by email.

Email is a hostile transport: messages get forwarded, scanned, previewed and
archived. These tests pin the properties that make a link safe to send through
one.
"""

from __future__ import annotations

from provenance.notify import LINK_TTL_HOURS, sign, verify

KEY = "a-console-write-token"


class TestReviewLinkTokens:
    def test_round_trips(self):
        token = sign("synqology__mvpa__abc", KEY)
        assert verify(token, KEY) == "synqology__mvpa__abc"

    def test_a_different_key_does_not_verify(self):
        token = sign("synqology__mvpa__abc", KEY)
        assert verify(token, "some-other-token") is None

    def test_tampering_is_rejected(self):
        token = sign("synqology__mvpa__abc", KEY)
        assert verify(token[:-3] + "zzz", KEY) is None

    def test_garbage_is_rejected_without_raising(self):
        """Anything can arrive in a URL path."""
        for junk in ("", "....", "not-base64!!", "a" * 500):
            assert verify(junk, KEY) is None

    def test_an_expired_link_stops_working(self):
        token = sign("synqology__mvpa__abc", KEY, ttl_hours=-1)
        assert verify(token, KEY) is None

    def test_the_window_survives_a_weekend(self):
        """A proposal arriving Friday must still be decidable Monday."""
        assert LINK_TTL_HOURS >= 72

    def test_a_token_names_exactly_one_finding(self):
        """Scoping is what stops a forwarded email deciding anything else."""
        token = sign("finding-a", KEY)
        assert verify(token, KEY) == "finding-a"
        assert verify(token, KEY) != "finding-b"


class TestEmailComposition:
    def _fixtures(self):
        from provenance.models import (
            Appraisal, Claim, EvidenceTier, Finding, Paper, ProposedChange, SourceName,
        )
        paper = Paper(
            doc_id="doi:10.1_x", source=SourceName.PUBMED,
            title="Weekend warrior activity and mortality",
            journal="Ann Intern Med", authors=["Xu Y", "Second B"],
            url="https://pubmed.ncbi.nlm.nih.gov/1/",
        )
        appraisal = Appraisal(
            paper_id="doi:10.1_x", tier=EvidenceTier.B,
            design="prospective cohort study", sample_size=51650,
            claims=[Claim(claim_id="c1", statement="x",
                          quote="weekend warriors had lower all-cause mortality")],
        )
        finding = Finding(
            finding_id="f1", subject_key="synqology", component_id="mvpa",
            statement="Concentrated activity tracked with the same outcomes.",
            current_behavior="Day factor denominator is 3.",
            supporting_paper_ids=["doi:10.1_x"], tier_counts={"B": 1},
            confidence=0.7,
            proposed_changes=[ProposedChange(
                file_path="a.swift", symbol="mvpaDayFactorDenominator",
                current_value="3.0", proposed_value="2.0", rationale="r",
            )],
        )
        return finding, {"doi:10.1_x": appraisal}, {"doi:10.1_x": paper}

    def _config(self):
        from provenance.notify import MailConfig
        return MailConfig(
            api_key="k", sender="a@b.c", recipient="d@e.f",
            console_url="https://console.example", signing_key=KEY,
        )

    def test_decision_email_carries_the_decision_not_just_a_ping(self):
        """A notification that only says 'something happened' is a dashboard
        with extra steps."""
        from provenance.notify import decision_email
        finding, appraisals, papers = self._fixtures()
        subject, html = decision_email(finding, appraisals, papers, self._config())

        assert "mvpa" in subject
        assert "3.0" in html and "2.0" in html          # the actual change
        assert "Ann Intern Med" not in subject           # subject stays short
        assert "prospective cohort study" in html        # evidence strength
        assert "Review and decide" in html               # one clear action

    def test_the_link_is_scoped_and_verifiable(self):
        from provenance.notify import decision_email
        import re
        finding, appraisals, papers = self._fixtures()
        _, html = decision_email(finding, appraisals, papers, self._config())
        match = re.search(r"/review/([A-Za-z0-9_-]+)", html)
        assert match and verify(match.group(1), KEY) == "f1"

    def test_digest_leads_with_what_was_refused(self):
        """Anyone can produce findings. The number worth showing is how much
        was read and thrown away."""
        from provenance.notify import digest_email
        subject, html = digest_email(
            {"papers_read": 507, "rejected_total": 486,
             "reasons": {"not_relevant": 470, "ungrounded_claim": 9}},
            [], self._config(),
        )
        assert "507" in subject and "507" in html
        assert "486" in html
        # The reason a person reads, not the code the log stores.
        assert "did not bear on any rule we watch" in html
        assert "Nothing is waiting on you" in html

    def test_digest_lists_what_is_pending(self):
        from provenance.notify import digest_email
        finding, _, _ = self._fixtures()
        _, html = digest_email({"papers_read": 1, "rejected_total": 0, "reasons": {}},
                               [finding], self._config())
        assert "Waiting on you" in html and "mvpa" in html


class TestTheBriefingIsReadableWithoutADegree:
    """The briefing is read at 6am on a phone by one person, who is not a
    clinician. A study that arrives as a title, a tier letter and a quote from
    an abstract has been logged, not communicated.
    """

    def _appraised(self, **overrides):
        from provenance.models import (
            Alignment, Appraisal, Claim, EvidenceTier, Paper, SourceName,
        )
        paper = Paper(
            doc_id="doi:10.1_x", source=SourceName.PUBMED,
            title="Weekend warrior physical activity patterns and mortality",
            journal="Ann Intern Med", url="https://pubmed.ncbi.nlm.nih.gov/1/",
        )
        fields = dict(
            paper_id="doi:10.1_x", tier=EvidenceTier.B,
            design="prospective cohort study", sample_size=51650,
            follow_up="over 25 years", component_ids=["mvpa"],
            alignment=Alignment.CHALLENGES,
            plain_summary=(
                "People who got all their exercise in one or two days lived just "
                "as long as people who spread it through the week."
            ),
            claims=[Claim(
                claim_id="c1", statement="Weekend warriors had lower mortality.",
                quote="weekend warriors had lower all-cause mortality than inactive adults",
                value=0.68, ci_low=0.61, ci_high=0.75,
            )],
        )
        fields.update(overrides)
        return paper, Appraisal(**fields)

    def _brief(self, pairs, **kwargs):
        from provenance.notify import MailConfig, briefing_email
        config = MailConfig(api_key="k", sender="a@b.c", recipient="d@e.f",
                            console_url="https://c.test", signing_key=KEY)
        return briefing_email(
            {"retrieved_new": 9, "appraised": len(pairs), "already_seen": 40,
             "seconds": 62.0, "algorithm_version": "VI v2.11.0"},
            pairs, [], [], config, **kwargs,
        )

    def test_a_kept_study_leads_with_plain_english(self):
        paper, appraisal = self._appraised()
        _, html = self._brief([(paper, appraisal)])
        assert "lived just as long" in html
        # And it comes before the reasoning and the evidence, not after them.
        assert html.index("lived just as long") < html.index("Why it was kept")

    def test_a_kept_study_says_why_it_was_kept(self):
        paper, appraisal = self._appraised()
        _, html = self._brief([(paper, appraisal)], components={"mvpa": "Cardio"})
        assert "Why it was kept" in html
        assert "argues against the Cardio rule" in html      # named as a person names it
        assert "51,650 people" in html                        # and how big
        assert "word-for-word" in html                        # and what was verified

    def test_the_component_falls_back_to_its_identifier(self):
        """No agenda to hand is a worse briefing, never a broken one."""
        paper, appraisal = self._appraised()
        _, html = self._brief([(paper, appraisal)])
        assert "the mvpa rule" in html

    def test_an_older_record_without_a_summary_still_reads(self):
        """Records appraised before plain_summary existed fall back to the
        claim statement rather than rendering an empty card."""
        paper, appraisal = self._appraised(plain_summary="")
        _, html = self._brief([(paper, appraisal)])
        assert "Weekend warriors had lower mortality." in html

    def test_the_verbatim_quote_survives_the_redesign(self):
        """Plain English sits on top of the evidence, it does not replace it."""
        paper, appraisal = self._appraised()
        _, html = self._brief([(paper, appraisal)])
        assert "weekend warriors had lower all-cause mortality" in html
        assert "0.68" in html and "95% CI 0.61 to 0.75" in html

    def test_the_strongest_evidence_is_shown_first(self):
        from provenance.models import Alignment, EvidenceTier
        weak_paper, weak = self._appraised(
            paper_id="doi:weak", tier=EvidenceTier.C, alignment=Alignment.SUPPORTS,
            plain_summary="A smaller study found roughly the same thing.",
        )
        strong_paper, strong = self._appraised()
        _, html = self._brief([(weak_paper, weak), (strong_paper, strong)])
        assert html.index("lived just as long") < html.index("roughly the same thing")

    def test_rejections_are_stated_in_english(self):
        from provenance.models import Rejection
        from provenance.notify import MailConfig, briefing_email
        config = MailConfig(api_key="k", sender="a@b.c", recipient="d@e.f",
                            console_url="", signing_key=KEY)
        rejections = [
            Rejection(paper_id=f"p{i}", stage="appraiser",
                      reason_code="not_relevant", reason="off topic")
            for i in range(3)
        ]
        _, html = briefing_email(
            {"retrieved_new": 3, "appraised": 0}, [], rejections, [], config,
        )
        assert "did not bear on any rule we watch" in html
        assert "not_relevant" not in html

    def test_the_briefing_asks_for_nothing(self):
        """It exists to prove the pipeline is alive. The moment it grows a
        button it starts competing with the email that has one."""
        paper, appraisal = self._appraised()
        _, html = self._brief([(paper, appraisal)])
        assert "No approvals are requested" in html
        assert "/review/" not in html


class TestSendingIsOptional:
    def test_unconfigured_mail_does_not_raise(self):
        """A missing key must not take the nightly run down with it."""
        from provenance.notify import MailConfig, send
        blank = MailConfig(api_key="", sender="", recipient="", console_url="", signing_key="")
        assert send("subject", "<p>body</p>", blank) is None


class TestVerdictReachesTheReader:
    """The audit exists so nobody approves code no independent model has read.

    That only holds if the verdict is in the email, stated plainly.
    """

    def _fixtures(self):
        from provenance.models import (
            Appraisal, Claim, EvidenceTier, Finding, Paper, ProposedChange, SourceName,
        )
        paper = Paper(doc_id="doi:10.1_x", source=SourceName.PUBMED, title="T",
                      journal="J", authors=["Xu Y"], url="https://example.test/1")
        appraisal = Appraisal(paper_id="doi:10.1_x", tier=EvidenceTier.B,
                              design="prospective cohort study", sample_size=1000,
                              claims=[Claim(claim_id="c1", statement="s",
                                            quote="a quote long enough to be evidence")])
        finding = Finding(finding_id="f1", subject_key="synqology", component_id="mvpa",
                          statement="s", current_behavior="c",
                          supporting_paper_ids=["doi:10.1_x"], tier_counts={"B": 1},
                          proposed_changes=[ProposedChange(
                              file_path="a.swift", symbol="denominator",
                              current_value="3.0", proposed_value="2.0", rationale="r")])
        return finding, {"doi:10.1_x": appraisal}, {"doi:10.1_x": paper}

    def _config(self):
        from provenance.notify import MailConfig
        return MailConfig(api_key="k", sender="a@b.c", recipient="d@e.f",
                          console_url="https://c.test", signing_key=KEY)

    def test_defect_is_stated_not_softened(self):
        from provenance.notify import decision_email
        f, a, p = self._fixtures()
        _, html = decision_email(f, a, p, self._config(),
                                 verdict="defect", audit_summary="Dead branch.")
        assert "DEFECT" in html
        assert "should not be merged as written" in html
        assert "Dead branch." in html

    def test_concerns_tells_the_reader_to_read_them_first(self):
        from provenance.notify import decision_email
        f, a, p = self._fixtures()
        _, html = decision_email(f, a, p, self._config(), verdict="concerns")
        assert "CONCERNS" in html and "before deciding" in html

    def test_clean_says_so(self):
        from provenance.notify import decision_email
        f, a, p = self._fixtures()
        _, html = decision_email(f, a, p, self._config(), verdict="clean")
        assert "CLEAN" in html and "nothing to raise" in html

    def test_no_verdict_renders_no_audit_block(self):
        """An email without an audit must not imply one happened."""
        from provenance.notify import decision_email
        f, a, p = self._fixtures()
        _, html = decision_email(f, a, p, self._config())
        assert "OPUS" not in html

    def test_the_audit_block_sits_above_the_decision_button(self):
        """Order on screen is order of reading: verdict before Approve."""
        from provenance.notify import decision_email
        f, a, p = self._fixtures()
        _, html = decision_email(f, a, p, self._config(), verdict="concerns")
        assert html.index("Opus") < html.index("Review and decide")


class TestNightlyNoLongerAsksForBlindApproval:
    def test_the_nightly_run_sends_no_decision_email(self):
        """A finding has converged but no code exists yet, and the cloud job
        cannot run the auditor. Emailing here asks for approval of code that
        has not been written."""
        import inspect
        from provenance import nightly
        source = inspect.getsource(nightly)
        assert "decision_email" not in source
        assert "digest_email" in source
