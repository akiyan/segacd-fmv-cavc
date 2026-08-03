# 24fps playback divergence harness

Tools that compare a DEBUG lossless recording against the sim's own expected
display, frame by frame, so playback corruption that the HUD gate cannot see
(wrong tile content with clean control flow) becomes measurable.

## Scripts

- `scan_divergence.py DECISIONS.pkl HUD.tsv LOSSLESS.mkv [--step N | --frames ...]`
  Replays the sim decision log into per-frame display images, extracts each
  sampled movie frame from the recording via its HUD-TSV capture index, and
  prints mean cell error plus the count of cells whose 8x8 mean differs by
  more than 40 levels ("bad cells"). Each capture is compared against sim
  frames N-1..N+1 and the best match is kept, so one-frame temporal
  misalignment does not count as divergence. The HUD text rows are excluded.
- `bad_cells.py ... FRAME`
  Lists the diverged cells at one frame with each cell's last-update frame,
  separating freshly-loaded corruption from stale-cell corruption.
- `identify_content.py ... FRAME [--window K]`
  Matches each diverged cell's recorded content against every pattern the sim
  applied in frames N-K..N+K and reports whose pattern the cell really shows.

## Findings (2026-08-03, Lunar OP 24fps)

- The HUD gate PASSes while the picture is badly corrupted: `sector_slip`,
  `control_desync`, `audio_resync` all stay zero because the control stream is
  intact; only tile content is wrong. Corrupted cells are almost entirely
  cells freshly loaded in that frame, plus occasional lost tail rows.
- Not cold-cap dependent: a uniform cold cap 100 encode corrupts as badly as
  2:160/3:220 or 2:170/3:250.
- Regression bisect on identical profiles (cap 225):
  - `37bba85` (p141, 24fps merge) — clean, 0 bad cells over the whole movie;
  - `aeaa25f` (p142, TTRC v25 + one-sided fade) — clean;
  - `90da67e` (p143, single name table via flip-VBlank DMA, issue #102) —
    catastrophic (sector_slip 15, audio_resync 8, 1707 cadence misses);
  - `8bb86c6` (p144, HUD sprite VRAM overlap fix) — gate PASSes again but the
    visual corruption remains.
  H40 15 fps and H40 30 fps were the only cadences qualified for #102;
  24 fps (periodic 2/3) breaks in both H32 and H40.
- GPGX LOGVDP frame TSV shows pattern DMA continuing past the vertical blank
  into active display on loaded frames while `transfer_vblanks` stays 1. This
  is NOT the corruption cause: the clean p141 build spills even more pattern
  words into active display (1,713 frames, 946k words) with zero visual
  damage — slot liveness makes active-phase pool writes safe. The name-table
  DMA is always fully inside a blank (1,760 words) in every build.
- `measure_lead.py` (quantized-exact matching through the emulator's RGB ramp
  0/34/69/101/138/170/207/239) proves the real defect: within a corrupt frame
  the first K freshly-loaded cells are pixel-exact correct, and every later
  cell displays, pixel-exact, the pattern intended for a cell 33..52 positions
  LATER in the same frame's unique-pattern sequence (e.g. f92: correct through
  unique position 16, then a constant +37 shift; onset K and shift vary per
  frame and drift within the frame). Cells past the shifted window match no
  scheduled pattern at all. Frame 92 has `transfer_vblanks=1` (a single,
  unsplit Main budget), so the displacement already exists in the delivered
  content or entry stream, not in Main's budget splitting.
- Every observed shifted pair shares the same palette line, so the palette
  test could not yet separate "pattern payload stream displaced" (Sub
  O_LOADS/PrgBuf pop side) from "name-table entry stream displaced" (Main
  shadow/blitter side); with contiguous two-pass slot allocation both produce
  identical pixel evidence. `90da67e` rewrote the Main shadow blitters and
  deleted `harness/main_codegen/verify_blitters.py`, and moved the NT publish
  into the flip VBlank; the Sub image was not modified by that commit, so a
  Main-side entry-stream defect or a Sub-side race newly exposed by the
  changed Main timing are both still open.

## Next steps

1. Instrument one side to break the ambiguity: either a Sub DEBUG counter of
   ring pops per frame (compare with the packed per-frame Prg pop count), or
   a Main-side checksum of the shadow entry stream per frame.
2. Once the side is known, bisect within `90da67e`'s Main rewrite (blitters,
   `bf_update_list`/`bf_stage_nt`, or flip timing) or the Sub pop/pump
   interleave, fix, and requalify H40 15/30 fps plus 24 fps H32/H40 with
   `scan_divergence.py` (bad_cells must be 0), then p-bump and re-run the
   three pending uploads.
