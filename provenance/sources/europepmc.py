"""Europe PMC retrieval.

Complements PubMed rather than duplicating it: Europe PMC indexes preprints
(medRxiv, bioRxiv) and non-MEDLINE journals, so it surfaces work months before
PubMed does. The Appraiser tiers preprints down accordingly -- reaching them
early is useful, trusting them equally is not.
"""

from __future__ import annotations

import logging
from datetime import date

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from ..models import AgendaItem, Paper, SourceName

log = logging.getLogger(__name__)

SEARCH_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"

#: Europe PMC source codes worth reading. PPR = preprint server.
_WANTED_SOURCES = {"MED", "PMC", "PPR"}


def build_query(item: AgendaItem) -> str:
    """Render an agenda item in Europe PMC's ``FIELD:"value"`` syntax.

    Passing PubMed's ``"Exercise"[MeSH Terms]`` here does not error -- it
    matches nothing and returns an empty result set, which reads as "no new
    literature" rather than as a bug. Hence two builders.
    """
    mesh = " OR ".join(f'MESH:"{t}"' for t in item.mesh_terms if t.strip())
    free = " OR ".join(
        f'(TITLE:"{c}" OR ABSTRACT:"{c}")' for c in item.search_concepts if c.strip()
    )
    parts = [f"({p})" for p in (mesh, free) if p]
    return "(" + " OR ".join(parts) + ")" if parts else ""


def _parse_date(raw: str) -> date | None:
    """Accept the several shapes Europe PMC returns: Y, Y-M, Y-M-D."""
    if not raw:
        return None
    bits = raw.split("-")
    try:
        year = int(bits[0])
        month = int(bits[1]) if len(bits) > 1 else 1
        day = int(bits[2]) if len(bits) > 2 else 1
        return date(year, max(1, min(12, month)), max(1, min(28, day)))
    except (ValueError, IndexError):
        return None


def _parse_record(record: dict) -> Paper | None:
    title = (record.get("title") or "").strip().rstrip(".")
    if not title:
        return None

    doi = (record.get("doi") or "").strip()
    pmid = (record.get("pmid") or "").strip()
    authors = [
        a.strip()
        for a in (record.get("authorString") or "").split(",")
        if a.strip()
    ]

    is_preprint = record.get("source") == "PPR"
    pub_types = [
        t.strip()
        for t in (record.get("pubTypeList", {}).get("pubType") or [])
        if isinstance(t, str) and t.strip()
    ]
    if is_preprint and "Preprint" not in pub_types:
        pub_types.append("Preprint")

    return Paper(
        doc_id=Paper.make_id(doi=doi, pmid=pmid, title=title),
        source=SourceName.MEDRXIV if is_preprint else SourceName.EUROPE_PMC,
        title=title,
        abstract=(record.get("abstractText") or "").strip(),
        journal=(record.get("journalTitle") or "").strip(),
        published=_parse_date(record.get("firstPublicationDate") or ""),
        doi=doi,
        pmid=pmid,
        pmcid=(record.get("pmcid") or "").strip(),
        authors=authors[:20],
        url=(
            f"https://europepmc.org/article/{record.get('source', 'MED')}/"
            f"{record.get('id', '')}"
        ),
        publication_types=pub_types,
    )


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
async def _get(client: httpx.AsyncClient, params: dict) -> dict:
    response = await client.get(SEARCH_URL, params=params, timeout=30.0)
    response.raise_for_status()
    return response.json()


async def search(
    query: str,
    *,
    since_days: int = 540,
    limit: int = 40,
    client: httpx.AsyncClient | None = None,
) -> list[Paper]:
    if not query.strip():
        return []

    owns_client = client is None
    client = client or httpx.AsyncClient(headers={"User-Agent": "provenance/0.1"})

    try:
        cutoff = date.fromordinal(max(1, date.today().toordinal() - since_days))
        # Abstracts are required: a record without one cannot be appraised, and
        # cannot supply the verbatim quote the grounding check demands.
        scoped = (
            f"({query}) AND (FIRST_PDATE:[{cutoff.isoformat()} TO "
            f"{date.today().isoformat()}]) AND (HAS_ABSTRACT:Y)"
        )
        payload = await _get(
            client,
            {
                "query": scoped,
                "format": "json",
                "resultType": "core",
                "pageSize": str(min(limit, 100)),
                "sort": "P_PDATE_D desc",
            },
        )
        records = payload.get("resultList", {}).get("result", [])
        papers = [
            paper
            for record in records
            if record.get("source") in _WANTED_SOURCES
            and (paper := _parse_record(record)) is not None
        ]
        log.info("europepmc: %d records for query", len(papers))
        return papers
    finally:
        if owns_client:
            await client.aclose()
