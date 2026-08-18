# The audit loop

Gemini writes the Swift. Claude Opus reviews it. A human decides.

These files live in the **subject application's** repository at
`apps/synqology/.claude/`, not here — this is the tracked copy, so the
integration is preserved and reviewable alongside the system it belongs to.

## Why a second model

Provenance has Gemini do everything on the code path: read the algorithm,
appraise the literature, decide a constant is wrong, and write the Swift that
changes it. One model, no independent check, and a human as the only gate.

That is not a hypothetical concern. The first review of a Gemini-authored
change — `m1insights/synq#2`, which had passed 51 tests and a human read —
found this:

```swift
static func mvpaDayFactorDenominator(schedule: WorkSchedule?) -> Double {
    guard let schedule = schedule, schedule.isEnabled, schedule.isShiftWorker else { return 2.0 }
    return 2.0
}
```

Both branches return the same value. The guard is dead, and the shift-worker
accommodation it used to express is gone — while the code still reads as though
it implements one. No test catches it, because both assertions were updated to
`2.0`; deleting the entire guard leaves the suite green.

That finding is now check number two in the review brief, with the real code as
the worked example.

## The loop

| Piece | File |
|---|---|
| **Trigger** | `hooks/provenance-check.sh`, registered as a `SessionStart` hook |
| **Execution skill** | `skills/provenance-audit/SKILL.md` — the review brief |
| **Command** | `commands/provenance.md` — `/provenance`, the operator entry point |
| **Verification** | A verdict: CLEAN · CONCERNS · DEFECT |
| **Memory** | The audit posted as a PR comment |

The audit comment is the memory. No state store, and the record sits where the
next person to read that pull request will find it — which is also how the hook
knows to stop raising it.

## Ordering, and why it matters

The obvious design emails you when the nightly run finds something. That is
wrong: the nightly job runs in Cloud Run, no pull request exists yet, and the
auditing model is not available there. You would be approving code that had not
been written, let alone reviewed.

```
nightly (cloud)   finds evidence, opens a Finding, stays silent
      ↓
/provenance       opens the draft PR
      ↓           Opus audits the diff
      ↓           audit posted as a PR comment
      ↓
one email         carries the verdict + the approve link
      ↓
you approve       already knowing what Opus found
```

## Three properties of the hook

In order of importance:

1. **It can never stop a session starting.** Every failure path exits 0 with no
   output — no token, no network, no `gh`, malformed JSON, anything.
2. **It is silent when there is nothing.** A hook that speaks every session gets
   ignored, and is then worse than absent.
3. **It is fast.** Hard timeouts on every call; measured at 1.5s across both
   repositories.

## Installing

Copy `skills/`, `commands/`, `hooks/` and `settings.json` into the subject
repository's `.claude/` directory. The hook takes its GitHub token from
`gh auth token`, so no secret is stored anywhere.

## The auditor never edits

It reports; a human decides; a fix is a separate deliberate act. Two models
writing the same file with no independent check on either is the problem this
exists to solve, one layer further in.
