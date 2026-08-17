# Design brief — Provenance research creatives

## What this is for

An agent pipeline reads new health literature, decides whether it should change
synqology's Vitality Index, and produces social content explaining the finding.
The content is **rendered deterministically**: HTML/CSS → headless Chrome →
frame capture → ffmpeg. There is no design tool in the loop and no image model
— the HTML you write *is* the final artwork, pixel for pixel.

The existing brand is settled and must not be redesigned. Inherit it from
`apps/synqology/marketing/meta-ads/ad.css`:

```css
--stage:  #0A0C0E;   /* background */
--lift:   #12161A;   /* raised surface */
--ink:    #F5F7F9;   /* primary text */
--accent: #5AC8E8;   /* the ONLY accent */
--line:   rgba(245, 247, 249, .10);
--display: -apple-system, BlinkMacSystemFont, "SF Pro Display", …;
```

House rules already in force: hierarchy by **opacity, never by hue**. Never
red/amber/green — good and bad are expressed as opacity or weight. One accent
colour only.

## Hard constraints

1. **Self-contained.** One `.html` file per deliverable, all CSS inline, no
   external fonts, no CDN, no network requests of any kind. Headless Chrome
   renders offline; anything external renders as a blank box.
2. **Exact canvas.** Set the body to exactly the stated pixel size. No
   responsive behaviour — the capture is a fixed viewport.
3. **Animation via one hook.** Expose `window.setFrame(p)` where `p` runs 0→1.
   Calling it must fully determine what is on screen. No CSS animations, no
   transitions, no `requestAnimationFrame` — frames are captured one at a time
   and CSS timing drifts between them.
4. **Dummy data inline**, clearly marked. Real values are injected at render
   time from verified research records.
5. **9:16 safe zones.** Instagram chrome covers roughly the **top 250px** and
   **bottom 420px**. Nothing that must be read may enter those bands.

---

## Deliverable 1 — `chart.css` (most important)

A stylesheet for **data charts inside the brand**. This does not exist yet
anywhere in the codebase and it is the thing the whole format rests on.

Specify, as CSS custom properties plus classes:

- **Axes**: line weight, colour, tick length, whether ticks sit inside or out.
- **Gridlines**: present or absent; if present, opacity.
- **Series**: 1–5 simultaneous lines. Because hue cannot carry meaning here,
  differentiate by **weight, opacity, and dash pattern**. Give an explicit
  ordered list: series 1 is the emphasis (full accent, heaviest), series 2–5
  recede. State what happens at 5 series.
- **Endpoint markers**: the reference reels label each line at its right edge
  with a dot plus a value. Define dot size, label offset, and collision
  behaviour when two endpoints land within ~20px.
- **Axis labels and units**: size, weight, opacity, capitalisation.
- **Annotation**: a vertical marker line with a caption (e.g. "BEDTIME"),
  used to mark a threshold on the x-axis.
- **Running counter**: large numeric readout, bottom-right, that counts up
  during animation (`23 min` → `24 h`). Tabular figures, so digits do not
  jitter as the number changes.

## Deliverable 2 — `reel.html`, 1080 × 1920

A vertical animated research clip. One chart is the subject; the copy frames it.

Regions, top to bottom:
- **Kicker** — one short line, e.g. `NEW EVIDENCE · CARDIO`.
- **Headline** — 2–3 lines, the finding in plain words. Largest type on screen.
- **Chart** — the subject. Occupies the middle band, below the fold of the
  top safe zone.
- **Running counter** — bottom-right of the chart area.
- **Source line** — the citation: `Xu et al., 2025 · Ann Intern Med · n=51,650`.
  This is a trust signal and must be legible, not a footnote whisper.
- **Wordmark** — enters late (~85% through), never sits on screen throughout.

`setFrame(p)` should: draw the chart lines in progressively, advance the
counter, and bring the wordmark in at the end. Get something moving inside the
first second — a static opening loses the viewer.

## Deliverable 3 — `carousel.html`, 1080 × 1350

Four slides, one per `<section class="slide">`, cream or dark — your call, but
pick one and commit. The reference look is editorial: generous whitespace,
a serif or high-contrast display headline, a short body paragraph, and **one
chart per slide**.

Per slide:
- **Slide index** — `2/4`, small, top-right.
- **Headline** — one clear claim.
- **Body** — 2–4 lines maximum.
- **Chart** — smaller than the reel's; may be a single line, a range bar, or a
  dot plot.
- **Source line** — same treatment as the reel.

Static only; no `setFrame` needed.

## Deliverable 4 — `source-line.md` (short)

One page defining how a citation is rendered anywhere it appears: author, year,
journal, sample size, and evidence tier. Include the degraded forms — no
sample size available, a preprint, a meta-analysis of many studies.

Every number on these creatives traces to a quoted sentence in a real abstract.
The citation treatment is the visible half of that guarantee, so it should look
deliberate rather than apologetic.

---

## What NOT to send

- Figma files, Sketch files, PNG comps, or a PDF style guide. None of these can
  be rendered. HTML and CSS only.
- A new colour palette or logo. The brand is settled.
- Font files, unless something beyond the system stack is genuinely needed —
  and then as base64 `@font-face`, embedded in the HTML.
- Icon sets. These layouts are type and data.

## How to check it before sending

Open each `.html` directly in Chrome. If it looks right at the stated pixel
size with the network disabled, it will render correctly in the pipeline. For
`reel.html`, call `setFrame(0)`, `setFrame(0.5)`, `setFrame(1)` in the console
and confirm each produces a complete, sensible frame.
