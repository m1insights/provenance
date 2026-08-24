# Durable Nightly Appraisal Backlog

**Date:** 2026-08-24  
**Status:** Proposed  
**Owner:** Provenance nightly pipeline

## Problem

The 2026-08-24 nightly run retrieved and stored 217 papers, then triaged 33 as
relevant and 184 as irrelevant. The appraiser hit Vertex AI's `429
RESOURCE_EXHAUSTED` response before the run persisted either result. Cloud Run
retried the job, but the retry treated all 217 stored papers as already known,
so it skipped them and failed again during synthesis. No morning briefing or run
record was sent.

The pipeline currently uses “newly retrieved in this process” as its appraisal
queue. That is not durable: once a paper has been stored, any failure between
retrieval and appraisal can make it permanently invisible to later nightly
runs. A synthesis-only catch improves notification but does not recover those
papers.

## Decision

Make pending appraisal work a durable Firestore-backed queue derived from paper
state. Each nightly run will:

1. retrieve and store new papers as it does today;
2. load every paper that has neither a terminal rejection nor an appraisal;
3. triage untriaged pending papers and persist the triage outcome before
   appraisal begins;
4. appraise at most ten relevant pending papers, with at most three model calls
   in flight;
5. reserve half the appraisal capacity for new papers and half for the oldest
   backlog, lending unused slots to the other group;
6. leave every unselected or temporarily failed paper pending for a later run;
7. send an honest briefing and save a run record even when a quota failure
   prevents the analysis from finishing.

This means the approximately 33 relevant papers from August 24 will be
recovered automatically. The first recovery run will appraise up to ten; the
remaining approximately 23 will stay in the automatic queue. Exact counts may
change slightly because the lost triage decisions must be recomputed.

## Options Considered

### 1. Derive the queue from existing evidence records — chosen

A paper is terminal when its ID appears in either `provenance_appraisals` or a
terminal `provenance_rejections` document. Otherwise it remains pending. A
small triage marker on the paper prevents relevant papers from being needlessly
triaged again while they wait for an appraisal slot.

This reuses Firestore, requires no new service, and makes retry behavior easy to
audit from the existing collections.

### 2. Add a dedicated queue collection

A `provenance_appraisal_queue` collection could store attempts,
`next_retry_at`, and dead-letter state. This provides more scheduling control
but creates a second source of truth that must stay transactionally consistent
with papers, appraisals, and rejections. The current volume does not justify
that subsystem.

### 3. Create one Cloud Task per paper

Cloud Tasks would isolate every model call and provide managed retries. It also
adds infrastructure, IAM, deployment, and per-task orchestration for a workload
that currently runs once a day. This is disproportionate to the ten-paper
nightly budget.

## Durable State

`Paper` gains optional triage metadata:

- `triaged_at`: when the relevance decision completed;
- `triage_agenda_digest`: the agenda version used for the decision.

For a relevant paper, triage updates `matched_components` and these fields, then
the paper is saved before appraisal starts. An irrelevant paper receives its
terminal rejection immediately. A queued relevant paper is therefore visible
as:

```text
paper exists
+ triaged_at is set for the current agenda
+ no appraisal exists
+ no terminal rejection exists
= ready for appraisal
```

Papers without current triage metadata are pending triage. If the research
agenda digest changes, a still-pending paper is triaged again against the new
agenda before appraisal.

The pending-paper lookup reads each rejection's stored `paper_id`; it does not
infer IDs by splitting Firestore document names.

## Selection and Fairness

The default appraisal budget is ten papers per run and is configurable through
`PROVENANCE_APPRAISAL_LIMIT`.

- Up to five slots go to papers retrieved by the current run.
- Up to five slots go to the oldest queued papers.
- If either group has fewer than five candidates, its unused slots are filled
  from the other group.
- Selection is deterministic, using `retrieved_at` and `doc_id` as tie-breakers.

This drains the backlog without allowing a large old queue to prevent newly
published evidence from being assessed. On the August 24 recovery run there
will be no newly retrieved candidates unless the sweep finds more papers, so
unused new-paper capacity can be lent to the backlog and all ten slots remain
available.

The appraiser processes selected papers in waves of at most three. Completed
wave results are persisted before the next wave starts, preventing a later 429
from erasing earlier successful work.

## Failure Behavior

### Quota failure during triage or appraisal

- stop launching additional model calls for that stage;
- persist all completed outcomes;
- leave the failed and not-yet-started papers pending;
- skip synthesis and engineering for that run, avoiding additional calls to an
  already exhausted model service;
- run the health sweep;
- save a run record and send an “analysis incomplete” morning briefing;
- return success so Cloud Run does not immediately repeat the same quota-heavy
  work.

Only recognized capacity failures such as HTTP 429 / `RESOURCE_EXHAUSTED` use
this path. Programming errors and Firestore write failures remain fatal so they
cannot be mislabeled as transient quota problems.

### Quota failure during synthesis

Retrieval and appraisal have already been persisted. The run records the
synthesis failure, opens no finding, runs no engineering, completes health
checks, and sends the incomplete briefing. Firestore failures while saving a
finding remain fatal and are outside this boundary.

### Normal capped run

Having papers left in the queue because of the ten-paper budget is expected,
not an error. Synthesis may use the successfully persisted appraisals from the
run, and the briefing reports how many papers remain queued.

## Run Record and Email

The run summary adds enough information to distinguish new discovery, recovered
work, ordinary backlog, and service failure:

- `pending_before`
- `triaged`
- `appraisal_selected`
- `appraised`
- `appraisal_pending`
- `pipeline_error`, containing stage, exception type, and a sanitized message
  when a recognized quota failure occurs

The morning briefing must never say there was “nothing to propose” when a stage
did not complete. Its incomplete state names the failed stage and the number of
papers still queued. A normal capped run can say that analysis completed for
the selected batch while clearly showing the remaining backlog.

## Recovery and Deployment

After tests pass:

1. build an image from the tested worktree commit;
2. deploy that exact image to the `provenance-nightly` Cloud Run Job without
   changing its existing secret references;
3. verify the job revision, image digest, environment, and secret wiring;
4. execute the job once manually;
5. verify that it re-triages the 217 stored papers, persists the triage results,
   appraises no more than ten relevant papers, records the remainder as pending,
   writes a run document, and sends the recovery briefing;
6. if the manual run encounters another 429, verify that the job exits
   successfully, the pending count remains nonzero, and the incomplete
   briefing is sent.

No manual data repair or one-off email reconstruction is required. The manual
execution uses the same durable recovery behavior future scheduled runs use.

## Test Strategy

Tests are written before implementation and cover:

- stored-but-unappraised papers are returned on the next nightly run;
- triage outcomes are persisted before appraisal begins;
- selection chooses at most ten papers and shares capacity between new work and
  the oldest backlog;
- unused capacity is lent to the other group;
- a normal cap leaves excess papers pending and still permits synthesis;
- an appraisal 429 preserves completed work, leaves unfinished papers pending,
  skips synthesis and engineering, sends an incomplete briefing, and records
  the run;
- a synthesis 429 sends an incomplete briefing and opens no finding;
- Firestore persistence errors still raise;
- incomplete email copy never claims that analysis completed or that there was
  nothing to propose;
- a zero-paper successful run retains its normal, non-alarming copy;
- the full existing suite remains green.

## Non-goals

- No dead-letter queue: a paper remains pending until it reaches a real
  appraisal or terminal rejection.
- No automatic model-tier downgrade: evidence quality must not silently depend
  on current quota.
- No automatic pull-request behavior changes.
- No new Cloud service or scheduler.
