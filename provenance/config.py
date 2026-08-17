"""Runtime configuration for Provenance.

Everything the fleet needs to reach Gemini, Firestore and the subject repository
lives here. Nothing else in the package reads ``os.environ`` directly.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

REPO_ROOT = Path(__file__).resolve().parent.parent


# The hackathon requires Gemini 3.5 or newer. ``gemini-3.1-pro-preview`` is the
# most capable model on offer but its version is 3.1, which is *older* than the
# floor — selecting it would fail the entry rule. Both models below clear it.
REASONING_MODEL = "gemini-3.7-flash"
TRIAGE_MODEL = "gemini-3.5-flash-lite"


@dataclass(frozen=True)
class CrossRepoCompanion:
    """A file that must change with the algorithm but lives in another repository.

    synqology's scoring rules are mirrored into the backend's chat explainer,
    which is a separate GitHub repository. A pull request cannot span the two,
    and an agent that edits a path it cannot push produces a proposal that
    silently drops part of the change. These are surfaced as a linked issue
    instead, so the obligation is recorded rather than lost.
    """

    github_repo: str
    path: str
    why: str


@dataclass(frozen=True)
class SubjectApp:
    """The application whose algorithm defines the research agenda."""

    key: str
    name: str
    #: Root of the git repository that pull requests target. Every editable
    #: path is relative to this, so it must be the repo itself and not a
    #: parent directory containing sibling repositories.
    repo_path: Path
    github_repo: str
    base_branch: str
    #: Prose specification of the scoring system. Read verbatim by the agenda builder.
    algorithm_doc: Path
    #: Implementation the constants actually live in. The Engineer edits this.
    algorithm_source: Path
    #: In-repo files that must change together whenever the algorithm changes.
    #: The subject repository's own contributor rules make this mandatory.
    companion_files: tuple[Path, ...] = field(default_factory=tuple)
    #: Obligations in other repositories. Reported, never edited.
    cross_repo_companions: tuple[CrossRepoCompanion, ...] = field(default_factory=tuple)
    branch_prefix: str = "provenance/"

    def exists(self) -> bool:
        return self.algorithm_doc.is_file() and self.algorithm_source.is_file()


_SYNQ = Path("/Users/m1labs/Dev/apps/synqology/synq")

SYNQOLOGY = SubjectApp(
    key="synqology",
    name="synqology",
    repo_path=_SYNQ,
    github_repo=os.getenv("SYNQOLOGY_GITHUB_REPO", "m1insights/synq"),
    # The active trunk, not `main`. Branching from the wrong ref produces a
    # pull request whose diff includes everyone else's work.
    base_branch=os.getenv("SYNQOLOGY_BASE_BRANCH", "launch"),
    algorithm_doc=_SYNQ / "LONGEVITY_FEATURE_STACK.md",
    algorithm_source=_SYNQ / "tapntrack/Services/VitalityIndexCalculator.swift",
    companion_files=(
        _SYNQ / "LONGEVITY_FEATURE_STACK.md",
        _SYNQ / "tapntrack/Services/ShiftWorkAdjuster.swift",
    ),
    cross_repo_companions=(
        CrossRepoCompanion(
            github_repo="m1insights/synq_insights",
            path="vi_system_explainer.py",
            why=(
                "The Vitality Index explainer injected into synqIQ chat prompts. "
                "If it is not updated alongside a scoring change, the assistant "
                "describes an algorithm the app no longer runs."
            ),
        ),
    ),
)

SUBJECTS: dict[str, SubjectApp] = {SYNQOLOGY.key: SYNQOLOGY}


@dataclass(frozen=True)
class Settings:
    gcp_project: str
    #: Where infrastructure lives -- Cloud Run, the bucket, Scheduler.
    gcp_region: str
    #: Where Gemini is *served*, which is not the same thing. The 3.5+ models
    #: are listed under regional endpoints but only answer on ``global``;
    #: pointing generation at ``us-central1`` returns 404 NOT_FOUND for a model
    #: that ``models.list()`` in that same region happily reports as available.
    gemini_location: str
    firestore_database: str
    use_vertex: bool
    google_api_key: str
    pubmed_api_key: str
    pubmed_email: str
    github_token: str
    creative_bucket: str
    dry_run: bool

    @property
    def has_gemini_credentials(self) -> bool:
        return self.use_vertex or bool(self.google_api_key)


@lru_cache(maxsize=1)
def settings() -> Settings:
    use_vertex = os.getenv("GOOGLE_GENAI_USE_VERTEXAI", "").lower() in {"1", "true", "yes"}
    return Settings(
        gcp_project=os.getenv("GOOGLE_CLOUD_PROJECT", "sentinel-505814"),
        gcp_region=os.getenv("GOOGLE_CLOUD_LOCATION", "us-central1"),
        gemini_location=os.getenv("GEMINI_LOCATION", "global"),
        firestore_database=os.getenv("FIRESTORE_DATABASE", "(default)"),
        use_vertex=use_vertex,
        google_api_key=os.getenv("GOOGLE_API_KEY", ""),
        # NCBI raises the rate limit from 3/s to 10/s once a key is present, and
        # asks every automated client to identify itself by email.
        pubmed_api_key=os.getenv("PUBMED_API_KEY", ""),
        pubmed_email=os.getenv("PUBMED_EMAIL", "info@m1labs.io"),
        github_token=os.getenv("GITHUB_TOKEN", ""),
        creative_bucket=os.getenv("CREATIVE_BUCKET", "sentinel-505814-provenance-creatives"),
        dry_run=os.getenv("PROVENANCE_DRY_RUN", "").lower() in {"1", "true", "yes"},
    )
