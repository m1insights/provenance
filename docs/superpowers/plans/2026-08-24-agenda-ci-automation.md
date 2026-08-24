# Agenda CI Automation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Publish a new Firestore research agenda automatically whenever a governing synqology Vitality Index source lands on `launch`, without relying on a developer Mac or a long-lived Google credential.

**Architecture:** The private `m1insights/synq` repository owns a path-filtered GitHub Actions workflow. It checks out an immutable Provenance publisher revision, authenticates to Google Cloud with branch-restricted Workload Identity Federation, and calls an explicit idempotent `agenda --publish` command; exact Firestore digest lookup prevents repeat Gemini calls.

**Tech Stack:** Python 3.12, pytest, Google GenAI SDK, Vertex AI Gemini 3.7 Flash, Firestore, GitHub Actions, GitHub OIDC, Google Workload Identity Federation, gcloud CLI

**Spec:** `docs/superpowers/specs/2026-08-24-agenda-ci-automation-design.md`

## Global Constraints

- Preserve all pre-existing uncommitted changes in both repositories; stage and commit only files named by the current task.
- Execute repository changes in isolated worktrees using `superpowers:using-git-worktrees`; do not switch branches in either dirty primary checkout.
- Keep `python -m provenance agenda` read-only. Only `--publish` may read/write the publication store.
- The agenda identity and Gemini request must include exactly `LONGEVITY_FEATURE_STACK.md`, `VitalityIndexCalculator.swift`, and `ShiftWorkAdjuster.swift`, in that order.
- A successful exact-digest retry must make no Gemini call and no Firestore write.
- GitHub publication is allowed only for `m1insights/synq` at `refs/heads/launch`.
- Store no Google service-account key or API key in GitHub.
- The publisher service account has no Firestore delete permission and no Cloud Run, Scheduler, Secret Manager, or Storage role.
- Pin third-party actions and the Provenance publisher to 40-character commit SHAs.
- Do not redeploy or change the existing `provenance-nightly` Cloud Run Job or its 03:00 America/New_York schedule.

## File and Responsibility Map

### `m1insights/provenance`

- `provenance/config.py`: resolve the synq checkout root and define the ordered agenda source set.
- `provenance/agenda.py`: fingerprint and send the complete source set to Gemini.
- `provenance/store/firestore.py`: fetch one agenda by deterministic subject-and-digest document ID.
- `provenance/cli.py`: implement the read-only versus publish command contract and publication outcome.
- `tests/test_agenda.py`: source-path, digest, prompt-completeness, and environment-path tests.
- `tests/test_store.py`: exact agenda document lookup tests.
- `tests/test_cli.py`: idempotent publication, refresh, read-only, and failure-propagation tests.
- `README.md`: document the explicit publication command and CI handoff.
- `docs/architecture.md`: replace the manual local handoff with the deployed CI handoff.
- `docs/superpowers/specs/2026-08-24-agenda-ci-automation-design.md`: record implementation status and production evidence.

### `m1insights/synq`

- `.github/workflows/publish-provenance-agenda.yml`: trigger, authenticate, publish, and summarize agenda synchronization. The identical file must exist on both `main` (GitHub manual-dispatch discovery) and `launch` (trusted execution ref and production push trigger).

---

### Task 1: Complete Agenda Source Identity

**Files:**
- Create: `tests/test_agenda.py`
- Modify: `provenance/config.py:44-103`
- Modify: `provenance/agenda.py:25-184`

**Interfaces:**
- Consumes: `SubjectApp.algorithm_doc: Path`, `SubjectApp.algorithm_source: Path`
- Produces: `SubjectApp.agenda_supporting_sources: tuple[Path, ...]`, `SubjectApp.agenda_sources: tuple[Path, ...]`, `_synq_root() -> Path`, `source_digest(subject: SubjectApp) -> str`, `_prompt_contents(subject: SubjectApp) -> list[str]`

- [ ] **Step 1: Write source-set, digest, prompt, and path tests**

Create `tests/test_agenda.py` with concrete temporary sources:

