"""Schemas for every artefact that moves through the pipeline.

These types are the contract between agents. An agent that cannot produce a
valid instance has failed, and its output is discarded rather than repaired --
a malformed appraisal is far more dangerous than a missing one.
"""

from __future__ import annotations

import hashlib
import re
from datetime import date, datetime, timezone
from enum import Enum
from typing import Literal

from pydantic import BaseModel, Field, field_validator


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------- #
# Research agenda -- derived from the subject app's own algorithm
# --------------------------------------------------------------------------- #


class AgendaItem(BaseModel):
    """One scoring component, and what the fleet should read about it.

    Search terms are *generated from the algorithm*, never hardcoded. Change the
    weighting of a component and its research agenda changes with it.
    """

    component_id: str = Field(description="Identifier as used in the source, e.g. 'mvpa'")
    display_name: str = Field(description="User-facing name, e.g. 'Cardio'")
    weight: float = Field(description="Points this component contributes to the score")
    window_days: int | None = Field(
        default=None, description="Observation window the component scores over"
    )
    current_rule: str = Field(
        description="Plain-language statement of what the algorithm does today, "
        "quoted or paraphrased from the source"
    )
    source_ref: str = Field(
        default="", description="file:line where the governing constant lives"
    )
    search_concepts: list[str] = Field(
        default_factory=list,
        description="Natural-language concepts to search, e.g. 'moderate-to-vigorous "
        "physical activity dose response all-cause mortality'",
    )
    mesh_terms: list[str] = Field(
        default_factory=list, description="MeSH headings for precise PubMed retrieval"
    )

    # Deliberately no ``query()`` here. PubMed and Europe PMC use incompatible
    # field syntax -- ``"Exercise"[MeSH Terms]`` versus ``MESH:"Exercise"`` --
    # and a query written for one silently returns zero results from the other.
    # Each source builds its own query from these concepts instead.


class ResearchAgenda(BaseModel):
    subject_key: str
    algorithm_version: str = Field(description="e.g. 'VI v2.11.0'")
    source_digest: str = Field(
        description="Hash of the algorithm sources. The agenda is invalidated by "
        "any change to the algorithm, which is the point."
    )
    items: list[AgendaItem]
    generated_at: datetime = Field(default_factory=_utcnow)


# --------------------------------------------------------------------------- #
# Papers
# --------------------------------------------------------------------------- #


class SourceName(str, Enum):
    PUBMED = "pubmed"
    EUROPE_PMC = "europepmc"
    CLINICAL_TRIALS = "clinicaltrials"
    MEDRXIV = "medrxiv"


class Paper(BaseModel):
    """A retrieved record, before any judgement has been made about it."""

    doc_id: str = Field(description="Stable Firestore key")
    source: SourceName
    title: str
    abstract: str = ""
    journal: str = ""
    published: date | None = None
    doi: str = ""
    pmid: str = ""
    pmcid: str = ""
    authors: list[str] = Field(default_factory=list)
    url: str = ""
    publication_types: list[str] = Field(default_factory=list)
    #: Which agenda components triggered retrieval of this record.
    matched_components: list[str] = Field(default_factory=list)
    #: Open-access body text, fetched on demand (``python -m provenance
    #: fulltext``). Empty for most papers: the abstract is the default
    #: grounding surface, and this exists for the paper whose numbers live in
    #: its results section. When present, the appraiser is shown it and
    #: grounding verifies quotes against it.
    fulltext: str = ""
    retrieved_at: datetime = Field(default_factory=_utcnow)

    @staticmethod
    def make_id(*, doi: str = "", pmid: str = "", title: str = "") -> str:
        """Prefer a DOI, fall back to PMID, then to a title hash.

        Records reach us from four sources and the same study routinely arrives
        twice -- as a preprint and as a journal article. A DOI-first identity
        collapses those into one document.
        """
        if doi:
            return "doi:" + re.sub(r"[^a-z0-9.\-/]", "", doi.strip().lower()).replace("/", "_")
        if pmid:
            return f"pmid:{pmid.strip()}"
        digest = hashlib.sha1(title.strip().lower().encode()).hexdigest()[:16]
        return f"title:{digest}"

    @staticmethod
    def surname(author: str) -> str:
        """Extract the family name from a "Massar SAA" style entry.

        Both PubMed and Europe PMC render authors as family name followed by
        initials with no comma, so taking the last token yields the initials --
        which is how a citation ends up reading "SAA et al." Everything except
        a trailing initials token is the name, which also keeps particles
        intact: "van de Sande JA" -> "van de Sande".
        """
        parts = author.split()
        if len(parts) > 1 and parts[-1].isupper() and len(parts[-1]) <= 4:
            return " ".join(parts[:-1])
        return author.strip()

    def citation(self) -> str:
        first = self.surname(self.authors[0]) if self.authors else "Unknown"
        year = self.published.year if self.published else "n.d."
        journal = f" {self.journal}." if self.journal else ""
        suffix = " et al." if len(self.authors) > 1 else ""
        return f"{first}{suffix}, {year}.{journal}".strip()


# --------------------------------------------------------------------------- #
# Appraisal
# --------------------------------------------------------------------------- #


class EvidenceTier(str, Enum):
    """GRADE-lite. The rubric lives in agents/appraiser.py."""

    A = "A"  # Meta-analysis / systematic review of RCTs, or a large well-powered RCT
    B = "B"  # Single RCT, or a large prospective cohort with hard endpoints
    C = "C"  # Small cohort, cross-sectional, or surrogate endpoints only
    D = "D"  # Mechanistic, animal, case series, or uncontrolled


