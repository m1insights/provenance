"""Appraiser -- grade the evidence, or reject it and say why.

Two passes, two models, for reasons of both cost and calibration:

* **Triage** (`gemini-3.5-flash-lite`) answers one cheap question -- does this
  paper bear on any scoring component at all? Retrieval is keyword-driven and
  returns a great deal of adjacent-but-irrelevant work; screening it out here
  costs a fraction of a cent per paper.
* **Appraisal** (`gemini-3.7-flash`) grades what survives against an explicit
  rubric, and must quote the source for every claim it makes.

Every rejection is recorded with a reason. A pipeline that silently discards is
indistinguishable from one that never looked.
"""

from __future__ import annotations

import asyncio
import json
import re
import logging

from google.adk.agents import LlmAgent
from google.adk.runners import InMemoryRunner
from google.genai import types
from pydantic import BaseModel

from .. import grounding
from ..llm import model as llm_model
from ..config import REASONING_MODEL, TRIAGE_MODEL
from ..models import (
    AgendaItem,
    Appraisal,
    AppraisalDraft,
    Paper,
    Rejection,
    RelevanceVerdict,
    ResearchAgenda,
)

log = logging.getLogger(__name__)

#: Concurrent model calls. Bounded to stay inside default Vertex quota.
_MAX_CONCURRENT = 6


RUBRIC = """\
Grade evidence with this rubric. Apply it strictly; when a study sits between \
two tiers, assign the lower one.

TIER A - Systematic review or meta-analysis of randomised trials, or a large \
multi-site randomised trial reporting hard clinical endpoints (mortality, \
incident disease, fracture, cardiovascular events).

TIER B - A single adequately powered randomised trial, or a prospective cohort \
with n >= 10,000 or >= 5 years of follow-up, reporting hard endpoints and \
adjusted for the major confounders of its field.

TIER C - A smaller prospective cohort, a cross-sectional or case-control study, \
short follow-up, or a study whose only endpoints are surrogate or intermediate \
measures (VO2 max, HRV, biomarkers, body composition).

TIER D - Mechanistic, animal, or in-vitro work; case series; uncontrolled \
before-after designs; narrative reviews; conference abstracts.

OVERRIDING RULES
- A preprint that has not been peer reviewed is capped at TIER C no matter how \
strong its design. Note the cap in `reasoning`.
- Non-human work is TIER D regardless of design or size.
- If the paper reports no quantitative result, it cannot be appraised. Return \
an empty `claims` list and say so in `reasoning`.
"""

APPRAISER_INSTRUCTION = f"""\
You are appraising a scientific paper for its bearing on a production health \
scoring algorithm. You will be shown the algorithm's CURRENT RULES for the \
relevant components, then the paper.

{RUBRIC}

For each claim you extract:
- `statement`: the claim in plain language.
- `quote`: a span copied EXACTLY from the title or abstract you were shown, \
character for character. Do not paraphrase, do not tidy the wording, do not \
join fragments from different sentences. This is checked against the source by \
string comparison and a claim whose quote is not found is discarded.
- `value` / `ci_low` / `ci_high`: the numeric result, ONLY when that exact \
number appears inside the span you quoted. If the number is stated elsewhere in \
the abstract, quote THAT sentence instead. Leave `value` null rather than \
reaching for a number that is not in your quote.

DOSE-RESPONSE CURVES: when the abstract reports a numeric result for MORE THAN \
ONE level of the same exposure (quartiles, quintiles, categories, doses, or \
per-increment results at named levels), extract EVERY level as its OWN claim -- \
one claim per point, each with its own verbatim quote and its own `value`. Do \
not summarise a table down to its extremes. Three or more grounded points along \
one axis are what let a downstream chart draw the curve; the highest-vs-lowest \
contrast alone cannot. When the abstract names the exposure level inside the \
quoted span (e.g. "quartile 3, median 8,300 steps"), keep that span intact so \
the level survives grounding with the result.

Set `alignment` by comparing the paper against the CURRENT RULES shown:
- `supports`   - consistent with what the algorithm already does.
- `challenges` - implies a different threshold, weight, or window. THIS IS THE \
IMPORTANT CASE. Only use it when the paper genuinely contradicts a stated \
number or rule, not when it is merely about the same topic.
- `extends`    - compatible, but concerns something the algorithm ignores.
- `neutral`    - bears on the component without implying any change.

`component_ids` must use the exact identifiers given in the CURRENT RULES.

`plain_summary` is one sentence for a reader who is not a clinician: what the \
study looked at, in whom, and what it found. Write it the way you would say it \
out loud. No abbreviations (write "moderate exercise", not "MVPA"), no \
statistical notation (write "people who did X were a third less likely to die \
during the study" rather than "HR 0.68, 95% CI 0.61-0.75"), no hedging \
throat-clearing. Say only what this paper found -- never what it implies for \
the algorithm, which is the `alignment` field's job. Do not state a number here \
that does not appear in one of your quotes.

Be sceptical. Most papers do not justify changing a production algorithm.
"""

