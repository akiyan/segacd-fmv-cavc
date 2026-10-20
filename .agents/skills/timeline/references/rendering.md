# Renderer contract

## Required content

Keep these parts in every image:

- The canonical five whole-movie rows, using the analysis colours and fixed
  scales: Req categories; combined Wrd remaining at the bottom of Supply with
  physical Prg above it; physical
  cold-run count scaled to the timed RUN maximum actually present in the TSV;
  the timeline-only DIC row showing tiles served from DicBuf per frame
  (total hits, not unique entries) scaled to the timed maximum actually
  present in the TSV; and useful BODY delivery split into Raw payload, Prg
  charge, and control versus physical slot bytes. Raw is the bottom Band
  segment, matching its leftmost position in the status bar. State above the
  timeline that Prg limits are constructed from the physical sector envelope
  before image decisions and that no reactive local-cap feedback is used.
  The DIC row exists only in this enlarged timeline; the analysis overlay
  does not gain a matching meter.
  Keep the Req row at the fixed 347 px height; this is also the upper panel
  height used by `/mixline`.
  Keep Supply at 60 px and RUN, DIC and Band at 32 px so these secondary rows
  do not dominate the image.
- Always insert a 32 px `R2V` row immediately below `RUN`, using the exact
  component columns in the analysis TSV. Count every pattern-transfer word
  once, add one first-word repair for every DMA-backed run, add the
  mode/grid/cadence-specific name-table and DEBUG HUD words, and add 64 CRAM
  words on palette-switch frames. Frame 0 remains untimed. Set the row maximum
  to the largest calculated total among timed frames. VDP setup-register writes
  are control operations rather than VDP-memory payload.
  `--r2v-workload-tsv` accepts a matching packed-stream extraction from
  `harness/cold_cap_model/extract_frames.py` as an independent cross-check.
  This trace must not steer encoder or player work.
- Show explicit vertical-axis ticks and horizontal guides at zero, half-scale,
  and full-scale on Req and Supply. Show only zero and full-scale on the
  compact RUN, R2V, DIC and Band rows. Put the unit below the Req and Supply
  headings; the compact RUN, R2V, DIC and Band headings have no unit
  subheading.
  Req uses cells and Supply uses patterns. R2V uses calculated VDP-memory
  transfer words.
  Band's axis remains a percentage of each frame's physical slot.
- Draw the configured `cold_cap_tiles` as a yellow horizontal guide across
  the REQ row, mapped to the same cell scale, and add its exact value as a
  vertical-axis tick. This is the per-frame cold-update ceiling, not a
  physical buffer level.
- The header legend lists every analysis legend category
  (`analysis_style.LEGEND_ORDER`) with its whole-movie EVAL-scope displayed
  tile total, mirroring the analysis overlay's category legend as one
  swatch-labelled line. Like the overlay, `Scrl` (green chevron swatch)
  appears only for a movie with an adopted hardware-scroll window and is
  omitted otherwise. The scope prefix states the exact EVAL frame range.
  The totals, their order, and the scope string are written to the layout
  receipt (`legend_totals`, `legend_totals_order`, `legend_totals_scope`) so
  `/mixline` can repeat the same line without re-reading the TSV.
- Segment boundaries, five-second labels, hexadecimal `f0xHEX` frame labels,
  exact frame-per-pixel mapping, and a clearly shaded excluded tail when
  requested.

Use at least two pixels per frame when practical. Req, Supply, and Band retain
their fixed comparison scales. RUN intentionally uses the current TSV's timed
maximum so its fragmentation remains legible.

Write a content-keyed layout receipt under `logs/` with the input hashes, frame
mapping, row geometry, and evaluation boundary. `/mixline` must consume this
receipt instead of inferring alignment from image dimensions.

## Interpretation safeguards

- `Prg` in the supply row is physical PrgBuf occupancy. It is not the virtual
  whole-movie quality allowance.
- `quality allowance` is encoder-only accounting and does not appear in the
  physical supply stack.
- `Buf` is not a physical meter. Report exact Prg/Wr/Dic sources instead.
- Run consolidation is diagnostic opportunity, not a promise that every saved
  32B could become one useful exact tile; changed residency and run grouping
  can alter the result.
- Do not treat raw Miss-frame or tile-frame totals as direct visual loss.
  Isolated one-frame Miss cells at 30 fps may be imperceptible and are often
  rescued immediately. Flag large simultaneous areas, consecutive any-Miss
  frames, and repeated same-cell streaks separately. Inside an adopted scroll
  window unsupplied wants report as `Scrl`, not `Miss`, so Miss totals are
  not directly comparable across scroll and non-scroll segments.
- Frame 0 is boot construction. Exclude it from timed totals.

## Resource

`scripts/render_timeline.py` is the canonical deterministic renderer. Update
and test that script instead of writing one-off plotting snippets. Category,
physical-source, status-bar, and timeline colours come from
`tools/analysis_style.py`; never duplicate those semantic colour values or
category-border styles in this renderer.
