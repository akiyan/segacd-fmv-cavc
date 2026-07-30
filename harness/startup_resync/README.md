# Startup audio re-sync HUD extractor

This harness reads a native DEBUG playback recording sequentially and finds the
first `audio_resync` transition without seeking by eye. It uses the player's
fixed 43-digit values-only HUD. H32 wraps after 32 digits; H40 wraps after 40.
The physical order and widths are:

```text
frame:4 palette_segment:1 sector_slip:1 control_desync:1 audio_resync:1
audio_lead_256b:2 cd_wait_count:1 sub_wait_scanlines:2 adpcm_decode_units:2
vblank_spill+transfer_ticks:4 cold_runs:2 prgbuf_jitter_peak_kib:2
flip_vcounter:2 first_share_exit_vcounter:2 pass2_delay_q4:2
apply_backpressure+pump_gap_ticks:4 msf_gap_recoveries:1
reader_ahead_frames+reader_slot_sector:2 transfer_vblanks:1
transfer_end_vcounter:2 pattern_dma_ready_vcounter:2
name_table_dma_ready_vcounter:2
```

Small cumulative counters use one hexadecimal digit. The four-digit transfer
word packs `vblank_spill` in the high nibble and `transfer_ticks` in the low
12 bits. The four-digit pump word packs `apply_backpressure` in bit 15 and
`pump_gap_ticks` in the low 12 bits. The two-digit reader word packs
`reader_ahead_frames` and `reader_slot_sector` as one nibble each. The OCR
reader expands all three packed words into descriptive TSV columns.

`audio_lead_256b` measures audio reserve in 256-byte units.
`cd_wait_count` counts blocking CD sector pumps.
`sub_wait_scanlines` measures Main's wait for Sub completion at `CMD_SWAP`.
`adpcm_decode_units` uses four-stopwatch-tick units (about 0.1229 ms).
`transfer_ticks` and `pump_gap_ticks` use 30.72 us stopwatch ticks.
`cold_runs` is the packed cold-run descriptor count before VBlank splits.
`prgbuf_jitter_peak_kib` is the streamed PrgBuf jitter-reserve high-water mark.
`msf_gap_recoveries` is cumulative; the TSV derives transport retry recoveries
from `sector_slip - msf_gap_recoveries` modulo the one-digit counter.
`transfer_vblanks` beyond the cadence window raises `WARNING` without failing
the upload gate.

Every capture frame is decoded by `ffmpeg` as a small grayscale rawvideo crop.
`tools/read_frameno.py:read_hud` reads all visible fields.  A sample is accepted only
when every field meets the confidence threshold, then repeated capture frames
with the same `F` value are aggregated.  This matters because a 29.97 fps movie
frame normally appears in about two frames of a 59.94 fps recording.
The black state immediately before playback is the player-only frame -1 and
shows `frame=FFFF`. The extractor prefers the first valid `frame=0000` run immediately
after that sentinel, making the movie-head decision exact without seeking by
wall-clock time. `FFFF` is never emitted as a HUD TSV row. Recordings from
players without the sentinel retain the plausible `frame=0000` sequence fallback.
The console report states which anchor method was used, and gate JSON preserves
the sentinel and frame-0 capture indices and times as `ocr_start_anchor`.
That transition proves the recording covers the Mega-CD startup through the
movie head without a gap; the recording itself remains untrimmed.

Run it against the lossless output from `/record`:

```sh
tools/python.sh harness/startup_resync/analyze.py \
  "$LOSSLESS" \
  profiles/sonic-jam-op.toml \
  --tsv logs/SonicJamOp_startup_audio2_ab_debug_hud.tsv
```

The console report shows every `audio_resync` transition, its movie-frame
number, and the surrounding descriptive fields. It reports minimum, mean,
median, and maximum `cd_wait_count`, `adpcm_decode_units`, and
`pump_gap_ticks` values across the timed first loop; untimed frame 0 and later
loops are excluded. The same statistics are stored in the gate JSON.
`cd_wait_count` is diagnostic only and does not affect the gate status.
At fixed cadence, the first and last four content frames at 30 fps and two at
15 fps remain in the display-VBlank measurements but are excluded from that
derived ALERT. The exception does not apply to gate fields or
`transfer_vblanks`.
`/hudline` and `/mixline` render the retained fields by their descriptive
names. The TSV contains one row per aggregated movie frame.
Transition rows additionally carry the previous and next lead, which makes
preload-to-live boundary failures easy to compare between A/B recordings. With
the profile argument and no explicit `--tsv`, the TSV body is stored
permanently as `logs/<datetime>_<profile>_<sha10>_eNN_pNN_hud.tsv`. Supplying
`--expected-frames` also writes the matching `_gate.json`. The tool prints both
direct paths and creates no compatibility symlink.

The default crop begins at native x=0.  A legacy 320-pixel recording whose H32
image is centered with 32 pixels on the left can be read with `--crop-x 32`.
Lower `--confidence` only for older transparent-background HUD recordings; the
current black diagnostic row should pass the default `0.90` threshold.

This harness is diagnostic only. Do **not** use its HUD timestamps to trim an
upload, to remove the Mega-CD startup, or to write a timestamp into an upload
description. Publication recordings keep the startup intact, and their
descriptions carry no chapters or timestamp links, as specified in `AGENTS.md`.
