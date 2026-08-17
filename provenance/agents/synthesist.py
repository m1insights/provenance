"""Synthesist -- open a Finding only when evidence converges.

The temptation in a system like this is to act on the first strong paper. That
is how you get an algorithm that lurches after whatever was published most
recently, which is worse than one that never updates at all: it inherits the
noise of the literature and calls it responsiveness.

So convergence is a precondition, enforced in code before any model is asked
what it thinks:

* at least ``MIN_CHALLENGERS`` distinct papers must challenge the same component
* at least ``MIN_STRONG_CHALLENGERS`` of them must be tier A or B
* they must come from more than one research group, approximated by DOI prefix

Only then is a model asked to state what the evidence collectively says and
what change it implies. The gate is arithmetic; the synthesis is judgement.
"""

from __future__ import annotations

import asyncio
import json
import logging
from collections import Counter, defaultdict

from google.adk.agents import LlmAgent
from google.genai import types
from pydantic import BaseModel, Field

from ..config import REASONING_MODEL, SubjectApp
from ..llm import model as llm_model
from ..models import (
    AgendaItem,
    Appraisal,
    EvidenceTier,
    Finding,
    Paper,
    ProposedChange,
    Rejection,
    ResearchAgenda,
)

log = logging.getLogger(__name__)

#: Distinct papers that must challenge a component before it is considered.
MIN_CHALLENGERS = 3

#: How many of those must be tier A or B. One strong study plus two weak ones
#: is a hypothesis, not a mandate.
MIN_STRONG_CHALLENGERS = 1

#: Distinct DOI registrants, as a cheap proxy for independent research groups.
#: Three papers from one consortium are one finding reported three times.
MIN_INDEPENDENT_SOURCES = 2

_STRONG = {EvidenceTier.A, EvidenceTier.B}


class SynthesisDraft(BaseModel):
    """What the model may produce. Identity and status are set by code."""

    statement: str = Field(description="What the evidence collectively says")
    current_behavior: str = Field(description="What the algorithm does today")
    proposed_changes: list[ProposedChange] = Field(default_factory=list)
    confidence: float = Field(ge=0.0, le=1.0)
    dissent: str = Field(
        default="", description="Strongest argument against making this change"
    )


INSTRUCTION = """\
You are deciding whether accumulated evidence justifies changing a constant in \
a production health scoring algorithm used by real people.

You will be shown one component's CURRENT RULE and every appraised paper that \
challenges it, with evidence tiers and verified quotes.

Produce:
- `statement`: what the evidence collectively says. Aggregate; do not simply \
restate the strongest paper.
- `current_behavior`: what the algorithm does today, quoted from the rule shown.
- `proposed_changes`: the smallest change that would bring the algorithm in \
line. Give `current_value` and `proposed_value` as they would appear in source. \
Prefer adjusting one constant over restructuring. If the evidence does not \
support a specific numeric change, return an empty list and say why in \
`statement`.
- `confidence`: 0-1. Reserve above 0.8 for multiple tier-A studies agreeing on \
a specific number. Most genuine findings sit between 0.4 and 0.7.
- `dissent`: the strongest argument AGAINST making this change -- confounding, \
population mismatch, surrogate endpoints, or the possibility that the current \
value is already defensible. Never leave this empty; if you cannot argue \
against your own proposal, you have not understood it well enough to make it.

The algorithm's current values were themselves chosen from literature and are \
usually defensible. The bar for change is evidence that the current value is \
WRONG, not merely that a different value is also supportable.
"""


def _doi_prefix(paper_id: str) -> str:
    """Registrant portion of a DOI, e.g. ``doi:10.1001_x`` -> ``10.1001``."""
    if paper_id.startswith("doi:"):
        return paper_id[4:].split("_", 1)[0]
    return paper_id


def gate(
    component_id: str, appraisals: list[Appraisal]
) -> tuple[list[Appraisal], Rejection | None]:
    """Apply the convergence preconditions. Pure arithmetic, no model."""
    challengers = [
        a
        for a in appraisals
        if a.alignment.value == "challenges" and component_id in a.component_ids
    ]

    if len(challengers) < MIN_CHALLENGERS:
        return [], Rejection(
            paper_id=f"component:{component_id}",
            title=component_id,
            stage="synthesist",
            reason_code="insufficient_convergence",
            reason=(
                f"{len(challengers)} challenging paper(s); "
                f"{MIN_CHALLENGERS} required before a change is considered."
            ),
        )

    strong = [a for a in challengers if a.tier in _STRONG]
    if len(strong) < MIN_STRONG_CHALLENGERS:
        return [], Rejection(
            paper_id=f"component:{component_id}",
            title=component_id,
            stage="synthesist",
            reason_code="no_strong_evidence",
            reason=(
                f"{len(challengers)} challengers but none above tier C; "
                f"{MIN_STRONG_CHALLENGERS} tier-A/B required."
            ),
        )

    registrants = {_doi_prefix(a.paper_id) for a in challengers}
    if len(registrants) < MIN_INDEPENDENT_SOURCES:
        return [], Rejection(
            paper_id=f"component:{component_id}",
            title=component_id,
            stage="synthesist",
            reason_code="single_source",
            reason=(
                f"All {len(challengers)} challengers share DOI registrant "
                f"{sorted(registrants)[0]}; independent replication required."
            ),
        )

    return challengers, None


