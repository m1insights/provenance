"""Derive the research agenda from the subject app's own algorithm.

This is the load-bearing idea of the project. The fleet is never handed a list
of topics to read about; it reads the algorithm -- the prose specification and
the implementation the constants actually live in -- and works out what
literature would bear on it.

A consequence worth stating plainly: change the algorithm and the research
agenda changes with it, because the agenda is keyed by a digest of the sources.
Nobody has to remember to update a topic list, which means it cannot go stale.
"""

from __future__ import annotations

import hashlib
import json
import logging
import re
from pathlib import Path

from google import genai
from google.genai import types

from . import auth
from .config import REASONING_MODEL, SubjectApp, settings
from .models import AgendaItem, ResearchAgenda

log = logging.getLogger(__name__)

CACHE_DIR = Path(__file__).resolve().parent.parent / ".cache"

INSTRUCTION = """\
You are reading the source of a production health application to work out what \
scientific literature would bear on its scoring algorithm.

You will be given two documents:
1. A prose specification of the scoring system.
2. The implementation, where the numeric constants actually live.

For each scoring component, produce one agenda item:

- `component_id`: the identifier used in the source (e.g. `mvpa`, `vo2`, `autonomic`).
- `display_name`: the user-facing name if the source states one.
- `weight`: points the component contributes. For a bonus component that sits \
outside the base average, report the maximum bonus it can add (e.g. 5 for a \
"+5 bonus"), never 0 -- a zero here reads as "this component does not matter", \
which is the opposite of what a bonus means.
- `window_days`: the observation window it scores over, if stated.
- `current_rule`: a precise plain-language statement of what the algorithm does \
TODAY, including the actual numbers. This is what future evidence gets compared \
against, so it must be accurate and specific. Quote thresholds exactly as written.
- `source_ref`: `filename:line` of the governing constant where you can identify it.
- `search_concepts`: 3-5 natural-language phrases that would retrieve literature \
capable of CONFIRMING OR OVERTURNING this specific rule. Target the rule, not the \
topic: for a component that credits a day of cardio at 20 minutes, search the \
minimum-bout-duration literature, not "exercise is good for you". Phrases must be \
ones an author would plausibly write in a title or abstract.
- `mesh_terms`: 2-4 controlled MeSH headings for precise retrieval. Use real MeSH \
headings only (e.g. "Exercise", "Sleep Initiation and Maintenance Disorders", \
"Heart Rate"). Never invent one.

Also report `algorithm_version` exactly as the source states it (e.g. "VI v2.11.0").

Cover every scoring component including bonuses. Do not invent components that \
are not in the source.
"""


def source_digest(subject: SubjectApp) -> str:
    """Hash the algorithm sources. Any change invalidates the cached agenda."""
    digest = hashlib.sha256()
    for path in (subject.algorithm_doc, subject.algorithm_source):
        digest.update(path.read_bytes() if path.is_file() else b"")
    return digest.hexdigest()[:16]


def _cache_path(subject: SubjectApp, digest: str) -> Path:
    return CACHE_DIR / f"agenda-{subject.key}-{digest}.json"


def _extract_version(source: str) -> str:
    match = re.search(r'static let current\s*=\s*"([^"]+)"', source)
    return match.group(1) if match else "unknown"


def _client() -> genai.Client:
    cfg = settings()
    if cfg.use_vertex:
        return genai.Client(
            vertexai=True,
            project=cfg.gcp_project,
            location=cfg.gemini_location,
            credentials=auth.credentials(cfg.gcp_project),
        )
    if not cfg.google_api_key:
        raise RuntimeError(
            "No Gemini credentials. Set GOOGLE_API_KEY, or set "
            "GOOGLE_GENAI_USE_VERTEXAI=true after `gcloud auth login`."
        )
    return genai.Client(api_key=cfg.google_api_key)


def build_agenda(subject: SubjectApp, *, refresh: bool = False) -> ResearchAgenda:
    """Read the algorithm and return the agenda it implies.

    Cached against the source digest, so this costs one Gemini call per
    algorithm change rather than one per nightly run.
    """
    if not subject.exists():
        raise FileNotFoundError(
            f"{subject.key}: cannot read algorithm sources at {subject.algorithm_source}"
        )

    digest = source_digest(subject)
    cached = _cache_path(subject, digest)
    if cached.is_file() and not refresh:
        log.info("agenda: reusing cache for digest %s", digest)
        return ResearchAgenda.model_validate_json(cached.read_text())

    spec = subject.algorithm_doc.read_text()
    source = subject.algorithm_source.read_text()

    log.info(
        "agenda: reading %s (%d lines) + %s (%d lines)",
        subject.algorithm_doc.name,
        spec.count("\n"),
        subject.algorithm_source.name,
        source.count("\n"),
    )

    # Bind the client to a name. Calling `_client().models.generate_content(...)`
    # leaves the Client as a temporary, and CPython is free to finalise it --
    # closing its httpx transport -- while the request is still in flight.
    client = _client()
    response = client.models.generate_content(
        model=REASONING_MODEL,
        contents=[
            f"# Specification: {subject.algorithm_doc.name}\n\n{spec}",
            f"# Implementation: {subject.algorithm_source.name}\n\n{source}",
        ],
        config=types.GenerateContentConfig(
            system_instruction=INSTRUCTION,
            response_mime_type="application/json",
            response_schema=list[AgendaItem],
            # Near-zero temperature: this is an extraction, not a composition.
            temperature=0.1,
        ),
    )

    items = [AgendaItem.model_validate(raw) for raw in json.loads(response.text)]
    agenda = ResearchAgenda(
        subject_key=subject.key,
        algorithm_version=_extract_version(source),
        source_digest=digest,
        items=items,
    )

    CACHE_DIR.mkdir(exist_ok=True)
    cached.write_text(agenda.model_dump_json(indent=2))
    log.info("agenda: %d components for %s", len(items), agenda.algorithm_version)
    return agenda