```python
from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys

import pytest

from provenance import agenda, config
from provenance.config import SubjectApp


def _subject(tmp_path: Path) -> SubjectApp:
    specification = tmp_path / "LONGEVITY_FEATURE_STACK.md"
    primary = tmp_path / "VitalityIndexCalculator.swift"
    supporting = tmp_path / "ShiftWorkAdjuster.swift"
    specification.write_text("specification-v1")
    primary.write_text('static let current = "VI v9.9.9"\nprimary-v1')
    supporting.write_text("shift-v1")
    return SubjectApp(
        key="test",
        name="Test",
        repo_path=tmp_path,
        github_repo="example/test",
        base_branch="launch",
        algorithm_doc=specification,
        algorithm_source=primary,
        agenda_supporting_sources=(supporting,),
    )


def test_agenda_sources_are_complete_and_ordered(tmp_path: Path):
    subject = _subject(tmp_path)
    assert [path.name for path in subject.agenda_sources] == [
        "LONGEVITY_FEATURE_STACK.md",
        "VitalityIndexCalculator.swift",
        "ShiftWorkAdjuster.swift",
    ]
    assert subject.exists()


@pytest.mark.parametrize("source_index", [0, 1, 2])
def test_source_digest_changes_for_every_governing_source(
    tmp_path: Path, source_index: int
):
    subject = _subject(tmp_path)
    before = agenda.source_digest(subject)
    path = subject.agenda_sources[source_index]
    path.write_text(path.read_text() + "\nchanged")
    assert agenda.source_digest(subject) != before


def test_prompt_contains_every_fingerprinted_source(tmp_path: Path):
    subject = _subject(tmp_path)
    contents = agenda._prompt_contents(subject)
    assert len(contents) == 3
    for path, rendered in zip(subject.agenda_sources, contents, strict=True):
        assert path.name in rendered
        assert path.read_text() in rendered


def test_synq_root_uses_ci_environment_override(monkeypatch, tmp_path: Path):
    monkeypatch.setenv("SYNQOLOGY_REPO_PATH", str(tmp_path))
    assert config._synq_root() == tmp_path


def test_ci_override_roots_every_synqology_agenda_source(tmp_path: Path):
    environment = os.environ | {"SYNQOLOGY_REPO_PATH": str(tmp_path)}
    code = """
from provenance.config import SYNQOLOGY
print(SYNQOLOGY.repo_path)
for path in SYNQOLOGY.agenda_sources:
    print(path.relative_to(SYNQOLOGY.repo_path))
"""
    result = subprocess.run(
        [sys.executable, "-c", code],
        check=True,
        capture_output=True,
        text=True,
        env=environment,
    )
    assert result.stdout.splitlines() == [
        str(tmp_path),
        "LONGEVITY_FEATURE_STACK.md",
        "tapntrack/Services/VitalityIndexCalculator.swift",
        "tapntrack/Services/ShiftWorkAdjuster.swift",
    ]
```

- [ ] **Step 2: Run the new tests and verify the intended failure**

Run: `/Users/m1labs/Dev/provenance/.venv/bin/python -m pytest tests/test_agenda.py -q`

Expected: collection or execution fails because `agenda_supporting_sources`, `agenda_sources`, `_synq_root`, and `_prompt_contents` do not exist.

- [ ] **Step 3: Add the ordered source model and CI path override**

In `provenance/config.py`, add the supporting-source field and ordered property without changing the engineering companion-file contract:

```python
@dataclass(frozen=True)
class SubjectApp:
    # existing fields remain above
    algorithm_doc: Path
    algorithm_source: Path
    agenda_supporting_sources: tuple[Path, ...] = field(default_factory=tuple)
    companion_files: tuple[Path, ...] = field(default_factory=tuple)
    # existing fields remain below

    @property
    def agenda_sources(self) -> tuple[Path, ...]:
        return (
            self.algorithm_doc,
            self.algorithm_source,
            *self.agenda_supporting_sources,
        )

    def exists(self) -> bool:
        return all(path.is_file() for path in self.agenda_sources)


def _synq_root() -> Path:
    return Path(
        os.getenv("SYNQOLOGY_REPO_PATH")
        or "/Users/m1labs/Dev/apps/synqology/synq"
    )


_SYNQ = _synq_root()
```

Configure synqology with the supporting implementation while leaving `companion_files` unchanged:

```python
agenda_supporting_sources=(
    _SYNQ / "tapntrack/Services/ShiftWorkAdjuster.swift",
),
```

- [ ] **Step 4: Make fingerprinting and Gemini input use the same source set**

In `provenance/agenda.py`, change the instruction from “two documents” to a prose specification plus one or more implementation sources. Implement:

```python
def source_digest(subject: SubjectApp) -> str:
    """Hash every source supplied to agenda extraction, in prompt order."""
    digest = hashlib.sha256()
    for path in subject.agenda_sources:
        digest.update(path.read_bytes() if path.is_file() else b"")
    return digest.hexdigest()[:16]


def _prompt_contents(subject: SubjectApp) -> list[str]:
    labels = [
        "Specification",
        "Primary implementation",
        *(
            "Supporting implementation"
            for _ in subject.agenda_supporting_sources
        ),
    ]
    return [
        f"# {label}: {path.name}\n\n{path.read_text()}"
        for label, path in zip(labels, subject.agenda_sources, strict=True)
    ]
```

In `build_agenda`, use `_prompt_contents(subject)` as `generate_content(contents=...)`, keep `_extract_version` bound to `subject.algorithm_source`, and log each input filename and line count. Change the missing-source recovery message to:

```python
"Publish one with `python -m provenance agenda --publish` from a source checkout."
```

- [ ] **Step 5: Run focused tests**

Run: `/Users/m1labs/Dev/provenance/.venv/bin/python -m pytest tests/test_agenda.py -q`

Expected: all tests pass.

- [ ] **Step 6: Run config consumers to catch constructor regressions**

Run: `/Users/m1labs/Dev/provenance/.venv/bin/python -m pytest tests/test_evidence_in_proposals.py tests/test_release.py tests/test_nightly.py -q`

Expected: all tests pass, including the companion `SubjectApp` constructor that relies on the new field default.

- [ ] **Step 7: Commit the source-identity increment**

