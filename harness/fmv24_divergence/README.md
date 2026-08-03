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
- GPGX LOGVDP frame TSV shows the mechanism: on heavily loaded 2-VBlank
  slots the pattern DMA continues past the vertical blank into active display
  (hundreds to 1,151 words active in one frame; `transfer_end_vcounter`
  reaches 0x9E) while `transfer_vblanks` stays 1, i.e. one VBlank word budget
  was never split. The name-table DMA itself is always fully inside a blank
  (1,760 blank words, 0 active words on every frame).
