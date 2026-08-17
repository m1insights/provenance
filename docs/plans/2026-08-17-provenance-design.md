# Provenance — design

**Date:** 2026-08-17
**For:** All Things Agentic Hackathon (Devpost) — submission deadline Aug 31, 2026 @ 5:00pm PDT
**Track:** Taskmaster (complete workflow automation)
**Subject app:** synqology (iOS longevity app, live on the App Store)

---

## Thesis

*Nothing ships without a traceable source.*

Provenance is an agent fleet that reads new health literature every night, decides whether
any of it should change a production algorithm, and — when the evidence converges — opens a
draft pull request against the real repository **and** produces the social content that
explains the change. A human approves both. Nothing merges or posts on its own.

The system's distinguishing property is not that it writes. It is that it **refuses**:
papers that fail appraisal are rejected with a reason, claims that outrun their evidence are
blocked before rendering, and the merge tool does not exist in the toolset.

## Why this problem

synqology's Vitality Index (VI v2.11.0) is a 100-point score built from eight weighted
components — sleep behavior, MVPA, steps, strength, VO₂max percentile, autonomic (HRV/RHR),
sleep physiology, body composition — each with thresholds derived from published literature.
That literature moves continuously. One person maintains the algorithm, the marketing, and
the app. The gap between "a relevant paper was published" and "the algorithm reflects it" is
currently unbounded.

## The clever part

The agent is **not** given a list of research topics. It reads the app's own algorithm —
`synq/LONGEVITY_FEATURE_STACK.md` and `synq/tapntrack/Services/VitalityIndexCalculator.swift` —
and derives its research agenda from the code. VI weights MVPA at 16 points over a 28-day
recency-weighted window, so the Scout goes hunting for MVPA dose-response literature. Change
the algorithm and the research agenda changes with it, automatically.

**The algorithm defines what the system reads.**

---

## Pipeline

```
Cloud Scheduler (nightly 03:00)
        │
        ▼
┌─────────────────────────────────────────────────────────────┐
│ 1. SCOUT            derives queries from VI source + KB     │
│                     PubMed · Europe PMC · ClinicalTrials    │
│                     · medRxiv → dedupe vs Firestore         │
└─────────────────────────────────────────────────────────────┘
        │ pub/sub: paper.ingested
        ▼
┌─────────────────────────────────────────────────────────────┐
│ 2. APPRAISER        design · n · effect size · CI · GRADE-  │
│                     lite tier A–D · verbatim quote span     │
│                     REJECTS with a logged reason            │
└─────────────────────────────────────────────────────────────┘
        │ pub/sub: paper.appraised
        ▼
┌─────────────────────────────────────────────────────────────┐
│ 3. SYNTHESIST       waits for convergence: ≥3 tier-A/B      │
│                     agreeing AND disagreeing with current   │
│                     constants → opens a Finding             │
└─────────────────────────────────────────────────────────────┘
        │ pub/sub: finding.opened
        ├──────────────────────────┬──────────────────────────┐
        ▼                          ▼                          │
┌──────────────────────┐  ┌──────────────────────┐            │
│ 4a. ENGINEER         │  │ 4b. STORYTELLER      │            │
│  GitHub issue +      │  │  creative spec JSON  │            │
│  DRAFT PR:           │  │  (words only — every │            │
│   · Swift constant   │  │  number is a ref)    │            │
│   · FEATURE_STACK.md │  │        │             │            │
│   · vi_system_       │  │        ▼             │            │
│     explainer.py     │  │  5. CLAIMS GATE      │            │
│   · version bump     │  │        │             │            │
│   · backtest output  │  │        ▼             │            │
│                      │  │  deterministic       │            │
│                      │  │  renderer → MP4/PNG  │            │
└──────────────────────┘  └──────────────────────┘            │
        │                          │                          │
        └──────────┬───────────────┘                          │
                   ▼                                          │
        ┌──────────────────────────┐                          │
        │ REVIEW CONSOLE           │◄─────────────────────────┘
        │ human approve / reject   │
        │ rejection → few-shot     │
        │ memory (feedback loop)   │
        └──────────────────────────┘
```

---

## Stack (hackathon-mandated, all load-bearing)

### Gemini

| Model | Role | Why |
|---|---|---|
| `gemini-3.7-flash` | Appraiser, Synthesist, Engineer, Claims gate | Latest stable; built for complex coding + agentic multi-step execution |
| `gemini-3.5-flash-lite` | Scout triage | $0.30/$2.50 per M tokens — screening ~400 abstracts/night costs cents |

**Compliance trap, recorded:** the most capable Gemini available is `gemini-3.1-pro-preview`,
but the hackathon requires **3.5 or newer**. 3.1 < 3.5, so the Pro model is disqualifying.
Do not "upgrade" to it.

### Google Agent Framework — ADK (Python)

| ADK primitive | Used for |
|---|---|
| `SequentialAgent` | Spine: Scout → Appraise → Synthesize |
| `ParallelAgent` | Fork: Engineer ∥ Storyteller |
| `LlmAgent` + `FunctionTool` | `pubmed_search`, `europepmc_fetch`, `firestore_upsert`, `read_repo_file`, `github_open_issue`, `github_open_pr`, `run_vi_backtest`, `render_creative` |
| `before_tool_callback` | Guardrails — claims gate and draft-only enforcement run as **code**, not prompt text |

