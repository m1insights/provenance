"""The content lane -- topics swept for the feed, never for the algorithm.

The research agenda is derived from the subject app's own algorithm, and that
is the right scope for changing a constant. It is the wrong scope for the
content backlog: the breakout reel to date (10k-steps, 84K views) attacked a
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
]


def lane_items(existing_ids: set[str] | None = None) -> list[AgendaItem]:
    """The lane, minus anything already present.

    A cloud run reads the agenda the last local run published, and that agenda
    already carries the lane -- appending blindly would duplicate every item.
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
