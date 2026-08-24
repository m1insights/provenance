# Agenda CI Automation Design

**Date:** 2026-08-24

**Status:** Proposed

**Repositories:** `m1insights/provenance`, `m1insights/synq`

**Production branch:** `m1insights/synq@launch`

## Purpose

Provenance derives its research agenda from synqology's private Vitality Index
sources. The deployed nightly job cannot read those sources, so it consumes the
latest agenda published to Firestore. Today that publication depends on a local
developer action, and the documented `python -m provenance agenda` command does
not actually publish anything.

Automate agenda publication whenever a governing Vitality Index source lands on
the production branch. The automation must work while the developer Mac is
offline, avoid long-lived cloud credentials, avoid duplicate Gemini calls on
retries, and preserve the last valid agenda if a run fails.

## Scope

This change:

- adds an explicit, idempotent agenda-publication CLI path;
- makes the synqology checkout path configurable for CI;
- fingerprints every source that governs the extracted agenda;
- adds a GitHub Actions workflow in the private synqology repository;
- authenticates GitHub Actions to Google Cloud through Workload Identity
  Federation;
- documents and verifies the automated handoff to the existing nightly job.

This change does not move synqology source code into the Cloud Run image, run a
literature sweep from the synchronization workflow, add another notification
service, or change the nightly schedule.

## Chosen Architecture

The workflow belongs to `m1insights/synq`. That repository already contains the
private source material and can check out the public Provenance repository
without a cross-repository GitHub credential.

The workflow runs on a push to `launch` that changes any of:

- `LONGEVITY_FEATURE_STACK.md`;
- `tapntrack/Services/VitalityIndexCalculator.swift`;
- `tapntrack/Services/ShiftWorkAdjuster.swift`.

It also supports `workflow_dispatch` for recovery and an optional forced
refresh. Pull requests and pushes to non-production branches never publish an
agenda.

The workflow checks out the synqology commit that triggered it and an immutable,
tested Provenance commit. It installs the Provenance Python requirements,
authenticates to Google Cloud through OIDC, points Provenance at the CI checkout
with `SYNQOLOGY_REPO_PATH`, and runs:

```bash
python -m provenance agenda --publish
```

The forced-refresh workflow input adds `--refresh` to that command.

## Alternatives Considered

### Cross-repository dispatch into Provenance

A synqology workflow could dispatch an event to Provenance, where the publisher
would run. The Provenance runner would then need a GitHub App or fine-grained
token to check out private synqology source. This adds a long-lived GitHub-side
credential and a second workflow without improving the trust boundary.

### Google Cloud Build trigger

Cloud Build could connect to the private GitHub repository and run the same
publisher. This adds another CI system and private-repository connection while
the existing GitHub push event already provides the correct trigger and commit.

### Local launchd automation

A Mac LaunchAgent could periodically compare source digests. It would remain
dependent on one machine being powered on, logged in, authenticated, and healthy,
so it would narrow rather than close the automation gap.

## Provenance Configuration

`SubjectApp` retains a primary `algorithm_doc` and `algorithm_source` for the
existing engineering workflow. It gains an explicit collection of supporting
agenda sources. For synqology, `ShiftWorkAdjuster.swift` is a supporting agenda
source because it governs shift-worker scoring behavior that the research agenda
must describe.

The complete ordered input set for agenda extraction and fingerprinting is:

1. `LONGEVITY_FEATURE_STACK.md`;
2. `VitalityIndexCalculator.swift`;
3. `ShiftWorkAdjuster.swift`.

The source digest hashes every file in that deterministic order. The Gemini
request labels and includes every file rather than silently hashing content the
model did not receive. A change to any input therefore produces a new digest and
a newly derived agenda.

`SYNQOLOGY_REPO_PATH` controls the checkout root. When unset, it defaults to the
existing local path `/Users/m1labs/Dev/apps/synqology/synq`, preserving local
behavior.

## Publication Contract

`python -m provenance agenda` remains a read-only inspection command. It may
read or populate the repository-local JSON cache and call Gemini when the cache
is absent, but it does not contact Firestore for publication.

`python -m provenance agenda --publish` is the explicit synchronization
command:

1. Compute the source digest from the complete ordered input set.
2. Read the exact Firestore document
   `provenance_agendas/{subject_key}__{source_digest}`.
3. If the document exists and `--refresh` is absent, use and display that agenda,
   report that it was already published, and exit zero without calling Gemini.
4. Otherwise, build the agenda from the checked-out sources and publish it with
   one Firestore document `set`.
5. Display the algorithm version, digest, component count, and publication
   outcome.

`--refresh --publish` bypasses both the repository-local cache and the exact
Firestore digest hit, regenerates the agenda, and overwrites the same document.
This is an operator recovery mechanism for correcting extraction quality; it
does not manufacture a new source identity.

