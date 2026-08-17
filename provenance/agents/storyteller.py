"""Storyteller -- explain a Finding to people who will never read the paper.

The agent is given a schema with nowhere to write a number. It chooses the
angle, the words, which claims to lean on, and what shape of chart suits them;
code fills in every figure from the appraised record.

If the copy it writes still contains a figure that no claim supports, the gate
rejects the plan and the agent is told which slide, which field, and which
number. It gets a small number of attempts, and if it cannot write honest copy
it produces nothing -- silence being much cheaper than a confident falsehood
over a citation.
"""

from __future__ import annotations

import json
import logging

from google.adk.agents import LlmAgent
from google.genai import types

from ..config import REASONING_MODEL
from ..creative import (
    GateFailure,
    StoryPlan,
    _is_observational,
    check_copy,
    check_language,
    check_readability,
    check_structure,
    resolve,
)
from ..llm import model as llm_model
from ..models import Appraisal, Claim, Finding, Paper

log = logging.getLogger(__name__)

#: Attempts before giving up. A model that cannot write grounded copy in three
#: tries is not going to find it on the fourth.
MAX_ATTEMPTS = 3


EVIDENCE_LANGUAGE_OBSERVATIONAL = """\
## This evidence is OBSERVATIONAL

Every supporting study here is a cohort or cross-sectional analysis. They show \
that people who did X had lower rates of Y. They do NOT show that X lowers Y.

Write associations, never causes: "was linked to", "had lower", "is associated \
with", "tracked with". Never "cuts", "reduces", "prevents", "protects against", \
"boosts", "improves", "buys you".

"""

INSTRUCTION = """\
You write short, factual social content explaining new health research to \
people who will never read the paper. The publisher is a longevity app whose \
whole positioning is that it does not overstate evidence.

## The one rule

**You do not write numbers.** Every figure on the finished creative is filled \
in by code from the appraised record. Your job is the words, the angle, and \
choosing which claims carry the point.

If a figure genuinely belongs in a headline, reference the claim through \
`feature_claim_id` and write the sentence around the gap -- "Each extra \
thousand steps cut the risk by" -- and the number is inserted for you.

Any digit you type into `kicker`, `headline`, `body` or an axis label is \
checked against the appraised claims. Unsupported figures are rejected and you \
will be asked to rewrite.

## Structure

Four slides:
1. **The finding** -- what was observed. Lead with the surprise.
2. **The size of it** -- how large the effect is. Usually the slide with a figure.
3. **The caveat or the twist** -- what people get wrong, or what the study \
found that contradicts the common belief.
4. **What to do with it** -- the practical consequence. Concrete and small.

## Write for someone who has never read a paper

This is the constraint most health content fails. Your reader is scrolling on a \
phone and has about a second to decide whether this is for them. Clinical \
vocabulary is precise and it is also where they stop reading.

Say "heart" not "cardiovascular". "dying" not "mortality". "blood sugar" not \
"metabolic". "fitness" not "VO2 max". "sitting" not "sedentary". "risk" not \
"hazard ratio".

The precise term still exists -- it lives in the source line at the bottom, \
where someone who wants it will find it. The headline is where somebody decides \
whether to keep reading, so it gets the plain sentence.

Chart labels are read in passing: one or two everyday words. "heart", "cancer", \
"accidents". Never "cardiovascular disease incidence".

## Voice

Short sentences. Plain words. No hype, no "game-changing", no "shocking". \
Write the way a careful clinician talks to a patient who asked a good question.

Mark the payoff phrase of a headline with *asterisks* to set it in the accent \
colour. One emphasis per headline at most.

Body copy is two to three lines, under 150 characters. The canvas is fixed: \
longer copy crowds the slide and squeezes the chart into whatever is left.

## Charts

- `bar` -- comparing effect sizes across claims.
- `dot` -- showing that something did NOT vary. A null result is a finding.
- `band` -- a range on an axis, from two claims.
- `none` -- when the point is a sentence, not a shape. Use this SPARINGLY: at \
least three of the four slides must carry a chart, because the charts are why \
anyone stops to look.

A chart needs at least TWO claims. One dot on an axis is not a chart -- it \
conveys nothing a sentence would not convey better, and it implies a \
comparison the reader then goes hunting for.

`point_labels` are words, not figures: "4 to 5k", "slowest", "brisk". Give one \
per claim, in the same order as `claim_ids`.

## Honesty constraints

- Never imply causation from a cohort study. These are associations.
- Never promise years of life, or any individual outcome.
- Do not describe an effect as large or small unless the claim says so.
- If the evidence is mostly from one cohort, do not write "study after study".
"""


