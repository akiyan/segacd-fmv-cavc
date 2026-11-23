# Standalone BlastEm qualification

Use the [pinned build in the repository README](../../README.md#blastem-playback-and-recording).
The qualification below used [`8a2cd78`](https://github.com/akiyan/blastem/commit/8a2cd7803cd43aa135456251b84736b756706014).
`BLASTEM` can select another build of the same fork. `BIOS_REGION=jp|us`
selects the region and `BIOS_IMAGE` can supply the matching BIOS path.

## Bounded boot and VDP events

```sh
OUTDIR="$PWD/tmp/blastem-boot" \
  tools/run_headless.sh out/CDCBENCH.cue \
  --max-frames 600 --vdp-event-log
```

The `-b` execution exercises the BIOS and disc loading path. It ends at a
fixed emulator frame budget. Use a recording with input to check movie
progression after the BIOS screen.

The fork's `BLSTEL` event stream contains VRAM, CRAM, VSRAM and VDP-register
writes and their cycle positions. It uses the base Genesis event format.
DMA command provenance, RF5C164 state and the Main/Sub CPU and CDC timeline
need separate observations.

Use the shared `event_stream.py` reader for diagnostics. The frame extractor
checks each first-loop publication against the scanout in an untrimmed
recording’s HUD TSV:

```sh
tools/python.sh harness/blastem/extract_frame_tsv.py "$VDP_EVENT_LOG" \
  --hud-tsv logs/RUN_hud.tsv --output logs/RUN_vdp.tsv
```

## Lossless capture

Build a short DEBUG disc from known patterns and palettes:

```sh
tools/python.sh harness/palette_capacity/build_fixture.py \
  --output tmp/blastem-palette --fps 30 --segments 17 --frames 68
```

The recorder uses the bundled START input for the Japanese BIOS. Pass
`--input-script` for a custom frame-indexed input file.

```sh
tools/record_movie.sh --disc tmp/blastem-palette/palette.cue --no-build \
  --seconds 35 --vdp-event-log
```

The backend checks the fork's completion metadata, all APNG chunks and the
WAV, then uses the H40 active rectangle and exact frame-rate metadata to
generate 320×224 FFV1/FLAC. The high-level recorder prints `LOSSLESS=` for
the bounded MKV. For a specific emulator frame count, invoke the backend
directly with `--max-frames N --record /path/to/output.mkv --input-script
start.txt`.

The run receipt printed as `BLASTEM_RECEIPT=` records the command, exit
status and hashes of the BIOS, executable, CUE, track files and input script.
The paths printed as `BLASTEM_LOG=` and `VDP_EVENT_LOG=` refer to the same
run. The intermediate APNG and WAV files are removed after a successful
mux. The fork's capture JSON remains available with the original frame and
sample counts.

Use `harness/startup_resync/analyze.py` on the native capture to check that
the 68 fixture movie frames appear in order and inspect the slip, desync and
resync counters. The fixture supplies silent ADPCM. A separate sound fixture
such as `PCMTEST` is needed to check nonzero RF5C164 output. For repeatability,
use `tools/compare_recordings.py` to compare two recordings made by the same
backend. Compare against the fixture and packed-stream expectations first.
Use hardware measurements to resolve timing-dependent behavior.

## Qualification scope

The 68-frame Japan fixture reached every movie frame and all 17 palette
segments in order. Two 1,900-frame runs agreed on decoded pixels, PCM,
packet timestamps and BLSTEL bytes across the 1,800-frame APNG boundary.
`PCMTEST` produced a measured 246.5 Hz tone. The DEBUG gate reported zero
sector slips, control desyncs and audio resyncs, with cadence warnings.

North American Lunar with the stock Sega CD 1.10 BIOS reached all 2,535 movie
frames in order. Its VDP trace showed zero sector slips, control desyncs, and
audio resyncs. The 24 fps cadence had eleven adjacent pairs of reversed
2/3-VBlank intervals, all within the first 175 movie frames. Physical drive
timing requires separate hardware qualification.
