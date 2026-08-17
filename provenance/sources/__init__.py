"""Literature sources.

Every source returns ``Paper`` objects with a DOI-first identity, so the same
study arriving from two sources collapses to one document rather than being
counted twice toward convergence -- which would be the easiest way for this
system to fool itself.
"""

from __future__ import annotations

import asyncio
import logging

import httpx

from ..models import AgendaItem, Paper
from . import europepmc, pubmed

log = logging.getLogger(__name__)

__all__ = ["europepmc", "pubmed", "gather"]


async def gather(
    item: AgendaItem,
    *,
    since_days: int = 540,
    limit_per_source: int = 40,
) -> list[Paper]:
    """Query every source concurrently and merge on identity.

    Each source renders the agenda item into its own query dialect. A source
    that fails does not fail the sweep -- one flaky API should never cost a
    night's ingest.
    """
    pubmed_query = pubmed.build_query(item)
    europepmc_query = europepmc.build_query(item)
    if not pubmed_query and not europepmc_query:
        return []

    async with httpx.AsyncClient(headers={"User-Agent": "provenance/0.1"}) as client:
        results = await asyncio.gather(
            pubmed.search(
                pubmed_query, since_days=since_days, limit=limit_per_source, client=client
            ),
            europepmc.search(
                europepmc_query, since_days=since_days, limit=limit_per_source, client=client
            ),
            return_exceptions=True,
        )

    merged: dict[str, Paper] = {}
    for outcome in results:
        if isinstance(outcome, BaseException):
            log.warning("source failed, continuing: %s", outcome)
            continue
        for paper in outcome:
            existing = merged.get(paper.doc_id)
            # Prefer whichever copy carries an abstract; between two that do,
            # prefer the peer-reviewed one over the preprint.
            if existing is None:
                merged[paper.doc_id] = paper
            elif not existing.abstract and paper.abstract:
                merged[paper.doc_id] = paper
            elif "Preprint" in existing.publication_types and "Preprint" not in paper.publication_types:
                merged[paper.doc_id] = paper

    for paper in merged.values():
        paper.matched_components = [item.component_id]

    return sorted(
        merged.values(),
        key=lambda p: (p.published is not None, p.published),
        reverse=True,
    )
