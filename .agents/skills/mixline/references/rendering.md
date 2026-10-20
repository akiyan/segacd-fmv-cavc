# Renderer contract

## Output contract

- Consolidate both source titles and run specifications into one header at the
  top. Show descriptive gate maxima/limits for `sector_slip`,
  `control_desync`, `audio_resync`, `vblank_spill`, and
  `prgbuf_jitter_peak_kib`. Show `cd_wait_count` separately as a diagnostic
  maximum. When present, also show the `pump_gap_ticks` maximum, APPLY
  back-pressure frame count, and pattern-ready pressure maximum, minimum
  first-VBlank margin, and missed-head count. Also show the NT-ready pressure
  maximum, minimum cadence-final-VBlank margin, and past-head count. The
  complete descriptive rows remain in the pixel-preserved hudline body. Do not
  retain two full, repetitive headers.
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
