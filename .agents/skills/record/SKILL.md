---
name: record
description: Build a DEBUG Sega CD disc by default, then make a fast fixed-Replay FFV1/FLAC recording with RetroArch and Genesis Plus GX from emulator launch through the Mega-CD startup screens and playback, preserving synchronized A/V and producing a native-resolution lossless MKV. A lossy verification preview is opt-in via --preview and is not produced normally. Use for "record it", "capture playback as video", "record the OP", "verify the recording", or "/record". Build release or use realtime pacing only when explicitly requested. Use DEBUG HUD OCR only for requested diagnostics, never for default head cueing. This skill records and verifies; compilation produces the final upload MP4 and publishes it.
---

# record: Sega CD Playback Recording

Record the emulator's own synchronized video and build-generated audio from launch through
the Mega-CD BIOS/CD player, START transition, movie, and tail. Keep the startup sequence by
default. "Offline" here means unpaced emulation, not replacement with an offline audio source.

Run every command from the repository root.

## Role boundary

Use this skill to:

- build a DEBUG disc by default, or release only when explicitly requested;
- launch RetroArch, send START, and record synchronized A/V;
- validate timing, video, audio, logs, and optional diagnostic counters;
- run the mandatory descriptive schema-16 HUD upload gate for any capture
  that may proceed to `compilation` or another upload step, while preserving
  `cd_wait_count` and `adpcm_decode_units` as diagnostics;
- render the complete HUD TSV through the `hudline` skill, show it inline, and
  publish the PNG to a public Gist after every full recording, then require the
  matching codec timeline and render, show, and publicly publish the combined
  `mixline`;
- return the raw lossless MKV and its sidecars. A lossy verification preview
  is produced only when `--preview` is explicitly requested.

Do not apply upload PAR/upscaling, create YouTube metadata, or upload here. Pass the verified
lossless MKV to `compilation`. Do not locate `frame=0000` or trim to the movie unless the user
explicitly asks for a movie-only clip.

## Preconditions

Require `retroarch`, the Genesis Plus GX libretro core, `Xvfb`, `xdotool`, ImageMagick,
`ffmpeg`, `ffprobe`, and the locked `.venv`. The harness stages the default
Japanese Mega-CD BIOS from `original/jp_mcd2_9212.bin` into a private per-run
RetroArch system directory and prints its SHA-256. Replay generation spans the BIOS/CD-player
transition with one START press per second; do not replace it with a
revision-specific fixed head cue.
Use these overrides only when needed. `SYSTEM_DIR` deliberately replaces the
private default, so do not point concurrent runs at one shared directory:

```sh
CORE=/path/to/genesis_plus_gx_libretro.so
SYSTEM_DIR=/path/to/retroarch/system
```

The high-level recorder always replaces `OUTDIR` with one leased managed-tmpfs
directory. Use `OUTDIR` only with a direct low-level `run_headless.sh`
diagnostic.

`tools/run_headless.sh` acquires one EMU token, dynamically allocates a private
X display and system directory, and releases them on exit. The qualified
default permits two emulator instances. CPU-heavy preview transcoding uses CPU
tokens. Never bypass these locks or kill another session's process.

Set the native recording raster explicitly before constructing the command.
This is mandatory because RetroArch may otherwise lock its recorder to the
Mega-CD BIOS startup geometry before the movie changes mode. The codec is
H40-only, so the raster is a fixed constant and is not read from the profile:

```sh
NATIVE_RECORD_SIZE=320x224
```

## Standard capture

Use `tools/record_movie.sh`, which owns the high-level recording workflow:

```sh
tools/record_movie.sh [--config TOML | --disc CUE --no-build] [--seconds N] \
  [--trim SEC | --auto-audio-trim] [--tag NAME] [--display :N] \
  [--preset realtime|ffv1-flac] [--record-size WxH] [--no-build] \
  [--release-build] [--offline-record | --realtime-lossless] [--input-replay FILE] \
  [--preview [--out MP4]]
```

Defaults and rules:

- Pass the same `--config profiles/PROFILE.toml` used by sim and pack. The
  harness derives `out/PROFILE.cue` from the TOML filename.