class Alignment(str, Enum):
    SUPPORTS = "supports"      # Agrees with what the algorithm already does
    CHALLENGES = "challenges"  # Disagrees -- the interesting case
    EXTENDS = "extends"        # Compatible, but covers ground the algorithm ignores
    NEUTRAL = "neutral"


class Claim(BaseModel):
    """A single assertion, tied to the exact words that support it.

    ``quote`` must appear verbatim in the paper's fetched text. That is checked
    by code, not trusted from the model -- see ``grounding.verify_claims``.
    """

    claim_id: str = Field(description="Stable within the appraisal, e.g. 'c1'")
    statement: str = Field(description="The claim, in plain language")
    quote: str = Field(description="Verbatim span from the abstract supporting it")
    value: float | None = Field(default=None, description="Numeric result, if any")
    unit: str = ""
    ci_low: float | None = None
    ci_high: float | None = None

    @field_validator("quote")
    @classmethod
    def _quote_is_substantial(cls, v: str) -> str:
        if len(v.strip()) < 20:
            raise ValueError("quote too short to constitute grounding")
        return v


class AppraisalDraft(BaseModel):
    """What the model is allowed to produce.

    Identity and timestamps are deliberately absent: the model judges, code
    records which paper was judged and when. A model that can write its own
    ``paper_id`` can attach a sound appraisal to the wrong study.
    """

    tier: EvidenceTier
    design: str = Field(description="e.g. 'randomised controlled trial'")
    sample_size: int | None = None
    population: str = ""
    follow_up: str = ""
    component_ids: list[str] = Field(default_factory=list)
    alignment: Alignment = Alignment.NEUTRAL
    claims: list[Claim] = Field(default_factory=list)
    reasoning: str = ""
    plain_summary: str = Field(
        default="",
        description="One sentence a non-specialist could read: what this study "
        "did and what it found. No jargon, no statistics notation.",
    )


class RelevanceVerdict(BaseModel):
    """First-pass triage. Cheap model, one question, no judgement of quality."""

    relevant: bool
    component_ids: list[str] = Field(default_factory=list)
    reason: str = Field(default="", description="One clause. Required when not relevant.")


class Appraisal(BaseModel):
    paper_id: str
    tier: EvidenceTier
    design: str = Field(description="e.g. 'randomised controlled trial'")
    sample_size: int | None = None
    population: str = ""
    follow_up: str = ""
    component_ids: list[str] = Field(
        default_factory=list, description="Agenda components this bears on"
    )
    alignment: Alignment = Alignment.NEUTRAL
    claims: list[Claim] = Field(default_factory=list)
    reasoning: str = ""
    #: Written for a reader who is not a clinician. Optional by design: records
    #: appraised before this field existed still load, and the briefing falls
    #: back to the plain-language claim statement for them.
    plain_summary: str = ""
    appraised_at: datetime = Field(default_factory=_utcnow)


class Rejection(BaseModel):
    """Why a paper did not survive. Kept, displayed, and counted.

    The rejection log is the trust surface: a system that accepts everything has
    not appraised anything.
    """

    paper_id: str
    title: str = ""
    stage: Literal["scout", "appraiser", "grounding", "synthesist"]
    reason_code: str
    reason: str
    rejected_at: datetime = Field(default_factory=_utcnow)


# --------------------------------------------------------------------------- #
# Findings
# --------------------------------------------------------------------------- #


class FindingStatus(str, Enum):
    OPEN = "open"
    PR_DRAFTED = "pr_drafted"
    APPROVED = "approved"
    REJECTED = "rejected"


class ProposedChange(BaseModel):
    file_path: str
    symbol: str = Field(description="Constant or function being changed")
    current_value: str
    proposed_value: str
    rationale: str


class Finding(BaseModel):
    """Opened only when evidence converges. One paper is never enough."""

    finding_id: str
    subject_key: str
    component_id: str
    statement: str = Field(description="What the evidence collectively says")
    current_behavior: str = Field(description="What the algorithm does today, from source")
    supporting_paper_ids: list[str] = Field(default_factory=list)
    tier_counts: dict[str, int] = Field(default_factory=dict)
    proposed_changes: list[ProposedChange] = Field(default_factory=list)
    confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    status: FindingStatus = FindingStatus.OPEN
    issue_url: str = ""
    pr_url: str = ""
    opened_at: datetime = Field(default_factory=_utcnow)


# --------------------------------------------------------------------------- #
# Creative
# --------------------------------------------------------------------------- #


class CreativeFormat(str, Enum):
    REEL = "reel"            # 1080x1920 animated data reel
    CAROUSEL = "carousel"    # 1080x1350 editorial slides


class Slide(BaseModel):
    """Copy plus a *reference* to data. Never data itself.

    ``chart_ref`` is resolved against Firestore at render time, so the numbers on
    screen come from the appraised record and cannot be invented by the model.
    """

    headline: str
    body: str = ""
    kicker: str = ""
    chart_ref: str = Field(
        default="", description="e.g. 'papers/doi:10.1001_x#claims.c2'"
    )
    claim_ids: list[str] = Field(default_factory=list)


class CreativeSpec(BaseModel):
    spec_id: str
    finding_id: str
    format: CreativeFormat
    slides: list[Slide]
    caption: str = ""
    source_line: str = Field(default="", description="On-creative citation")
    created_at: datetime = Field(default_factory=_utcnow)
