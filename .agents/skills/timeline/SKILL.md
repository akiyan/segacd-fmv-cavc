---
name: timeline
description: Render and show one large, detailed whole-movie timeline PNG from a codec-analysis TSV, with canonical Req/supply/Band scales and a measured RUN scale. Use after every encoder adjustment or comparison, when the user asks for a timeline, heatmap, TSV visualization, or a visual A/B summary.
---

# Analysis Timeline

Create a consistent whole-movie diagnostic image from the exact TSV used by
the analysis overlay. The image is a comparison artifact, so preserve scales
and include the settings that explain the result.

## Workflow

1. Locate the adjustment-specific analysis TSV. If it does not exist and only
   the timeline is needed, run
   `tools/render_analysis.py profiles/PROFILE.toml --tsv-only`. Run the full
   analysis renderer only when its MP4 is also required.
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
  --sim-out /dev/shm/segacd-fmv-cavc/artifacts/SIM_ENTRY/data \
  --r2v-workload-tsv logs/PROFILE_eNN_pNN_r2v_workload.tsv \
  --label "short adjustment label" \
  --evaluation-end-frame FRAME
```

   The renderer prints the direct tmpfs PNG path and the persistent layout
   receipt under `logs/`.
5. Inspect the printed PNG path with `view_image`. Check that the full time axis, tail
   marker, category colours, four row scales, and labels are legible. Confirm
   that the fixed effective cold cap and fps-derived normal/jitter/delivery
   PrgBuf values match the sim metadata.
6. Publish the PNG as a public GitHub Gist. The helper creates a Git-backed
   public Gist so the binary PNG is preserved exactly, writes a
   content-keyed Gist receipt under `logs/`, and returns both the Gist page and
   raw PNG URL:

```sh
tools/python.sh .agents/skills/timeline/scripts/publish_gist.py \
  /dev/shm/segacd-fmv-cavc/artifacts/TIMELINE_ENTRY/STEM_timeline.png \
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
  /dev/shm/segacd-fmv-cavc/artifacts/ANALYSIS_ENTRY/STEM_analysis.mp4 \
  --timeline-receipt logs/STEM_SHA10_timeline-gist.json \
  --description-file "$ANALYSIS_DESCRIPTION"
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