- Use an explicit `--disc CUE --no-build` only for a previously verified image.
- Build with `DEBUG=1` by default. The Window-row/SAT HUD is part of the normal recording artifact.
- Use `--release-build` only when the user explicitly asks for a release build. It changes the
  harness build to `make disc CONFIG=profiles/PROFILE.toml DEBUG=0`.
- Keep the startup sequence. The default is `--trim 0`; omitting `--trim` has the same result.
- Treat `--seconds` as the final duration from emulator launch. Include enough time for the
  startup screens, the full movie, and a short tail. With the default
  `jp_mcd2_9212.bin`, reserve at least 30 seconds beyond the source duration;
  measured full recordings reach the visible frame-0 flip at 14.9 seconds, so
  a smaller margin truncates the movie tail. That startup is deterministic
  because replay generation mashes START densely enough to stay dense in
  emulated time while the emulator runs unpaced at 8x-26x.
- Use `--trim SEC` or `--auto-audio-trim` only when the user explicitly requests a
  movie-only clip. Neither mode may be used for a normal `compilation` input.
- Use `--no-build` only after confirming in the current work that the disc represents the
  requested code/data and build mode. Unless release was explicitly requested, it must be a
  `DEBUG=1` disc; do not trust an unknown pre-existing image.
- Always pass `--record-size "$NATIVE_RECORD_SIZE"`. Never omit it or rely on
  RetroArch's first reported geometry. H40 is 320x224.
- Omit `--display` for normal work; Xvfb allocates a free display with
  `-displayfd`. An explicit `--display :N` is diagnostic-only and fails if an
  existing server owns it.
- The lossy H.264 verification preview is opt-in: pass `--preview` to create
  it and `--out` only to name it. The harness writes the bounded raw MKV,
  Replay, and sidecars into one leased tmpfs directory and prints `LOSSLESS=`
  (plus `OUT=` only when a preview was requested) with their real paths.
  Verify recordings with stills extracted from the lossless MKV instead of a
  preview transcode.
- A direct `tools/run_headless.sh out/PROFILE.cue` call defaults its screenshots,
  logs, PID files, and raw diagnostic capture to `tmp/PROFILE/record/`; do not
  put multiple profile runs directly in the shared `tmp/` root.
- `ffv1-flac` is the pixel-lossless default and the only normal input to `compilation`.
  The high-level default records it uncapped through a fixed Replay. Explicit
  `--preset realtime` uses wall-clock-paced H.264 with 4:2:0 chroma, writes `_native.mkv`
  rather than `_lossless.mkv`, and must not feed an upload compilation.
- `--offline-record` remains as an explicit spelling of the default. Offline always uses
  FFV1/FLAC; lossy presets and arbitrary low-level recorder configurations are rejected.
- `--realtime-lossless` selects the paced FFV1/FLAC fallback used to requalify or diagnose
  the offline path. It is not required for routine recordings.
- `--input-replay FILE` reuses an existing input Replay for an exact-frame paced or offline
  run. Reuse it only with the disc, libretro core, core options, and harness configuration
  that created it.

Canonical full capture for later upload:

```sh
tools/record_movie.sh --config profiles/PROFILE.toml --seconds 180 \
  --tag STEM_emu --preset ffv1-flac \
  --record-size "$NATIVE_RECORD_SIZE"
```

Replace `STEM` and the mode-specific size. The harness records with a safety tail, then
stream-copies the requested launch-to-tail duration into the native lossless input at
the printed `LOSSLESS=` tmpfs path. This bounds the tail without seeking past
the startup. Keep that artifact leased through the HUD stage and use the
printed path for `compilation`.

For a short boot/playback check:

```sh
tools/record_movie.sh --config profiles/PROFILE.toml \
  --seconds 30 --tag rec_check
```

## Default fast offline capture

Routine `$record` work uses faster-than-realtime FFV1/FLAC without an extra mode flag:

```sh
tools/record_movie.sh --config profiles/PROFILE.toml --seconds 180 \
  --tag STEM_offline --record-size 320x224
```

With no `--input-replay`, the high-level harness first records an input Replay under
the same managed tmpfs directory, makes it 120 emulator frames longer than the main fixed-frame run,
and prints its path as `REPLAY=...`. Playback of that saved Replay fixes the captured input
frames. The recording retains the Mega-CD startup, CD player, START transition, full movie,
DEBUG HUD, and tail. Replay EOF before the frame limit is a hard failure.

