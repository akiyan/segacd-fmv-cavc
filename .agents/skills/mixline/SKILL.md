---
name: mixline
description: Validate, align, combine, inspect, and publicly publish matching codec /timeline and playback /hudline PNGs on one shared whole-movie frame axis with a consolidated header. Use when the user invokes /mixline or wants encoder decisions and recorded HUD behavior compared together.
---

# Mixed Codec and HUD Timeline

Combine one matching `/timeline` and `/hudline` result. Trust their machine-
readable layout receipts, not visual guesses.

## Workflow

1. Require both direct tmpfs PNG paths and their content-keyed layout receipts
   under `logs/`. Regenerate an older timeline if its receipt is missing.
2. Run:

```sh
tools/python.sh .agents/skills/mixline/scripts/render_mixline.py \
  /dev/shm/segacd-fmv-ttrc/artifacts/TIMELINE_ENTRY/STEM_timeline.png \
  /dev/shm/segacd-fmv-ttrc/artifacts/HUDLINE_ENTRY/STEM_hudline.png \
  --timeline-layout logs/STEM_TIMELINE_SHA10_timeline-layout.json \
  --hudline-layout logs/STEM_HUDLINE_SHA10_hudline-layout.json
```

   The renderer prints the direct tmpfs mixline path and the persistent
   mixline layout receipt under `logs/`.

3. The renderer must reject mismatched frame count, fps, pixels per frame,
   plot-left coordinate, plot width, or source image hash. An explicitly
   failed incomplete HUD uses the full expected frame axis and records its
   shorter observed prefix separately. Never resize, stretch, or shift one
   graph to force a match.
4. Inspect the PNG with `view_image`. The section order must be `/timeline`,
   optional `/logvdpline`, then `/hudline`; each boundary bar must carry its
   left-aligned heading. The same frame/time gridline must have the same x
   coordinate in every panel.
5. Always publish the combined PNG to a public Gist and show it inline:

```sh
tools/python.sh .agents/skills/timeline/scripts/publish_gist.py \
  /dev/shm/segacd-fmv-ttrc/artifacts/MIXLINE_ENTRY/STEM_mixline.png \
  --description "SEGA-CD FMV mixed codec/HUD timeline: run label"
```

Report the Gist page, raw PNG URL, and clickable local image path.

## Output contract

- Consolidate both source titles and run specifications into one header at the
  top. Show descriptive gate maxima/limits for `sector_slip`,
  `control_desync`, `audio_resync`, `vblank_spill`, and
  `prgbuf_jitter_peak_kib`. Show `cd_wait_count` separately as a diagnostic
  maximum. When present, also show the `pump_gap_ticks` maximum, APPLY
  back-pressure frame count, and pattern-ready pressure maximum, minimum
  first-VBlank margin, and missed-head count. Also show the NT-start pressure
  maximum, minimum VBlank-end margin, and how many repeated `E5..EA` samples
  used the conservative later occurrence. The complete descriptive rows remain
  in the pixel-preserved hudline body. Do not retain two full, repetitive
  headers.
- Directly below the hud summary line, repeat the timeline's whole-movie
  category-totals legend (swatch, category name, EVAL-scope displayed tile
  total per `analysis_style.LEGEND_ORDER` item). Read the values, order, and
  scope string from the timeline layout receipt (`legend_totals`,
  `legend_totals_order`, `legend_totals_scope`); omit the line only when a
  pre-totals receipt lacks them.
- Preserve both source graph bodies pixel-for-pixel. Crop the duplicated
  headers. Also crop `/timeline` immediately after its final data row so its
  horizontal ticks and lower explanation are omitted; `/hudline` owns the one
  shared horizontal scale and footer.
- Put a thin boundary bar with a left-aligned heading before each graph
  section. When the HUD receipt contains the complete contiguous LOGVDP row
  block, extract those rows into a middle `/logvdpline` section. Concatenate
  the remaining pre- and post-LOGVDP HUD source ranges, in that order, under
  `/hudline`. Without LOGVDP rows, render only `/timeline` and `/hudline`.
- Consume current source images and layout receipts on every render; never
  duplicate timeline or hudline row geometry, scales, labels, or colours in
  the compositor. Source presentation changes must flow through automatically.
- Keep the common frame equation:
  `x = 220 + frame * pixels_per_frame`.
- Preserve the hexadecimal `f0xHEX` horizontal frame labels from both source
  graphs and use the same notation for the consolidated EVAL range.
- Write a content-keyed JSON under `logs/` with both source hashes, source
  receipts, shared frame geometry, and the y range of each panel.
- Treat the mixed image as diagnostic evidence. Preserve green `PASS`, yellow
  `WARNING`, and red `FAIL`; never hide or relabel a warning or failure.

## Resource

`scripts/render_mixline.py` is the canonical deterministic compositor.
