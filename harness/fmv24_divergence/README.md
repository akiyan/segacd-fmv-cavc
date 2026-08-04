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

## Root cause (resolved, e178)

The full LOGVDP value trace settled it. Reconstructing every VRAM pool write
of one frame and matching it pixel-exact against the intended cold sequence
showed the payload was the intended stream **displaced forward by exactly 32
patterns (1,024 bytes = half a CD sector)**, first appearing at cumulative
ring pop 13,440 = the PrgBuf ring's physical capacity (420 KiB), then growing
by another 32 per ring lap. The name-table entries, record walk, and Main DMA
were all correct; active-display pattern DMA was proven harmless (p141 spills
more and stays clean).

The defect was encoder-side, not the single-NT player: the WordBuf-ring
schedule (`tools/wordbuf_ring.py`) froze `prebuf_pat` at the raw fps-derived
PrgBuf ceiling. At 24 fps that ceiling is 389 KiB = 12,448 patterns = 194.5
sectors. The player prefills exactly `prebuf_pat*32` bytes and continues the
timed BODY payload from the same byte offset, so `ring_tail` becomes
permanently half-sector-misaligned: each ring lap one 2,048-byte sector store
straddles `RING_END`, its last 1,024 bytes land outside the ring (over the
`WORD_PENDING` scratch), and the pop stream gains a permanent +32-pattern
lead. 30 fps (400 KiB = 200 sectors) and 15 fps (380 KiB = 190 sectors) are
sector multiples by luck, so only 24 fps corrupted. Encodes whose ring plan
was infeasible fell back to the sector-floored `stream_schedule` prebuffer
(12,416) and played back clean on the same p144 player — that per-encode split
(HEADER.DAT `Bpat` 12,448 vs 12,416) is what made the earlier build bisect
look like a single-NT regression. The single-NT commit's own failure
(catastrophic slips at p143) was the HUD sprite-table VRAM overlap already
fixed by `8bb86c6`; an aligned-Bpat 24 fps encode on p144 is fully clean, so
single-NT itself qualifies at 24 fps.

Fix (e178): floor the ring-plan prebuffer to whole sectors and reject
fractional-sector prebuffers in `replay_frozen_schedule`, `pack_stream`, and
the `player_constants` header reader.

## Requalification

Re-encode with e178 (`Bpat` must be sector-aligned in HEADER.DAT), record,
then require `scan_divergence.py` bad_cells = 0 across the movie in addition
to the HUD gate.