```bash
git add provenance/config.py provenance/agenda.py tests/test_agenda.py
git commit -m "feat(agenda): fingerprint every governing source"
```

### Task 2: Exact Firestore Agenda Lookup

**Files:**
- Modify: `provenance/store/firestore.py:173-200`
- Modify: `tests/test_store.py`

**Interfaces:**
- Consumes: Firestore document ID `{subject_key}__{source_digest}` and `ResearchAgenda`
- Produces: `agenda_for_digest(subject_key: str, source_digest: str, *, db: firestore.Client | None = None) -> ResearchAgenda | None`

- [ ] **Step 1: Write exact-document lookup tests**

Append to `tests/test_store.py`:

```python
from provenance.models import ResearchAgenda


class _LookupSnapshot:
    def __init__(self, payload: dict | None):
        self.exists = payload is not None
        self._payload = payload

    def to_dict(self) -> dict | None:
        return self._payload


class _LookupDocument:
    def __init__(self, db: "_LookupDb", doc_id: str):
        self.db = db
        self.doc_id = doc_id

    def get(self) -> _LookupSnapshot:
        self.db.requested.append(self.doc_id)
        return _LookupSnapshot(self.db.documents.get(self.doc_id))


class _LookupCollection:
    def __init__(self, db: "_LookupDb"):
        self.db = db

    def document(self, doc_id: str) -> _LookupDocument:
        return _LookupDocument(self.db, doc_id)

    def stream(self):
        raise AssertionError("exact lookup must not scan the collection")


class _LookupDb:
    def __init__(self, documents: dict[str, dict] | None = None):
        self.documents = dict(documents or {})
        self.requested: list[str] = []

    def collection(self, name: str) -> _LookupCollection:
        assert name == store.AGENDAS
        return _LookupCollection(self)


def _stored_agenda() -> ResearchAgenda:
    return ResearchAgenda(
        subject_key="synqology",
        algorithm_version="VI test",
        source_digest="abc123",
        items=[],
    )


def test_agenda_for_digest_reads_only_the_deterministic_document():
    agenda = _stored_agenda()
    doc_id = "synqology__abc123"
    db = _LookupDb({doc_id: agenda.model_dump(mode="json")})
    assert store.agenda_for_digest("synqology", "abc123", db=db) == agenda
    assert db.requested == [doc_id]


def test_agenda_for_digest_returns_none_when_document_is_absent():
    db = _LookupDb()
    assert store.agenda_for_digest("synqology", "missing", db=db) is None
    assert db.requested == ["synqology__missing"]
```

- [ ] **Step 2: Run the lookup tests and verify failure**

Run: `/Users/m1labs/Dev/provenance/.venv/bin/python -m pytest tests/test_store.py -q`

Expected: FAIL because `agenda_for_digest` is undefined.

- [ ] **Step 3: Implement deterministic lookup**

Add immediately after `save_agenda` in `provenance/store/firestore.py`:

```python
def agenda_for_digest(
    subject_key: str,
    source_digest: str,
    *,
    db: firestore.Client | None = None,
) -> ResearchAgenda | None:
    """Return one published agenda without scanning unrelated versions."""
    db = db or client()
    doc_id = f"{subject_key}__{source_digest}"
    snapshot = db.collection(AGENDAS).document(doc_id).get()
    if not snapshot.exists:
        return None
    payload = snapshot.to_dict()
    return ResearchAgenda.model_validate(payload) if payload else None
```

- [ ] **Step 4: Run store tests**

Run: `/Users/m1labs/Dev/provenance/.venv/bin/python -m pytest tests/test_store.py -q`

Expected: all tests pass and the fake collection’s `stream()` guard is never reached.

- [ ] **Step 5: Commit exact lookup**

```bash
git add provenance/store/firestore.py tests/test_store.py
git commit -m "feat(store): load agendas by exact source digest"
```

### Task 3: Explicit Idempotent Publication Command

**Files:**
- Modify: `provenance/cli.py:16-49,611-614`
- Modify: `tests/test_cli.py`

**Interfaces:**
- Consumes: `source_digest(subject)`, `store.agenda_for_digest(...)`, `build_agenda(subject, refresh=bool)`, `store.save_agenda(...)`
- Produces: `python -m provenance agenda --publish [--refresh]` and the exact outcomes `published`, `refreshed`, or `already current`

- [ ] **Step 1: Add a reusable test agenda and read-only test**

Append to `tests/test_cli.py`:

```python
from provenance.models import ResearchAgenda


def _research_agenda(digest: str = "digest") -> ResearchAgenda:
    return ResearchAgenda(
        subject_key="synqology",
        algorithm_version="VI test",
        source_digest=digest,
        items=[],
    )


def test_agenda_without_publish_does_not_open_firestore(monkeypatch, capsys):
    agenda = _research_agenda()
    monkeypatch.setattr(cli, "build_agenda", lambda _subject, refresh=False: agenda)
    monkeypatch.setattr(
        store,
        "client",
        lambda: (_ for _ in ()).throw(AssertionError("Firestore opened")),
    )
    result = cli.cmd_agenda(
        SimpleNamespace(subject="synqology", refresh=False, detail=False, publish=False)
    )
    assert result == 0
    assert "digest digest" in capsys.readouterr().out
```

