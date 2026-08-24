# Durable Nightly Appraisal Backlog Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make stored-but-unappraised papers return automatically in bounded nightly batches, preserve partial work across Vertex 429s, and send an honest recovery briefing.

**Architecture:** Firestore remains the source of truth: a paper without an appraisal or terminal rejection is pending, while triage metadata on the paper distinguishes work ready for appraisal from work still needing triage. The nightly orchestrator processes triage and appraisal in bounded waves, persists each completed wave, and treats only recognized quota errors as fail-soft; persistence and programming failures remain fatal.

**Tech Stack:** Python 3.12, asyncio, Pydantic 2, Google ADK/Gemini, Google Cloud Firestore, Cloud Run Jobs, pytest

**Spec:** `docs/superpowers/specs/2026-08-24-nightly-appraisal-backlog-design.md`

## Global Constraints

- Appraise at most 10 relevant pending papers per nightly run.
- Run at most 3 appraisal model calls concurrently.
- Split capacity equally between newly retrieved papers and the oldest backlog, lending unused slots to the other group.
- Persist completed triage and appraisal outcomes before starting another wave.
- Leave deferred papers pending; do not write a rejection for a 429.
- Skip synthesis and engineering after a triage or appraisal quota failure.
- Only HTTP 429 / `RESOURCE_EXHAUSTED` is fail-soft; programming and Firestore persistence failures still raise.
- Do not downgrade the evidence model automatically.
- Do not change pull-request automation.
- Preserve the Cloud Run Job's existing secret references during deployment.

---

## File Structure

- `provenance/models.py`: adds backward-compatible triage metadata to `Paper`.
- `provenance/store/firestore.py`: owns the cross-collection query that identifies pending papers.
- `provenance/backlog.py`: owns deterministic, Firestore-independent appraisal selection policy.
- `provenance/llm.py`: recognizes the narrow class of quota errors eligible for fail-soft handling.
- `provenance/agents/appraiser.py`: exposes partial-result triage/appraisal batches without changing the existing CLI-facing functions.
- `provenance/nightly.py`: orchestrates durable queue recovery, wave persistence, stage gating, summaries, and notification.
- `provenance/notify.py`: renders backlog and stage-failure state truthfully.
- `provenance/cli.py`: reuses the canonical pending-paper query instead of maintaining divergent ID logic.
- `tests/test_backlog.py`: pure selection-policy and quota-classification tests.
- `tests/test_nightly.py`: queue recovery, wave persistence, and fail-soft orchestration tests.
- `tests/test_notify.py`: normal-backlog and incomplete-analysis email copy tests.

---

### Task 1: Canonical Durable Queue State

**Files:**
- Modify: `provenance/models.py:86-110`
- Modify: `provenance/store/firestore.py:169-181`
- Modify: `provenance/cli.py:82-124`
- Create: `tests/test_backlog.py`

**Interfaces:**
- Produces: `Paper.triaged_at: datetime | None`
- Produces: `Paper.triage_agenda_digest: str`
- Produces: `store.pending_papers(*, db) -> list[Paper]`
- Consumes: Firestore documents from `PAPERS`, `APPRAISALS`, and `REJECTIONS`

- [ ] **Step 1: Write failing model and store tests**

Add tests that validate old paper documents without triage fields and exercise pending-state derivation using a small Firestore stub. The critical assertions are:

```python
def test_old_paper_documents_default_to_untriaged():
    paper = Paper.model_validate({
        "doc_id": "paper-1", "source": "pubmed", "title": "Old record"
    })
    assert paper.triaged_at is None
    assert paper.triage_agenda_digest == ""


def test_pending_papers_exclude_appraised_and_rejected_records():
    db = QueueDb(
        papers=[paper_doc("pending"), paper_doc("appraised"), paper_doc("rejected")],
        appraisals=[doc("appraised", {})],
        rejections=[doc("opaque-firestore-id", {"paper_id": "rejected"})],
    )
    assert [paper.doc_id for paper in store.pending_papers(db=db)] == ["pending"]
```

The rejection test must use an opaque document ID so the implementation cannot pass by splitting `doc.id` on `__`.

- [ ] **Step 2: Run the tests and verify RED**

Run: `pytest tests/test_backlog.py -v`

Expected: failures because the triage fields and `pending_papers` do not exist.

- [ ] **Step 3: Add backward-compatible triage fields**

Add to `Paper`:

```python
triaged_at: datetime | None = None
triage_agenda_digest: str = ""
```

No migration is required because Pydantic supplies these defaults for existing Firestore documents.

