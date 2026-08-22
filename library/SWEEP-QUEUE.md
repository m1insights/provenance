# Sweep queue — reels ready to build (verified 2026-08-21)

Ranked, claims verified in the store. Recipe: `.claude/commands/social.md`
(sweep-first Load step + contracts #12–13). Engine: `render.mjs reel`, 12s.
After posting: `python -m provenance content --mark <paper_id>`.

## 1. Total movement dose — BMJ accelerometry meta-analysis — BUILT 2026-08-21
`doi:10.1136_bmj.l4570` · reel at `library/2026-08-21-mvpa-any-movement/`
("The gym was never the point."). Medians are NOT in the abstract so `--redo`
cannot ground them; x = population-percentile axis (quarter midpoints), counter
"of 100 · ranked by daily movement". Awaiting founder post → then
`python -m provenance content --mark doi:10.1136_bmj.l4570`.

## 2. Steps after 60 — Circulation harmonized meta-analysis — BUILT 2026-08-21
`doi:10.1161_circulationaha.122.061288` · reel at
`library/2026-08-21-steps-after-60/` ("After 60, a walk was never just a
walk."). Older-arm only; younger-arm null in the caption, attributed. Step
medians not in the abstract → percentile axis, counter "of 100 · ranked by
daily steps". Awaiting founder post → then
`python -m provenance content --mark doi:10.1161_circulationaha.122.061288`.

## 3. Resting heart rate — CMAJ meta-analysis
`doi:10.1503_cmaj.150535` · Tier B · n=1,246,203 · real x-values, no gap.
All-cause: <60 bpm (ref) → 60–80 = +12% (c3) → >80 = +45% (c5); CVD arm +8%/+33%
(c4, c6). Angle: "Your watch shows this number every morning" — 3-point sweep
over bpm. Note: only 3 points; flat-ish then jump — check it reads as a curve,
not two bars, before committing.

## 4. Brain age vs genes — BUILT 2026-08-22 (as the paper's LEAD reel)
`doi:10.1038_s41591-025-03798-1` · Tier B · claims c1/c2 grounded.
Reel at `library/2026-08-22-organage-brain-sweep/` ("Your brain has its own
age.", SWEEP — founder ruling 2026-08-22: sweepable reels ONLY; the grow-bars
version at `2026-08-22-organage-brain-age/` is retired with the count reel).
Axis = peer rank ("of 100 · your age, ranked by brain age"); genre model =
datakatadka SEX HORMONES BY AGE (counter sweeping an owned number). Founder ruling: the ORGAN-COUNT reel
(`2026-08-22-organage-one-number/`) is RETIRED as a post — nobody owns "a
count of aged organs" (contract #13, owned-axis rule); its ladder numbers are
caption context at most. This brain reel is the paper's lead post. Awaiting
founder post → then `python -m provenance content --mark doi:10.1038_s41591-025-03798-1`.

## 5. NEXT FROM THE ORGAN PAPER (full-text claims now grounded, 2026-08-22)
Fetched via the new `python -m provenance fulltext` lane; appraisal holds 11
grounded claims. Space these out — one organ-paper post per week:
- **Immune system** (c10/c11): "Your immune system has an age too" — youthful
  immune −42% mortality, brain+immune together −56%. The hopeful post.
- **Heart** (c3): heart testing older → +83% heart-failure risk per step of
  heart aging. Per-SD units — needs an owned-axis translation before it can
  sweep (peer-rank axis like the brain reel).
- **Brain, raw incidence** (c12): over 17 years, 4.56% of aged-brain adults
  developed Alzheimer's vs 0.35% of youthful-brain adults — 13× in raw people
  terms; caption ammo for the brain-sweep reel or its own follow-up.
- **Lung** (c5): lung aging → +39% COPD per SD. Weakest hook; hold.

## 5b. Youthful trio — same paper, carousel NOT a reel
c6–c8: youthful brain −40% / immune −42% / both −56% mortality. Three
discrete groups, no continuous axis → `grow` carousel companion. Currently
the caption flip of reel #5 — trim overlap if it becomes its own post.

## Not sweeps — don't force them
- `doi:10.1161_jaha.118.008552` (JAHA sleep, 9/10/11h): long side only —
  caption "zoom out" material for the posted sleep J-curve, not its own reel.
- `doi:10.1136_bjsports-2023-107849` (fitness umbrella, n=20.9M): high-vs-low
  endpoints across different outcomes, not one axis → `grow`, not sweep.

## Posted (mark if not yet marked)
- Sleep J-curve `doi:10.1016_j.smrv.2016.02.005` — posted 2026-08-21, 17K/4h.
  Run: `python -m provenance content --mark doi:10.1016_j.smrv.2016.02.005`
