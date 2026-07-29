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

Standard H32/H40 DEBUG builds carry the same
`Q/V/O/E/G/K/H/X/Y/Z/T/I/Y3/Y4` information as one 69-cell stream. H32 wraps
into three 32-cell rows (`Q` and `Y3` cross row boundaries); H40 wraps into
two 40-cell rows (`G/K/H/X/Y/Z/T/I/Y3/Y4` occupy row 1).
Supplying either profile selects
the matching combined layout automatically. `G` is the longest interval outside a Sub CDC pump
opportunity in 30.72 us ticks; its bit 15 becomes the separate per-frame APPLY
back-pressure field `B`. `K` is the cumulative MSF-gap recovery count, and the
TSV derives CDC_TRN retry exhaustion as `(S-K) & 0xFF`. `H` is the per-frame
physical PrgBuf peak in exact 32-byte patterns. `X` packs complete reader
frame slots ahead in its high byte and the current slot's sector index in its
low byte. `Y/Z/Y3/Y4` are the exact logical pattern-word shares in the first
four fresh runtime VBlank budgets; weighted capacity cost is separate.
`O/I` are their first/final exit V-counters, and `T` is the total number of
budgets opened. Fixed-N `T>N` raises alert `WARNING` without failing the gate.
Keep `--flip-fields`
and `--poll-gap-fields` only for legacy one-row H40 recordings; use
`--combined-fields` only when parsing a standard H32/H40 recording without a
profile.

Every capture frame is decoded by `ffmpeg` as a small grayscale rawvideo crop.
`tools/read_frameno.py:read_hud` reads all visible fields.  A sample is accepted only
when every field meets the confidence threshold, then repeated capture frames
with the same `F` value are aggregated.  This matters because a 29.97 fps movie
frame normally appears in about two frames of a 59.94 fps recording.
The black state immediately before playback is the player-only frame -1 and
shows `F=FFFF`. The extractor prefers the first valid `F0000` run immediately
after that sentinel, making the movie-head decision exact without seeking by
wall-clock time. `FFFF` is never emitted as a HUD TSV row. Recordings from
players without the sentinel retain the plausible `F0000` sequence fallback.
The console report states which anchor method was used, and gate JSON preserves
the sentinel and frame-0 capture indices and times as `ocr_start_anchor`.
Playback-upload CRAM chapters use its exact `F=FFFF` to `F=0000` transition;
the recording itself remains untrimmed.

Run it against the lossless output from `/record`:

```sh
tools/python.sh harness/startup_resync/analyze.py \
  videos/SonicJamOp_startup_audio2_ab_debug_lossless.mkv \
  profiles/sonic-jam-op.toml \
  --tsv videos/SonicJamOp_startup_audio2_ab_debug_hud.tsv
```

The console report shows every `R` transition, its movie-frame number in hex and
decimal, and the surrounding `L/C/W/M/A` values. It always reports the
minimum, mean, median, and maximum of both `C` and `A` across the timed first
loop; untimed frame 0 and later loops are excluded. The same statistics are
stored in the gate JSON. `C` is diagnostic only and does not affect the gate
status. Standard H32/H40 parsing and legacy `--poll-gap-fields` both preserve G
minimum/mean/median/maximum and the B frame count in the report and gate JSON;
standard parsing also preserves H/X and Y/Z/Y3/Y4/T/I maxima. `/hudline` and
`/mixline` render G/B/K/H/X/Y/Z/Y3/Y4/T/I permanently. The TSV contains one row
per aggregated movie frame.
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