- [ ] **Step 4: Implement the canonical pending query**

Add to `provenance/store/firestore.py`:

```python
def pending_papers(*, db: firestore.Client | None = None) -> list[Paper]:
    db = db or client()
    appraised = {
        doc.id for doc in db.collection(APPRAISALS).select([]).stream()
    }
    rejected = {
        payload["paper_id"]
        for doc in db.collection(REJECTIONS).stream()
        if (payload := (doc.to_dict() or {})).get("paper_id")
    }
    terminal = appraised | rejected
    papers = [
        Paper.model_validate(doc.to_dict())
        for doc in db.collection(PAPERS).stream()
        if doc.id not in terminal
    ]
    return sorted(papers, key=lambda p: (p.retrieved_at, p.doc_id))
```

- [ ] **Step 5: Make the CLI reuse the canonical query**

Replace the non-`--redo` branch's hand-built `done` set and paper scan with `store.pending_papers(db=db)`. Keep `--redo` behavior unchanged: it still selects only explicitly named papers and may overwrite their appraisals.

- [ ] **Step 6: Run focused tests and verify GREEN**

Run: `pytest tests/test_backlog.py -v`

Expected: all tests pass.

- [ ] **Step 7: Commit the durable-state unit**

```bash
git add provenance/models.py provenance/store/firestore.py provenance/cli.py tests/test_backlog.py
git commit -m "feat(nightly): derive a durable appraisal backlog"
```

---

### Task 2: Fair Bounded Selection and Quota Recognition

**Files:**
- Create: `provenance/backlog.py`
- Modify: `provenance/llm.py`
- Modify: `tests/test_backlog.py`

**Interfaces:**
- Produces: `select_for_appraisal(papers: list[Paper], *, new_ids: set[str], limit: int) -> list[Paper]`
- Produces: `is_quota_error(exc: BaseException) -> bool`
- Consumes: pending relevant papers after triage

- [ ] **Step 1: Write failing selection tests**

Cover the cap, fairness, lending, and deterministic order:

```python
def test_selection_shares_ten_slots_between_new_and_old():
    old = papers("old", 8, start_day=1)
    new = papers("new", 8, start_day=20)
    selected = select_for_appraisal(
        old + new, new_ids={paper.doc_id for paper in new}, limit=10
    )
    assert len(selected) == 10
    assert sum(p.doc_id.startswith("new") for p in selected) == 5
    assert [p.doc_id for p in selected if p.doc_id.startswith("old")] == [
        "old-0", "old-1", "old-2", "old-3", "old-4"
    ]


def test_selection_lends_unused_new_slots_to_backlog():
    old = papers("old", 12, start_day=1)
    assert len(select_for_appraisal(old, new_ids=set(), limit=10)) == 10
```

Also assert that `limit=0` returns an empty list and that ties are resolved by `doc_id`.

- [ ] **Step 2: Write failing quota-classification tests**

Use fake exceptions exposing status through common SDK shapes and a plain exception message:

```python
@pytest.mark.parametrize("exc", [
    StatusError(429),
    RuntimeError("429 RESOURCE_EXHAUSTED"),
    RuntimeError("ResourceExhausted: quota exceeded"),
])
def test_quota_errors_are_recognized(exc):
    assert is_quota_error(exc)


def test_programming_errors_are_not_quota_errors():
    assert not is_quota_error(TypeError("bad payload"))
```

- [ ] **Step 3: Run focused tests and verify RED**

Run: `pytest tests/test_backlog.py -v`

Expected: import failures because `provenance.backlog` and `is_quota_error` do not exist.

- [ ] **Step 4: Implement fair deterministic selection**

Create `provenance/backlog.py` with a stable sort by `(retrieved_at, doc_id)`. Allocate `limit // 2` initial slots to new work and the remainder to backlog, then fill unused slots from the other ordered group. Never return the same paper twice and never exceed `limit`.

- [ ] **Step 5: Implement narrow quota recognition**

Add `is_quota_error` to `provenance/llm.py`. Recognize numeric `status_code == 429`, enum/string `code()` values containing `RESOURCE_EXHAUSTED`, and exception text containing either `429` or `RESOURCE_EXHAUSTED`. Do not classify generic timeouts, validation failures, or Firestore errors as quota problems.

- [ ] **Step 6: Run focused tests and verify GREEN**

Run: `pytest tests/test_backlog.py -v`

Expected: all tests pass.

- [ ] **Step 7: Commit policy and classification**

```bash
git add provenance/backlog.py provenance/llm.py tests/test_backlog.py
git commit -m "feat(nightly): bound and balance appraisal work"
```

