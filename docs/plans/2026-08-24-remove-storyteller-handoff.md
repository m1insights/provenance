# Handoff: remove the Storyteller, make the docs say what provenance actually does

Repo: /Users/m1labs/Dev/provenance (branch main). Python: `.venv/bin/python`. Tests: `.venv/bin/python -m pytest` (181 pass today).
Do NOT commit until asked. Do NOT touch `renderer/render.mjs`, `renderer/templates/reel.html`, `renderer/templates/motion.html`, `library/` except for removing the obsolete `slide-1.png` line from `library/README.md`, `provenance/content*.py`, or `provenance/grounding.py` — that is the process that works.

## Ground truth (verified 2026-08-24)

What provenance DOES for the sweep reels that are performing on Instagram:
1. Finds papers — nightly PubMed / Europe PMC sweep against the agenda (VI components + `content.*` folk-belief lane in `provenance/content_agenda.py`).
2. Appraises with Gemini — tier A–D, one verbatim quote per claim, every tabulated dose-response point as its own claim (`provenance/agents/appraiser.py`).
3. Verifies grounding IN CODE — quote must appear in the source (abstract or PMC full text via `fulltext --pmcid`); the number must sit inside the quote (`provenance/grounding.py`).
4. Ranks for reel-ability — `python -m provenance content --sweepable` (dose-response detector in `provenance/content.py`); morning email flags "Reel-ready" (`provenance/notify.py`); `content --mark <paper_id>` records what was posted.
5. Keeps the evidence record — every `library/YYYY-MM-DD-*/spec-*.json` carries a `_provenance` block mapping each on-screen digit to a claim id + verbatim quote.

What provenance does NOT do (and never did in practice):
- The Gemini **Storyteller** agent (`provenance/agents/storyteller.py`, `cmd_storyteller` in `provenance/cli.py`) never produced a reel. It is Finding-gated (one Finding ever) and `--render` only calls the `carousel` mode. Every reel spec, motion choice, copy and caption is written by a human + Claude Code session via `.claude/commands/social.md`; `renderer/render.mjs` (headless Chrome → ffmpeg) is repo code but human-operated.
- The four gates in `provenance/creative.py` (claims / language / structure / readability) run only on the Storyteller path. For reels, digit integrity = `grounding.verify` on the claims + the `_provenance` block — not an automated gate on the spec.

The founder is happy with this process. Goal: delete the dead Storyteller branch and make every doc describe the real loop. ~1.5 h total.

## Phase 1 — delete the Storyteller branch (code) ~30 min

1. Delete `provenance/agents/storyteller.py`.
2. `provenance/cli.py`: remove `cmd_storyteller` (lines ~339–396) and its parser block (`story = sub.add_parser("storyteller", …)` ~712–716). Remove the now-unused `subprocess`/`Path` imports if they were only used there.
3. Delete `provenance/creative.py` and `tests/test_claims_gate.py` (creative.py is imported ONLY by storyteller.py and that test — verified with grep). If you prefer to keep the language gate as a future spec-linter, see "Later" — but default is delete.
4. `provenance/guardrails/callbacks.py`: remove `require_grounded_numbers` (line ~91; docstring says "Used by the Storyteller"; grep shows no other caller). Keep `enforce_draft_only` — the Engineer uses it. Remove any matching test in `tests/test_guardrails.py`.
5. `.claude/commands/social.md` step 1: delete the sentence "Otherwise: a Finding (mirror `cmd_storyteller` in `provenance/cli.py`) … Run the Storyteller to get the resolved payload + plan. If nothing survives the gates, say so and stop." Replace with: "Otherwise: a ranked appraisal from `python -m provenance content`." Also delete the "A model never supplies a figure" paragraph's reference to `provenance/creative.py` — rewrite as: "`provenance/grounding.py` has already verified every claim's quote and value; you copy the value from the claim and record claim id + quote in the spec's `_provenance` block. If you ever find yourself typing a number that is not in a claim, stop."
6. `library/README.md`: drop `slide-1.png … # static carousel slides, if any` from the folder layout.
7. Run `.venv/bin/python -m pytest` — expect the total to drop by the deleted test file's count, zero failures. Run `grep -rni storyteller --exclude-dir=node_modules --exclude-dir=.venv --exclude-dir=_archive .` — only `docs/plans/*` history files may still mention it.

