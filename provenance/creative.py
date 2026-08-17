"""Turn a Finding into a render-ready creative, without letting a model near a number.

The division of labour is the whole design:

* The **Storyteller** chooses what to say, which claims to lean on, and what
  shape of chart suits them. It writes prose. It never writes a figure.
* This module **resolves** those choices against the stored appraisals, pulling
  every value from a claim that already survived grounding, and hands the
  renderer a payload of real data.
* The **claims gate** then re-reads the finished copy and refuses any digit
  that does not trace back to one of those claims.

A model can therefore be wrong about emphasis, or about which study to feature,
and the worst outcome is a badly-argued slide. It cannot be wrong about the
number on the chart, because it never supplied one.
"""

from __future__ import annotations

import logging
import re
from enum import Enum

from pydantic import BaseModel, Field

from .models import Appraisal, Claim, Finding, Paper

log = logging.getLogger(__name__)


class ChartType(str, Enum):
    BAR = "bar"      # one bar per claim — comparing effect sizes
    DOT = "dot"      # one dot per claim — showing an absence of trend
    BAND = "band"    # a highlighted range on an axis
    NONE = "none"    # copy only; some slides are better without a chart


class ChartPlan(BaseModel):
    """What to draw, expressed as references rather than data."""

    type: ChartType = ChartType.NONE
    label: str = Field(default="", description="Uppercase label above the chart")
    note: str = Field(default="", description="Small caption inside the plot area")
    claim_ids: list[str] = Field(
        default_factory=list,
        description="Claims supplying the values, in the order they should appear",
    )
    point_labels: list[str] = Field(
        default_factory=list,
        description="Short axis label per claim, e.g. '4→5k'. Words only, no figures.",
    )


class SlidePlan(BaseModel):
    kicker: str = Field(description="Short uppercase eyebrow, e.g. 'THE SIZE OF IT'")
    headline: str = Field(
        description="The claim in plain words. Wrap the payoff phrase in *asterisks* "
        "to set it in the accent colour."
    )
    body: str = Field(default="", description="Two to four lines. Plain language.")
    feature_claim_id: str = Field(
        default="",
        description="Claim whose value becomes the oversized figure on this slide. "
        "Leave empty for no figure. The figure is filled in from the record.",
    )
    chart: ChartPlan = Field(default_factory=ChartPlan)


class StoryPlan(BaseModel):
    """What the Storyteller returns. Notice there is nowhere to put a number."""

    slides: list[SlidePlan]
    caption: str = Field(default="", description="Post caption, plain language")


#: Numbers a reviewer would never mistake for a finding: slide indices, years,
#: and the small integers that appear in ordinary prose ("two of three").
_INNOCUOUS = set(range(0, 13)) | set(range(1900, 2101))

_NUMBER = re.compile(r"\d[\d,]*(?:\.\d+)?|\.\d+")


def _numbers_in(text: str) -> set[float]:
    values: set[float] = set()
    for match in _NUMBER.finditer(text or ""):
        try:
            values.add(float(match.group(0).replace(",", "")))
        except ValueError:
            continue
    return values


def _claim_values(claims: dict[str, Claim]) -> set[float]:
    """Every figure the evidence actually supports, including bounds."""
    allowed: set[float] = set()
    for claim in claims.values():
        for value in (claim.value, claim.ci_low, claim.ci_high):
            if value is None:
                continue
            allowed.add(abs(value))
            # A hazard ratio of 0.82 is honestly reported as "18% lower risk".
            # That derivation is arithmetic on a verified number, not an
            # invention, so both renderings are permitted.
            if 0 < abs(value) < 2:
                allowed.add(round(abs(1 - abs(value)) * 100, 4))
                allowed.add(round(abs(1 - abs(value)) * 100))
    return {round(v, 6) for v in allowed}


class GateFailure(BaseModel):
    slide: int
    field: str
    detail: str


def check_copy(
    plan: StoryPlan, claims: dict[str, Claim]
) -> list[GateFailure]:
    """Refuse any figure in the copy that no verified claim supports.

    This is the last thing standing between a model's turn of phrase and a
    number printed over a citation. It runs on the finished text, after the
    model has had every opportunity to be creative with it.
    """
    allowed = _claim_values(claims)
    failures: list[GateFailure] = []

    for index, slide in enumerate(plan.slides, start=1):
        for field in ("kicker", "headline", "body"):
            text = getattr(slide, field, "") or ""
            for value in _numbers_in(text):
                if value in _INNOCUOUS or round(abs(value), 6) in allowed:
                    continue
                failures.append(
                    GateFailure(
                        slide=index,
                        field=field,
                        detail=(
                            f"{value:g} appears in the copy but no appraised claim "
                            f"reports it. Reference a claim, or drop the figure."
                        ),
                    )
                )

        for label in slide.chart.point_labels:
            for value in _numbers_in(label):
                if value in _INNOCUOUS or round(abs(value), 6) in allowed:
                    continue
                failures.append(
                    GateFailure(
                        slide=index,
                        field="chart.point_labels",
                        detail=f"{value:g} in an axis label has no supporting claim.",
                    )
                )

        missing = [
            claim_id
            for claim_id in [*slide.chart.claim_ids, slide.feature_claim_id]
            if claim_id and claim_id not in claims
        ]
        for claim_id in missing:
            failures.append(
                GateFailure(
                    slide=index,
                    field="claim_ids",
                    detail=f"claim {claim_id!r} does not exist in the evidence set.",
                )
            )

    return failures