- [ ] **Step 2: Add exact-hit, publish, refresh, and persistence-failure tests**

Append:

```python
def test_agenda_publish_reuses_exact_digest_without_gemini_or_write(
    monkeypatch, capsys
):
    agenda = _research_agenda()
    db = object()
    monkeypatch.setattr(store, "client", lambda: db)
    monkeypatch.setattr(cli, "source_digest", lambda _subject: "digest")
    monkeypatch.setattr(
        store, "agenda_for_digest", lambda subject, digest, *, db: agenda
    )
    monkeypatch.setattr(
        cli,
        "build_agenda",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("Gemini called")),
    )
    monkeypatch.setattr(
        store,
        "save_agenda",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(AssertionError("write made")),
    )
    result = cli.cmd_agenda(
        SimpleNamespace(subject="synqology", refresh=False, detail=False, publish=True)
    )
    assert result == 0
    assert "publication: already current" in capsys.readouterr().out


def test_agenda_publish_builds_and_saves_missing_digest(monkeypatch, capsys):
    agenda = _research_agenda()
    db = object()
    saved: list[ResearchAgenda] = []
    monkeypatch.setattr(store, "client", lambda: db)
    monkeypatch.setattr(cli, "source_digest", lambda _subject: "digest")
    monkeypatch.setattr(
        store, "agenda_for_digest", lambda subject, digest, *, db: None
    )
    monkeypatch.setattr(cli, "build_agenda", lambda _subject, refresh=False: agenda)
    monkeypatch.setattr(store, "save_agenda", lambda value, *, db: saved.append(value))
    result = cli.cmd_agenda(
        SimpleNamespace(subject="synqology", refresh=False, detail=False, publish=True)
    )
    assert result == 0
    assert saved == [agenda]
    assert "publication: published" in capsys.readouterr().out


def test_agenda_refresh_skips_remote_hit_and_overwrites(monkeypatch, capsys):
    agenda = _research_agenda()
    db = object()
    calls: list[bool] = []
    monkeypatch.setattr(store, "client", lambda: db)
    monkeypatch.setattr(cli, "source_digest", lambda _subject: "digest")
    monkeypatch.setattr(
        store,
        "agenda_for_digest",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("refresh consulted remote cache")
        ),
    )
    monkeypatch.setattr(
        cli,
        "build_agenda",
        lambda _subject, refresh=False: calls.append(refresh) or agenda,
    )
    monkeypatch.setattr(store, "save_agenda", lambda value, *, db: None)
    result = cli.cmd_agenda(
        SimpleNamespace(subject="synqology", refresh=True, detail=False, publish=True)
    )
    assert result == 0
    assert calls == [True]
    assert "publication: refreshed" in capsys.readouterr().out


def test_agenda_publish_propagates_firestore_failure(monkeypatch):
    agenda = _research_agenda()
    monkeypatch.setattr(store, "client", lambda: object())
    monkeypatch.setattr(cli, "source_digest", lambda _subject: "digest")
    monkeypatch.setattr(store, "agenda_for_digest", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(cli, "build_agenda", lambda _subject, refresh=False: agenda)
    monkeypatch.setattr(
        store,
        "save_agenda",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(RuntimeError("write failed")),
    )
    with pytest.raises(RuntimeError, match="write failed"):
        cli.cmd_agenda(
            SimpleNamespace(
                subject="synqology", refresh=False, detail=False, publish=True
            )
        )


def test_agenda_publish_propagates_generation_failure(monkeypatch):
    monkeypatch.setattr(store, "client", lambda: object())
    monkeypatch.setattr(cli, "source_digest", lambda _subject: "digest")
    monkeypatch.setattr(store, "agenda_for_digest", lambda *_args, **_kwargs: None)
    monkeypatch.setattr(
        cli,
        "build_agenda",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            RuntimeError("generation failed")
        ),
    )
    with pytest.raises(RuntimeError, match="generation failed"):
        cli.cmd_agenda(
            SimpleNamespace(
                subject="synqology", refresh=False, detail=False, publish=True
            )
        )
```

Add `import pytest` to `tests/test_cli.py`.

- [ ] **Step 3: Run the focused tests and verify failure**

Run: `/Users/m1labs/Dev/provenance/.venv/bin/python -m pytest tests/test_cli.py -q`

Expected: new publication tests fail because `source_digest` is not imported by `cli`, `--publish` is not implemented, and no publication outcome is printed.

- [ ] **Step 4: Implement the publication branch**

Change the agenda import in `provenance/cli.py` to:

```python
from .agenda import build_agenda, source_digest
```

Replace `cmd_agenda`’s setup with:

```python
def cmd_agenda(args: argparse.Namespace) -> int:
    subject = _subject(args.subject)
    publication: str | None = None

    if args.publish:
        from .store import firestore as store

        db = store.client()
        digest = source_digest(subject)
        agenda = None
        if not args.refresh:
            agenda = store.agenda_for_digest(subject.key, digest, db=db)
        if agenda is None:
            agenda = build_agenda(subject, refresh=args.refresh)
            store.save_agenda(agenda, db=db)
            publication = "refreshed" if args.refresh else "published"
        else:
            publication = "already current"
    else:
        agenda = build_agenda(subject, refresh=args.refresh)
```

