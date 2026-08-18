# Provenance

**An agent fleet that reads the literature, proposes algorithm changes as draft
pull requests, and produces the content that explains them — with every number
traceable to a quoted source.**

Built for the All Things Agentic Hackathon. Subject application: **synqology**,
a live iOS longevity app whose Vitality Index scores users out of 100 across
eleven weighted components.

---

## The idea

Provenance is never handed a list of research topics. It **reads the subject
application's own algorithm** — the prose specification and the Swift file the
constants actually live in — and derives its research agenda from the code.

The Vitality Index weights cardio at 16 points, scored over a 28-day window,
crediting any day with at least 20 minutes of exercise. From that, the agenda
builder produces search concepts aimed at *that rule*:

```
mvpa (Cardio) · 16pt · 28d
  RULE: 28-day window with 4-week recency weighting [0.4, 0.3, 0.2, 0.1].
        Per-week base score 0min=0, 75=50, 150=80, 300+=100, multiplied by
        day factor min(creditDays,3)/3 where a credit day requires >=20 min.
  SEARCH:
    · physical activity bout duration minimum threshold
    · weekly exercise frequency vs weekend warrior mortality
    · exercise volume vs frequency all-cause mortality
```

Not "exercise is good for you". The literature that could *overturn the
specific constant*.

Change the algorithm and the agenda changes with it — it is cached against a
digest of the source files, so editing the algorithm invalidates it
automatically. Nobody has to remember to update a topic list, which means it
cannot go stale.

**System map:** https://claude.ai/code/artifact/80430eb1-ef05-4f9c-8ec9-f858b2db956d
— the whole loop with real numbers on the arrows, and what each stage refuses.

---

## The pipeline

```
Cloud Scheduler (nightly)
      │
      ▼
  SCOUT ──── PubMed · Europe PMC, one query dialect each, DOI-first dedupe
      │      pub/sub: paper.ingested
      ▼
  TRIAGE ─── gemini-3.5-flash-lite · relevance only, one cheap question
      │
      ▼
  APPRAISER  gemini-3.7-flash · GRADE-lite tier A–D, verbatim quote per claim
      │      pub/sub: paper.appraised
      ▼
  GROUNDING  code, not a model: every quote must appear in the source
      │
      ▼
  SYNTHESIST arithmetic gate, then judgement — see "Convergence" below
      │      pub/sub: finding.opened
      ├──────────────────────┐
      ▼                      ▼
  ENGINEER              STORYTELLER
  issue + DRAFT PR      creative spec → CLAIMS GATE → deterministic renderer
      │                      │
      └──────────┬───────────┘
                 ▼
          REVIEW CONSOLE — a human approves. Nothing merges or posts itself.
```

---

## The contract: Gemini writes words, code writes numbers

Every guarantee below is enforced in code and covered by tests, not requested
in a prompt.

**1. Claims must quote, and quotes are verified.** The Appraiser returns a span
for every claim. `provenance/grounding.py` checks that span appears in the
retrieved text under a normalisation that forgives typography and nothing else.
A paraphrase fails.

**2. Numbers must appear in the span they are attached to.** A genuine quote
with an invented effect size beside it passes a quote check and fails here.
This is the check that matters:

```python
claim.quote  = "a hazard ratio of 0.82 (95% CI 0.74-0.91)"   # verbatim, real
claim.value  = 0.62                                           # invented
# -> "value 0.62 does not appear in the quoted span"
```

**3. One paper never moves the algorithm.** A Finding opens only when at least
three distinct papers challenge the same component, at least one is tier A or
B, and they come from more than one DOI registrant. The gate is pure
arithmetic and runs *before* any model is consulted.

**4. The merge tool does not exist.** Not "the model is instructed not to
merge" — there is no `github_merge` in the toolset, and a `before_tool_callback`
blocks any pull request that is not `draft: true` on a `provenance/*` branch.

**5. Rejections are recorded, with reasons.** A pipeline that silently discards
is indistinguishable from one that never looked. Every filtered paper keeps its
reason code: `not_relevant`, `no_quantitative_result`, `ungrounded_claim`,
`insufficient_convergence`, `single_source`.

---

## Stack

| Requirement | Choice |
|---|---|
| Gemini 3.5+ | `gemini-3.7-flash` (reasoning) · `gemini-3.5-flash-lite` (triage) |
| Google Agent Framework | **ADK** (`LlmAgent`, `SequentialAgent`, `ParallelAgent`, `before_tool_callback`) and the **GenAI SDK** |
| Google Cloud | **Firestore** (evidence store) · **Cloud Run** (agents + console) · **Pub/Sub** (stage events) · **Cloud Scheduler** (nightly) · **Cloud Storage** (creatives) |

> **Version trap, recorded so nobody re-introduces it:** the most capable
> Gemini available is `gemini-3.1-pro-preview`, but the hackathon requires 3.5
> or newer. 3.1 < 3.5, so the Pro model is disqualifying. Do not "upgrade" to it.

> **Serving location:** Gemini 3.5+ models are *listed* under regional endpoints
> but only answer on `global`. Pointing generation at `us-central1` returns 404
> for a model that same region reports as available.

---

## Running it

```bash
uv venv --python 3.12 .venv
VIRTUAL_ENV=.venv uv pip install -r requirements.txt
cp .env.example .env          # then fill in

gcloud auth login             # credentials are borrowed from here if ADC is unavailable

python -m provenance agenda --detail    # the algorithm, as the fleet understands it
python -m provenance sweep              # retrieve and persist new literature
python -m provenance appraise           # triage, grade, verify grounding
python -m provenance synthesise --show-gated
python -m provenance status
```

Tests:

```bash
python -m pytest tests/ -q
```

---

## Layout

```
provenance/
  agenda.py         reads the subject algorithm, derives the research agenda
  grounding.py      verbatim-quote and numeric verification (no model involved)
  llm.py            ADK model handles, credential injection, serving location
  auth.py           ADC, or a borrowed gcloud user credential
  sources/          pubmed.py · europepmc.py — one query dialect each
  agents/           scout.py · appraiser.py · synthesist.py
  store/            firestore.py — provenance_* collections
docs/plans/         design documents
tests/              grounding and convergence-gate suites
```