---

### Task 3: Partial-Result Model Batches

**Files:**
- Modify: `provenance/agents/appraiser.py:334-442`
- Create: `tests/test_appraiser_batches.py`

**Interfaces:**
- Produces: `TriageBatch(kept, rejections, deferred, quota_error)`
- Produces: `AppraisalBatch(appraisals, rejections, deferred, quota_error)`
- Produces: `triage_batch(papers, agenda, *, max_concurrent=6) -> TriageBatch`
- Produces: `appraise_batch(papers, agenda, *, max_concurrent=3) -> AppraisalBatch`
- Preserves: existing `triage(...) -> tuple[list[Paper], list[Rejection]]`
- Preserves: existing `appraise(...) -> tuple[list[Appraisal], list[Rejection]]`

- [ ] **Step 1: Write failing triage partial-result tests**

Patch `_run` so one paper returns a relevant verdict, one returns an irrelevant verdict, and one raises `RuntimeError("429 RESOURCE_EXHAUSTED")`. Assert:

```python
result = asyncio.run(triage_batch(papers, agenda, max_concurrent=3))
assert [p.doc_id for p in result.kept] == ["relevant"]
assert [r.paper_id for r in result.rejections] == ["irrelevant"]
assert [p.doc_id for p in result.deferred] == ["quota"]
assert is_quota_error(result.quota_error)
```

Add a second test proving an unexpected `TypeError` is raised rather than returned as deferred.

- [ ] **Step 2: Write failing appraisal partial-result tests**

Patch `_run` and grounding so one paper yields a valid appraisal, one receives a terminal no-result outcome, and one raises 429. Assert successful and rejected outcomes survive alongside the deferred paper. Add a concurrency probe that never observes more than three active calls when `max_concurrent=3`.

- [ ] **Step 3: Run focused tests and verify RED**

Run: `pytest tests/test_appraiser_batches.py -v`

Expected: imports fail because the batch result types and functions do not exist.

- [ ] **Step 4: Extract the existing one-paper logic**

Move the bodies of the nested `one` functions into private async helpers that receive the already-created agent and rules/index. Keep verdict parsing, rejection reasons, and grounding behavior byte-for-byte equivalent.

- [ ] **Step 5: Implement batch result dataclasses and resilient gather**

Use `asyncio.gather(..., return_exceptions=True)` under a semaphore. Partition successful outcomes from exceptions. Return recognized quota failures as `deferred`; re-raise the first non-quota exception. Keep output order aligned with input order.

- [ ] **Step 6: Preserve the existing public wrappers**

Make `triage` and `appraise` call their batch counterparts. If a batch contains a quota error, re-raise it so existing CLI semantics remain fail-fast. Otherwise return the original two-list tuple.

- [ ] **Step 7: Run focused and existing agent tests**

Run: `pytest tests/test_appraiser_batches.py tests/test_grounding.py tests/test_evidence_in_proposals.py -v`

Expected: all tests pass.

- [ ] **Step 8: Commit the partial-result API**

```bash
git add provenance/agents/appraiser.py tests/test_appraiser_batches.py
git commit -m "feat(appraiser): preserve partial batches on quota errors"
```

---

### Task 4: Nightly Queue Orchestration

**Files:**
- Modify: `provenance/nightly.py:20-230`
- Modify: `tests/test_nightly.py`

**Interfaces:**
- Consumes: `store.pending_papers`, `triage_batch`, `appraise_batch`, `select_for_appraisal`, `is_quota_error`
- Produces: summary fields `pending_before`, `triaged`, `appraisal_selected`, `appraised`, `appraisal_pending`, and optional `pipeline_error`
- Preserves: `run(subject, *, since_days, limit_per_source, engineer) -> dict`

- [ ] **Step 1: Replace the old synthesis-only fixture with a reusable stateful DB stub**

The stub must expose papers, appraisals, rejections, findings, and run documents, with collection streams reflecting writes. This permits a first run to leave work pending and a second run to recover it without mocking the behavior under test.

- [ ] **Step 2: Write the failing automatic-recovery test**

Seed 33 relevant stored papers with no appraisal/rejection and make the sweep return zero new papers. Mock triage batches as relevant and appraisal batches as successful. Assert the run selects exactly ten, saves exactly ten appraisals, reports `appraisal_pending == 23`, and passes the saved ten into notification.

- [ ] **Step 3: Write failing fairness and persistence-order tests**