Keep the existing agenda rendering loop. Immediately before `return 0`, add:

```python
    if publication:
        print(f"  publication: {publication}")
```

Register the flag:

```python
agenda.add_argument(
    "--publish",
    action="store_true",
    help="publish this exact source digest to Firestore",
)
```

- [ ] **Step 5: Run CLI and agenda/store tests**

Run: `/Users/m1labs/Dev/provenance/.venv/bin/python -m pytest tests/test_cli.py tests/test_agenda.py tests/test_store.py -q`

Expected: all tests pass.

- [ ] **Step 6: Verify the real command remains locally read-only**

Run: `/Users/m1labs/Dev/provenance/.venv/bin/python -m provenance agenda --detail`

Expected: the agenda prints with no `publication:` line and no Firestore write log.

- [ ] **Step 7: Commit the CLI contract**

```bash
git add provenance/cli.py tests/test_cli.py
git commit -m "feat(cli): publish agendas explicitly and idempotently"
```

### Task 4: Verify and Publish the Provenance Revision

**Files:**
- Modify: `README.md:12-40,136-147`

**Interfaces:**
- Consumes: completed Tasks 1-3
- Produces: one tested 40-character Provenance publisher commit available from `origin/main`

- [ ] **Step 1: Update user-facing command documentation**

In `README.md`, state that the agenda reads the prose specification plus both governing Swift implementations, that CI publishes after relevant changes land on synqology `launch`, and add:

```bash
python -m provenance agenda --publish   # explicit Firestore synchronization
```

Do not claim the CI workflow is deployed yet; describe `--publish` as the command the forthcoming workflow invokes.

- [ ] **Step 2: Run the complete Provenance suite**

Run: `/Users/m1labs/Dev/provenance/.venv/bin/python -m pytest tests/ -q`

Expected: the entire suite passes with no failures.

- [ ] **Step 3: Run static and CLI smoke checks**

Run: `/Users/m1labs/Dev/provenance/.venv/bin/python -m compileall -q provenance tests`

Expected: exit zero.

Run: `/Users/m1labs/Dev/provenance/.venv/bin/python -m provenance agenda --help`

Expected: help includes `--publish` and describes Firestore publication.

- [ ] **Step 4: Commit the pre-deployment documentation**

```bash
git add README.md
git commit -m "docs: explain explicit agenda synchronization"
```

- [ ] **Step 5: Confirm the isolated worktree is clean and push**

Run: `git status --short`

Expected: no output in the isolated implementation worktree.

Run: `git push origin main`

Expected: the tested commits are present on `m1insights/provenance@main`.

- [ ] **Step 6: Record and verify the immutable publisher revision**

Run:

```bash
PROVENANCE_AUTOMATION_SHA=$(git rev-parse HEAD)
test "${#PROVENANCE_AUTOMATION_SHA}" -eq 40
git fetch origin main
git merge-base --is-ancestor "$PROVENANCE_AUTOMATION_SHA" origin/main
```

Expected: `PROVENANCE_AUTOMATION_SHA` is 40 lowercase hexadecimal characters and the ancestry check exits zero, proving the commit is reachable from remote `main`.

### Task 5: Provision Passwordless Google Cloud Identity

**Files:**
- None; this task changes Google Cloud IAM state in project `sentinel-505814`.

**Interfaces:**
- Consumes: GitHub OIDC assertions for `m1insights/synq` and `refs/heads/launch`
- Produces: provider `projects/1060267807802/locations/global/workloadIdentityPools/github-actions/providers/synq-provenance` and service account `provenance-agenda-publisher@sentinel-505814.iam.gserviceaccount.com`

- [ ] **Step 1: Confirm the intended gcloud account and project**

Run: `gcloud auth list --filter=status:ACTIVE --format='value(account)'`

Expected: `info@m1labs.io`.

Run: `gcloud config set project sentinel-505814`

Expected: project becomes `sentinel-505814`.

- [ ] **Step 2: Enable only the APIs required for federation, Vertex, and Firestore**

Run:

```bash
gcloud services enable iam.googleapis.com iamcredentials.googleapis.com sts.googleapis.com aiplatform.googleapis.com firestore.googleapis.com --project=sentinel-505814
```

Expected: exit zero; existing enabled services remain unchanged.

- [ ] **Step 3: Create the dedicated service account**

Run:

```bash
gcloud iam service-accounts create provenance-agenda-publisher --project=sentinel-505814 --display-name="Provenance agenda publisher"
```

Expected: service account `provenance-agenda-publisher@sentinel-505814.iam.gserviceaccount.com` exists and is enabled.

- [ ] **Step 4: Create the no-delete Firestore custom role**

Run:

```bash
gcloud iam roles create provenanceAgendaPublisher --project=sentinel-505814 --title="Provenance Agenda Publisher" --description="Read and upsert agenda documents without delete access" --permissions="datastore.entities.get,datastore.entities.create,datastore.entities.update" --stage=GA
```

Expected: the role contains exactly the three entity permissions and no `datastore.entities.delete`.

- [ ] **Step 5: Bind Vertex invocation and Firestore upsert roles**