The Firestore store exposes an exact-digest lookup rather than scanning the
entire agendas collection. `latest_agenda` remains the cloud fallback used when
the source checkout is absent.

## Idempotence and Concurrency

The Firestore document key is deterministic. Replaying a successful workflow
for the same synqology commit finds the existing document and makes no Gemini
call and no write.

The workflow uses a concurrency group scoped to agenda publication on `launch`
and does not cancel an in-progress publisher. If two relevant commits arrive in
quick succession, they run serially. Each publishes the agenda for its own
checked-out commit. Firestore's `latest_agenda` selection by `generated_at`
therefore resolves to the last successfully generated production revision.

## Authentication and Authorization

GitHub Actions requests a short-lived Google credential using
`google-github-actions/auth`. The workflow declares only:

```yaml
permissions:
  contents: read
  id-token: write
```

The Workload Identity Provider condition accepts only the
`m1insights/synq` repository and `refs/heads/launch`. The workflow uses a
dedicated agenda-publisher service account rather than the nightly fleet service
account.

The service account receives:

- the managed Vertex AI User role, `roles/aiplatform.user`, required to invoke
  the configured Gemini model;
- a custom Firestore role containing exactly `datastore.entities.get`,
  `datastore.entities.create`, and `datastore.entities.update`;
- no Firestore delete permission and no Cloud Run, Scheduler, Secret Manager,
  Storage, or GitHub permissions.

Firestore IAM cannot restrict an Admin SDK service account to one collection.
The custom role is consequently database-wide at the entity permission layer,
while the publisher code addresses only `provenance_agendas`. This limitation is
accepted to avoid adding a separate publication service.

No Google service-account key or API key is stored in GitHub Secrets. The
workflow stores only non-secret identifiers for the Workload Identity Provider,
service account, project, and location.

## Failure Behavior and Observability

Gemini generation completes before the single Firestore publication write. A
Gemini, authentication, validation, or Firestore error exits nonzero and marks
the GitHub Actions run failed. The existing Firestore agenda remains untouched,
so the nightly job continues using the last valid version.

The workflow summary records:

- the synqology commit SHA;
- the source digest;
- the extracted algorithm version;
- whether the result was newly published, refreshed, or already current.

GitHub's standard failed-workflow notification is the initial alerting channel.
No email, Slack, or additional monitoring service is introduced in this change.

## Testing

### Unit and CLI tests in Provenance

Tests must prove that:

- the digest is stable for unchanged inputs and changes when each of the three
  governing files changes;
- all fingerprinted sources are also included in the Gemini request;
- `agenda` without `--publish` performs no Firestore publication work;
- `agenda --publish` reuses an exact published digest without calling Gemini;
- a missing digest builds once and saves one agenda document;
- `--refresh --publish` rebuilds and overwrites the same digest document;
- Gemini and Firestore failures propagate as command failures;
- the configurable repository path resolves every subject source consistently;
- exact agenda lookup uses the deterministic document path rather than a
  collection scan.

### Workflow validation

Review and static validation must confirm that the workflow:

- triggers only for pushes to `launch` with the three source path filters, plus
  manual dispatch;
- requests only `contents: read` and `id-token: write`;
- pins third-party actions and the Provenance checkout to immutable revisions;
- sets `SYNQOLOGY_REPO_PATH` to the triggering checkout;
- maps forced refresh only from the manual input;
- serializes publication and never cancels an active publisher.

### Production verification

After provisioning and merging:

1. Run the workflow manually without forced refresh.
2. Confirm a document exists at the expected subject-and-digest key.
3. Confirm its algorithm version and component count match local inspection.
4. Run the workflow again and confirm the outcome is `already current`, with no
   Gemini generation.
5. Execute or inspect the next nightly run and confirm it reports the same
   agenda digest.

## Rollout Sequence

1. Implement and merge the Provenance configuration, digest, store, CLI, tests,
   and documentation changes.
2. Record the exact tested Provenance commit SHA for the workflow checkout.
3. Create the dedicated Google service account, custom Firestore role, Workload
   Identity Pool and Provider, repository-and-branch attribute condition, and
   service-account impersonation binding.
4. Add the synqology GitHub Actions workflow referencing the exact Provenance
   commit.
5. Merge the workflow to `launch` and run the production verification sequence.
6. Update the architecture status from a manual local handoff to the verified CI
   handoff.

The rollout does not alter or redeploy the existing Cloud Run nightly job. Its
contract—read the latest published agenda when source files are absent—remains
unchanged.

## Success Criteria

- A relevant merge to `m1insights/synq@launch` publishes its agenda without any
  developer-machine action.
- A retry of the same source digest does not call Gemini or rewrite Firestore.
- No long-lived Google credential exists in GitHub.
- A failed publisher cannot remove or partially replace the last valid agenda.
- The nightly job consumes the agenda digest produced by CI.
- Documentation and CLI help describe the real publication behavior.