Qualify an offline result against a realtime FFV1/FLAC run of the same Replay. Do not use
the Replay-generation run as the baseline: Replay initial-state handling can change its
audio boundary by one stereo PCM sample.

```sh
REPLAY=/dev/shm/segacd-fmv-cavc/artifacts/RECORD_ENTRY/data/replay/STEM_offline_input.replay

tools/record_movie.sh --disc out/PROFILE.cue --no-build --seconds 180 --realtime-lossless \
  --preset ffv1-flac --input-replay "$REPLAY" \
  --tag STEM_realtime --record-size 320x224

tools/record_movie.sh --disc out/PROFILE.cue --no-build --seconds 180 \
  --input-replay "$REPLAY" --tag STEM_offline_ab \
  --record-size 320x224

tools/python.sh tools/compare_recordings.py \
  "$REALTIME_LOSSLESS" "$OFFLINE_AB_LOSSLESS" \
  --json "$(dirname "$OFFLINE_AB_LOSSLESS")/STEM_offline_ab_compare.json"
```

When requalifying the harness, run the offline command a second time with another tag and
require another passing exact comparison. The comparator checks every decoded video frame,
every decoded PCM sample, packet PTS/DTS/durations, stream metadata, and total counts without
trimming or alignment. Routine captures do not repeat the three-run qualification unless
RetroArch, the core, harness timing/recording code, or recorder settings changed, or a result
is suspect. Requalify same-Replay captures again before raising
`SEGACD_EMU_TOKENS`; compare each concurrent capture with its one-instance
baseline exactly.

## What the harness guarantees

`tools/run_headless.sh` records with RetroArch's FFmpeg recorder; Xvfb only supplies the
headless display. Both modes initialize RetroArch's audio path through the SDL dummy sink,
so the core's PCM reaches the recorder without a physical output device.

- Default offline recording disables audio sync, rate control, and video vsync. It exits
  naturally after `--max-frames`, rejects Replay EOF, and requires packet and decoded-frame
  counts to equal the limit exactly.
- Explicit `--realtime-lossless` keeps audio sync and rate control enabled while preserving
  FFV1/FLAC. It is the paced baseline for qualification and diagnosis.

- `realtime` / `flac-fast`: x264 CRF 0 plus FLAC, but with 4:2:0 chroma, so the result is
  native-size and synchronized but not pixel-lossless.
- `ffv1-flac`: FFV1 video plus FLAC audio; use this raw MKV for pixel analysis and upload
  preparation because it preserves the recorder's pixels.

Stop RetroArch through the harness. Do not kill it first; doing so can leave an incomplete
Matroska trailer.

## Required verification

Check the raw MKV and reports before trusting a capture:

1. Use `ffprobe` to confirm video, audio, expected native raster, about 60000/1001 fps, and a
   valid duration. Compare width and height to `NATIVE_RECORD_SIZE`
   immediately. A mismatch is a failed recording: do not start HUD OCR,
   compilation, or upload, even if the movie is otherwise visible. Re-record
   with the explicit native size.
2. For the default offline run, confirm the exact requested packet/frame count and report
   media-to-wall speed; faster-than-realtime is expected. For `--realtime-lossless`, confirm
   the harness timing is near the requested emulated duration.
3. Confirm exit zero plus `Content ran for a total of` and `Unloading core`. Some RetroArch
   builds also print `Average monitor Hz`, but 1.22.2 does not do so consistently. Reject a
   log ending at `SET_GEOMETRY`, a nonzero exit, Replay EOF, or an unreadable trailer.
4. Confirm that `ffprobe` sees a non-empty audio stream with the expected codec,
   sample rate, channels, and packet count. The recorder deliberately has no
   sample-jump, clipping, or RMS threshold gate: legitimate source transients
   and lossy preview encoding made those tests content-dependent.