def _claims_block(claims: dict[str, Claim], appraisals: dict[str, Appraisal]) -> str:
    by_paper: dict[str, list[Claim]] = {}
    for appraisal in appraisals.values():
        for claim in appraisal.claims:
            by_paper.setdefault(appraisal.paper_id, []).append(claim)

    lines = []
    for claim_id, claim in claims.items():
        value = "" if claim.value is None else f" [value {claim.value:g} {claim.unit}]".rstrip()
        lines.append(f"- `{claim_id}`{value}: {claim.statement}\n    quote: \"{claim.quote}\"")
    return "\n".join(lines)


def _feedback(failures: list[GateFailure]) -> str:
    lines = "\n".join(
        f"- slide {f.slide}, {f.field}: {f.detail}" for f in failures
    )
    return (
        "Your previous draft was rejected by the claims gate:\n\n"
        f"{lines}\n\n"
        "Rewrite. Remove the unsupported figures, or reference a claim that "
        "actually reports them. Do not argue with the gate."
    )


def collect_claims(
    finding: Finding, appraisals: dict[str, Appraisal]
) -> dict[str, Claim]:
    """Every grounded claim behind a finding, keyed uniquely across papers.

    Claim ids are only unique within one appraisal, so they are namespaced by
    paper here -- otherwise two papers' `c1` collide and a chart silently draws
    the wrong study's number.
    """
    claims: dict[str, Claim] = {}
    for index, paper_id in enumerate(finding.supporting_paper_ids):
        appraisal = appraisals.get(paper_id)
        if appraisal is None:
            continue
        for claim in appraisal.claims:
            key = f"p{index}_{claim.claim_id}"
            claims[key] = claim.model_copy(update={"claim_id": key})
    return claims


async def tell(
    finding: Finding,
    appraisals: dict[str, Appraisal],
    papers: dict[str, Paper],
) -> tuple[dict, StoryPlan] | None:
    """Produce a render-ready creative payload, or nothing at all."""
    from .appraiser import _run

    claims = collect_claims(finding, appraisals)
    if not claims:
        log.warning("storyteller: %s has no grounded claims", finding.finding_id)
        return None

    agent = LlmAgent(
        name="storyteller",
        model=llm_model(REASONING_MODEL),
        instruction=INSTRUCTION,
        output_schema=StoryPlan,
        generate_content_config=types.GenerateContentConfig(
            temperature=0.6, max_output_tokens=8192
        ),
    )

    observational = _is_observational(appraisals, finding.supporting_paper_ids)
    lead = papers.get(finding.supporting_paper_ids[0]) if finding.supporting_paper_ids else None
    base_prompt = (
        f"# FINDING\n{finding.statement}\n\n"
        f"## What the app currently does\n{finding.current_behavior}\n\n"
        f"## Evidence base\n"
        f"{sum(finding.tier_counts.values())} appraised papers, tiers {finding.tier_counts}. "
        f"Lead study: {lead.title if lead else 'n/a'}"
        f"{f' ({lead.journal})' if lead and lead.journal else ''}.\n\n"
        f"## Claims you may reference\n{_claims_block(claims, appraisals)}\n\n"
        f"{EVIDENCE_LANGUAGE_OBSERVATIONAL if observational else ''}"
        f"Write four slides."
    )

    prompt = base_prompt
    for attempt in range(1, MAX_ATTEMPTS + 1):
        raw = await _run(agent, prompt)
        if raw is None:
            log.warning("storyteller: no plan on attempt %d", attempt)
            prompt = base_prompt
            continue

        try:
            plan = StoryPlan.model_validate(raw)
        except Exception as exc:
            log.warning("storyteller: invalid plan on attempt %d: %s", attempt, exc)
            prompt = base_prompt
            continue

        failures = (
            check_copy(plan, claims)
            + check_language(plan, observational=observational)
            + check_structure(plan)
            + check_readability(plan)
        )
        if not failures:
            log.info(
                "storyteller: %d slides accepted on attempt %d", len(plan.slides), attempt
            )
            return resolve(plan, finding, claims, papers, appraisals), plan

        log.info(
            "storyteller: attempt %d rejected by claims gate (%d issue(s))",
            attempt,
            len(failures),
        )
        for failure in failures:
            log.info("  slide %d %s: %s", failure.slide, failure.field, failure.detail)
        prompt = f"{base_prompt}\n\n{_feedback(failures)}"

    log.warning(
        "storyteller: %s produced no grounded copy in %d attempts; publishing nothing",
        finding.finding_id,
        MAX_ATTEMPTS,
    )
    return None
