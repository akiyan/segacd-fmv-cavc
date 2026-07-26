# Startup audio re-sync HUD extractor

This harness reads a native DEBUG playback recording sequentially and finds the
first audio re-sync (`R`) without seeking by eye. It uses the player's fixed
top-row values-only HUD; the internal key order remains
`F/P/S/D/R/L/C/W/M/A/U/N/J`:

```text
H32/H40: xxxx xx xx xx xx xx xx xx xx xx xxxx xx xx
```

The startup-specific fields are:

- `L`: audio reserve in 256-byte units;
- `C`: blocking CD sector pumps (current control plus older BODY payload/pad);
- `W`: Main's wait for Sub completion at `CMD_SWAP`, in approximate scanlines;
- `M`: Main-side VBlank-start waits while applying pattern DMA;
- `A`: Sub ADPCM decode time in four-stopwatch-tick units (about 0.1229 ms
  per displayed unit); PCM builds show zero.
- `U`: Main pattern-transfer time in 30.72 us Mega-CD stopwatch ticks;
- `N`: low byte of the packed cold-run descriptor count before VBlank
  splits; it wraps at 256.
- `J`: streamed PrgBuf jitter-reserve high-water mark in KiB.

The startup fields use two hexadecimal digits. `U` uses four digits and `N`
uses two. The extra counters exist only in a `DEBUG=1` player and add no DMA.

Specialized H40 DEBUG builds may extend the row to 40 cells. Use
`--flip-fields` for `Q/V/O/E`, or `--poll-gap-fields` for the mutually
exclusive `G/K/O/E` diagnostic layout. `G` is the longest interval outside a
Sub CDC pump opportunity in 30.72 us ticks; its bit 15 becomes the separate
per-frame APPLY back-pressure field `B`. `K` is the cumulative MSF-gap
recovery count, and the TSV derives CDC_TRN retry exhaustion as
`(S-K) & 0xFF`.

Every capture frame is decoded by `ffmpeg` as a small grayscale rawvideo crop.
`tools/read_frameno.py:read_hud` reads all visible fields.  A sample is accepted only
when every field meets the confidence threshold, then repeated capture frames
with the same `F` value are aggregated.  This matters because a 29.97 fps movie
frame normally appears in about two frames of a 59.94 fps recording.

Run it against the lossless output from `/record`:

```sh
tools/python.sh harness/startup_resync/analyze.py \
  videos/SonicJamOp_startup_audio2_ab_debug_lossless.mkv \
  configs/sonic-jam-op-h40.toml \
  --tsv videos/SonicJamOp_startup_audio2_ab_debug_hud.tsv
```

The console report shows every `R` transition, its movie-frame number in hex and
decimal, and the surrounding `L/C/W/M/A` values. It always reports the
minimum, mean, median, and maximum of both `C` and `A` across the timed first
loop; untimed frame 0 and later loops are excluded. The same statistics are
stored in the gate JSON. `C` is diagnostic only and does not affect the gate
status. With `--poll-gap-fields`, the report and gate JSON also preserve G
minimum/mean/median/maximum and the B frame count; `/hudline` and `/mixline`
render G/B/K permanently. The TSV contains one row per aggregated movie frame.
Transition rows additionally carry the previous and next lead, which makes
preload-to-live boundary failures easy to compare between A/B recordings. With
the profile argument, the TSV body is stored permanently as
`logs/<datetime>_<profile>_<sha10>_eNN_pNN_hud.tsv`; the requested `--tsv` path
is a compatibility symlink to that log.

The default crop begins at native x=0.  A legacy 320-pixel recording whose H32
image is centered with 32 pixels on the left can be read with `--crop-x 32`.
Lower `--confidence` only for older transparent-background HUD recordings; the
current black diagnostic row should pass the default `0.90` threshold.

This harness is diagnostic only.  Do **not** use its HUD timestamps to trim an
upload, remove the Mega-CD startup, or place YouTube chapters.  Publication
recordings keep the startup intact, and chapter offsets are determined by
ordinary visual playback as specified in `AGENTS.md`.