5. Inspect frames from the MKV and confirm that the Mega-CD startup appears first, playback
   begins later, the DEBUG Window-row/SAT HUD is visible, and the movie advances. Do not use the HUD
   to seek the movie start. Extract these stills with
   `tools/extract_verification_frames.sh`; give it a `$(dirname "$LOSSLESS")/record_check` base and
   named `LABEL=SECONDS` samples. It creates a never-reused source-specific directory,
   records source/still hashes in `manifest.tsv`, and builds its montage only from the
   explicit files extracted by that invocation. Never montage a shared check directory with
   `*.png` or reuse loose stills from an earlier recording.
6. After changing RetroArch, the core, the offline harness, or recorder settings, requalify
   with a same-Replay `--realtime-lossless` comparison and a second offline run through
   `tools/compare_recordings.py`. Also requalify any suspect result.
7. Before handing a recording to `compilation` or any upload step, OCR one
   complete movie loop and write an upload-capable HUD gate sidecar:

   ```sh
   tools/python.sh harness/startup_resync/analyze.py \
     "$LOSSLESS" profiles/PROFILE.toml \
     --expected-frames FRAME_COUNT
   ```

   With the required profile argument, the analyzer writes the HUD TSV body
   permanently to `logs/<datetime>_<profile>_<sha10>_eNN_pNN_hud.tsv` and the
   matching gate to `_gate.json`. Use the two printed direct paths for every
   downstream tool; no compatibility symlink is created.

   The analyzer uses the single standard 43-cell layout, which wraps after 40
   cells into a three-cell second row. The analyzer unpacks `vblank_spill`
   from the high nibble of the
   transfer word, `apply_backpressure` from bit 15 of the pump-gap word, and
   reader lead into `reader_ahead_frames` plus `reader_slot_sector`.

   The profile is mandatory and positional because cadence and PrgBuf limits
   follow the packed player. The result contains gate `PASS`/`FAIL` and alert
   `NONE`/`WARNING`/`FAIL`. Alert `WARNING` keeps gate `PASS`, exits zero, and
   remains upload-capable; alert `FAIL` makes gate `FAIL` and exits nonzero.
   The first loop must contain every frame. `sector_slip`,
   `control_desync`, and `audio_resync` must remain zero.
   `vblank_spill` above the cadence-derived limit raises a warning.
   `prgbuf_jitter_peak_kib` must remain below its physical-ring-derived limit.

   For authoritative cadence playback, compare consecutive first-capture
   positions for every timed, nonterminal `frame` against that frame's exact
   cadence phase. This is four VBlanks at 15 fps, repeating 2/3 VBlanks at
   24 fps, and two VBlanks at 30 fps. A different visible duration raises
   alert `WARNING` while retaining gate `PASS`, except within the first/last
   two content frames at 15 fps, three at 24 fps, and four at 30 fps. Preserve
   those edge observations as diagnostics together with the complete
   histogram and affected frames. This exception applies only to derived
   display duration, not gate fields or transfer diagnostics. A
   `transfer_vblanks` maximum above the cadence's largest interval is another
   warning.

   Periodic 24 fps playback phase-locks its long-term display clock after a
   missed target. A compensating two-VBlank interval in a nominal three-VBlank
   phase remains a visible cadence warning; it is expected to prevent the miss
   from accumulating permanent reader lead, not to hide the original miss.

   Report distributions for `cd_wait_count`, `adpcm_decode_units`, and
   `pump_gap_ticks`; APPLY back-pressure frame count; cumulative
   `msf_gap_recoveries`; reader lead; and transfer VBlank/phase maxima.
   Correlate these diagnostics with actual playback failures. Do not waive,
   hand-edit, or reuse a gate JSON from another recording.

   On every result, report minimum, mean, median, and maximum for
   `cd_wait_count` and `adpcm_decode_units` across the timed first loop,
   excluding frame 0. Do the same for `pump_gap_ticks`. On gate `PASS`, also
   report all five descriptive gate maxima and the diagnostic
   `cd_wait_count` maximum. A standalone `record` request ends with the
   verified recording because it did not authorize publication. Under `$run`,
   the existing upload authorization is sufficient; continue without asking
   again merely because the gate ran.

