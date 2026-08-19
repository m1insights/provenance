# Demo video — 4 minutes

Recording notes: 1080p screen capture, no face cam needed. Every number spoken
below is real and reproducible; nothing is mocked. Where a command is given,
run it live rather than showing a recording of it.

---

## 0:00 – 0:30 · The problem, stated as a fact about one person

**On screen:** synqology on the App Store, then `LONGEVITY_FEATURE_STACK.md`
scrolling past the eleven scoring components.

> "This is a longevity app I built. Its Vitality Index scores you out of a
> hundred across eleven components — sleep, cardio, VO2 max, heart rate
> variability. Every threshold in it came from a paper.
>
> The literature moves every week. I maintain the algorithm, the marketing and
> the app. So the gap between 'a relevant study was published' and 'the
> algorithm knows about it' is however long it takes me to notice."

---

## 0:30 – 1:00 · The idea, which is not a topic list

**On screen:** run it live.

```
python -m provenance agenda --detail
```

> "Provenance is never told what to research. It reads the algorithm's own
> source — the spec and the Swift file the constants live in — and works out
> what literature would bear on it.
>
> Cardio credits a day at twenty minutes and wants three days a week. So it
> goes looking for bout-duration and weekend-warrior studies. Not 'exercise is
> good for you' — the literature that could prove that specific number wrong."

**Point at the screen:** the agenda is cached against a hash of those files.
Edit the algorithm and the research agenda changes with it.

---

## 1:00 – 1:45 · The filter, which is the trust surface

**On screen:** the console's counters — 571 papers, 70 appraised, 515 rejected.
Then scroll the rejection reasons.

> "Last night it read five hundred and seventy-one papers. Seventy survived.
>
> Everything else is on file with a reason: not relevant, no quantitative
> result, ungrounded claim, insufficient convergence. A system that discards
> silently is indistinguishable from one that never looked."

**Then the grounding check, in the editor:**

> "Every claim carries a sentence the model says appears in the abstract. Code
> checks that it does. And separately, that the number attached to it appears
> in that same sentence — because a real quote with an invented effect size
> beside it passes a quote check and fails this one."

---

## 1:45 – 2:30 · It proposes a change to production

**On screen:** GitHub — issue #1, then draft PR #2, scrolling the evidence
table and the backtest.

> "Twenty-two papers converged on one thing: hitting your weekly exercise
> across one or two days tracks with the same mortality outcomes as spreading
> it out. That contradicts a constant in my code.
>
> So it opened this. Eleven edits across five files — the constant, both call
> sites, the pinned tests, and the version history entry, because my own
> contributing rules require all of them.
>
> It ran my scoring suite against the change: fifty-one of fifty-one pass. That
> number is from xcodebuild, not from a model."

**Scroll to the caveat.** Read it aloud:

> "And it worked out on its own that nine of the twenty-two studies are UK
> Biobank re-analyses, so twenty-two papers is not twenty-two replications. It
> put that in the pull request instead of leaving me to find it."

---

## 2:30 – 3:05 · A second model audits the first

**On screen:** a fresh terminal in `apps/synqology/`. The session-start hook
fires and names the un-audited pull request. Then type `/provenance`.

> "I don't trust one model writing changes to a health app that people use. So
> Gemini proposes, and Claude Opus audits before I'm asked to approve anything.
>
> This runs on its own when I open the project. Watch what it found."

**Scroll to the audit comment on the PR.** Read the finding aloud:

```swift
guard let schedule = schedule, schedule.isEnabled, schedule.isShiftWorker else { return 2.0 }
return 2.0
```

> "Both branches return the same number. The guard does nothing. And shift
> workers — people on disrupted schedules — quietly lost an accommodation the
> comment still says they have.
>
> Fifty-one tests passed on this. I read it myself. Neither caught it, because
> both assertions had been updated to the new value — you could delete the
> whole thing and the suite stays green."

**Then the trap, which is the best 15 seconds in the video:**

> "The obvious fix is to restore the old ratio, which means a denominator of
> 1.33. That would have been worse. The code divides by it *and* truncates it
> to an integer — so every shift worker gets capped at 75% of the score they
> earned. Permanently. No test fails.
>
> It's 1.0 now, with a test that asserts the shift bar stays strictly easier
> than the default — because pinning each number separately is exactly what let
> them collide in the first place."

**Show the mutation test.** Put the bug back, run the suite, three tests go red.

## 3:05 – 3:20 · The gate refuses its own output

**On screen:** run the Storyteller live.

```
python -m provenance storyteller --component mvpa
```

> "The same evidence becomes social content. The model writes the words and
> never a number — every figure is filled in from the verified claim.
>
> Watch the log."

**When a gate fires, read the line aloud.** They fire often; if none does, show
the recorded run where the first draft came back:
*"Concentrated training sharply reduces cardiovascular risk"* — every figure
grounded, and rejected twice over: an intensifier the result doesn't license,
and a causal verb on cohort evidence.

> "This is the part I care about. Getting a number wrong is the easy failure to
> catch. Overstating how strong a finding is looks completely fine and is the
> way health content actually goes wrong."

**Then the rendered output:** the four slides and the reel.

---

## 3:20 – 3:45 · The human decides

**On screen:** the console, approving the finding.

> "Nothing merges. There is no merge function in this codebase — not a rule in
> a prompt, an absent tool, and a callback that refuses any pull request that
> isn't a draft on a branch it owns.
>
> I approve or I reject. A rejection is recorded with a reason, and that reason
> goes back to the agents as guidance for the next run."

---

## 3:45 – 4:00 · Stack, and close

**On screen:** the architecture diagram.

> "Gemini 3.7 Flash for appraisal, 3.5 Flash-Lite for triage. ADK for the
> fleet. Vertex AI, Firestore, Cloud Run, Cloud Scheduler. And
> Claude Opus auditing what Gemini writes, because one model checking its own
> work isn't a check.
>
> It reads the literature so the algorithm doesn't fall behind it. It shows its
> working every time. And the most useful thing it does is refuse."

---

## Things to have open before recording

1. synqology App Store page
2. `LONGEVITY_FEATURE_STACK.md`
3. Terminal in `agent-hackathon`, venv active
4. github.com/m1insights/synq — issue #1 and PR #2
5. The console, unlocked with the write token
6. A second terminal in `~/Dev/apps/synqology/`, not yet started — the
   session-start hook has to fire on camera, so open it during the take
