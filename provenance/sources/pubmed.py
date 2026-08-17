"""PubMed retrieval via NCBI E-utilities.

Two calls per query: ``esearch`` for identifiers, ``efetch`` for records. NCBI
allows 3 requests/second unauthenticated and 10 with an API key, and asks every
automated client to identify itself -- both are honoured below.
"""

from __future__ import annotations

import asyncio
import logging
import xml.etree.ElementTree as ET
from datetime import date, timedelta

import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

from ..config import settings
from ..models import AgendaItem, Paper, SourceName

log = logging.getLogger(__name__)

BASE = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


def build_query(item: AgendaItem) -> str:
    """Render an agenda item in PubMed's bracketed field syntax."""
    mesh = " OR ".join(f'"{t}"[MeSH Terms]' for t in item.mesh_terms if t.strip())
    free = " OR ".join(f'"{c}"[Title/Abstract]' for c in item.search_concepts if c.strip())
    parts = [f"({p})" for p in (mesh, free) if p]
    return "(" + " OR ".join(parts) + ")" if parts else ""

_MONTHS = {
    m: i
    for i, m in enumerate(
        ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
         "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"],
        start=1,
    )
}


class _RateLimiter:
    """Spacing gate. NCBI blocks IPs that ignore the published ceiling."""

    def __init__(self, per_second: float) -> None:
        self._interval = 1.0 / per_second
        self._lock = asyncio.Lock()
        self._last = 0.0

    async def wait(self) -> None:
        async with self._lock:
            loop = asyncio.get_running_loop()
            gap = loop.time() - self._last
            if gap < self._interval:
                await asyncio.sleep(self._interval - gap)
            self._last = loop.time()


def _common_params() -> dict[str, str]:
    cfg = settings()
    params = {"db": "pubmed", "tool": "provenance", "email": cfg.pubmed_email}
    if cfg.pubmed_api_key:
        params["api_key"] = cfg.pubmed_api_key
    return params


def _text(node: ET.Element | None, path: str, default: str = "") -> str:
    if node is None:
        return default
    found = node.find(path)
    if found is None:
        return default
    return "".join(found.itertext()).strip() or default


def _parse_date(article: ET.Element) -> date | None:
    """Prefer the electronic publication date; fall back to the journal issue."""
    for path in ("ArticleDate", "Journal/JournalIssue/PubDate"):
        node = article.find(path)
        if node is None:
            continue
        year = _text(node, "Year")
        if not year.isdigit():
            medline = _text(node, "MedlineDate")
            year = medline[:4] if medline[:4].isdigit() else ""
        if not year.isdigit():
            continue
        raw_month = _text(node, "Month", "1")
        month = _MONTHS.get(raw_month[:3], int(raw_month) if raw_month.isdigit() else 1)
        raw_day = _text(node, "Day", "1")
        day = int(raw_day) if raw_day.isdigit() else 1
        try:
            return date(int(year), max(1, min(12, month)), max(1, min(28, day)))
        except ValueError:
            continue
    return None


def _parse_abstract(article: ET.Element) -> str:
    """Structured abstracts arrive as labelled sections; keep the labels.

    "METHODS: ... RESULTS: ..." is materially easier to appraise than one run-on
    paragraph, and the labels survive into the verbatim-quote check.
    """
    parts: list[str] = []
    for chunk in article.findall("Abstract/AbstractText"):
        label = (chunk.get("Label") or "").strip()
        body = "".join(chunk.itertext()).strip()
        if not body:
            continue
        parts.append(f"{label}: {body}" if label else body)
    return "\n".join(parts)


def _parse_article(citation: ET.Element) -> Paper | None:
    article = citation.find("Article")
    if article is None:
        return None

    title = _text(article, "ArticleTitle")
    if not title:
        return None

    pmid = _text(citation, "PMID")
    doi = ""
    for ident in citation.findall("../PubmedData/ArticleIdList/ArticleId"):
        if ident.get("IdType") == "doi":
            doi = (ident.text or "").strip()
            break

    authors: list[str] = []
    for author in article.findall("AuthorList/Author"):
        last = _text(author, "LastName")
        initials = _text(author, "Initials")
        if last:
            authors.append(f"{last} {initials}".strip())

    return Paper(
        doc_id=Paper.make_id(doi=doi, pmid=pmid, title=title),
        source=SourceName.PUBMED,
        title=title,
        abstract=_parse_abstract(article),
        journal=_text(article, "Journal/ISOAbbreviation") or _text(article, "Journal/Title"),
        published=_parse_date(article),
        doi=doi,
        pmid=pmid,
        authors=authors,
        url=f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/" if pmid else "",
        publication_types=[
            (pt.text or "").strip()
            for pt in article.findall("PublicationTypeList/PublicationType")
            if (pt.text or "").strip()
        ],
    )


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
async def _get(client: httpx.AsyncClient, path: str, params: dict, limiter: _RateLimiter):
    await limiter.wait()
    response = await client.get(f"{BASE}/{path}", params=params, timeout=30.0)
    response.raise_for_status()
    return response


async def search(
    query: str,
    *,
    since_days: int = 540,
    limit: int = 40,
    client: httpx.AsyncClient | None = None,
) -> list[Paper]:
    """Run one boolean query and return parsed records, newest first.

    ``since_days`` defaults to ~18 months: long enough that convergence across
    three studies is reachable, recent enough that the agenda stays current.
    """
    if not query.strip():
        return []

    cfg = settings()
    limiter = _RateLimiter(10.0 if cfg.pubmed_api_key else 3.0)
    owns_client = client is None
    client = client or httpx.AsyncClient(headers={"User-Agent": "provenance/0.1"})

    try:
        window_start = (date.today() - timedelta(days=since_days)).strftime("%Y/%m/%d")
        search_params = _common_params() | {
            "term": query,
            "retmax": str(limit),
            "retmode": "json",
            "sort": "date",
            "datetype": "pdat",
            "mindate": window_start,
            "maxdate": date.today().strftime("%Y/%m/%d"),
        }
        found = await _get(client, "esearch.fcgi", search_params, limiter)
        ids = found.json().get("esearchresult", {}).get("idlist", [])
        if not ids:
            return []

        fetched = await _get(
            client,
            "efetch.fcgi",
            _common_params() | {"id": ",".join(ids), "retmode": "xml"},
            limiter,
        )
        root = ET.fromstring(fetched.text)
        papers: list[Paper] = []
        for entry in root.findall(".//PubmedArticle"):
            citation = entry.find("MedlineCitation")
            if citation is None:
                continue
            # _parse_article reaches for ../PubmedData to pick up the DOI, which
            # only resolves if it walks from the citation node.
            parsed = _parse_article(citation)
            if parsed is None:
                continue
            if not parsed.doi:
                for ident in entry.findall("PubmedData/ArticleIdList/ArticleId"):
                    if ident.get("IdType") == "doi":
                        doi = (ident.text or "").strip()
                        parsed = parsed.model_copy(
                            update={
                                "doi": doi,
                                "doc_id": Paper.make_id(
                                    doi=doi, pmid=parsed.pmid, title=parsed.title
                                ),
                            }
                        )
                        break
            papers.append(parsed)
        log.info("pubmed: %d records for query", len(papers))
        return papers
    finally:
        if owns_client:
            await client.aclose()