### Google Cloud

1. **Cloud Run** — two services: `provenance-agents` (ADK app, via `adk deploy cloud_run`) and `provenance-console` (review dashboard)
2. **Firestore** — `papers/`, `findings/`, `approvals/`, `rejections/`. Already synqology's production database (`users/{uid}/vitality_index/{date}`), so this is a real integration, not a bolt-on
3. **Pub/Sub** — `paper.ingested` → `paper.appraised` → `finding.opened` → `finding.approved`. Decoupled, replayable, survives a stage crashing
4. **Cloud Scheduler** — nightly 03:00 trigger
5. **Cloud Storage** — rendered MP4 / PNG creatives

**GCP project:** `sentinel-505814`

---

## The anti-hallucination contract

**Gemini writes words. Code writes numbers. Never both.**

1. **Appraiser must quote.** Every extracted claim carries a verbatim span from the fetched
   abstract. Code does a literal string match against the source text. No match → the paper
   is rejected, not "flagged." Grounding that can be asserted on in a test.
2. **Storyteller emits references, not values.** Its JSON is
   `{headline, body, chart_ref: "papers/<doi>#table2", claim_ids: [...]}`. The renderer
   resolves `chart_ref` against Firestore and draws the real points. Gemini never sees an axis.
3. **A digit in prose is a rejection** unless it maps to a `claim_id` whose stored value
   matches exactly.
4. **The merge tool does not exist.** Not "the model is instructed not to merge" — there is
   no `github_merge` in the toolset, and `before_tool_callback` hard-blocks any PR that is
   not `draft: true` on a `provenance/*` branch.
5. **Backtests are real test runs.** `run_vi_backtest` executes `VitalityIndexCalculatorTests`
   plus a cohort replay. The PR body quotes actual output, never an LLM's estimate of it.

### Claims discipline (inherited)

`marketing/meta-ads/README.md` already encodes the rule set that survived the audit behind
`synqology.io/science`. The claims gate mechanises it. Canonical example: Mandsager 2018
reports hazard ratios with **no observed upper limit** — the permitted phrasing is
"no ceiling on the benefit," never "up to 5 more years."

---

## Content output

Two formats, both rendered deterministically. Forked from the existing
`apps/synqology/marketing/meta-ads` pipeline (HTML/CSS → headless Chrome → `setFrame(p)`
frame capture → ffmpeg), which already produces reproducible 1080×1920 and 1080×1350 output
with no CSS-animation timing drift.

| Format | Spec | Reference |
|---|---|---|
| **Animated data reel** | 1080×1920, ~15s, H.264. Curve draws in against a running clock | `datakatadka` — PK-style decay animation |
| **Editorial carousel** | 1080×1350 ×4 slides. Headline + short body + one chart per slide | `timeline_longevity` — VO₂max / cardio-dose slides |

9:16 placement safety is inherited from the meta-ads README: Instagram chrome covers roughly
the top 250px and bottom 420px. Nothing that must be read enters those bands.

---

## Why it should win

- **Operationally real.** It acts on a live App Store product — real algorithm, real repo,
  real users. Most entries demo on toy data.
- **Domain-credible.** The evidence rubric is authored by a PharmD, not improvised.
- **Two modalities from one evidence spine** — code change and video, same citations. Puts
  Best Multimodal UX in play alongside the track prize.
- **Architectural discipline is demonstrable.** Guardrails are callbacks and absent tools,
  not prompt instructions. That is the difference judges are scoring at 30%.

---

## Build order

| Phase | Dates | Definition of done |
|---|---|---|
| 1 · Foundations | Aug 17–18 | `adk run scout` pulls real papers into Firestore |
| 2 · Appraise + Synthesize | Aug 19–21 | Rejection log fills; converging studies open a Finding |
| 3 · Engineer | Aug 22–24 | A real draft PR on the synq repo |
| 4 · Storyteller + renderer | Aug 25–27 | An MP4 that plays; claims gate visibly blocking |
| 5 · Console + deploy + video | Aug 28–29 | Hosted Cloud Run URL, 4-min video, submitted |

Aug 30–31 held as buffer. The deadline is never the plan.

## Risks

| Risk | Mitigation |
|---|---|
| Gemini 3.7 quota or regional availability | Verify day 1; `gemini-3.5-flash-lite` is a compliant fallback for every stage |
| Source API rate limits | PubMed 3 req/s unauthenticated, 10 with a key; Europe PMC unmetered. Nightly volume is well under both |
| No Finding converges during the demo window | Seed corpus from the last 24 months so convergence is reachable; the rejection log is compelling on its own |
| synqology repo is private, judges need public code | Provenance repo is public; synqology stays private. Reviewers spin up against a public fixture repo |
| Renderer drift from meta-ads | Fork rather than import — the hackathon repo must stand alone for reviewers |

## Open decisions

- Confirm Devpost allows a single track selection (assumed Taskmaster).
- Design aesthetic for the two creative formats — owner supplying source files.