Seed old pending papers plus new sweep papers. Assert the selected IDs match the five/five policy. Record calls and assert relevant-paper triage state and triage rejections are saved before the first appraisal batch is invoked, then assert each three-paper appraisal wave is saved before the next wave.

- [ ] **Step 4: Write the failing appraisal-429 test**

Have the first three-paper wave return two appraisals and one deferred quota paper. Assert:

```python
assert summary["appraised"] == 2
assert summary["appraisal_pending"] == 31
assert summary["pipeline_error"]["stage"] == "appraisal"
synthesise.assert_not_awaited()
engineer_plan.assert_not_called()
assert summary["notified"] == {"sent": ["briefing"]}
assert db.saved_run == summary
```

- [ ] **Step 5: Write the failing persistence-error tests**

Make `save_papers`, `save_rejections`, `save_appraisals`, and `save_finding` fail in separate parameterized cases. Assert each exception escapes `run`; none is converted into `pipeline_error`.

- [ ] **Step 6: Run nightly tests and verify RED**

Run: `pytest tests/test_nightly.py -v`

Expected: failures because nightly only appraises `result.papers`, has no cap, and does not catch appraisal quota errors.

- [ ] **Step 7: Implement queue loading and triage waves**

After saving sweep results, call `store.pending_papers(db=db)`. Split papers into those already triaged for `result.agenda.source_digest` and those requiring triage. Process untriaged work in bounded batches, set `triaged_at` and `triage_agenda_digest` on relevant survivors, save the survivors and rejections, and stop on a returned quota error.

- [ ] **Step 8: Implement fair appraisal selection and three-paper waves**

Read `PROVENANCE_APPRAISAL_LIMIT` with a default of `10`. Select candidates through `select_for_appraisal`. Process slices of three using `appraise_batch(..., max_concurrent=3)`, persist each slice's appraisals and rejections immediately, and stop after a quota result.

- [ ] **Step 9: Gate synthesis and engineering on stage health**

When triage or appraisal reports quota exhaustion, populate:

```python
summary["pipeline_error"] = {
    "stage": "triage" or "appraisal",
    "type": type(exc).__name__,
    "message": str(exc)[:300],
}
```

Skip synthesis and ensure `fresh` remains empty. On a healthy capped run, synthesize normally even if `appraisal_pending` is nonzero. Convert the draft synthesis catch to the same `pipeline_error` shape with `stage="synthesis"`; keep finding persistence outside the catch.

- [ ] **Step 10: Count durable pending work and finish all non-model stages**

Set `appraisal_pending = len(store.pending_papers(db=db))` after completed writes. Always attempt health and notification, then save the run document. The appraisals and rejections sent to `_notify` must be exactly those persisted during this run.

- [ ] **Step 11: Run nightly tests and verify GREEN**

Run: `pytest tests/test_nightly.py -v`

Expected: all tests pass.

- [ ] **Step 12: Commit nightly orchestration**

```bash
git add provenance/nightly.py tests/test_nightly.py
git commit -m "fix(nightly): recover and drain pending appraisals"
```

---

### Task 5: Honest Backlog and Failure Briefings

**Files:**
- Modify: `provenance/notify.py:551-759`
- Modify: `tests/test_notify.py`

**Interfaces:**
- Consumes: `run["appraisal_pending"]` and optional `run["pipeline_error"]`
- Produces: morning briefing subject and HTML that distinguish capped backlog from failed analysis

- [ ] **Step 1: Write the failing normal-backlog email test**

Render a successful run with ten appraisals and `appraisal_pending=23`. Assert the subject does not say “Analysis incomplete,” the HTML says 23 papers are queued automatically, and synthesis outcome copy remains present.

- [ ] **Step 2: Generalize the existing synthesis-failure tests**

Parameterize `pipeline_error.stage` over `triage`, `appraisal`, and `synthesis`. For every stage assert:

```python
assert "Analysis incomplete" in subject
assert "nothing to propose" not in html
assert "watched and left alone tonight" not in html
assert "23" in html and "queued" in html
```

Also preserve the zero-paper successful-run test so ordinary quiet mornings do not look alarming.

- [ ] **Step 3: Run notification tests and verify RED**

Run: `pytest tests/test_notify.py -v`

Expected: failures because the template only recognizes `synthesis_error` and does not render backlog.

- [ ] **Step 4: Implement unified incomplete-state copy**

Use `pipeline_error` as the failure signal. Name the failed stage in plain English, state that no conclusion was made, and say pending papers will retry automatically. Add `appraisal_pending` as a fifth stat or a compact queue line beneath the stats without adding any approval button.