Run:

```bash
gcloud projects add-iam-policy-binding sentinel-505814 --member="serviceAccount:provenance-agenda-publisher@sentinel-505814.iam.gserviceaccount.com" --role="roles/aiplatform.user"
```

Run:

```bash
gcloud projects add-iam-policy-binding sentinel-505814 --member="serviceAccount:provenance-agenda-publisher@sentinel-505814.iam.gserviceaccount.com" --role="projects/sentinel-505814/roles/provenanceAgendaPublisher"
```

Expected: both bindings are present; no broader Datastore role is granted.

- [ ] **Step 6: Create the GitHub Actions identity pool**

Run:

```bash
gcloud iam workload-identity-pools create github-actions --project=sentinel-505814 --location=global --display-name="GitHub Actions"
```

Expected: pool state is `ACTIVE`.

- [ ] **Step 7: Create the synq repository-and-branch-restricted provider**

Run:

```bash
gcloud iam workload-identity-pools providers create-oidc synq-provenance --project=sentinel-505814 --location=global --workload-identity-pool=github-actions --display-name="synq Provenance publisher" --issuer-uri="https://token.actions.githubusercontent.com" --attribute-mapping="google.subject=assertion.sub,attribute.repository=assertion.repository,attribute.ref=assertion.ref" --attribute-condition="assertion.repository == 'm1insights/synq' && assertion.ref == 'refs/heads/launch'"
```

Expected: provider state is `ACTIVE` and its condition contains both the exact repository and exact branch ref.

- [ ] **Step 8: Allow only the synq repository principal set to impersonate the publisher**

Run:

```bash
gcloud iam service-accounts add-iam-policy-binding provenance-agenda-publisher@sentinel-505814.iam.gserviceaccount.com --project=sentinel-505814 --role="roles/iam.workloadIdentityUser" --member="principalSet://iam.googleapis.com/projects/1060267807802/locations/global/workloadIdentityPools/github-actions/attribute.repository/m1insights/synq"
```

Expected: the service-account policy names no other GitHub repository principal.

- [ ] **Step 9: Audit the resulting role and provider**

Run: `gcloud iam roles describe provenanceAgendaPublisher --project=sentinel-505814 --format=json`

Expected: only get/create/update entity permissions; no delete.

Run:

```bash
gcloud iam workload-identity-pools providers describe synq-provenance --project=sentinel-505814 --location=global --workload-identity-pool=github-actions --format=json
```

Expected: GitHub issuer, the three mappings, and the exact repository-and-launch condition.

### Task 6: Add the synqology GitHub Actions Publisher

**Files:**
- Create on `m1insights/synq@main`: `.github/workflows/publish-provenance-agenda.yml`
- Create identically on `m1insights/synq@launch`: `.github/workflows/publish-provenance-agenda.yml`

**Interfaces:**
- Consumes: repository variables `GCP_PROJECT_ID`, `GCP_WORKLOAD_IDENTITY_PROVIDER`, `GCP_SERVICE_ACCOUNT`, `PROVENANCE_PUBLISHER_SHA`; Provenance `agenda --publish`
- Produces: path-filtered production publication and manual launch-ref recovery with a GitHub step summary

- [ ] **Step 1: Set non-secret repository variables**

From the tested Provenance worktree, recompute the exact remote revision:

```bash
PROVENANCE_AUTOMATION_SHA=$(git rev-parse HEAD)
test "${#PROVENANCE_AUTOMATION_SHA}" -eq 40
```

Set repository variables:

```bash
gh variable set GCP_PROJECT_ID --repo m1insights/synq --body "sentinel-505814"
gh variable set GCP_WORKLOAD_IDENTITY_PROVIDER --repo m1insights/synq --body "projects/1060267807802/locations/global/workloadIdentityPools/github-actions/providers/synq-provenance"
gh variable set GCP_SERVICE_ACCOUNT --repo m1insights/synq --body "provenance-agenda-publisher@sentinel-505814.iam.gserviceaccount.com"
gh variable set PROVENANCE_PUBLISHER_SHA --repo m1insights/synq --body "$PROVENANCE_AUTOMATION_SHA"
```

Expected: `gh variable list --repo m1insights/synq` shows all four values and the publisher value is a 40-character SHA.

- [ ] **Step 2: Create the workflow in an isolated `main` worktree**

Use `apply_patch` to create `.github/workflows/publish-provenance-agenda.yml` with this complete content:

