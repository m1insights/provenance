"""Scout -- nightly literature sweep.

Runs every agenda component against every source, concurrently, and returns
what has not been seen before. The Scout makes no judgements: a record either
is new and retrievable, or it is not. Everything evaluative happens downstream
in the Appraiser, which keeps the "did we see it" question separable from the
"is it any good" question.
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field

from ..agenda import build_agenda
from ..config import SubjectApp
from ..content_agenda import lane_items
from ..models import Paper, Rejection, ResearchAgenda
from ..sources import gather

log = logging.getLogger(__name__)

#: Concurrency ceiling across components. NCBI throttles per IP, and the
#: per-source limiter is per-call, so this bounds total pressure on the API.
_MAX_CONCURRENT_COMPONENTS = 4

#: Publication types that cannot support an algorithm change no matter what
#: they say. Filtered here rather than spending an appraisal call on them.
_UNAPPRAISABLE = {
    "Comment",
    "Editorial",
    "Published Erratum",
    "Retraction of Publication",
    "Retracted Publication",
    "News",
    "Biography",
    "Congress",
}


@dataclass
class SweepResult:
    agenda: ResearchAgenda
    papers: list[Paper] = field(default_factory=list)
    rejections: list[Rejection] = field(default_factory=list)
    seen_count: int = 0

    @property
    def per_component(self) -> dict[str, int]:
        counts: dict[str, int] = {}
        for paper in self.papers:
            for component in paper.matched_components:
                counts[component] = counts.get(component, 0) + 1
        return counts


def _screen(paper: Paper) -> Rejection | None:
    """Cheap structural screening. Not a judgement about quality."""
    if not paper.abstract or len(paper.abstract) < 200:
        return Rejection(
            paper_id=paper.doc_id,
            title=paper.title,
            stage="scout",
            reason_code="no_abstract",
            reason="No abstract, or too short to appraise or to quote from.",
        )
    blocked = _UNAPPRAISABLE.intersection(paper.publication_types)
    if blocked:
        return Rejection(
            paper_id=paper.doc_id,
            title=paper.title,
            stage="scout",
            reason_code="unappraisable_type",
            reason=f"Publication type {sorted(blocked)[0]!r} cannot support a change.",
        )
    return None


async def sweep(
    subject: SubjectApp,
    *,
    since_days: int = 540,
    limit_per_source: int = 25,
    known_ids: set[str] | None = None,
    components: list[str] | None = None,
) -> SweepResult:
    """Query every agenda component and return unseen, screenable papers."""
    agenda = build_agenda(subject)
    # The content lane rides along: universal-belief topics adjacent to the
    # app, swept for the feed rather than the algorithm. It joins the agenda
    # HERE, after build_agenda, so the algorithm-derived agenda stays pure --
    # and deduplicated by id, because a cloud run's stored agenda already
    # carries the lane from the run that published it. The synthesist skips
    # `content.*` components, so nothing here can ever become a pull request.
    extra = lane_items({item.component_id for item in agenda.items})
    if extra:
        agenda = agenda.model_copy(update={"items": agenda.items + extra})
    items = [
        item
        for item in agenda.items
        if components is None or item.component_id in components
    ]
    known = known_ids or set()
    result = SweepResult(agenda=agenda)

    semaphore = asyncio.Semaphore(_MAX_CONCURRENT_COMPONENTS)

    async def one(item):
        async with semaphore:
            try:
                return await gather(
                    item, since_days=since_days, limit_per_source=limit_per_source
                )
            except Exception as exc:  # a component failing must not fail the sweep
                log.warning("scout: %s failed: %s", item.component_id, exc)
                return []

    harvested = await asyncio.gather(*(one(item) for item in items))

    # Merge across components before screening. The same trial legitimately
    # bears on cardio and on VO2 max; it should be appraised once and carry
    # both component tags, not appraised twice and counted twice toward
    # convergence.
    merged: dict[str, Paper] = {}
    for batch in harvested:
        for paper in batch:
            existing = merged.get(paper.doc_id)
            if existing is None:
                merged[paper.doc_id] = paper
            else:
                for component in paper.matched_components:
                    if component not in existing.matched_components:
                        existing.matched_components.append(component)

    for paper in merged.values():
        if paper.doc_id in known:
            result.seen_count += 1
            continue
        rejection = _screen(paper)
        if rejection is not None:
            result.rejections.append(rejection)
            continue
        result.papers.append(paper)

    log.info(
        "scout: %d components -> %d retrieved, %d new, %d already seen, %d screened out",
        len(items),
        len(merged),
        len(result.papers),
        result.seen_count,
        len(result.rejections),
    )
    return result