def _evidence_block(challengers: list[Appraisal], papers: dict[str, Paper]) -> str:
    blocks = []
    for appraisal in sorted(challengers, key=lambda a: a.tier.value):
        paper = papers.get(appraisal.paper_id)
        header = (
            f"### [TIER {appraisal.tier.value}] {paper.title if paper else appraisal.paper_id}\n"
            f"{paper.citation() if paper else ''} | {appraisal.design}"
            f"{f' | n={appraisal.sample_size}' if appraisal.sample_size else ''}"
            f"{f' | {appraisal.follow_up}' if appraisal.follow_up else ''}"
        )
        claims = "\n".join(
            f"- {c.statement}\n  QUOTE: \"{c.quote}\""
            + (f"\n  VALUE: {c.value:g} {c.unit}".rstrip() if c.value is not None else "")
            for c in appraisal.claims
        )
        blocks.append(f"{header}\n{claims}")
    return "\n\n".join(blocks)


async def synthesise(
    subject: SubjectApp,
    agenda: ResearchAgenda,
    appraisals: list[Appraisal],
    papers: dict[str, Paper],
) -> tuple[list[Finding], list[Rejection]]:
    """Evaluate every component, open Findings where evidence converges."""
    by_component: dict[str, list[Appraisal]] = defaultdict(list)
    for appraisal in appraisals:
        for component in appraisal.component_ids:
            by_component[component].append(appraisal)

    agent = LlmAgent(
        name="synthesist",
        model=llm_model(REASONING_MODEL),
        instruction=INSTRUCTION,
        output_schema=SynthesisDraft,
        generate_content_config=types.GenerateContentConfig(temperature=0.2),
    )

    findings: list[Finding] = []
    rejections: list[Rejection] = []

    for item in agenda.items:
        challengers, blocked = gate(item.component_id, by_component.get(item.component_id, []))
        if blocked is not None:
            rejections.append(blocked)
            continue

        finding = await _synthesise_one(agent, subject, item, challengers, papers)
        if finding is None:
            rejections.append(
                Rejection(
                    paper_id=f"component:{item.component_id}",
                    title=item.component_id,
                    stage="synthesist",
                    reason_code="no_change_proposed",
                    reason="Evidence converged but implied no specific numeric change.",
                )
            )
            continue
        findings.append(finding)

    log.info(
        "synthesise: %d components -> %d findings, %d gated",
        len(agenda.items),
        len(findings),
        len(rejections),
    )
    return findings, rejections


async def _synthesise_one(
    agent: LlmAgent,
    subject: SubjectApp,
    item: AgendaItem,
    challengers: list[Appraisal],
    papers: dict[str, Paper],
) -> Finding | None:
    from .appraiser import _run  # shared ADK driver

    prompt = (
        f"# COMPONENT: {item.component_id} ({item.display_name})\n"
        f"Weight {item.weight:g} points"
        f"{f', {item.window_days}-day window' if item.window_days else ''}\n"
        f"Source: {item.source_ref}\n\n"
        f"## CURRENT RULE\n{item.current_rule}\n\n"
        f"## CHALLENGING EVIDENCE ({len(challengers)} papers)\n"
        f"{_evidence_block(challengers, papers)}"
    )

    payload = await _run(agent, prompt)
    if payload is None:
        return None

    draft = SynthesisDraft.model_validate(payload)
    if not draft.proposed_changes:
        return None

    tier_counts = Counter(a.tier.value for a in challengers)
    return Finding(
        finding_id=f"{subject.key}__{item.component_id}__{agenda_digest(challengers)}",
        subject_key=subject.key,
        component_id=item.component_id,
        statement=draft.statement,
        current_behavior=draft.current_behavior,
        supporting_paper_ids=[a.paper_id for a in challengers],
        tier_counts=dict(tier_counts),
        proposed_changes=draft.proposed_changes,
        confidence=draft.confidence,
    )


def agenda_digest(challengers: list[Appraisal]) -> str:
    """Stable id fragment from the supporting set.

    Keying a Finding by its evidence means re-running on the same corpus
    updates one document rather than accumulating near-duplicates, while new
    supporting papers legitimately open a new Finding.
    """
    import hashlib

    joined = "|".join(sorted(a.paper_id for a in challengers))
    return hashlib.sha1(joined.encode()).hexdigest()[:10]
