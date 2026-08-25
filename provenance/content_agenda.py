"""The content lane -- topics swept for the feed, never for the algorithm.

The research agenda is derived from the subject app's own algorithm, and that
is the right scope for changing a constant. It is the wrong scope for the
content backlog: the strongest posts attack a
number everyone has been told to hit, and most such numbers -- coffee cups,
sitting hours, protein grams -- are adjacent to what synqology tracks without
being a scoring component at all.

This module is the second, static lane. Each item is a universal-belief number
with a dose-response literature behind it, which is exactly the claim shape the
sweep reel renders (`/social`, motion `sweep`). The `current_rule` field holds
the POPULAR BELIEF rather than an algorithm rule, so the appraiser's
`challenges` alignment means "challenges the folk number" -- the most watchable
outcome a post can have.

Hard boundary: `content.*` components must never reach the Synthesist. There
is no constant to change, so convergence here can never become a Finding, an
issue, or a pull request. The guard lives in `agents/synthesist.py`; this
docstring is the contract it enforces.
"""

from __future__ import annotations

from .models import AgendaItem

#: Every content-lane component id starts with this. The prefix IS the guard
#: key: the synthesist skips it, and nothing else needs to know the list.
PREFIX = "content."


def is_content_component(component_id: str) -> bool:
    return component_id.startswith(PREFIX)