TRIAGE_INSTRUCTION = """\
Decide whether a paper could bear on any of the listed scoring components of a \
health algorithm. This is a relevance filter, not a quality judgement.

Mark `relevant: false` when the paper is about a different organ system, a \
clinical population whose findings would not generalise, a diagnostic or \
therapeutic question rather than a behaviour or physiological measure, or is \
purely methodological.

When `relevant: false`, give a one-clause `reason`. When true, list the \
`component_ids` it touches, using the exact identifiers given.
"""


def _rules_block(items: list[AgendaItem]) -> str:
    return "\n\n".join(
        f"### {item.component_id} ({item.display_name}) - {item.weight:g} points"
        f"{f', {item.window_days}-day window' if item.window_days else ''}\n"
        f"{item.current_rule}"
        for item in items
    )


def _paper_block(paper: Paper) -> str:
    meta = " | ".join(
        part
        for part in (
            paper.journal,
            str(paper.published) if paper.published else "",
            ", ".join(paper.publication_types[:4]),
        )
        if part
    )
    return f"TITLE: {paper.title}\nMETADATA: {meta}\n\nABSTRACT:\n{paper.abstract}"


def _agent(name: str, model_name: str, instruction: str, schema) -> LlmAgent:
    return LlmAgent(
        name=name,
        model=llm_model(model_name),
        instruction=instruction,
        output_schema=schema,
        # An appraisal is an extraction, not a composition. Sampling here buys
        # nothing and costs reproducibility.
        generate_content_config=types.GenerateContentConfig(temperature=0.1),
    )


async def _run(agent: LlmAgent, prompt: str) -> dict | None:
    """Drive one ADK agent to completion and return its structured output."""
    runner = InMemoryRunner(agent=agent, app_name="provenance")
    session = await runner.session_service.create_session(
        app_name="provenance", user_id="provenance"
    )
    final = None
    try:
        async for event in runner.run_async(
            user_id="provenance",
            session_id=session.id,
            new_message=types.Content(role="user", parts=[types.Part(text=prompt)]),
        ):
            if event.is_final_response() and event.content and event.content.parts:
                text = "".join(part.text or "" for part in event.content.parts)
                if text.strip():
                    final = text
    finally:
        await runner.close()

    if not final:
        return None
    return _parse_json(final)


def _parse_json(text: str) -> dict | None:
    """Parse a model response that should be JSON.

    Agents constrained by ``output_schema`` return bare JSON. Agents with tools
    cannot use ``output_schema`` -- ADK forbids the combination -- so they are
    asked for JSON in the prompt instead and routinely wrap it in a fenced
    block. Both shapes have to parse.
    """
    candidate = text.strip()
    fenced = re.search(r"```(?:json)?\s*(.+?)\s*```", candidate, re.DOTALL)
    if fenced:
        candidate = fenced.group(1).strip()

    try:
        return json.loads(candidate)
    except json.JSONDecodeError:
        pass

    # Last resort: the outermost brace-balanced span, for responses that carry
    # a sentence of preamble before the object.
    start = candidate.find("{")
    if start != -1:
        depth = 0
        for index in range(start, len(candidate)):
            if candidate[index] == "{":
                depth += 1
            elif candidate[index] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(candidate[start : index + 1])
                    except json.JSONDecodeError:
                        break
    log.warning("could not parse model response as JSON: %s", text[:200])
    return None


