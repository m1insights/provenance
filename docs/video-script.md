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

**Point at the screen:** the agenda is cached against a digest of those files.
Edit the algorithm and the research agenda changes with it.

**Then cut to GitHub → synq → Actions → "Publish Provenance agenda".** Show the
green run, its step list ("Authenticate to Google Cloud", "Build and publish
agenda"), and the summary block listing the eleven components.

> "And that handoff is automatic now. Push a change to one of the three files
> that govern the algorithm on the production branch, and GitHub Actions
> publishes the new agenda to Firestore before the next nightly run. It gets a
> short-lived Google credential for that one job — no key stored anywhere —
> and the private Swift source never leaves that checkout. My Mac doesn't have
> to be on."

---

## 1:00 – 1:45 · The filter, which is the trust surface

**On screen:** the console's counters — 1,437 papers read, 288 appraised,
1,174 rejected, 1 finding (as of Aug 25; run `python -m provenance status`
right before recording — the 3:00 AM job moves these nightly).
Keep the browser's address bar in frame here — the `.run.app` domain is the
first proof this runs on Google Cloud, not a laptop. Then scroll the
rejection reasons.

> "So far it has read one thousand four hundred and thirty-seven papers. Two
> hundred and eighty-eight survived appraisal.
>
> Everything else is on file with a reason: not relevant, no quantitative
> result, ungrounded claim, insufficient convergence. A system that discards
> silently is indistinguishable from one that never looked."

**Then the grounding check, in the editor:**

> "Every claim carries a sentence the model says appears in the paper — the
> abstract, or the PubMed Central full text when there is one. Code checks
> that it does. And separately, that the number attached to it appears
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

## 2:30 – 3:05 · Reading the diff myself

**On screen:** the pull request on GitHub, scrolled to the diff.

> "I don't approve a change to a health app off a green test suite. I read
> every diff myself before deciding. Here's what that caught on the first
> real one."

**Scroll to the guard clause. Read the finding aloud:**

```swift
guard let schedule = schedule, schedule.isEnabled, schedule.isShiftWorker else { return 2.0 }
return 2.0
```

> "Both branches return the same number. The guard does nothing. And shift
> workers — people on disrupted schedules — quietly lost an accommodation the
> comment still says they have.
>
> Fifty-one tests passed on this. Both assertions had been updated to the new
> value, so you could delete the whole guard and the suite stays green. Only
> reading it catches that."

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

## 3:05 – 3:20 · From grounded claims to the reel

**On screen:** show the ranked sweepable queue.

```
python -m provenance content --sweepable
```

> "The same grounded evidence becomes the content queue. This view ranks papers
> whose data can actually be shown — at least three grounded points on one axis
> for the sweep format."

**Open** `library/*/spec-sweep.json` and expand its `_provenance` block.

> "A human content session chooses the words and chart. Every digit in the spec
> maps back to a claim id and the verbatim quote that grounded it; the renderer
> then draws that reviewed spec deterministically."

**Then play the reel.**

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

**On screen:** cut between the architecture diagram and the Cloud Console —
this is the hackathon's required proof the backend actually runs on Google
Cloud, not just a claim in the diagram. Timed to the words below:

- On "Vertex AI" — Logs Explorer filtered to the `provenance-nightly` job
  with the `Sending out request, model: gemini-3.7-flash, backend:
  VERTEX_AI` lines visible (the Vertex data-access audit log is not enabled,
  so an `aiplatform.googleapis.com` filter comes back empty — use the job log).
- On "Cloud Run" — the Cloud Run **Jobs** list, `provenance-nightly`, with a
  completed execution open so the timestamp is visible on screen.
- On "Cloud Scheduler" — the trigger firing `provenance-nightly` at 03:00.
- On "GitHub Actions" — a two-second flash of the green "Publish Provenance
  agenda" run from 0:45; the step list is enough.

> "Gemini 3.7 Flash for appraisal, 3.5 Flash-Lite for triage. ADK for the
> fleet. Vertex AI, Firestore, Cloud Run, Cloud Scheduler — and GitHub Actions
> with a short-lived federated credential for the agenda. No static API key
> anywhere; the fleet's service account is the credential.
>
> It reads the literature so the algorithm doesn't fall behind it. It shows its
> working every time. And the most useful thing it does is refuse."

---

## Things to have open before recording

1. synqology App Store page
2. `LONGEVITY_FEATURE_STACK.md`
3. Terminal in `provenance`, venv active
4. github.com/m1insights/synq — issue #1 and PR #2, scrolled to the diff
5. The console, unlocked with the write token — address bar visible, not
   cropped, so the `.run.app` domain reads on camera
6. Google Cloud Console, signed in as the account that owns the project,
   three tabs pre-loaded: Logs Explorer filtered to the `provenance-nightly`
   job with `gemini-3.7-flash` request lines visible, Cloud Run → Jobs →
   `provenance-nightly` → Executions (the 03:00 rows), and Cloud Scheduler
   showing `provenance-nightly-0300` — this is the hard requirement ("must
   demonstrate the backend is running on Google Cloud"), don't discover
   navigation live
7. github.com/m1insights/synq → Actions → the latest green "Publish Provenance
   agenda" run, on the job page so the step list is visible
