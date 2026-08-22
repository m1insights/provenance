"""Verify that claims are supported by words the source actually contains.

The Appraiser returns, for every claim, a span it says appears in the paper.
This module checks that assertion against the retrieved text. A model that
paraphrases while calling it a quote, or that reports a number the abstract
never states, fails here -- in code, deterministically, before anything
downstream can act on it.

Two independent checks:

1. **Quote check.** The span must appear in the source under a normalisation
   that forgives typography and nothing else.
2. **Number check.** If a claim carries a numeric value, that number must
   appear in the quote. This is the one that matters: prose survives being
   loosely worded, a fabricated effect size does not.
"""

from __future__ import annotations

import logging
import re
import unicodedata

from .models import Appraisal, Claim, Paper, Rejection

log = logging.getLogger(__name__)

#: Typographic variants that carry no meaning and routinely differ between a
#: model's echo of a span and the source it came from.
_EQUIVALENCES = {
    "‘": "'", "’": "'", "‚": "'", "‛": "'",
    "“": '"', "”": '"', "„": '"', "‟": '"',
    "‐": "-", "‑": "-", "‒": "-", "–": "-",
    "—": "-", "―": "-", "−": "-",
    " ": " ", " ": " ", " ": " ", "​": "",
    "…": "...",
}

_WHITESPACE = re.compile(r"\s+")

#: Integers and decimals, including the bare-decimal form abstracts favour for
#: hazard ratios (".82"). Deliberately not scientific notation -- an abstract
#: writing "1.2e-4" and a claim writing "0.00012" are not the same assertion
#: and should not silently match.
_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?|\.\d+")


def normalise(text: str) -> str:
    """Fold typography and spacing. Never folds words."""
    folded = unicodedata.normalize("NFKC", text)
    for variant, plain in _EQUIVALENCES.items():
        folded = folded.replace(variant, plain)
    return _WHITESPACE.sub(" ", folded).strip().lower()


def _numbers_in(text: str) -> set[float]:
    """Numeric tokens parsed to values.

    Comparing numerically rather than by string rules out a whole class of
    false negatives at once: ".82" and "0.82", "12" and "12.0", "12,345" and
    "12345" are each one number written two ways. Decimal literals convert
    exactly, so equality here is safe.
    """
    values: set[float] = set()
    for match in _NUMBER.finditer(text):
        try:
            values.add(float(match.group(0).replace(",", "")))
        except ValueError:  # a stray token like "1,2,3"
            continue
    return values


def check_claim(claim: Claim, source: str) -> str | None:
    """Return a failure reason, or ``None`` if the claim is grounded."""
    haystack = normalise(source)
    needle = normalise(claim.quote)

    if not needle:
        return "quote is empty"
    if needle not in haystack:
        return f"quote not found in source: {claim.quote[:110]!r}"

    if claim.value is not None:
        quoted_numbers = _numbers_in(needle)
        # Compare magnitudes. Abstracts write "a reduction of 0.56" and mean
        # -0.56, so the sign is carried by the prose rather than the numeral;
        # requiring a literal "-0.56" in the span rejects a correct reading.
        # Magnitude is what can actually be fabricated, and it is what a chart
        # would plot, so that is what gets checked. The direction stays legible
        # because `statement` and `quote` travel with the value everywhere it
        # is displayed.
        if abs(claim.value) not in {abs(n) for n in quoted_numbers}:
            rendered = sorted(f"{n:g}" for n in quoted_numbers)
            return (
                f"value {claim.value:g} does not appear in the quoted span "
                f"(span contains {rendered or 'no numbers'})"
            )

    return None


def verify(appraisal: Appraisal, paper: Paper) -> tuple[Appraisal, list[Rejection]]:
    """Strip ungrounded claims and report each one.

    Claim-level rather than paper-level: a single sloppy quote should not
    discard a sound study, but no ungrounded claim may survive into a pull
    request or onto a slide. An appraisal left with no claims is returned with
    an empty list, and the caller treats that as a rejected paper.
    """
    source = f"{paper.title}\n{paper.abstract}"
    if paper.fulltext:
        source = f"{source}\n{paper.fulltext}"
    kept: list[Claim] = []
    rejections: list[Rejection] = []

    for claim in appraisal.claims:
        failure = check_claim(claim, source)
        if failure is None:
            kept.append(claim)
            continue
        log.info("grounding: dropped %s/%s -- %s", paper.doc_id, claim.claim_id, failure)
        rejections.append(
            Rejection(
                paper_id=paper.doc_id,
                title=paper.title,
                stage="grounding",
                reason_code="ungrounded_claim",
                reason=f"[{claim.claim_id}] {failure}",
            )
        )

    return appraisal.model_copy(update={"claims": kept}), rejections
