"""The grounding check is the load-bearing guarantee. Prove it."""

from __future__ import annotations

import pytest

from provenance.grounding import check_claim, normalise, verify
from provenance.models import Appraisal, Claim, EvidenceTier, Paper, SourceName

ABSTRACT = (
    "BACKGROUND: Guidelines recommend 150 minutes of moderate activity weekly. "
    "METHODS: We followed 12,345 adults for a median of 8.4 years. "
    "RESULTS: Participants accumulating activity in bouts shorter than 10 minutes "
    "showed a hazard ratio of 0.82 (95% CI 0.74-0.91) for all-cause mortality "
    "compared with inactive participants. The association did not differ by "
    "bout length (p for interaction = 0.43). "
    "CONCLUSIONS: Bout duration did not modify the mortality benefit of activity."
)

PAPER = Paper(
    doc_id="doi:10.1000_test",
    source=SourceName.PUBMED,
    title="Activity bout duration and all-cause mortality",
    abstract=ABSTRACT,
)


def _claim(**kwargs) -> Claim:
    base = {
        "claim_id": "c1",
        "statement": "Bout duration did not modify the benefit.",
        "quote": "The association did not differ by bout length",
    }
    return Claim(**(base | kwargs))


class TestQuoteCheck:
    def test_verbatim_quote_passes(self):
        assert check_claim(_claim(), ABSTRACT) is None

    def test_quote_spanning_sentences_passes(self):
        quote = "showed a hazard ratio of 0.82 (95% CI 0.74-0.91) for all-cause mortality"
        assert check_claim(_claim(quote=quote), ABSTRACT) is None

    def test_typographic_variants_pass(self):
        """A model echoing a span with smart quotes and an en dash is honest."""
        quote = "hazard ratio of 0.82 (95% CI 0.74–0.91)"  # en dash, not hyphen
        assert check_claim(_claim(quote=quote), ABSTRACT) is None

    def test_collapsed_whitespace_passes(self):
        quote = "We  followed 12,345 adults\n  for a median of 8.4 years"
        assert check_claim(_claim(quote=quote), ABSTRACT) is None

    def test_paraphrase_fails(self):
        """The whole point: a plausible restatement is not a quote."""
        quote = "The relationship was unaffected by how long each bout lasted"
        failure = check_claim(_claim(quote=quote), ABSTRACT)
        assert failure is not None and "not found" in failure

    def test_fabricated_quote_fails(self):
        quote = "Participants who exercised in the morning lived 4.2 years longer"
        assert check_claim(_claim(quote=quote), ABSTRACT) is not None


class TestNumberCheck:
    def test_number_present_in_quote_passes(self):
        claim = _claim(
            quote="a hazard ratio of 0.82 (95% CI 0.74-0.91)",
            value=0.82,
            ci_low=0.74,
            ci_high=0.91,
        )
        assert check_claim(claim, ABSTRACT) is None

    def test_leading_zero_variant_passes(self):
        """'.82' in an abstract and 0.82 in a claim are the same number."""
        source = "the hazard ratio was .82 in the adjusted model"
        claim = _claim(quote="the hazard ratio was .82 in the adjusted model", value=0.82)
        assert check_claim(claim, source) is None

    def test_integer_rendered_as_float_passes(self):
        claim = _claim(quote="Guidelines recommend 150 minutes of moderate activity", value=150.0)
        assert check_claim(claim, ABSTRACT) is None

    def test_thousands_separator_passes(self):
        claim = _claim(quote="We followed 12,345 adults", value=12345)
        assert check_claim(claim, ABSTRACT) is None

    def test_fabricated_number_fails(self):
        """The money test.

        The quote is genuine and appears verbatim. The number attached to it is
        invented. Quote-checking alone would let this through; this is why the
        number check exists separately.
        """
        claim = _claim(
            quote="a hazard ratio of 0.82 (95% CI 0.74-0.91)",
            value=0.62,
        )
        failure = check_claim(claim, ABSTRACT)
        assert failure is not None and "does not appear" in failure

    def test_number_from_elsewhere_in_abstract_fails(self):
        """A real number, but not in the span cited for it."""
        claim = _claim(quote="The association did not differ by bout length", value=8.4)
        assert check_claim(claim, ABSTRACT) is not None