#: Verbs that assert one thing made another happen. An observational study
#: cannot support them however large its cohort, and this is the single most
#: common way health copy overstates its evidence -- far more common, and far
#: harder to spot, than an invented figure.
_CAUSAL_VERBS = (
    "causes", "caused", "cuts", "cut ", "reduces", "reduced", "prevents",
    "prevented", "boosts", "boosted", "improves", "improved", "protects",
    "protected", "lowers", "lowered", "increases your", "leads to", "makes you",
    "adds years", "buys you", "gives you",
)

#: Intensifiers a study result does not license. "Substantial" belongs to the
#: authors if they wrote it, not to the copywriter.
_INTENSIFIERS = (
    "sharply", "dramatically", "massively", "hugely", "drastically",
    "shocking", "stunning", "game-changing", "groundbreaking", "revolutionary",
    "miracle", "astonishing", "remarkable", "profound",
)

#: Designs that can carry a causal claim.
#:
#: Deliberately excludes bare "meta-analysis" and "systematic review". A
#: meta-analysis inherits the design of what it pools: twenty cohort studies
#: synthesised are still twenty cohort studies, and pooling them buys
#: precision, not causal warrant. Only randomisation licenses "reduces".
#: A meta-analysis OF trials still matches, via "randomis".
_EXPERIMENTAL = ("randomis", "randomiz", "controlled trial", "crossover trial")


def _is_observational(appraisals: dict[str, Appraisal], paper_ids: list[str]) -> bool:
    """True when nothing in the evidence base is experimental."""
    designs = [
        (appraisals[pid].design or "").lower()
        for pid in paper_ids
        if pid in appraisals
    ]
    if not designs:
        return True
    return not any(any(k in d for k in _EXPERIMENTAL) for d in designs)


def check_language(
    plan: StoryPlan, *, observational: bool
) -> list[GateFailure]:
    """Refuse causal phrasing on observational evidence, and refuse hype outright.

    A cohort study shows that people who did X had lower rates of Y. It does
    not show that X lowers Y. The distinction is the whole difference between
    honest health communication and the genre this product exists to avoid.
    """
    failures: list[GateFailure] = []

    for index, slide in enumerate(plan.slides, start=1):
        for field in ("kicker", "headline", "body"):
            text = (getattr(slide, field, "") or "").lower()

            for word in _INTENSIFIERS:
                if word in text:
                    failures.append(GateFailure(
                        slide=index, field=field,
                        detail=(
                            f"{word!r} overstates the result. Report what was "
                            f"measured and let the figure carry the weight."
                        ),
                    ))

            if not observational:
                continue
            for verb in _CAUSAL_VERBS:
                if verb in text:
                    failures.append(GateFailure(
                        slide=index, field=field,
                        detail=(
                            f"{verb.strip()!r} asserts causation, but this evidence "
                            f"is observational. Write the association instead: "
                            f"'was linked to', 'had lower', 'is associated with'."
                        ),
                    ))
    return failures


#: A carousel of text cards is not what this format is for. The charts are the
#: reason to look, so most slides must carry one.
MIN_SLIDES_WITH_CHART = 3

#: Points below which a "chart" is a decoration. One dot on an axis conveys
#: nothing a sentence would not convey better, and it implies a comparison the
#: reader then goes looking for.
MIN_CHART_POINTS = 2

#: Body copy long enough to wrap past three lines crowds the slide and, on a
#: fixed canvas, pushes the chart into whatever space is left.
MAX_BODY_CHARS = 150


def check_structure(plan: StoryPlan) -> list[GateFailure]:
    """Refuse layouts that will render as empty or misleading."""
    failures: list[GateFailure] = []
    with_chart = 0

    for index, slide in enumerate(plan.slides, start=1):
        chart = slide.chart
        if chart.type is not ChartType.NONE:
            points = len(chart.claim_ids)
            if points < MIN_CHART_POINTS:
                failures.append(GateFailure(
                    slide=index, field="chart",
                    detail=(
                        f"a {chart.type.value} chart with {points} point(s) is not a "
                        f"chart. Reference at least {MIN_CHART_POINTS} claims, or set "
                        f"the chart type to 'none' and let the copy carry the slide."
                    ),
                ))
            else:
                with_chart += 1

        if len(slide.body or "") > MAX_BODY_CHARS:
            failures.append(GateFailure(
                slide=index, field="body",
                detail=(
                    f"body is {len(slide.body)} characters; keep it under "
                    f"{MAX_BODY_CHARS} so it reads as two or three lines."
                ),
            ))

    if plan.slides and with_chart < MIN_SLIDES_WITH_CHART:
        failures.append(GateFailure(
            slide=0, field="slides",
            detail=(
                f"only {with_chart} of {len(plan.slides)} slides carry a usable chart; "
                f"at least {MIN_SLIDES_WITH_CHART} must. The charts are the reason "
                f"this format exists."
            ),
        ))
    return failures


