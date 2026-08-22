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

## The sweep hunt — look here FIRST for a reel

The one breakout this account has (10k-steps: 84K vs a ~2K baseline) was a
**dose-response curve animated so the number arrives with the motion** — risk
falling as the dose climbs, the data changing as the reel runs. That claim
shape is rare and it is the whole game, so the pipeline hunts for it by name:

- `python -m provenance content --sweepable` — the ranked queue narrowed to
  papers carrying dose-response signals ("dose-response", "J-shaped", "per
  additional", "p for trend", graded quartiles with enough points to draw…).
  Each pick prints its `sweep signals:` line. Start every reel session here.
- The **morning briefing email flags these as "Reel-ready"** the night they are
  appraised — a sweep-shaped Tier A/B paper is worth a same-week reel while the
  study is news.
- The **content lane** (`content.*` components: coffee, sitting time, protein,
  sauna, alcohol, walking pace) sweeps universal-belief numbers *adjacent* to
  the app, not just the VI algorithm's own components — because the breakout
  attacked a number everyone has been told to hit, and most such numbers are
  not scoring components. These exist ONLY for content: the synthesist skips
  them, so they can never become a Finding or a PR. Their `current_rule` is
  the folk belief itself, so `challenges` = challenges the folk number — the
  exact open-loop headline shape the reveal test demands.

The detector reads the appraiser's grounded words, so it flags *candidates*:
an abstract that says "dose-response" may tabulate only two points. The
operator confirms, with the paper open, that enough of the curve is published
to sweep honestly — and specs only the points the paper actually reports.

## Steps

0. **Read the distribution evidence first.** Read
   `/Users/m1labs/Dev/apps/synqology/docs/growth/ig-knowledge-base.md` — at
   minimum §2 (ranking signals), §3.2–§3.3 (the animated-sweep genre: what an
   outlier reel of exactly this format looks like), §4 (hooks/captions), and
   §7 (health-content trust bar). That KB is owned by the ig-expert agent and
   is where reel performance learnings accumulate; this command chooses *form*,
   and the KB is the evidence about which forms distribute. The working recipe
   as of 2026-08-20 (§3.3): one sweep per reel, whole-reel duration ~20s,
   counter's endpoint visible early, 2–3 event annotations firing mid-sweep,
   value chips riding the line, identity-framed caption ("this is your body"),
   citation footer every frame, licensed audio added at post time.

1. **Load — sweep first.** Run `python -m provenance content --sweepable`
   BEFORE the general queue: the sweep is the only twice-proven format (see the
   replication log under Format), so a sweepable paper outranks a higher-scored
   non-sweep. A sweep needs **≥3 grounded points on ONE exposure axis** — and
   sweepable content is MADE, not just found: the appraiser extracts every
   tabulated dose-response point as its own claim (curve block in
   `provenance/agents/appraiser.py`), and `python -m provenance appraise
   --redo <paper_id>` re-runs a paper whose abstract tabulates more points than
   its stored claims. Dose-response meta-analyses on universal-number topics
   (steps, sleep hours, sitting, coffee, resting heart rate, fitness) print
   their curves in the abstract — hunt those when the pool runs dry. A named
   reference level in the abstract ("compared with 7 h") grounds the curve's
   zero point as the comparator. Otherwise: a Finding (mirror `cmd_storyteller`
   in `provenance/cli.py`) or a ranked appraisal from `python -m provenance
   content`. Run the Storyteller to get the resolved payload + plan. If nothing
   survives the gates, say so and stop.
2. **Pick a motion per slide** from the vocabulary below. The claim's shape
   picks it — never pick for variety. Same shape twice in a set is fine.
3. **Create the post folder.** Everything for this post goes in ONE folder:
   `library/YYYY-MM-DD-<component>-<slug>/` (slug = 2–4 words of the claim).
   The convention is `library/README.md`; `library/_archive/` is the old
   `renderer/out-*` sprawl — never write there, never create a new `out-*`
   sibling.
4. **Write the spec JSON** per slide into the post folder
   (`spec-<motion>.json`). The reel spec used to live only as `window.DEMO`
   inside the template, which made the clip unreproducible. Specs are
   artifacts; write them to disk.
5. **Render** through `renderer/render.mjs` with the post folder as outDir
   (headless Chrome → PNG/ffmpeg). Deterministic and diffusion-free: a chart
   is drawn from data, by code.
6. **Verify, then show.** Screenshot frames at ~1s, mid, and final into
   `frames/` inside the post folder. Check every digit against the spec. Check
   the anti-patterns list. Write the proposed caption to `caption.txt` (hook →
   study with follow-up → number → tie-back → source → hashtags, per the IG
   KB §4). **The caption's lead numbers must be THE numbers in the video,
   labeled as such** ("The numbers in this video: …"); a second endpoint from
   another study may follow, explicitly attributed ("Zoom out and the pattern
   holds for…"). The weekend-warrior caption originally led with the
   meta-analysis's 24% all-cause figure while the video showed 28%/25% heart
   disease — close enough that readers assume they should match, notice they
   don't, and "which is it?" becomes the top comment. Open the folder for the
   founder.

## Motion vocabulary

| Claim shape | `spec.motion` | Renders with |
|---|---|---|
| Dose-response across a range | *(sweep)* | `render.mjs reel spec.json out/` |
| 2–4 discrete groups | `grow` | `render.mjs clip spec.json out/` |
| No effect found | `hold` | `render.mjs clip spec.json out/` — **carousel only, never a reel** |
| ~~No effect found, on a Reel~~ | ~~`clockhold`~~ | **DO NOT USE FOR A POSTED REEL** — fails the reveal test below (v11: 1,891 views vs 84K). Route null findings to `hold` in a carousel |
| A range or threshold | `narrow` | `render.mjs clip spec.json out/` |
| Copy only | `type` | `render.mjs clip spec.json out/` |

Sweep lives in `templates/reel.html` (1080×1920) because it needs a continuous
domain to sweep. The other four share `templates/motion.html` — one file, one
set of chrome, one contract — rendered at 4:5 (`clip`) or 9:16 (`motionreel`,
where type and plot scale up automatically). A new motion is a new branch in
`MOTIONS`, never a fifth near-copy of the template.

**Every motion spec whose axis measures a reference-relative quantity (risk vs
inactive, hazard vs a quartile) MUST carry `deck`** — one plain-language line,
e.g. `"deck": "Lower heart disease risk vs staying inactive"`. It renders under
the headline at reading size behind a hairline (contract #7) and suppresses the
21px in-plot eyebrow, which is the faint-type defect the contract exists to
prevent. This is the 10k-steps frame's headline → rule → deck → chart shape.

**Grow** stagger their arrival — simultaneous bars read as a static chart that
faded in. **Hold** never bounces or settles: movement in data that did not move
is a lie. **Clockhold** is hold with an engine for full-screen Reels: the dots
land inside the first second, then a big mono counter ticks the study's
follow-up time (`spec.clock.to` — a grounded digit like any other) while the
gap refuses to open. The data still never moves; the clock is the only thing
that does, and it makes the stillness the story. Static `hold` stays for 4:5
carousel cells, where a frame does not have to carry 12 seconds alone.

> **THE REVEAL TEST — read before writing a headline or choosing a motion for
> a REEL.** *If a viewer who pauses at second one already has the answer, the
> reel has no completion mechanism and no send trigger.* Complete watches and
> reshares are two of the four outcomes Reels explicitly predicts (KB §2, T1),
> so a frame that resolves at t=0 forfeits both.
>
> This is not theory. `reel-clockhold-v11.mp4` (weekend-warrior, posted
> 2026-08-20) did **1,891 views / 3 likes at 16h**; the 10k-steps curve reel
> did **84,000**. Same engine, same style, same account, one day apart — the
> cleanest control this pipeline will ever get. **Both had an animated line
> device, so animation was never the difference** (KB §3.4).
>
> **1. The headline must OPEN a loop.** Name the belief, withhold the
> replacement; the chart supplies it.
> - `10,000 steps was never the point` → 84K. You still don't know the number.
> - `You do not need to train every day.` → 1,891. That IS the answer, whole,
>   in frame one.
>
>   Test any draft: *does a viewer who reads only the headline still have an
>   unanswered question?* If not, rewrite it. Cheapest lever in the pipeline.
>   And the headline NAMES THE TOPIC in words — "8 hours *of sleep* was never
>   the target", never bare "8 hours" (founder correction, 2026-08-21). A
>   scroller reads only the headline; an unnamed subject costs the hook its
>   meaning. Open the loop AND name the thing.
>
> **2. The animation must CARRY the data, not just move.** In 10k the line IS
> the value (`y` = risk), so its motion is new information and the big counter
> is a progress bar toward an unknown. In v11 lane mode makes `y` stop encoding
> the value (see the lane-mode comment in `motion.html`) — the lines move,
> carry nothing, and `28%`/`25%` sat printed for 14 seconds beside two 3px
> hairlines. **A race with the result pre-printed is motion, not suspense.**
>
> **3. Name a stake by ~t=0.5.** 10k had "Almost all of the drop is done by
> 5,800 steps" on screen at t=0.3 and two annotations firing during the run.
> v11's single annotation landed at p=0.93 — 13 of 14 seconds carried nothing
> new.
>
> **Consequence: `hold` and `clockhold` are the anti-format for reach and must
> not be used for a reel.** They exist to render an absence of effect honestly,
> and an honest null has, by construction, nothing to reveal — the motion is
> working as designed, which is exactly the problem. A null or equivalence
> finding is true, valuable and on-brand, and it belongs in a **carousel or the
> caption**. Reels get `sweep` — ONLY `sweep` (founder ruling 2026-08-22: the winning
> form is data RESOLVING as the reel runs; bars that arrive are not it).
> `grow` and every other motion are carousel/companion material. When a
> claim looks discrete, find the owned continuous axis behind it (peer
> rank, age, hours) and sweep that — the brain-age reel turned three
> discrete states into a curve over "of 100, your age, ranked by brain
> age". The genre model beyond our own breakouts: datakatadka's hormones-
> by-age reel — a counter sweeping a number the viewer owns (their age)
> while named curves resolve under it.
>
> **Also prefer a universal-belief topic:** attack a number everyone has been
> told to hit (10k steps, 8 glasses, 8 hours), not one that only speaks to
> people already doing the thing. KB §3.3's weakest competitor reel was
> likewise its least identity-relevant.
>
> Eliminated by the same control, so do NOT "fix" these: the late wordmark and
> the safe-zone margins are present in the 84K breakout too. The music track is
> unevidenced at every tier — never spend a post testing it.

Clockhold's storytelling layer is a story COLUMN in the dead zone between
dots and null line, and it obeys the two laws the 10k-steps reel taught:
**one entrance at a time** (nothing sits on screen before its beat — the clock
row itself fades in at its turn) and **nothing ever exits** (v5 swapped three
beats through one slot — count-up, vanish, replace — and the churn read as
confusion; the steps reel's every element lands and STAYS, so its final frame
carries the whole story). Order, each line persisting under the last:
headers stand → dots drop → `cohort` counts up and parks (`{n, label}` — the
grounded sample size as an entrance, not a time series) → `promise` poses the
question → clock ticks bottom-right → the final `clock.marks` entry answers
directly beneath the question ("7.9 years. Nobody pulled ahead.") — ONE
whole-period mark, because the paper reports one number and mid-run teasers
were churn → statement lands last and the frame holds on the complete story.
14s. The screenshot test: the last frame alone must tell the whole thing.

**`timeline: true` — the sweep form, and the default for Reels.** Time runs on
the x-axis and each group gets its own LANE — chips ride the sweep edge with a
flat trail growing behind, the winning sweep-genre look applied to
equivalence. Lanes, not a value scale: a 3-point difference is ~34px on any
honest y-scale, so the chips kiss and the frame reads as one blob. In lanes, y
encodes the GROUP, the numerals riding the chips carry the quantitative claim,
and sameness is shown by synchronized motion — two runners crossing the frame
together, neither ever ahead. (No y-anchored null line in lane mode — y
encodes nothing, so it would be a lie of geometry; the baseline is the time
axis.) Lane-start labels map header→lane once the chips move off. The mono counter
sits CENTRED under the lanes with the payoff mark directly beneath it — one
number, one place; the payoff never repeats the counter's value ("Nobody
pulled ahead.", not "7.9 years. Nobody pulled ahead."). **In timeline mode
the `promise` IS the hook — it lands right behind the group headers, before
anything else moves.** And the frame carries ONLY the story: no `cohort`, no
`statement` — sample size and the takeaway sentence are CAPTION material (the
10k reel's frame had neither). On-frame text budget: headline, deck, headers,
lane labels, values, hook, counter, payoff, source line. Nothing else. **Honesty rule: the paper reports ONE whole-period
number, so the trail is the study's AVERAGE drawn across its follow-up —
`timeline_note` ("study average, drawn across follow-up") must be on the
axis, and nothing may imply per-year measurements.**

**Promise/mark copy names the viewer's BELIEF, never the chart's group.**
"Watch for the 3+ days group to pull ahead" makes the viewer decode which dot
is which before the tension exists. "More days should win… right?" installs
the expectation in one read, and the final mark answers it in the same
register: "7.9 years. Nobody pulled ahead." Mid-marks are pure elapsed time
("2 years pass…"). Same rule as the region annotations (#7): say what people
DID or believed, not what bucket the analysis used — and item labels carry
their own units ("1–2 days a week", not "1–2 days").

**The compared groups are #2 in the reading hierarchy** — headline first, then
the groups that drive the narrative, then the numbers. So clockhold sets them
as column HEADERS ("1–2 days a week · vs · 3+ days a week") at reading size,
on screen from the first frame, with the dots dropping into their columns —
never as small tags hanging under the data marks. **Narrow** never closes to zero — the width that remains is the
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
12. **A reference-relative curve must decode itself in one glance.** The sleep
    J-curve (2026-08-21) rendered correctly and still failed a founder read —
    "I don't understand what the visual is trying to tell me" — until all three
    of these landed:
    - The deck LEADS with what "up" means, in plain words: "*Extra risk of
      dying*, compared with people who sleep 7 hours a day" — never "Risk of
      dying vs people sleeping 7 hours", where the quantity hides mid-sentence.
    - The reference point gets a visible tag — a marker label ("lowest") at the
      nadir/zero. An unlabeled dip is an invisible baseline; the viewer cannot
      know the curve touches "same risk as the comparison group".
    - Region flags carry MEANING, not place names. For a J/U-curve the
      Goldilocks frame — "TOO LITTLE · SWEET SPOT · TOO MUCH" — tells the whole
      story in one sweep; "THE LONG SIDE" names where, not what.
13. **The cold-read test: a layman must decode the frame from its text alone.**
    Reel #5 v1 (2026-08-22) failed a founder read twice over: the deck "Risk
    of dying, vs people with no organs aging early" garden-pathed as "people
    with no organs", and nothing on the frame stated the PREMISE — that each
    of your 11 organs can test older than you. When the x-axis measures
    something the viewer does not know exists, the deck must establish it, in
    the same line that names the quantity. Before rendering, read every frame
    line as a stranger: no noun phrase that parses two ways, no axis whose
    subject is off-frame. The caption cannot rescue the frame — scrollers read
    the frame.

    And the stronger form (founder ruling, 2026-08-22): **the axis must be a
    thing the viewer already owns in their head** — steps, sleep hours, their
    brain, their heart rate — never a derived statistical quantity, however
    honest. "How many of your 11 organs test old" parsed correctly after a
    rewrite and STILL failed, because nobody owns a *count of aged organs*;
    the same paper worked the moment the axis became one named organ ("how
    old your brain tests"). A fix to the wording cannot rescue a variable the
    viewer has no mental shelf for — reframe to the named thing, or drop it.
14. **Width-gate region copy like any label (#6).** Region flags run ~17px/char
    (26px caps) and details ~12px/char (25px); both must fit inside
    `x(next.at) − x(at)`. "THE SWEET SPOT" overflowed a 2-hour span twice on
    2026-08-21 before "SWEET SPOT" fit. Compute the span in pixels BEFORE
    rendering, not after frame inspection.

## Format

- **The Reel is the primary deliverable — every post ships one.** 1080×1920.
  Ruling reversed 2026-08-20: Reels ride the recommendation engine to
  non-followers (KB §2), and both breakouts we can point to — ours (§3.2) and
  the four competitor outliers (§3.3) — are 9:16 animated charts. A 4:5
  carousel harvests engagement from people already reached; it cannot do the
  reaching.
  - Sweep-shaped claim → `render.mjs reel` (the sweep IS the genre). 12s,
    pinned to the breakout (`FORMATS.reel.seconds = 12`) — replicate, don't
    drift. **Replication log:** 10k-steps 84K/24h (2026-08-19) · sleep J-curve
    **17K at 4h** (2026-08-21, vs 10k-steps' ~2K at 6h — ahead of the breakout
    at the same age). Same engine, same recipe, N=2. The recipe is the
    standing plan; every post starts by looking for its sweep.
  - Any other motion → `render.mjs motionreel` — same motion.html, padded
    into the 9:16 safe zone, named `reel-<spec>.mp4`. 10–12s.
- **Carousel clips** — 1080×1350, the companion set, from the same specs.
  Worth rendering (carousels edge Reels on ER-per-follower, KB §3) but never
  the only output.
- **Wordmark: faint, final second, video only.** The 10k-steps breakout ended
  on a 25px ink-4 "SYNQOLOGY" fading in over the last ~1.5s and distributed
  anyway — that late whisper stays on reels and clips. KB §3.1's ban covers
  lockups on stills: carousel PNGs stay unmarked. Never make the video mark
  earlier, bigger, or brighter.
- Instagram covers roughly the top 250px and bottom 420px of a 9:16 frame.
  Nothing that must be read goes there.
- ~12s is long for a feed clip; aim for any sweep to be legible by ~6s. A
  reel carries 10–20s when the motion keeps resolving (§3.3).

## Before you call it done

The 2026-08-20 weekend-warrior reel took TEN versions. Every one of these
checks is a version somebody had to ask for — run them all BEFORE showing v1:

- Every digit on screen traces to a claim id in the spec.
- **Hook by ~1s.** The promise line is on screen right after the group
  headers.
- **Timeline reels COLD-OPEN mid-motion.** The sweep is already running in
  the first frames — a complete, labelled, MOVING chart by second one (the
  10k reel's real hook). No drops, no staggers, no entrance choreography
  before the primary motion; later arrivals (hook, payoff) fade in around the
  already-moving race, and lane labels are position-gated behind the sweep
  edge, never time-gated. Entrance beats belong to column mode only.
- **One entrance at a time; nothing ever exits.** Scrub the motion: no two
  things arriving together, no element that appears then vanishes, nothing
  parked on screen before its beat.
- **Screenshot test:** the final frame ALONE tells the whole story — and holds
  ~2.5s so someone can take it.
- **Text budget:** headline, deck, headers, lane labels, values, hook,
  counter, payoff, source. Anything else (sample size, takeaway sentence)
  belongs in the caption.
- **Collision pass:** crop-check the frames where a riding element passes
  fixed text (the 25% under the promise line) — clearance, not adjacency.
- Frames at 1s / mid / final screenshotted and actually looked at — the palette
  validator checks colour, not layout.
- Checked against `dataviz` → `references/anti-patterns.md`.
- Specs written to disk alongside the assets.
- Output opened for the reader.
