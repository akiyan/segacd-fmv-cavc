# Renderer contract

## Image contract

- Frame axis: `x = 220 + frame * pixels_per_frame`.
- First row: derived displayed VBlanks per content frame. Frame 0 and the
  terminal frame are unknown. The authoritative cadence is four VBlanks at
  15 fps, repeating 2/3 VBlanks at 24 fps, and two VBlanks at 30 fps;
  unqualified delivery-paced rates have no guide. Each qualified frame is
  checked against its exact phase. Observations in the first/last two content
  frames at 15 fps, three at 24 fps, and four at 30 fps stay plotted as
  diagnostics but do not raise ALERT.
  Periodic 24 fps catch-up remains plotted phase-by-phase: both a late target
  and a compensating two-VBlank long phase are warnings, while the complete
  histogram shows whether the long-term clock recovered.
- The next two rows are derived `pattern_dma_ready_pressure` and
  `name_table_dma_ready_pressure`. They are diagnostic-only and sit directly
  below VBLANK. Pattern ready is sampled immediately before Main waits for the
  first fresh blank head; it is not the post-wait DMA trigger. Ready pressure
  measures lateness: visible scanlines `00..DF` map directly to pressure
  `00..DF`. A blank-phase sample within one complete blank of the preceding
  flip is identified with `pass2_delay_q4` and clamps to zero because it
  precedes the active raster leading to PT VBlank 1. `E0` otherwise is the
  zero-margin first target head, and a later blank value maps to the `0x100`
  missed-head sentinel. A frame with no cold run has no pressure point; a real
  ready event on scanline 0 is pressure zero. This saturation avoids inventing
  an order for the NTSC V-counter's repeated `E5..EA` values.

  NT ready is sampled before the cadence-final VBlank wait. Its pressure
  targets the VBlank head that carries the single-table DMA: VBlank 4 at
  15 fps, alternating VBlank 2/3 at 24 fps, and VBlank 2 at 30 fps. Use
  `transfer_vblanks` to identify the opened
  pattern budget. Readiness before the final active raster clamps to zero;
  within that raster, `00..DF` maps directly to pressure. If PT splits into the
  target budget, NT can begin only after PT2, so a target-blank sample retains
  its physical `E0..FF` pressure. A visible sample after that budget opens, or
  a later PT budget, maps to the `0x100` escaped-target-blank sentinel. A blank
  sample before the target belongs to the preceding budget and clamps to zero,
  so the repeated `E5..EA` range is never ordered speculatively. Draw an orange
  `E0` guide and colour values after it red. Each row uses three times the
  standard row height so small phase differences remain visible in the whole-movie image.
  Plot each frame as an unconnected point; do not fill bars or connect points.
- Gate rows, in descriptive order:
  `sector_slip`, `control_desync`, `audio_resync`, `vblank_spill`,
  `prgbuf_jitter_peak_kib`.
- Diagnostic rows when present:
  `pump_gap_ticks`, `msf_gap_recoveries`, `apply_backpressure`,
  `reader_ahead_frames`, `reader_slot_sector`, `transfer_vblanks`,
  `transfer_end_vcounter`, `cd_wait_count`, `audio_lead_256b`,
  `sub_wait_scanlines`, `adpcm_decode_units`, `transfer_ticks`, `cold_runs`,
  `flip_vcounter`, `first_share_exit_vcounter`,
  `pattern_dma_ready_pressure` (derived from
  `pattern_dma_ready_vcounter` + `cold_runs` + `pass2_delay_q4`),
  `name_table_dma_ready_pressure` (derived from
  `name_table_dma_ready_vcounter` + `transfer_vblanks` + cadence), and
  `pass2_delay_q4`.
- The palette segment is a switch label and vertical boundary, not a separate
  value row.
- Frame 0 keeps its horizontal cell for alignment but contributes to no bar,
  maximum, statistic, event, or scale.
- Preserve native units and hexadecimal axis labels.
- Gate limits and both ready-pressure `E0` deadlines are orange. The normal
  cadence guide is green; the normal jitter interval is yellow.
- The receipt records row geometry and plot style, hashes, expected/observed
  frames, gate limits, descriptive diagnostic maxima, statistics, and
  recording identity.

## Gate interpretation

Schema 16 gate fields are:

```text
sector_slip control_desync audio_resync vblank_spill
prgbuf_jitter_peak_kib
```

`vblank_spill` is warning-only. The other four fields fail when they exceed
their limits. Fixed-cadence `transfer_vblanks` above the cadence interval and
derived visible-duration misses outside the cadence edge exception are also
warnings. The edge exception affects only the derived display-duration alert;
it does not waive gate fields or `transfer_vblanks`. `cd_wait_count`,
`adpcm_decode_units`, `pump_gap_ticks`, APPLY back-pressure, reader lead, and
transfer phases are diagnostic.

Always preserve minimum, mean, median, maximum, and sample count for
`cd_wait_count` and `adpcm_decode_units`; do the same for `pump_gap_ticks` when
present. Report APPLY back-pressure frame count and reader/transfer maxima.

## Resource

`scripts/render_hudline.py` is the canonical renderer.
`scripts/report_overages.py` is the canonical event reporter. Update and test
them rather than creating one-off plots.