_RATIO_UNITS = {"", "hr", "rr", "or", "hazard ratio", "risk ratio", "odds ratio"}

#: How a study design should read on a creative. The full phrase ("prospective
#: cohort study") does not fit a chip and reads as jargon; the first word alone
#: produced "PROSPECTIVE", which names the wrong thing entirely.
_DESIGN_CHIP = (
    ("meta-analysis", "META-ANALYSIS"),
    ("systematic review", "SYSTEMATIC REVIEW"),
    ("randomis", "RCT"),
    ("randomiz", "RCT"),
    ("cohort", "COHORT"),
    ("case-control", "CASE-CONTROL"),
    ("cross-sectional", "CROSS-SECTIONAL"),
)


def design_chip(design: str) -> str:
    lowered = (design or "").lower()
    for needle, label in _DESIGN_CHIP:
        if needle in lowered:
            return label
    return "STUDY"


def format_value(claim: Claim) -> tuple[str, str]:
    """Render a claim's value as it should read on a slide, with its unit.

    Returns ``(value, unit)``. A ratio converted to a percentage change comes
    back with an EMPTY unit: printing "28% HR" states two different things at
    once, and the "HR" is left over from the quantity that was converted away.
    """
    if claim.value is None:
        return "", ""
    value = abs(claim.value)
    unit = (claim.unit or "").strip()

    if 0 < value < 2 and unit.lower() in _RATIO_UNITS:
        # Hazard and risk ratios read as a percentage change, which is the form
        # a reader can act on. The ratio itself is not a unit of the result.
        return f"{round(abs(1 - value) * 100):g}%", ""
    if value >= 1000:
        return f"{value:,.0f}", unit
    return f"{value:g}", unit


def _format_value(claim: Claim) -> str:
    return format_value(claim)[0]


def resolve(
    plan: StoryPlan,
    finding: Finding,
    claims: dict[str, Claim],
    papers: dict[str, Paper],
    appraisals: dict[str, Appraisal],
) -> dict:
    """Build the renderer payload, filling every figure from stored claims."""
    lead_paper_id = finding.supporting_paper_ids[0] if finding.supporting_paper_ids else ""
    lead_paper = papers.get(lead_paper_id)
    lead_appraisal = appraisals.get(lead_paper_id)

    source = {
        "authors": lead_paper.citation().split(".")[0] + "." if lead_paper else "",
        "journal": lead_paper.journal if lead_paper else "",
        "sample": (
            f"n={lead_appraisal.sample_size:,}"
            if lead_appraisal and lead_appraisal.sample_size
            else ""
        ),
        "tier": design_chip(lead_appraisal.design) if lead_appraisal else "",
    }

    slides = []
    for slide in plan.slides:
        payload: dict = {
            "kicker": slide.kicker,
            "headline": slide.headline,
            "body": slide.body,
            "source": source,
        }

        feature = claims.get(slide.feature_claim_id)
        if feature is not None and feature.value is not None:
            value, unit = format_value(feature)
            payload["figure"] = {"value": value, "unit": unit}

        chart = slide.chart
        if chart.type is not ChartType.NONE:
            values = [
                (claims[cid].value, claims[cid])
                for cid in chart.claim_ids
                if cid in claims and claims[cid].value is not None
            ]
            if values:
                labels = chart.point_labels + [""] * len(values)
                if chart.type is ChartType.BAR:
                    payload["chart"] = {
                        "type": "bar", "label": chart.label,
                        "bars": [
                            {"label": labels[i] or _format_value(c), "value": abs(v)}
                            for i, (v, c) in enumerate(values)
                        ],
                    }
                elif chart.type is ChartType.DOT:
                    payload["chart"] = {
                        "type": "dot", "label": chart.label, "note": chart.note,
                        "dots": [
                            {"label": labels[i] or _format_value(c), "value": abs(v)}
                            for i, (v, c) in enumerate(values)
                        ],
                    }
                elif chart.type is ChartType.BAND and len(values) >= 2:
                    low, high = sorted(abs(v) for v, _ in values[:2])
                    span = max(high - low, 1)
                    payload["chart"] = {
                        "type": "band", "label": chart.label, "note": chart.note,
                        "min": max(0, low - span), "max": high + span,
                        "from": low, "to": high,
                        "ticks": [
                            {"at": low, "label": f"{low:,.0f}"},
                            {"at": high, "label": f"{high:,.0f}"},
                        ],
                    }
        slides.append(payload)

    return {"slides": slides, "caption": plan.caption}
