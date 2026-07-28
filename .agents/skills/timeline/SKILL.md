---
name: timeline
description: Render and show one large, detailed whole-movie timeline PNG from a codec-analysis TSV, with canonical Req/supply/Band scales and a measured RUN scale. Use after every encoder adjustment or comparison, when the user asks for a timeline, heatmap, TSV visualization, or a visual A/B summary.
---

# Analysis Timeline

Create a consistent whole-movie diagnostic image from the exact TSV used by
the analysis overlay. The image is a comparison artifact, so preserve scales
and include the settings that explain the result.

## Workflow

1. Locate the adjustment-specific analysis TSV. If it does not exist, run
   `tools/render_analysis.py` for that simulation output; it writes the TSV
   before rendering frames.
2. Pass the matching profile and simulation output directory. Do not combine a
   TSV from one run with metadata from another.
3. When an intentional tail-drain rule would distort evaluation, pass its first
   frame with `--evaluation-end-frame`. The timeline still shows the complete
   movie; the excluded tail is shaded and totals show both scopes.
4. Run the bundled renderer with the locked project environment:

```sh
tools/python.sh .agents/skills/timeline/scripts/render_timeline.py \
  logs/YYYYMMDD-HHMMSS-ffffff_PROFILE_SHA10_eNN_pNN_timeline.tsv \
  --config profiles/PROFILE.toml \
  --sim-out videos/STEM/ADJUSTMENT \
  --r2v-workload-tsv logs/PROFILE_eNN_pNN_r2v_workload.tsv \
  --r2v-vblank-words 3200 \
  --r2v-vblanks-per-frame 2 \
  --label "short adjustment label" \
  --evaluation-end-frame FRAME \
  --output videos/STEM_ADJUSTMENT_timeline.png
```

5. Inspect the PNG with `view_image`. Check that the full time axis, tail
   marker, category colours, four row scales, and labels are legible. Confirm
   that the fixed effective cold cap and fps-derived normal/jitter/delivery
   PrgBuf values match the sim metadata.
6. Publish the PNG as a public GitHub Gist. The helper creates a Git-backed
   public Gist so the binary PNG is preserved exactly, writes a
   `<image>.gist.json` receipt, and returns both the Gist page and raw PNG URL:

```sh
tools/python.sh .agents/skills/timeline/scripts/publish_gist.py \
  videos/STEM_ADJUSTMENT_timeline.png \
  --description "SEGA-CD FMV codec timeline: adjustment label"
```

7. Show the image inline in the conversation on every reported adjustment.
   Also give a clickable path, but never substitute a path-only response for
   the inline image.
8. Before uploading the matching analysis video to YouTube, add the public raw
   PNG URL and Gist page URL to both the English and Japanese sections of the
   video description. Keep the links after the encoder details and before each
   language section's project link. The helper updates the local description
   idempotently and, when the video is already uploaded, synchronizes that
   description through the ordinary YouTube upload/edit credentials:

```sh
PY="$HOME/.config/youtube/venv/bin/python"
"$PY" .agents/skills/timeline/scripts/sync_youtube_description.py \
  videos/STEM_ADJUSTMENT_analysis.mp4 \
  --timeline-receipt videos/STEM_ADJUSTMENT_timeline.png.gist.json \
  --description-file videos/STEM_ADJUSTMENT_analysis_description.txt
```

For a video that has not been uploaded yet, pass `--local-only`, then use the
updated description file for the upload. Do not put the link in a YouTube
comment unless the user separately asks for a comment.

Keep the Gist public and the video unlisted unless the user asks for a
different video privacy level. Public Gist publication is an external write;
perform it only when the user requested this timeline workflow.

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
- When `--r2v-workload-tsv` is supplied, insert a 32 px `R2V` row immediately
  below `RUN`. The workload TSV must come from
  `harness/cold_cap_model/extract_frames.py` for the matching packed stream.
  Count every pattern-transfer word once, including CPU-direct words at 1x,
  add one first-word repair for every DMA-backed run, the complete 64x28 H40
  name-table DMA (which already contains the DEBUG HUD), and 64 CRAM words on
  palette-switch frames. Frame 0 remains untimed. The row scale is
  `--r2v-vblank-words * --r2v-vblanks-per-frame`; draw over-budget frames in
  the canonical over-limit colour. VDP setup-register writes and the reg2 flip
  are control operations rather than VDP-memory payload, so they are not R2V
  words. This row is an analysis-only budget hypothesis; it must not steer
  encoder or player work.
- Show explicit vertical-axis ticks and horizontal guides at zero, half-scale,
  and full-scale on Req and Supply. Show only zero and full-scale on the
  compact RUN, R2V, DIC and Band rows. Put the unit below the Req and Supply
  headings; the compact RUN, R2V, DIC and Band headings have no unit
  subheading.
  Req uses cells and Supply uses patterns. R2V uses assumed VDP transfer words.
  Band's axis remains a percentage of each frame's physical slot.
- The header legend lists every analysis legend category
  (`analysis_style.LEGEND_ORDER`) with its whole-movie EVAL-scope displayed
  tile total, mirroring the analysis overlay's category legend as one
  swatch-labelled line. The scope prefix states the exact EVAL frame range.
  The totals, their order, and the scope string are written to the layout
  receipt (`legend_totals`, `legend_totals_order`, `legend_totals_scope`) so
  `/mixline` can repeat the same line without re-reading the TSV.
- Segment boundaries, five-second labels, hexadecimal `f0xHEX` frame labels,
  exact frame-per-pixel mapping, and a clearly shaded excluded tail when
  requested.

Use at least two pixels per frame when practical. Req, Supply, and Band retain
their fixed comparison scales. RUN intentionally uses the current TSV's timed
maximum so its fragmentation remains legible.

Write a `<output>.json` layout receipt with the input hashes, frame mapping,
row geometry, and evaluation boundary. `/mixline` must consume this receipt
instead of inferring alignment from image dimensions.

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
  frames, and repeated same-cell streaks separately.
- Frame 0 is boot construction. Exclude it from timed totals.

## Resource

`scripts/render_timeline.py` is the canonical deterministic renderer. Update
and test that script instead of writing one-off plotting snippets. Category,
physical-source, status-bar, and timeline colours come from
`tools/analysis_style.py`; never duplicate those semantic colour values or
category-border styles in this renderer.
