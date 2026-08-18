---
name: provenance-audit
description: Review a Gemini-authored pull request on the synq or synq_insights repositories before a human decides on it. Use when auditing a provenance/* branch, when the /provenance command runs, or when asked to review an agent-written change to the Vitality Index. Checks that the edit does what its evidence claimed, that nothing was silently removed, that Swift correctness holds against this codebase's real bug history, and that tests were updated rather than weakened.
---

# Auditing an agent-written change

A pull request on a `provenance/*` branch was written by Gemini, from research
evidence, without a human in the loop. Your job is to be the independent check
before a person decides on it.

You are not re-judging the evidence. Whether 22 papers justify changing a
constant is the Synthesist's call and then the founder's. You are judging
whether **the code does what was claimed, correctly, in this codebase's idiom.**

## Read these first

1. The pull request body — it states the finding, the evidence, and the
   backtest result.
2. `apps/synqology/CLAUDE.md` — the repository conventions. **It sits one level
   ABOVE the `synq` repo**, so a session started inside `synq/` will not pick it
   up implicitly. Read it explicitly.
3. The full diff, not just the summary.

## What to check, in priority order

### 1. Does the edit do what the finding claimed?

The pull request body states a specific change: some constant moves from X to
Y, because the evidence says so. Verify the diff actually does that, to that
constant, and not to a neighbouring one.

A clean-looking diff that moves a *different* value than the evidence supports
is the failure no test catches, because the tests were updated to match
whatever it did.

### 2. Did it change behaviour nobody asked for?

Ask directly: **does any branch, flag, guard or special case still exist but no
longer do anything?**

This is the check that matters most. The real example from this repository:

```swift
static func mvpaDayFactorDenominator(schedule: WorkSchedule?) -> Double {
    guard let schedule = schedule, schedule.isEnabled, schedule.isShiftWorker else { return 2.0 }
    return 2.0
}
```

Both paths return the same value. The guard is dead, and the shift-worker
accommodation it used to express is gone — while the code still looks like it
implements one. That change passed 51 tests and a human read.

Look for: identical return values across branches, conditions that can no
longer be false, doc comments describing a distinction the code no longer
draws.

### 3. Swift correctness, weighted to this codebase's actual bugs

These have shipped here before. Check for them specifically:

- **NaN-propagating clamps.** `min(1.0, x)` absorbs NaN; `min(x, 1.0)`
  propagates it. Layout clamps must be constant-first, and zero divisors need
  explicit guards.
- **Bare `GeometryReader` in a stack.** Two in one `HStack` put `inf - inf`
  into layout arithmetic, which lands as NaN in a sibling's origin and traps.
  Progress bars use `ProgressTrack`, never a hand-rolled reader.
- **Force unwraps** and implicitly unwrapped optionals in scoring paths.
- **SwiftData concurrency** — collection and upload route through
  `HealthSyncCoordinator` only.
- **Division by a value that can be zero**, especially newly parameterised
  denominators.

### 4. Repository conventions

From `CLAUDE.md`, the ones an outside model reliably violates:

- Design tokens from `DesignTokens.swift` / `TodayDesign.swift`; never raw
  `.font()` or hard-coded spacing.
- Icon colour is `.themeAccent`; **never** `.red`, `.orange`, `.yellow`,
  `.purple` for category colouring. Good and bad are opacity, never hue.
- UserDefaults is the single source of truth for health settings.
- An algorithm change must bump the version, update
  `LONGEVITY_FEATURE_STACK.md`, and update `vi_system_explainer.py` in the
  `synq_insights` repository — which a pull request cannot reach, so it should
  be flagged rather than silently missing.

### 5. Were tests weakened rather than updated?

Adjusting an assertion to match new intended behaviour is legitimate. Deleting
one is not. The diffs look almost identical — check which happened.

### 6. Can any test still detect this being wrong?

If every assertion moved to the new value, ask whether the behaviour is now
untested by construction. In the example above, both assertions became `2.0`,
so deleting the entire guard would leave the suite green. That is a finding.

## Verdict

Return exactly one:

- **DEFECT** — would ship a bug, or silently removes behaviour. Say what breaks
  and for whom.
- **CONCERNS** — dead code, stale comments, a branch no test can reach, a
  missing companion change. Worth fixing; would not corrupt data.
- **CLEAN** — genuinely nothing to say. Do not reach for this to be agreeable;
  an audit that never finds anything is not being read carefully.

## Reporting

Lead with the verdict and a one-sentence summary. Then each finding as:

- **What** — the specific code, with file and line.
- **Why it matters** — the consequence, concretely. Who is affected and how.
- **What to do** — the options, when there is more than one honest choice.

State plainly what you checked and found clean, so a reader knows the scope of
the audit and not just its complaints.

Never edit the code. Report; the founder decides; a fix is a separate
deliberate act.