```yaml
name: Publish Provenance agenda

on:
  push:
    branches:
      - launch
    paths:
      - LONGEVITY_FEATURE_STACK.md
      - tapntrack/Services/VitalityIndexCalculator.swift
      - tapntrack/Services/ShiftWorkAdjuster.swift
  workflow_dispatch:
    inputs:
      force_refresh:
        description: Regenerate even when this digest is already published
        required: true
        default: false
        type: boolean

permissions:
  contents: read
  id-token: write

concurrency:
  group: provenance-agenda-launch
  cancel-in-progress: false

jobs:
  publish:
    name: Publish exact source digest
    runs-on: ubuntu-latest
    timeout-minutes: 20
    env:
      GOOGLE_CLOUD_PROJECT: ${{ vars.GCP_PROJECT_ID }}
      GOOGLE_GENAI_USE_VERTEXAI: "true"
      GEMINI_LOCATION: global
      FIRESTORE_DATABASE: "(default)"
      SYNQOLOGY_REPO_PATH: ${{ github.workspace }}/synq

    steps:
      - name: Validate pinned publisher
        shell: bash
        run: |
          if [[ ! "${{ vars.PROVENANCE_PUBLISHER_SHA }}" =~ ^[0-9a-f]{40}$ ]]; then
            echo "PROVENANCE_PUBLISHER_SHA must be an immutable 40-character commit SHA" >&2
            exit 1
          fi

      - name: Check out synqology source
        uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4
        with:
          path: synq
          persist-credentials: false

      - name: Check out Provenance publisher
        uses: actions/checkout@11d5960a326750d5838078e36cf38b85af677262 # v4
        with:
          repository: m1insights/provenance
          ref: ${{ vars.PROVENANCE_PUBLISHER_SHA }}
          path: provenance
          persist-credentials: false

      - name: Set up Python
        uses: actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065 # v5
        with:
          python-version: "3.12"
          cache: pip
          cache-dependency-path: provenance/requirements.txt

      - name: Install Provenance
        working-directory: provenance
        run: python -m pip install -r requirements.txt

      - name: Authenticate to Google Cloud
        uses: google-github-actions/auth@7c6bc770dae815cd3e89ee6cdf493a5fab2cc093 # v3
        with:
          project_id: ${{ vars.GCP_PROJECT_ID }}
          workload_identity_provider: ${{ vars.GCP_WORKLOAD_IDENTITY_PROVIDER }}
          service_account: ${{ vars.GCP_SERVICE_ACCOUNT }}

      - name: Build and publish agenda
        id: publish
        shell: bash
        working-directory: provenance
        run: |
          set -uo pipefail
          agenda_args=(agenda --publish)
          if [[ "${{ inputs.force_refresh }}" == "true" ]]; then
            agenda_args+=(--refresh)
          fi

          publish_status=0
          python -m provenance "${agenda_args[@]}" 2>&1 \
            | tee "$RUNNER_TEMP/provenance-agenda.txt" \
            || publish_status=${PIPESTATUS[0]}

          synq_commit=$(git -C "$SYNQOLOGY_REPO_PATH" rev-parse HEAD)
          {
            echo "## Provenance agenda publication"
            echo
            echo "- synq commit: \`$synq_commit\`"
            echo "- publisher commit: \`${{ vars.PROVENANCE_PUBLISHER_SHA }}\`"
            echo
            echo '```text'
            cat "$RUNNER_TEMP/provenance-agenda.txt"
            echo '```'
          } >> "$GITHUB_STEP_SUMMARY"

          exit "$publish_status"
```

- [ ] **Step 3: Review the workflow’s security and trigger contract locally**

Run:

```bash
rg -n "branches:|LONGEVITY_FEATURE_STACK|VitalityIndexCalculator|ShiftWorkAdjuster|id-token|contents:|cancel-in-progress|uses:" .github/workflows/publish-provenance-agenda.yml
```

Expected: only `launch`, the three governing paths, `contents: read`, `id-token: write`, `cancel-in-progress: false`, and the three immutable action SHAs appear.

Run: `rg -n "service-account-key|GOOGLE_API_KEY|roles/datastore.user|@v[0-9]$" .github/workflows/publish-provenance-agenda.yml`

Expected: no output.

- [ ] **Step 4: Commit and push the workflow to the default branch**

```bash
git add .github/workflows/publish-provenance-agenda.yml
git commit -m "ci: publish Provenance agenda from Vitality changes"
git push origin main
```

Expected: GitHub registers `workflow_dispatch` from the default branch, but no publication runs because this is not `launch`.

- [ ] **Step 5: Apply the identical file in an isolated `launch` worktree**

Use `apply_patch` with the exact YAML from Step 2. Verify identity against `origin/main`:

Run:

```bash
git show origin/main:.github/workflows/publish-provenance-agenda.yml | diff - .github/workflows/publish-provenance-agenda.yml
```

Expected: no diff.

- [ ] **Step 6: Commit and push the workflow to `launch`**

```bash
git add .github/workflows/publish-provenance-agenda.yml
git commit -m "ci: publish Provenance agenda from Vitality changes"
git push origin launch
```

Expected: the workflow exists on the trusted branch. Adding the workflow alone does not publish because the workflow file is not one of the three source path filters.

- [ ] **Step 7: Verify GitHub parsed the workflow on both refs**

Run: `gh workflow view publish-provenance-agenda.yml --repo m1insights/synq --yaml --ref main`

Run: `gh workflow view publish-provenance-agenda.yml --repo m1insights/synq --yaml --ref launch`

Expected: both commands return the workflow YAML; neither reports a syntax error.

### Task 7: Production Verification and Documentation Closeout

**Files:**
- Modify: `README.md`
- Modify: `docs/architecture.md:12-25,82-90,169-184`
- Modify: `docs/superpowers/specs/2026-08-24-agenda-ci-automation-design.md:1-6` and append verification evidence

**Interfaces:**
- Consumes: deployed workflow, OIDC provider, publisher service account, exact Firestore lookup, existing nightly job
- Produces: verified idempotent CI handoff and documentation that describes the deployed state

- [ ] **Step 1: Manually dispatch from the trusted `launch` ref**

Run:

```bash
gh workflow run publish-provenance-agenda.yml --repo m1insights/synq --ref launch -f force_refresh=false
```

Capture the run:

```bash
AGENDA_CI_RUN_ID=$(gh run list --repo m1insights/synq --workflow=publish-provenance-agenda.yml --event=workflow_dispatch --limit=1 --json=databaseId --jq='.[0].databaseId')
gh run watch "$AGENDA_CI_RUN_ID" --repo m1insights/synq --exit-status
```

Expected: success. The summary shows the launch commit, immutable publisher commit, algorithm version, digest, component count, and `publication: published` or `publication: already current`.

- [ ] **Step 2: Verify the exact Firestore document read-only**

From the Provenance checkout with the synq source root exported, run:

```bash
SYNQOLOGY_REPO_PATH=/Users/m1labs/Dev/apps/synqology/synq /Users/m1labs/Dev/provenance/.venv/bin/python - <<'PY'
from provenance.agenda import source_digest
from provenance.config import SUBJECTS
from provenance.store import firestore as store