- [ ] **Step 5: Implement normal capped-run copy**

When there is no `pipeline_error` but `appraisal_pending > 0`, retain the healthy kept/finding headline and add: “N papers remain in the automatic appraisal queue.” Do not use “analysis incomplete” for a deliberate cap.

- [ ] **Step 6: Run notification and nightly tests**

Run: `pytest tests/test_notify.py tests/test_nightly.py -v`

Expected: all tests pass.

- [ ] **Step 7: Commit briefing behavior**

```bash
git add provenance/notify.py tests/test_notify.py
git commit -m "fix(email): report pending and incomplete analysis honestly"
```

---

### Task 6: Full Verification, Review, Deployment, and Recovery

**Files:**
- Modify if needed after review: files from Tasks 1-5
- No infrastructure manifest changes expected

**Interfaces:**
- Consumes: the tested branch commit and existing Cloud Run Job configuration
- Produces: a deployed immutable image and a verified recovery execution

- [ ] **Step 1: Run static diff checks and the full suite**

Run:

```bash
git diff --check
pytest -q
```

Expected: no diff errors and all tests pass.

- [ ] **Step 2: Inspect the final diff for unrelated changes**

Run:

```bash
git status --short
git diff 2b5d30d...HEAD --stat
git diff 2b5d30d...HEAD -- provenance tests docs/superpowers
```

Confirm the main worktree's unrelated library, renderer, and content-agenda edits are absent.

- [ ] **Step 3: Request code review and address findings**

Review the complete range from `2b5d30d` through branch `HEAD` against the approved spec. Verify especially that only quota errors are swallowed, every completed result is persisted, and capped backlog is not mislabeled as failure. Apply valid findings test-first and rerun focused tests.

- [ ] **Step 4: Commit any review fixes and rerun verification**

Run:

```bash
git diff --check
pytest -q
git status --short
```

Expected: all tests pass and the only uncommitted changes, if any, are explicitly understood.

- [ ] **Step 5: Record the exact deploy target before mutation**

Read the current `provenance-nightly` Cloud Run Job description and capture its region, service account, command/args, environment variables, secret references, retry count, and image. This is a read-only guard against overwriting the already-fixed `CONSOLE_WRITE_TOKEN` secret mapping.

- [ ] **Step 6: Build the exact tested commit**

After the final verification commit, tag and submit the worktree directory with:

```bash
gcloud builds submit . \
  --project sentinel-505814 \
  --tag us-central1-docker.pkg.dev/sentinel-505814/cloud-run-source-deploy/provenance-nightly:nightly-backlog-20260824
```

Record the tested Git commit and resulting immutable image digest together. Do not make another source change between this build and deployment.

- [ ] **Step 7: Update only the Cloud Run Job image**

Run:

```bash
gcloud run jobs update provenance-nightly \
  --project sentinel-505814 \
  --region us-central1 \
  --image us-central1-docker.pkg.dev/sentinel-505814/cloud-run-source-deploy/provenance-nightly:nightly-backlog-20260824
```

Do not pass `--set-env-vars`, `--set-secrets`, `--command`, or `--args`; preserving the job's existing configuration is part of the verification.

- [ ] **Step 8: Verify deployed identity and secret wiring**

Describe the job again. Assert its image digest matches the build, its command remains `python -m provenance.nightly`, and `CONSOLE_WRITE_TOKEN` remains a Secret Manager reference rather than a plaintext value.

- [ ] **Step 9: Execute one recovery run**

Manually execute `provenance-nightly` and wait for completion. Do not start a second execution while the first is active.

- [ ] **Step 10: Verify the durable recovery outcome**

Inspect Cloud Run logs and the newest `provenance_runs` document. Confirm:

- the stored August 24 papers were loaded despite `retrieved_new` possibly being zero;
- approximately 33 were relevant after re-triage;
- no more than ten were selected for appraisal;
- the remainder is reported by `appraisal_pending`;
- triage/appraisal writes exist in Firestore;
- the run document exists;
- the briefing send returned a provider message ID.

If another 429 occurs, confirm `pipeline_error.stage` is correct, synthesis was skipped, the execution succeeded, and unfinished papers remain pending.

- [ ] **Step 11: Verify the scheduled trigger remains enabled**

Describe the existing Cloud Scheduler job and confirm its next 03:00 America/New_York invocation still targets `provenance-nightly`.

- [ ] **Step 12: Mark the design implemented**

Update the spec status from `Proposed` to `Implemented`, record the deployed image digest and recovery execution name, commit the documentation, and run `git status --short` one final time.
