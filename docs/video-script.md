# Demo video — ~2.5 minutes

Recording notes: 1080p screen capture, no face cam needed. Every number spoken
below is real; nothing is mocked. Where a command is given, run it live.

Style note: short sentences, plain words, one idea at a time. If a line needs
a second read to understand, cut it or split it. Skip anything that isn't
either (a) the point, or (b) proof for the point. When in doubt, cut it.

---

## 0:00 – 0:20 · The app and the problem

**On screen:** synqology on the App Store, then a quick scroll down
`LONGEVITY_FEATURE_STACK.md` — don't stop on any one line.

> "This is a longevity app I built. It scores your health out of 100, using
> rules based on medical research.
>
> New studies come out every week. I can't read all of them myself. So I
> built a system that does — and keeps the app's numbers up to date on its
> own."

---

## 0:20 – 0:45 · It figures out what to check

**On screen:** run it live.

```
python -m provenance agenda --detail
```

> "It reads my own code to figure out what to research — I don't hand it a
> topic list.
>
> For example, my app gives credit for a workout after 20 minutes, and
> wants 3 of those a week. So it goes and checks: is that still the right
> number, based on the latest studies?"

**Quick flash:** GitHub → synq → Actions, the green "Publish Provenance
agenda" run. One sentence, then move on.

> "And it publishes what it finds automatically, every night — I don't have
> to be at my computer."

---

## 0:45 – 1:15 · Proof it's careful, not lazy

**On screen:** the console's counters — 1,681 papers read, 336 appraised,
1,370 rejected, 2 findings (as of Aug 31; run `python -m provenance status`
right before recording — the 3 AM job moves these numbers). Two findings
show now — point at the **APPROVED** one, not the OPEN one.
Keep the address bar in frame — the `.run.app` domain shows this is running
on Google Cloud, not a laptop.

> "It's read one thousand six hundred eighty-one papers so far. Only three
> hundred thirty-six were solid enough to use.
>
> Everything else got rejected, and it wrote down why. So I always know it
> did the work — it's not just skimming."

---

## 1:15 – 1:45 · It writes the fix itself

**On screen:** GitHub PR #2, scrolled to the evidence table.

> "It found twenty-two studies that all agreed on something my app had
> wrong. So it wrote the code fix itself, and ran my tests.
>
> All fifty-one passed."

---

## 1:45 – 2:05 · Same system runs my social videos

**On screen:** play the reel, then the Instagram insights screenshot.

> "The same fact-checked research also powers my Instagram videos — every
> number on screen is one this system verified first.
>
> My first five videos made this way passed four hundred thousand views."

---

## 2:05 – 2:30 · I approve everything, and it's real

**On screen:** the console, the finding marked APPROVED. Then three Google
Cloud Console tabs — Logs, Cloud Run, Cloud Scheduler — one per beat, fast.
Close on the architecture diagram.

> "Nothing goes live without me. I approve or reject every single change.
>
> And this isn't just running on my laptop — it's real Google Cloud
> infrastructure, running on its own every night.
>
> It keeps my app honest. And I'm still the one who decides."

---

## Things to have open before recording

1. synqology App Store page (or the screenshot at
   `~/Desktop/provenance-hackathon-screenshots/10-synqology-vitality-index-cropped.png`)
2. `LONGEVITY_FEATURE_STACK.md`
3. Terminal in `provenance`, venv active
4. github.com/m1insights/synq — PR #2, scrolled to the evidence table
5. The console, unlocked with the write token — address bar visible so the
   `.run.app` domain reads on camera
6. Google Cloud Console, signed in as the account that owns the project,
   three tabs pre-loaded: Logs Explorer filtered to `provenance-nightly`
   with `gemini` request lines visible, Cloud Run → Jobs →
   `provenance-nightly` → Executions, Cloud Scheduler showing
   `provenance-nightly-0300` — this is the hard requirement ("must
   demonstrate the backend is running on Google Cloud"), don't navigate live
7. github.com/m1insights/synq → Actions → the latest green "Publish
   Provenance agenda" run
8. Preview: the Instagram insights screenshot, and the Chetty reel queued
   in QuickTime
9. `docs/architecture.md` scrolled to the diagram — the closing shot

**Cut from the old script, on purpose:** the double grounding-check
explanation (quote check vs. number check), the UK Biobank re-analysis
caveat, the "eleven edits across five files" detail, the exact 1.33 →
75%-cap math, the `jq` / `_provenance` JSON walkthrough, the full stack
name-drop (Gemini/ADK/Firestore/etc.), and the whole "I read every line
myself and caught a bug" beat (the guard-clause / commit `5f342ef` story).
That last one is real and verified — it's just not in the video anymore. It
still lives in `docs/devpost-submission.md` and `docs/architecture.md` if
you want to point someone to it in writing. If you want any of this back,
the prior version is in git history.