#: Curated, deliberately short. Each entry earns its place by being (a) a
#: number people already believe, (b) adjacent to something synqology tracks,
#: and (c) backed by a dose-response literature a sweep can draw. Adding an
#: item is cheap; the appraiser and tier floor still decide what survives.
ITEMS: list[AgendaItem] = [
    AgendaItem(
        component_id="content.caffeine",
        display_name="Coffee",
        weight=0.0,
        current_rule=(
            "CONTENT LANE — no scoring rule to change. The popular belief under "
            "test: coffee is a vice, and more than a cup or two a day is bad "
            "for you. The literature reports a J-shaped dose-response for "
            "coffee consumption against all-cause and cardiovascular mortality."
        ),
        search_concepts=[
            "coffee consumption", "dose-response", "all-cause mortality",
            "cups per day", "caffeine intake",
        ],
        mesh_terms=["Coffee", "Mortality"],
    ),
    AgendaItem(
        component_id="content.sitting",
        display_name="Sitting time",
        weight=0.0,
        current_rule=(
            "CONTENT LANE — no scoring rule to change. The popular belief under "
            "test: sitting is the new smoking, and a workout cannot undo a desk "
            "job. The literature reports dose-response associations for daily "
            "sitting time against mortality, modified by activity level."
        ),
        search_concepts=[
            "sedentary time", "sitting time", "dose-response",
            "all-cause mortality", "prolonged sitting",
        ],
        mesh_terms=["Sedentary Behavior", "Mortality"],
    ),
    AgendaItem(
        component_id="content.protein",
        display_name="Protein",
        weight=0.0,
        current_rule=(
            "CONTENT LANE — no scoring rule to change. The popular belief under "
            "test: 0.8 g/kg/day of protein is enough for everyone. The "
            "literature reports dose-response relations for protein intake "
            "against muscle mass, strength, and healthy ageing, particularly "
            "over 60."
        ),
        search_concepts=[
            "protein intake", "dose-response", "muscle mass",
            "sarcopenia", "older adults",
        ],
        mesh_terms=["Dietary Proteins", "Sarcopenia"],
    ),
    AgendaItem(
        component_id="content.sauna",
        display_name="Sauna",
        weight=0.0,
        current_rule=(
            "CONTENT LANE — no scoring rule to change. The popular belief under "
            "test: sauna is a spa habit, not a health behaviour. The Finnish "
            "cohort literature reports dose-response associations for sauna "
            "sessions per week against cardiovascular and all-cause mortality."
        ),
        search_concepts=[
            "sauna bathing", "dose-response", "cardiovascular mortality",
            "heat therapy", "sessions per week",
        ],
        mesh_terms=["Steam Bath", "Cardiovascular Diseases"],
    ),
    AgendaItem(
        component_id="content.alcohol",
        display_name="Alcohol",
        weight=0.0,
        current_rule=(
            "CONTENT LANE — no scoring rule to change. The popular belief under "
            "test: a glass of red wine a day is good for the heart. The recent "
            "literature (Mendelian randomisation, corrected cohorts) reports no "
            "safe threshold and challenges the classic J-curve."
        ),
        search_concepts=[
            "alcohol consumption", "dose-response", "all-cause mortality",
            "mendelian randomization", "moderate drinking",
        ],
        mesh_terms=["Alcohol Drinking", "Mortality"],
    ),
    AgendaItem(
        component_id="content.organage",
        display_name="Organ age",
        weight=0.0,
        current_rule=(
            "CONTENT LANE — no scoring rule to change. The popular belief under "
            "test: you have one age, the number on your birthday. The "
            "proteomic-clock literature estimates per-organ biological ages "
            "from blood and reports graded mortality and disease risk as the "
            "count of biologically aged organs accrues."
        ),
        search_concepts=[
            "organ age", "biological age", "plasma proteomics",
            "aging clock", "age gap",
        ],
        mesh_terms=["Aging", "Proteomics"],
    ),
    AgendaItem(
        component_id="content.walkingpace",
        display_name="Walking pace",
        weight=0.0,
        current_rule=(
            "CONTENT LANE — no scoring rule to change. The popular belief under "
            "test: what matters is how far you walk, not how fast. The "
            "literature reports graded associations for walking pace and "
            "cadence against mortality, independent of volume."
        ),
        search_concepts=[
            "walking pace", "walking speed", "dose-response",
            "step cadence", "all-cause mortality",
        ],
        mesh_terms=["Walking Speed", "Mortality"],
    ),
    AgendaItem(
        component_id="content.income",
        display_name="Income and lifespan",
        weight=0.0,
        current_rule=(
            "CONTENT LANE — no scoring rule to change. The popular belief under "
            "test: everyone gets roughly the same lifespan — around 78 years in "
            "the US — and how long you live comes down to genes and luck, not "
            "money. The registry literature reports a graded, near-linear "
            "association between household income rank and life expectancy "
            "at 40, by sex, with the gap between the richest and poorest "
            "widening over time."
        ),
        search_concepts=[
            "income", "life expectancy", "income percentile",
            "socioeconomic", "longevity",
        ],
        mesh_terms=["Income", "Life Expectancy"],
    ),
    # --- Added 2026-08-25: the pool ran thin on sweepable topics. Every item
    # below is a number the viewer already owns (their bedtime, their blood
    # pressure, their BMI, their working week), with a graded dose-response
    # literature whose ABSTRACT tabulates ≥3 points — the shape behind the
    # four 80K+ reels (steps, sleep hours, resting heart rate, income rank).
    AgendaItem(
        component_id="content.workhours",
        display_name="Working hours",
        weight=0.0,
        current_rule=(
            "CONTENT LANE — no scoring rule to change. The popular belief under "
            "test: long hours are a career cost, not a health cost — if you are "
            "young and fit, a 60-hour week is harmless. The pooled-cohort "
            "literature reports a graded association between usual hours worked "
            "per week (35–40 reference, 41–48, 49–54, 55+) and stroke and "
            "coronary heart disease."
        ),
        search_concepts=[
            "long working hours", "working hours", "hours per week",
            "stroke", "coronary heart disease",
        ],
        mesh_terms=["Work Schedule Tolerance", "Workload"],
    ),
    AgendaItem(
        component_id="content.bedtime",
        display_name="Bedtime",
        weight=0.0,
        current_rule=(
            "CONTENT LANE — no scoring rule to change. The popular belief under "
            "test: it is the hours of sleep that count, not what time you fall "
            "asleep. The accelerometer cohort literature reports a graded, "
            "U-shaped association between sleep-onset time (before 10pm, 10–11pm, "
            "11pm–midnight, after midnight) and incident cardiovascular disease."
        ),
        search_concepts=[
            "sleep onset timing", "bedtime", "sleep timing",
            "cardiovascular disease", "chronotype",
        ],
        mesh_terms=["Sleep", "Circadian Rhythm"],
    ),
    AgendaItem(
        component_id="content.bloodpressure",
        display_name="Blood pressure",
        weight=0.0,
        current_rule=(
            "CONTENT LANE — no scoring rule to change. The popular belief under "
            "test: 120/80 is 'normal' and anything under 140 is fine. The "
            "literature reports graded cardiovascular risk across blood-pressure "
            "categories (normal, elevated, stage 1, stage 2) including in young "
            "adults, and trial meta-analyses report lower event rates at "
            "achieved systolic levels well below 140."
        ),
        search_concepts=[
            "blood pressure", "systolic blood pressure", "elevated blood pressure",
            "cardiovascular events", "hypertension classification",
        ],
        mesh_terms=["Blood Pressure", "Hypertension"],
    ),
    AgendaItem(
        component_id="content.bmi",
        display_name="BMI",
        weight=0.0,
        current_rule=(
            "CONTENT LANE — no scoring rule to change. The popular belief under "
            "test: a BMI under 25 is healthy and the risk only starts above it. "
            "The pooled-cohort literature reports a J-shaped association between "
            "body-mass index and all-cause mortality, with the minimum in the "
            "20–25 band and risk rising on both sides."
        ),
        search_concepts=[
            "body mass index", "all-cause mortality", "dose-response",
            "obesity", "underweight",
        ],
        mesh_terms=["Body Mass Index", "Mortality"],
    ),
    AgendaItem(
        component_id="content.fruitveg",
        display_name="Five a day",
        weight=0.0,
        current_rule=(
            "CONTENT LANE — no scoring rule to change. The popular belief under "
            "test: five portions of fruit and veg a day is the target, and more "
            "is always better. The cohort meta-analysis literature reports a "
            "dose-response for daily servings against mortality that flattens "
            "around five servings."
        ),
        search_concepts=[
            "fruit and vegetable", "servings per day", "all-cause mortality",
            "dose-response", "fruit intake",
        ],
        mesh_terms=["Fruit", "Vegetables"],
    ),
    AgendaItem(
        component_id="content.naps",
        display_name="Naps",
        weight=0.0,
        current_rule=(
            "CONTENT LANE — no scoring rule to change. The popular belief under "
            "test: a nap is always good rest, and a longer one is better rest. "
            "The dose-response meta-analysis literature reports no association "
            "for short naps and rising cardiovascular and all-cause risk once "
            "nap length passes about 40–60 minutes."
        ),
        search_concepts=[
            "daytime napping", "nap duration", "cardiovascular disease",
            "all-cause mortality", "dose-response",
        ],
        mesh_terms=["Sleep", "Mortality"],
    ),
    AgendaItem(
        component_id="content.screentime",
        display_name="TV hours",
        weight=0.0,
        current_rule=(
            "CONTENT LANE — no scoring rule to change. The popular belief under "
            "test: television is harmless downtime. The meta-analysis literature "
            "reports graded associations per hour of daily TV viewing against "
            "type 2 diabetes, cardiovascular disease, and all-cause mortality."
        ),
        search_concepts=[
            "television viewing", "screen time", "hours per day",
            "all-cause mortality", "type 2 diabetes",
        ],
        mesh_terms=["Television", "Sedentary Behavior"],
    ),
    AgendaItem(
        component_id="content.lifting",
        display_name="Strength training minutes",
        weight=0.0,
        current_rule=(
            "CONTENT LANE — no scoring rule to change. The popular belief under "
            "test: more time lifting is always better. The meta-analysis "
            "literature reports a J-shaped dose-response for muscle-strengthening "
            "minutes per week against mortality, with the maximum benefit around "
            "30–60 minutes and no further gain — or a loss — beyond about 130."
        ),
        search_concepts=[
            "muscle-strengthening", "resistance training", "minutes per week",
            "all-cause mortality", "dose-response",
        ],
        mesh_terms=["Resistance Training", "Mortality"],
    ),
]


def lane_items(existing_ids: set[str] | None = None) -> list[AgendaItem]:
    """The lane, minus anything already present.

    Cloud Run reads the latest agenda GitHub Actions published from synqology's
    ``launch`` branch. That agenda already carries the lane, so appending
    blindly would duplicate every item.
    """
    existing = existing_ids or set()
    return [item for item in ITEMS if item.component_id not in existing]


def with_lane(agenda):
    """The agenda plus the content lane, deduplicated by component id.

    Every consumer that appraises papers must go through this -- the CLI
    ``appraise`` path once built the bare algorithm agenda, and triage then
    rejected every content-lane paper as bearing on no scoring component.
    """
    extra = lane_items({item.component_id for item in agenda.items})
    if not extra:
        return agenda
    return agenda.model_copy(update={"items": agenda.items + extra})
