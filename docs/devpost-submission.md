# Devpost submission — Provenance

**Track:** Taskmaster (complete workflow automation)
**Repo:** https://github.com/m1insights/provenance
**Live:** https://provenance-console-vwe3lj6lwq-uc.a.run.app

---

## Elevator pitch (200 char)

An agent fleet that reads new health research nightly, opens draft pull
requests against a live app's scoring algorithm, and writes the content
explaining it — every number traceable to a quoted source.

---

## Inspiration

I build synqology, a longevity app on the App Store. Its Vitality Index scores
users out of 100 across eleven weighted components — sleep timing, cardio dose,
VO₂ max percentile, heart-rate variability. Every threshold in it was chosen
from published literature.

That literature moves every week. One person maintains the algorithm, the
backend, the marketing and the app. So the gap between "a relevant study was
published" and "the algorithm reflects it" is however long it takes me to
notice — which is unbounded, and I have no way to even measure it.

The obvious fix is an agent that reads papers. The reason nobody trusts that
fix is that a language model summarising a clinical trial will, sooner or
later, state a number the trial does not contain. So the interesting problem
was never retrieval. It was building something whose output you could hand to a
reviewer without checking it line by line.

## What it does

Every night, Provenance:

1. **Derives its own research agenda from the app's source code.** It reads
   `LONGEVITY_FEATURE_STACK.md` and `VitalityIndexCalculator.swift` and works
   out what literature bears on each constant. The Vitality Index credits a
   cardio day at 20 minutes and wants 3 such days a week, so it goes hunting
   for bout-duration and weekend-warrior studies — the work that could prove
   that specific number wrong.
2. **Retrieves and screens** from PubMed and Europe PMC, deduplicating on a
   DOI-first identity so the same trial arriving as a preprint and as a journal
   article counts once.
3. **Appraises what survives** against a GRADE-lite rubric — design, sample
   size, follow-up, tier A–D — and extracts claims, each carrying a sentence
   quoted from the abstract.
4. **Verifies that grounding in code.** The quoted span must appear in the
   retrieved text, and any number attached to a claim must appear inside that
   span.
5. **Waits for convergence.** A Finding opens only when at least three distinct
   papers challenge the same component, at least one is tier A or B, and they
   come from more than one DOI registrant.
6. **Opens a draft pull request** against the real repository, resolving the
   actual symbol in the live source, editing every file the project's own
   contributing rules require, and running the project's scoring test suite
   against the change.
7. **Writes the social content** from the same evidence, through four gates.
8. **Waits for a human.** Nothing merges. Nothing posts.

Steps 1–5 run unattended on Cloud Scheduler at 03:00. Step 6 — opening a pull
request — is deliberately manual: a draft PR is cheap to close and still a
notification, and one arriving nightly for the same finding trains its reader
to ignore it. Every run writes a summary to `provenance_runs`, so what happened
overnight is a record rather than an inference.

## How I built it

**Gemini 3.7 Flash** appraises, synthesises, engineers and writes.
**Gemini 3.5 Flash-Lite** does first-pass relevance triage, where volume is
high and the question is cheap.

**ADK** structures the fleet: `LlmAgent` per role, `FunctionTool` for the
read-only repository navigation the Engineer uses, and `before_tool_callback`
for the guardrails. The **GenAI SDK** handles the structured extraction that
builds the agenda.

**Firestore** is the evidence store — papers, appraisals, rejections, findings,
decisions. **Cloud Run** hosts the review console and the fleet. **Pub/Sub**
carries stage events. **Cloud Scheduler** starts the nightly run.
**Cloud Storage** holds rendered creatives.

Creatives are rendered deterministically: HTML and CSS through headless Chrome,
frame-by-frame for motion, assembled with ffmpeg. No image model touches them.
A diffusion model asked for "a chart showing a 15% reduction" returns something
that looks like a chart and says something else.

## The design decision everything rests on

**Gemini writes words. Code writes numbers.**

The Storyteller's output schema has no numeric field. It chooses the angle, the
claims to lean on and the shape of the chart; code fills in every figure from a
claim that already survived grounding. The model can be wrong about emphasis,
and the worst case is a badly-argued slide. It cannot be wrong about the number
on the chart, because it never supplied one.

Four gates then re-read the finished copy:

| Gate | Refuses |
|---|---|
| **Claims** | Any figure no appraised claim reports |
| **Language** | Causal verbs on observational evidence; intensifiers |
| **Structure** | Charts with fewer than two points; decks where fewer than three slides carry one |
| **Readability** | Clinical vocabulary where a reader decides whether to keep reading |

## Challenges

**Retrieval was returning noise, and it was my fault.** Early sweeps produced
96% irrelevant results and not a single paper that challenged a constant. I had
OR'd a broad MeSH heading with a long exact phrase: `"Exercise"[MeSH]` matches
everything and `"physical activity dose response mortality"[tiab]` matches
nothing, so every result arrived through the broad clause. ANDing them, with
short searchable phrases and a study-design filter, took tier-A/B papers from 1
to 35 and papers challenging a constant from 0 to 23.

**A chart that lied about a null result.** One slide reported that walking pace
made no difference — values 0.98, 1.01, 0.99, 1.00 — and the chart auto-scaled
them across the full plot height into a dramatic zigzag, directly beneath a
headline saying pace didn't matter. Charts now enforce a minimum domain spread.
A chart may understate a difference; it may never manufacture one.

**The language gate caught what the number gate structurally cannot.** Its
first rejection was *"Concentrated training sharply reduces cardiovascular
risk"* — every figure grounded, and still wrong twice: an intensifier the
result doesn't license, and a causal verb on cohort evidence.

**It would have re-proposed things I had already rejected.** Findings are keyed
by a hash of their supporting papers, so a single new study changed the key and
opened a fresh proposal for a question I had answered — my rejection taught it
nothing, and it would have re-asked every time one more paper landed. That is
precisely how a system like this trains its reviewer to stop reading it. A
rejected component now stays quiet until five more challenging papers exist.

**Which then exposed an epidemiology error in my own rule.** I had listed
"meta-analysis" as experimental, so two systematic reviews among twenty-one
cohort studies silently licensed causal language. A meta-analysis inherits the
design of what it pools; pooling buys precision, not causal warrant.

## Accomplishments

It opened a pull request I would seriously consider merging. Twenty-two papers,
twenty of them tier B, on whether concentrating weekly exercise into one or two
days carries the same mortality benefit as spreading it out. Eleven edits
across five files. Fifty-one of fifty-one scoring tests passing.

And it argued against itself, unprompted, twice: it noticed the proposed value
would collapse a distinction my own code comment calls deliberate, and it
computed that nine of the twenty-two studies are UK Biobank re-analyses — so
twenty-two papers are not twenty-two replications. Both went in the pull
request rather than being left for me to find.

## What I learned

The hard part of an agent that reads science is not reading. It is building
something that refuses — and then discovering that your refusals encode your
own mistaken assumptions, and having tests that catch that.

## What's next

Cohort-overlap detection is a string search today and should read study
metadata. The backtest reports test pass/fail and should report the score
distribution shift across a real cohort. And the fleet currently reads one
application's algorithm; the subject is a config object, so pointing it at a
second app is a data change rather than a code change.