## Phase 2 — docs that overclaim ~45 min

Replace "the fleet writes/renders social content" with the honest, stronger line:
> **Gemini reads and grounds the science; code verifies every number; a human-in-the-loop content session turns grounded claims into deterministic charts. Nothing on screen was written by a model without a verbatim source.**

Per file:
- `README.md` lines ~60–68 (pipeline diagram): remove the STORYTELLER column. Replace with a CONTENT box under GROUNDING: `CONTENT ── ranked pool · sweep detector · "Reel-ready" email · --mark` → `/social (human + Claude Code) → renderer/render.mjs (HTML → headless Chrome → ffmpeg) → library/`. Keep the ENGINEER column as is. Also scan the README for any "four gates"/"Storyteller" prose and replace with the honest line above.
- `docs/architecture.md` lines ~39–52 (mermaid): delete STORY and GATES nodes; RENDER stays but is fed by a "Content queue → /social session (human)" node, and its output goes to `library/`, NOT to the review console (the console approves PRs only). Line ~271 "4 rendered slides + 1 reel" → "1 reel per post in library/". Search the rest of the file for Storyteller/gates prose and fix.
- `docs/devpost-submission.md` (this is the Google submission text):
  - Step 7 (line ~61) "Writes the social content from the same evidence, through four gates." → "Ranks the appraised papers for content and flags the ones whose data can be *shown* — dose-response curves that sweep. A human content session turns those grounded claims into deterministic charts; every digit on screen traces to a verified quote."
  - Step 8 "Nothing posts." — keep; it is true.
  - Paragraph at ~89 "Creatives are rendered deterministically…" — keep the deterministic/no-diffusion sentences (true), but add: "The renderer is operated by a person, not by the fleet."
  - Section "The design decision everything rests on" (~line 95+): rewrite "The Storyteller's output schema has no numeric field…" to the grounding.py contract instead: quotes verified against source, numbers verified inside the quote, `_provenance` block per spec. Delete the four-gates table or reduce it to the one gate that is real in code: grounding (quote + value).
  - Anywhere it says the console approves creatives → it approves pull requests.
- `docs/video-script.md` lines ~129–150: the demo beat "run the Storyteller live" is dead. Replace with `python -m provenance content --sweepable` on screen, then open a `library/*/spec-sweep.json` `_provenance` block, then play the reel. Line 150 "the four slides and the reel" → "the reel".
- `docs/system-map.html`, `docs/recording-runbook.html`: grep "Storyteller" and apply the same substitution (content queue → human /social session → renderer). `docs/provenance-flow.html` (untracked) already says "Storyteller-to-reel is not fully connected" — update it to the final wording so the three HTML docs agree.
- `console/main.py` docstring line 5: "Every draft pull request and every creative waits for an explicit approval" → "Every draft pull request waits for an explicit approval." Check `console/` for a creatives view; delete it if one exists (grep found none).
- `docs/design-brief.md`: keep (it is the renderer's design contract, still true), but remove any line saying real values are injected by the Storyteller — values come from the spec written in /social.
- `docs/plans/2026-08-17-provenance-design.md`: historical — leave, or add a one-line note at top: "Storyteller removed 2026-08-24; content is human-in-the-loop via /social."

## Phase 3 — verify ~10 min
1. `.venv/bin/python -m pytest` green.
2. `.venv/bin/python -m provenance content --sweepable` still runs.
3. `cd renderer && node render.mjs reel ../library/2026-08-23-income-rich-live-longer/spec-sweep.json /tmp/reelcheck` still renders (proves the working renderer remains intact without editing it).
4. `grep -rni "storyteller\|four gates" --exclude-dir=node_modules --exclude-dir=.venv --exclude-dir=_archive --exclude-dir=.git .` → only docs/plans history.
5. Report the diff summary; wait for the founder before committing.

## Later (optional, not now)
- Leave the harmless, self-contained carousel path in `renderer/render.mjs` and `renderer/templates/carousel.html`. Removing it buys nothing and risks the working reel path; reconsider only as a separately verified cleanup.
- If you want the "claims gate" to be real for reels: a tiny `python -m provenance lint-spec library/<post>/spec-*.json` that checks every `_provenance.claims[].value_on_screen` digit appears in the stored claim's quote (reuse `grounding.check_claim`). That would let the Devpost text say "an automated gate re-checks every spec" truthfully. ~1 h.
