# Brief for the Devpost-description session: what is changing in provenance today, and what is true

Repo: /Users/m1labs/Dev/provenance. Another Codex session is, right now, deleting the Storyteller agent and rewriting the repo docs. Do NOT edit `README.md`, `docs/architecture.md`, `docs/devpost-submission.md`, `docs/video-script.md`, `docs/*.html`, `console/main.py`, or `.claude/commands/social.md` — that session owns them. Your job is the Devpost website text (description, "how we built it", tagline, etc.). Write it from the facts below, not from the current `docs/devpost-submission.md`, which still overclaims until that session finishes.

## The one-line change
Old story (wrong): "Gemini agents write and render the social content through four gates."
New story (true, and stronger): **Gemini reads and grounds the science; code verifies every number; a human-in-the-loop content session turns grounded claims into deterministic charts. Nothing on screen was written by a model without a verbatim source.**

## What is being removed from the codebase (do not mention any of it)
- The **Storyteller** agent (`provenance/agents/storyteller.py`) and `python -m provenance storyteller`.
- The **"four gates"** on creative copy (claims / language / structure / readability in `provenance/creative.py`) and their tests.
- The Storyteller-only guardrail `require_grounded_numbers`.
- Any claim that the review console approves "creatives" — it approves **pull requests** only.
- Any claim that the fleet renders 1080×1350 carousels / static slides. No carousel was ever posted.

## What provenance actually does (verified 2026-08-24)
1. **Scout** — nightly PubMed + Europe PMC sweep against an agenda derived from the real scoring algorithm (synqology's Vitality Index components) plus a **content lane** of folk-belief numbers (income, coffee, steps, sleep hours, resting heart rate…). DOI-first dedupe.
2. **Triage** — Gemini 3.5 Flash-Lite, relevance only.
3. **Appraise** — Gemini 3.7 Flash: GRADE-lite tier A–D, design, n, follow-up, and **one verbatim quote per claim**, including every tabulated dose-response point as its own claim. Full text is pulled from PubMed Central when available, so quotes ground against the paper, not just the abstract.
4. **Grounding, in code** (`provenance/grounding.py`) — the quote must appear in the retrieved text (typographic normalisation only; a paraphrase fails), and the number attached to the claim must appear **inside** the quoted span. This is the guarantee behind every digit on screen.
5. **Convergence gate → Engineer** — a Finding opens only when ≥3 distinct papers, ≥1 tier A/B, >1 DOI registrant challenge the same component; the Engineer opens a **draft** PR against the live repo (there is no merge tool; a callback blocks non-draft PRs). Unchanged — keep describing this.
6. **Content queue** — `python -m provenance content --sweepable` ranks tier-A/B appraisals and detects **sweepable** claims (dose-response, J-shaped, per-additional-unit, graded quartiles). The morning briefing email flags them "Reel-ready". `content --mark` records what was posted.
7. **Human content session** — a person + Claude Code (`/social`) choose the angle, write a JSON spec whose every number is copied from a grounded claim, and record a `_provenance` block (claim id + verbatim quote per on-screen digit) inside the spec.
8. **Deterministic renderer** — `renderer/render.mjs`: HTML/CSS → headless Chrome, frame-by-frame → ffmpeg. 12 s, 1080×1920, 30 fps. No image model touches it. Operated by the person, not the fleet.
9. **Evidence record** — `library/YYYY-MM-DD-<component>-<slug>/` holds spec + reel + caption + verification frames. 12 post folders exist as of today.
10. **Nothing posts itself.** Audio and posting are done by the founder.

## Performance facts you may cite (from the repo's own notes; say "one reel", not "reels average")
- One sweep reel reached a large multiple of the account's baseline views.
- A later reel that broke the open-loop headline rule did ~1.9K — the format, not the topic, is the lever; the queue now hunts sweep-shaped claims by name.
- Latest build (2026-08-23): "The rich live longer. By how much?" — two-line race, men vs women, expected age at death at 40 by income rank, Chetty et al. 2016 JAMA, 1.4 billion person-years, 15 grounded claims, every digit quote-verified.

## Stack (unchanged, still true)
Gemini 3.7 Flash (appraise, synthesise, engineer), Gemini 3.5 Flash-Lite (triage), ADK (`LlmAgent` per role, `FunctionTool` read-only repo navigation, `before_tool_callback` guardrails), GenAI SDK structured extraction, Vertex AI (service-account credential, no API keys), Firestore (papers, appraisals, rejections, findings, decisions), Cloud Run (console + nightly job), Cloud Scheduler 03:00, Secret Manager. Renderer: Node + Puppeteer + ffmpeg, local only — not in the cloud image.

## Words to avoid
"Storyteller", "four gates", "the fleet writes the social content", "auto-posts", "carousel", "1080×1350", "creatives await approval in the console".