SUMMARISER_INSTRUCTION = """\
Write one sentence about a study, for a reader who is not a clinician: what it \
looked at, in whom, and what it found. Write it the way you would say it out \
loud to a friend.

No abbreviations (write "moderate exercise", not "MVPA"; "heart rate \
variability", not "HRV"). No statistical notation -- say "a fifth less likely", \
not "HR 0.80, 95% CI 0.72-0.89". No throat-clearing: do not begin "This study \
shows" or "Researchers found".

You are shown the claims already extracted and verified from this paper. Say \
only what those support. Do not introduce a number that is not in them, and do \
not say what it implies for anyone's algorithm -- that judgement is recorded \
elsewhere and is not yours to make here.
"""


class PlainSummary(BaseModel):
    summary: str


async def summarise(
    pairs: list[tuple[Paper | None, Appraisal]]
) -> list[Appraisal]:
    """Fill in ``plain_summary`` for appraisals that predate the field.

    Separate from ``appraise`` on purpose: this reads an appraisal that already
    passed grounding and rewrites nothing but its cover sentence. It cannot
    change a tier, an alignment or a claim, so a backfill can never quietly
    alter what the corpus says.
    """
    agent = _agent("summariser", REASONING_MODEL, SUMMARISER_INSTRUCTION, PlainSummary)
    # A backfill runs over the whole corpus at once rather than over one night's
    # papers, which is enough to trip the Vertex quota. Narrower, and patient.
    semaphore = asyncio.Semaphore(3)

    async def one(paper: Paper | None, appraisal: Appraisal) -> Appraisal | None:
        claims = "\n".join(
            f"- {c.statement}"
            + (f" [{c.value:g}{' ' + c.unit if c.unit else ''}]" if c.value is not None else "")
            + f'\n  quoted: "{c.quote}"'
            for c in appraisal.claims
        )
        prompt = (
            f"# PAPER\n{_paper_block(paper) if paper else appraisal.paper_id}\n\n"
            f"# VERIFIED CLAIMS\n{claims}\n\n"
            f"# DESIGN\n{appraisal.design}"
            + (f", n={appraisal.sample_size:,}" if appraisal.sample_size else "")
            + (f", followed {appraisal.follow_up}" if appraisal.follow_up else "")
        )
        # One paper failing -- a rate limit, a malformed response -- must not
        # cost the whole backfill the papers that did succeed. Every appraisal
        # here is already complete and stored; a missing cover sentence falls
        # back to the claim statement, which is the state we started from.
        payload = None
        for attempt, pause in enumerate((2, 8, 20)):
            try:
                async with semaphore:
                    payload = await _run(agent, prompt)
                break
            except Exception as exc:  # noqa: BLE001 - any model failure is retryable here
                log.warning(
                    "summarise: attempt %d failed for %s: %s",
                    attempt + 1, appraisal.paper_id, str(exc)[:120],
                )
                await asyncio.sleep(pause)
        if not payload:
            log.warning("summarise: no summary for %s", appraisal.paper_id)
            return None
        summary = PlainSummary.model_validate(payload).summary.strip()
        if not summary:
            return None
        return appraisal.model_copy(update={"plain_summary": summary})

    results = await asyncio.gather(*(one(p, a) for p, a in pairs))
    updated = [a for a in results if a is not None]
    log.info("summarise: %d of %d written", len(updated), len(pairs))
    return updated