class TestVerify:
    def _appraisal(self, claims: list[Claim]) -> Appraisal:
        return Appraisal(
            paper_id=PAPER.doc_id,
            tier=EvidenceTier.B,
            design="prospective cohort",
            claims=claims,
        )

    def test_grounded_claims_survive(self):
        appraisal = self._appraisal([_claim()])
        kept, rejections = verify(appraisal, PAPER)
        assert len(kept.claims) == 1
        assert rejections == []

    def test_ungrounded_claim_dropped_and_reported(self):
        good = _claim(claim_id="c1")
        bad = _claim(claim_id="c2", quote="Morning exercisers lived substantially longer lives")
        kept, rejections = verify(self._appraisal([good, bad]), PAPER)

        assert [c.claim_id for c in kept.claims] == ["c1"]
        assert len(rejections) == 1
        assert rejections[0].stage == "grounding"
        assert rejections[0].reason_code == "ungrounded_claim"
        assert "c2" in rejections[0].reason

    def test_appraisal_with_no_surviving_claims_is_empty(self):
        """Caller treats an empty claim list as a rejected paper."""
        bad = _claim(quote="This sentence appears in no abstract anywhere at all")
        kept, rejections = verify(self._appraisal([bad]), PAPER)
        assert kept.claims == []
        assert len(rejections) == 1

    def test_title_is_quotable(self):
        """Findings are often stated in the title and nowhere else."""
        claim = _claim(quote="Activity bout duration and all-cause mortality")
        kept, _ = verify(self._appraisal([claim]), PAPER)
        assert len(kept.claims) == 1


class TestNormalise:
    def test_folds_typography_not_words(self):
        assert normalise("The  “quick”—brown\nfox") == 'the "quick"-brown fox'

    def test_is_idempotent(self):
        once = normalise("Some  “text” – here")
        assert normalise(once) == once


def test_short_quotes_are_rejected_at_the_schema():
    """A two-word 'quote' matches too much to be evidence of anything."""
    with pytest.raises(ValueError):
        Claim(claim_id="c1", statement="x", quote="did not")


class TestSignHandling:
    """Sign is carried by prose, magnitude by the numeral.

    Abstracts write "a reduction of 0.56" and mean -0.56. Requiring a literal
    "-0.56" in the span rejects a correct reading; requiring the magnitude
    still catches a fabricated effect size, which is the actual threat.
    """

    SOURCE = "HRV showed a reduction of 0.56 ms (95% CI 0.02-1.11) in the intervention arm"

    def test_negative_value_matches_unsigned_span(self):
        claim = _claim(quote=self.SOURCE, value=-0.56)
        assert check_claim(claim, self.SOURCE) is None

    def test_positive_value_matches_same_span(self):
        claim = _claim(quote=self.SOURCE, value=0.56)
        assert check_claim(claim, self.SOURCE) is None

    def test_fabricated_magnitude_still_fails(self):
        claim = _claim(quote=self.SOURCE, value=-0.75)
        assert check_claim(claim, self.SOURCE) is not None


class TestFulltextGrounding:
    """A paper carrying open-access body text grounds quotes from that body."""

    def _paper(self, fulltext=""):
        from provenance.models import Paper, SourceName
        return Paper(
            doc_id="doi:10.1_test", source=SourceName.PUBMED, title="A study",
            abstract="The abstract says one thing about exercise and mortality here.",
            fulltext=fulltext,
        )

    def _appraisal(self, quote, value=None):
        from provenance.models import Alignment, Appraisal, Claim, EvidenceTier
        return Appraisal(
            paper_id="doi:10.1_test", tier=EvidenceTier.B, design="cohort",
            alignment=Alignment.NEUTRAL,
            claims=[Claim(claim_id="c1", statement="s", quote=quote, value=value)],
        )

    BODY_SPAN = "an aged immune system conferred a hazard ratio of 1.6 for mortality"

    def test_body_quote_grounds_when_fulltext_present(self):
        from provenance import grounding
        paper = self._paper(fulltext=f"Results. In this analysis {self.BODY_SPAN} overall.")
        verified, rejections = grounding.verify(self._appraisal(self.BODY_SPAN, 1.6), paper)
        assert len(verified.claims) == 1 and not rejections

    def test_body_quote_fails_without_fulltext(self):
        """The default surface stays abstract-only — body quotes cannot ground
        against a paper whose fulltext was never fetched."""
        from provenance import grounding
        verified, rejections = grounding.verify(self._appraisal(self.BODY_SPAN, 1.6), self._paper())
        assert verified.claims == [] and rejections
