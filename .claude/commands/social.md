---
description: Turn a provenance finding into motion social assets — carousel clips + reel — with every number traced to a quoted source
---

# /social

Turn a provenance Finding into publishable social assets. One invocation does
every step. `$ARGUMENTS` is the component id (e.g. `mvpa`); with none, list
components that have findings and ask which.

## The rule that outranks every other rule

**A model never supplies a figure.** `provenance/creative.py` resolves every
number from a claim that already passed grounding; the claims gate then refuses
any digit that does not trace to one. You are choosing *form*, never *value*.
If you ever find yourself typing a number into a spec, stop — pull it from the
appraisal, or drop the slide.

## Two sources, and the second one is bigger

A **Finding** exists to change the algorithm and demands convergence — several
papers pointing the same way. Of 113 appraisals in the store, exactly one has
ever cleared that bar. That bar is right for editing a constant and far too high
for saying something true on the internet.

So `/social` draws from **two** pools:

| Source | Bar | Use it for |
|---|---|---|
| **Findings** | convergence | "we're changing the app because of this" |
| **Appraisals** | Tier A/B, grounded claims | the standing content backlog (~74 papers) |

`python -m provenance content` ranks the appraisal pool: tier floor, a bonus for
studies that *challenge* the current rule, figures, reported uncertainty, sample
size, recency — then spreads the queue across components so it does not post six
weekend-warrior cohorts in a row. It suggests a motion per paper. Add
`--component mvpa` to focus, `--mark <paper_id>` once posted so it stops being
offered.

**The tier floor is not negotiable.** Tier C and D are excluded unless you pass
`--include-weak`, and even then a single weak study is a thing to have read, not
a thing to post — "one small trial suggests" is how supplement marketing works.
Whatever you post, the tier chip travels onto the asset.

## Steps

1. **Load.** Either a Finding (mirror `cmd_storyteller` in `provenance/cli.py`)
   or a ranked appraisal from `python -m provenance content`. Run the
   Storyteller to get the resolved payload + plan. If nothing survives the
   gates, say so and stop.
2. **Pick a motion per slide** from the vocabulary below. The claim's shape
   picks it — never pick for variety. Same shape twice in a set is fine.
3. **Write the spec JSON** per slide, and **save it** next to the output. The
   reel spec used to live only as `window.DEMO` inside the template, which made
   the clip unreproducible. Specs are artifacts; write them to disk.
4. **Render** through `renderer/render.mjs` (headless Chrome → PNG/ffmpeg).
   Deterministic and diffusion-free: a chart is drawn from data, by code.
5. **Verify, then show.** Screenshot frames at ~1s, mid, and final. Check every
   digit against the spec. Check the anti-patterns list. Open the output.

## Motion vocabulary

| Claim shape | `spec.motion` | Renders with |
|---|---|---|
| Dose-response across a range | *(sweep)* | `render.mjs reel spec.json out/` |
| 2–4 discrete groups | `grow` | `render.mjs clip spec.json out/` |
| No effect found | `hold` | `render.mjs clip spec.json out/` |
| A range or threshold | `narrow` | `render.mjs clip spec.json out/` |
| Copy only | `type` | `render.mjs clip spec.json out/` |

Sweep lives in `templates/reel.html` (1080×1920) because it needs a continuous
domain to sweep. The other four share `templates/motion.html` (1080×1350) — one
file, one set of chrome, one contract. A new motion is a new branch in `MOTIONS`,
never a fifth near-copy of the template.

**Grow** stagger their arrival — simultaneous bars read as a static chart that
faded in. **Hold** never bounces or settles: movement in data that did not move
is a lie. **Narrow** never closes to zero — the width that remains is the
uncertainty, and it is the honest part. **Type** is the one place accent may
touch letters, because a copy-only slide has no data colour to be confused with.

## The typography + motion contract

Learned the hard way on the step-count reel. Violating any of these produced a
visible defect.

1. **Ease OUT, never ease-in-out.** Ease-in-out spent its first second covering
   1.5% of the domain — a static-looking sliver that reads as a photo and gets
   swiped. `1 - (1-t)^2.2`, head-hold ≤ 1.5%. A real, labelled chart must be on
   screen by 1.0s.