async def triage(
    papers: list[Paper], agenda: ResearchAgenda
) -> tuple[list[Paper], list[Rejection]]:
    """Cheap relevance filter. Returns survivors and reasons for the rest."""
    agent = _agent("triage", TRIAGE_MODEL, TRIAGE_INSTRUCTION, RelevanceVerdict)
    rules = _rules_block(agenda.items)
    semaphore = asyncio.Semaphore(_MAX_CONCURRENT)

    async def one(paper: Paper):
        async with semaphore:
            payload = await _run(
                agent,
                f"# SCORING COMPONENTS\n{rules}\n\n# PAPER\n{_paper_block(paper)}",
            )
        if payload is None:
            # An unreadable verdict must not silently drop a paper; pass it to
            # the appraiser, which is the stricter judge anyway.
            return paper, None
        verdict = RelevanceVerdict.model_validate(payload)
        if not verdict.relevant:
            return None, Rejection(
                paper_id=paper.doc_id,
                title=paper.title,
                stage="appraiser",
                reason_code="not_relevant",
                reason=verdict.reason or "Does not bear on any scoring component.",
            )
        if verdict.component_ids:
            paper.matched_components = verdict.component_ids
        return paper, None

    outcomes = await asyncio.gather(*(one(p) for p in papers))
    kept = [paper for paper, _ in outcomes if paper is not None]
    rejected = [rejection for _, rejection in outcomes if rejection is not None]
    log.info("triage: %d in -> %d relevant, %d filtered", len(papers), len(kept), len(rejected))
    return kept, rejected


async def appraise(
    papers: list[Paper], agenda: ResearchAgenda
) -> tuple[list[Appraisal], list[Rejection]]:
    """Grade each paper and verify every claim against its source."""
    agent = _agent("appraiser", REASONING_MODEL, APPRAISER_INSTRUCTION, AppraisalDraft)
    by_id = {item.component_id: item for item in agenda.items}
    semaphore = asyncio.Semaphore(_MAX_CONCURRENT)

    async def one(paper: Paper):
        relevant = [by_id[c] for c in paper.matched_components if c in by_id] or agenda.items
        async with semaphore:
            payload = await _run(
                agent,
                f"# CURRENT RULES\n{_rules_block(relevant)}\n\n# PAPER\n{_paper_block(paper)}",
            )
        if payload is None:
            return None, [
                Rejection(
                    paper_id=paper.doc_id,
                    title=paper.title,
                    stage="appraiser",
                    reason_code="no_appraisal",
                    reason="Model returned no parsable appraisal.",
                )
            ]

        draft = AppraisalDraft.model_validate(payload)
        appraisal = Appraisal(paper_id=paper.doc_id, **draft.model_dump())

        # Distinguish "had nothing to claim" from "claimed things it could not
        # support". Both end in rejection, but conflating them would make the
        # rejection log lie about how often grounding actually fires -- and the
        # log is the only evidence that this system filters anything at all.
        if not appraisal.claims:
            return None, [
                Rejection(
                    paper_id=paper.doc_id,
                    title=paper.title,
                    stage="appraiser",
                    reason_code="no_quantitative_result",
                    reason=(
                        draft.reasoning[:300]
                        or "Reports no quantitative result that could bear on a threshold."
                    ),
                )
            ]

        # The grounding check is the point of the whole exercise: claims that
        # cannot be traced to words in the source do not survive.
        verified, ground_rejections = grounding.verify(appraisal, paper)
        if not verified.claims:
            return None, ground_rejections + [
                Rejection(
                    paper_id=paper.doc_id,
                    title=paper.title,
                    stage="grounding",
                    reason_code="no_grounded_claims",
                    reason=(
                        f"All {len(appraisal.claims)} claim(s) failed verification "
                        "against the source text."
                    ),
                )
            ]
        return verified, ground_rejections

    outcomes = await asyncio.gather(*(one(p) for p in papers))
    appraisals = [a for a, _ in outcomes if a is not None]
    rejections = [r for _, rs in outcomes for r in rs]
    log.info(
        "appraise: %d in -> %d appraised, %d rejected", len(papers), len(appraisals), len(rejections)
    )
    return appraisals, rejections
