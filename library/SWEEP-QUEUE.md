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

## 2. Steps after 60 — Circulation harmonized meta-analysis
`doi:10.1161_circulationaha.122.061288` · Tier B · n=20,152 · 6 points.
Older adults (60+): Q2/Q3/Q4 vs Q1 = −20% / −38% / −49% heart disease (c1–c3);
younger adults ~flat (c4–c6, not significant). Angle: "Steps pay off MORE after
60" — two-lane sweep or older-arm only. Same quartile-median gap as #1
(`--redo` to ground step counts per quartile).

## 3. Resting heart rate — CMAJ meta-analysis
`doi:10.1503_cmaj.150535` · Tier B · n=1,246,203 · real x-values, no gap.
All-cause: <60 bpm (ref) → 60–80 = +12% (c3) → >80 = +45% (c5); CVD arm +8%/+33%
(c4, c6). Angle: "Your watch shows this number every morning" — 3-point sweep
over bpm. Note: only 3 points; flat-ish then jump — check it reads as a curve,
not two bars, before committing.

## Not sweeps — don't force them
- `doi:10.1161_jaha.118.008552` (JAHA sleep, 9/10/11h): long side only —
  caption "zoom out" material for the posted sleep J-curve, not its own reel.
- `doi:10.1136_bjsports-2023-107849` (fitness umbrella, n=20.9M): high-vs-low
  endpoints across different outcomes, not one axis → `grow`, not sweep.

## Posted (mark if not yet marked)
- Sleep J-curve `doi:10.1016_j.smrv.2016.02.005` — posted 2026-08-21, 17K/4h.
  Run: `python -m provenance content --mark doi:10.1016_j.smrv.2016.02.005`