2. **Annotations name REGIONS, not moments.** A caption that replaces another
   caption points at nothing — "past here" needs a *here*. Draw a bracket
   spanning the x-range each annotation describes, in the plot's own scale,
   directly above it, with a rule dropping at the boundary. Once revealed a
   region **persists**: the final frame carries every label at once, over the
   stretch of curve each describes. That frame is the one people screenshot.
3. **Text never wears a data colour.** `--accent` is byte-identical to
   `--band-2`. Accent belongs on marks — brackets, rules — never on letters.
   Words stay in `--ink` / `--ink-2`.
4. **The line that changes is the line that matters — size it that way.** The
   annotation carries the finding; it gets statement type (32–40px, primary
   ink), not eyebrow type (26px accent caps over tertiary ink).
5. **Reserve the height, or the chart jumps.** `min-height` on any block whose
   text swaps mid-motion. Verify by diffing the chart's y across two frames.
6. **Gate labels on width, not just height.** A band tall enough for a word can
   still be narrower than it — the sweep edge sliced "DIABETES" to "DIABETE".
   Suppress until it fits, and clamp it inside the revealed strip. A clipped
   label is worse than no label.
7. **No prose that restates the marks.** The subtitle said "share of deaths by
   cause, by daily step count" while the bands were already labelled, the axis
   already ran 0–100%, and the counter already said "steps / day". Reading it
   competed with watching. What the axis measures goes **on the axis**.

   The inverse is also a defect. When the y-axis measures something no mark can
   say on its own — a hazard ratio, an index, a share of a reference group — it
   needs a deck line under the headline, at ~36px in near-primary ink. Setting
   it 21px and muted *inside* the plot put the one line explaining what the
   graph shows in the faintest type in the frame, with a region rule crossing
   it. Test: can the label be derived from the marks? Cut it. Can it not? Then
   it belongs above the chart at reading size, not inside it at footnote size.

   Then make it belong to the CHART, not the headline. Set directly under the
   title at the same left edge in the same ink family, a deck just reads as a
   second line of headline. Close the headline block with a hairline, then set
   the deck below it and pull the plot up tight — proximity decides what a label
   is labelling. The rule also mirrors the source rule at the foot, which
   brackets the frame top and bottom.

   Finally, say what the comparison group DID, not what bucket it was. "Risk of
   dying vs the least active quarter" is the paper's quartile 1 and nobody reads
   a chart in quartiles; Q1's median was 3,553 steps, so it becomes "vs someone
   walking 3,500 steps a day". Sweep the annotations for the same tell —
   "quartile", "tertile", "referent", "adjusted" — and name the behaviour.
8. **Decide value placement once per chart, not per mark.** Testing each bar
   individually put one value inside its bar and its neighbours' outside — the
   same quantity in two different places in one chart. Test the longest bar,
   then apply that answer to all of them.
9. **One baseline for a row of labels.** Hanging each label off its own mark
   made them stagger by a few pixels, which is exactly the visual noise the
   Hold motion exists to deny.
10. **Direct-label the bands; no legend.** Label inside the band, dark type on
   bands 1–3 and white on 4–6, set via `style` (a `fill` attribute loses to the
   `svg.chart text` rule and silently paints them all grey).
11. **`??` cannot sit beside `||` unbracketed.** Puppeteer reports it only as
    "window.setSpec is not a function" — a template that fails to parse looks
    exactly like a missing function. Syntax-check the script block before
    blaming the renderer.

## Format

- **Carousel clips** — 1080×1350, the primary deliverable.
- **Reel** — 1080×1920 from the same specs.
- Instagram covers roughly the top 250px and bottom 420px of a 9:16 frame.
  Nothing that must be read goes there.
- ~12s is long for a feed; aim for the sweep to be legible by ~6s.

## Before you call it done

- Every digit on screen traces to a claim id in the spec.
- Frames at 1s / mid / final screenshotted and actually looked at — the palette
  validator checks colour, not layout.
- Checked against `dataviz` → `references/anti-patterns.md`.
- Specs written to disk alongside the assets.
- Output opened for the reader.