subject = SUBJECTS["synqology"]
digest = source_digest(subject)
agenda = store.agenda_for_digest(subject.key, digest)
assert agenda is not None
assert agenda.source_digest == digest
print(digest, agenda.algorithm_version, len(agenda.items))
PY
```

Expected: one line containing the digest, current VI version, and nonzero component count.

- [ ] **Step 3: Dispatch the same revision again and prove idempotence**

Run the same `gh workflow run` command with `force_refresh=false`, then capture and watch the new run:

```bash
gh workflow run publish-provenance-agenda.yml --repo m1insights/synq --ref launch -f force_refresh=false
AGENDA_CI_SECOND_RUN_ID=$(gh run list --repo m1insights/synq --workflow=publish-provenance-agenda.yml --event=workflow_dispatch --limit=1 --json=databaseId --jq='.[0].databaseId')
gh run watch "$AGENDA_CI_SECOND_RUN_ID" --repo m1insights/synq --exit-status
```

Run:

```bash
gh run view "$AGENDA_CI_SECOND_RUN_ID" --repo m1insights/synq --log | rg "publication: already current"
```

Expected: one match. The log must not contain `agenda: reading` or `generate_content`.

- [ ] **Step 4: Execute the existing nightly job once without redeploying it**

Run:

```bash
gcloud run jobs execute provenance-nightly --project=sentinel-505814 --region=us-central1 --wait
```

Expected: the existing job succeeds; its image and configuration remain unchanged.

- [ ] **Step 5: Confirm nightly consumed the CI-published digest**

Run:

```bash
gcloud logging read 'resource.type="cloud_run_job" AND resource.labels.job_name="provenance-nightly" AND textPayload:"agenda: no local sources; using published agenda"' --project=sentinel-505814 --freshness=1h --limit=10 --format='value(textPayload)'
```

Expected: a log line reports the same algorithm version and digest printed in Step 2.

- [ ] **Step 6: Update deployed-state documentation**

In `README.md` and `docs/architecture.md`:

- replace the claim that source changes rely on a local developer run;
- show `synq launch push → GitHub Actions/OIDC → Gemini → provenance_agendas → nightly Cloud Run`;
- state that exact-digest retries skip Gemini;
- retain the fact that private Swift source never enters the Cloud Run image;
- document `python -m provenance agenda --publish` as an explicit operator recovery command.

In the design spec, change `**Status:** Proposed` to `**Status:** Implemented` and append a `## Verification` section containing the observed first and second GitHub run IDs, synq commit SHA, Provenance publisher SHA, agenda digest/version/component count, and the existing nightly execution name. These are recorded outputs from Steps 1-5, not invented values.

- [ ] **Step 7: Run final regression and documentation checks**

Run: `/Users/m1labs/Dev/provenance/.venv/bin/python -m pytest tests/ -q`

Expected: full suite passes.

Run:

```bash
rg -n 'local run published|Run `python -m provenance agenda` locally first|nothing goes stale' README.md docs/architecture.md provenance/agenda.py
```

Expected: no stale manual-publication claim remains.

Run: `git diff --check`

Expected: no whitespace errors.

- [ ] **Step 8: Commit and push the verified deployment record**

```bash
git add README.md docs/architecture.md docs/superpowers/specs/2026-08-24-agenda-ci-automation-design.md
git commit -m "docs: record automated agenda publication"
git push origin main
```

- [ ] **Step 9: Final cross-system audit**

Run: `git status --short` in every isolated worktree.

Expected: no output. The original primary checkouts still contain exactly their pre-existing user changes.

Run: `gh run list --repo m1insights/synq --workflow=publish-provenance-agenda.yml --limit=2`

Expected: both verification runs succeeded.

Run: `gcloud iam roles describe provenanceAgendaPublisher --project=sentinel-505814 --format='value(includedPermissions)'`

Expected: get/create/update only, with no delete permission.
