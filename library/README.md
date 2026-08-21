# library/ — every finished social asset lives here

One folder per post, named `YYYY-MM-DD-<component>-<slug>`:

```
library/
  2026-08-20-mvpa-weekend-warrior/
    spec-sweep.json      # one spec per rendered asset — the reproducibility artifact
    reel.mp4             # 1080×1920
    grow.mp4             # 1080×1350 carousel clips, named by motion
    slide-1.png …        # static carousel slides, if any
    caption.txt          # the caption as posted (hook → study+follow-up → number → tie-back → source → hashtags)
    frames/              # 1s / mid / final verification screenshots
  _archive/              # pre-convention dev renders (out, out-batch, out-clip-*, out-reel-*)
```

Rules:

- **`/social` writes here and nowhere else.** No more `renderer/out-*` siblings —
  that sprawl is what `_archive/` is.
- The folder is complete when it holds spec(s) + render(s) + `caption.txt` +
  `frames/`. A render without its spec is unreproducible; a post without its
  caption is unrecorded.
- Date = render date. Component = the provenance component id (`mvpa`, `sleep`,
  …). Slug = 2–4 words of the claim.
- After posting, mark the paper so it leaves the queue:
  `python -m provenance content --mark <paper_id>`.
- Media is gitignored; specs, captions, and this README are tracked.