8. Immediately invoke the `hudline` skill with this exact HUD TSV, gate JSON,
   profile, and recording identity. Render and inspect the full first-loop PNG,
   show it inline, and publish it to a public Gist even when the gate fails.
   Require the matching timeline from the exact sim decision log, generating
   and publicly publishing it first when absent. Immediately invoke `mixline`,
   inspect and show the aligned combined PNG, and publish it to a public Gist.
   Preserve the timeline, hudline, and mixline layout/Gist receipts under
   `logs/`; the PNGs are direct tmpfs artifacts. A `FAIL` still stops
   compilation and uploads
   after both diagnostic images have been published. Under `$run`, gate `PASS`
   continues without another approval pause, including alert `WARNING`.

Structural audio presence is not a substitute for listening. Claim that the
sound is clean or free of audible clicks only after listening to the final file.

## Required upload HUD gate and optional diagnostics

The standard capture already builds DEBUG. The HUD is a 43-cell values-only
stream in one layout that wraps after 40 cells into a three-cell second row.
Parse the complete first loop
whenever the capture can be uploaded; for a local-only recording, full OCR
remains optional unless diagnostics were requested. Keep
OCR work separate from ordinary recording and publication head cueing:

```sh
make disc CONFIG=profiles/PROFILE.toml DEBUG=1
tools/python.sh tools/tmpfs_workspace.py run-directory \
  --kind record-diagnostic --key STEM_debug --required-gb 8 -- \
  env OUTDIR='{output}' tools/run_headless.sh out/PROFILE.cue \
    --tag STEM_debug --record --record-preset ffv1-flac \
    --record-size 320x224 --shots 68 --interval 2
```

Confirm the Window-row/SAT HUD is visible before a long OCR scan. Read the complete
loop. `transfer_ticks` is the Main pattern-transfer time in 30.72 us ticks,
`cold_runs` is the packed run count's low byte, and
`prgbuf_jitter_peak_kib` is sticky ceil-KiB excess above the cadence-derived
normal ceiling. Gate `PASS` in the descriptive schema-16 result is the
required handoff condition; alert may be `NONE` or `WARNING`. Fixed-cadence
visible-duration and transfer-budget excesses are warning-only. When the
enclosing request already authorizes a full run, reviewing its maxima is not a
separate approval pause. Its HUD timing must never be reused as a publication
trim point or as a timestamp in an upload description. The matching timeline, `hudline`, and `mixline` PNGs and
public-Gist receipts are required recording sidecars.

## Existing recordings and smoke tests

Inspect an existing file without recording again:

```sh
ffprobe -v error -count_packets \
  -show_entries stream=index,codec_name,codec_type,width,height,sample_rate,channels,nb_read_packets \
  -show_entries format=duration \
  -of json "$PREVIEW"
```

Run a headless smoke test without video recording:

```sh
tools/run_headless.sh out/PROFILE.cue \
  --tag smoke --shots 8 --interval 1
```

## Audio and boot triage

There is no waveform-threshold audio gate. If a startup-inclusive capture is
quiet at the beginning, inspect the complete movie section instead of silently
trimming the startup. Use `tools/compare_recordings.py` for exact same-Replay
PCM comparison, and listen to the final file before making an audible-quality
claim.

For boot failures, inspect frames extracted from the MKV rather than live Xvfb screenshots.
Keep the foreground defaults for boot wait and repeated START presses. If output is missing,
black, silent, or durationless, inspect the RetroArch/Xvfb logs and rerun one capture in the
foreground. If an explicit display was used, first retry with automatic allocation.

Raw FFV1 captures can be several GB. Keep the bounded upload input until publication is
complete, then remove only artifacts created by this session when space is needed.

## Report

Report the raw MKV path (and the preview MP4 path when one was explicitly
requested), duration, raster/fps, audio codec,
sample rate, channels and packet presence, whether startup was retained, and
whether human listening was performed. For offline runs also report the Replay
path, requested/max frame count, wall time, and speed. When the run requalifies
the fast path, additionally report the exact-comparison JSON/pass state and
repeat-run result. For an upload-capable capture, report the HUD gate JSON,
complete-loop frame count, all five descriptive gate maxima, diagnostic
`cd_wait_count` maximum, `cd_wait_count` / `adpcm_decode_units` /
`pump_gap_ticks` statistics, APPLY and MSF recovery counts, reader and transfer
maxima, gate state, hudline and mixline PNGs, and both public Gist/raw image
URLs.
