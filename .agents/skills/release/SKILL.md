---
name: release
description: Build a release (DEBUG=0) Sega CD disc for a profile, record its playback without the DEBUG HUD, and qualify that recording against an existing gate-PASS DEBUG recording of the byte-identical packed stream using the GPGX LOGVDP DMA trace and visual inspection. Use for "release build", "HUDなしで録画", "/release", or whenever a publication playback video must not carry the debug overlay.
---

# release: HUD-free playback build

Produce the playback artifact a viewer should see: the same stream the DEBUG
build already qualified, played by a release player that draws no debug
overlay.

Run every command from the repository root.

## Why this skill exists separately

`record` builds `DEBUG=1` by default because the on-screen HUD is what the
schema-16 upload gate reads. A release build draws no HUD, so:

- there is no HUD TSV and no `_gate.json` for a release recording;
- `harness/gpgx_logvdp/extract_frame_tsv.py` cannot run, because it aligns the
  DMA trace to HUD frame numbers;
- `compilation`'s normal precondition, a gate JSON whose `recording` matches the
  input MKV, cannot be satisfied by the release capture itself.

None of that means a release capture is unqualified. It means its evidence comes
from a different place: the DEBUG recording that already passed, plus proof that
the release disc carries the same bytes and the release player does no more VDP
work. This skill states that chain explicitly. Do not reuse a DEBUG gate JSON by
hand-editing it, and do not claim a release capture has a HUD gate.

## Preconditions

Require all of the following before building anything:

1. A completed `record` capture of the same profile whose schema-16 HUD result
   has gate `PASS` (alert `NONE` or `WARNING`), together with its
   `logs/<run>_hud.tsv`, `logs/<run>_hud_gate.json`, and the compact RetroArch
   log kept beside its lossless MKV.
2. The same encoder/player version in `tools/av_version.txt` for both. A
   release build at a different `e`/`p` has no baseline; produce the DEBUG
   recording first through `run`.
3. The current packed stream in `out/PROFILE/`, produced by that same DEBUG
   pipeline and not modified since.

A missing or `FAIL` baseline gate stops this skill. Do not substitute a
release-only visual check for the qualification.

## Stage 1: Prove the stream did not change

The release build reruns `make disc`, which rewrites the packed stream. The
DEBUG gate only transfers to the release capture when those bytes are
identical, so record their hashes first and check them afterwards:

```sh
sha256sum out/PROFILE/HEADER.DAT out/PROFILE/BODY.DAT \
          out/PROFILE/paltab.bin out/PROFILE/palidx.bin > tmp/PROFILE/stream_hashes.txt
```

A release build writes `out/PROFILE_release.iso` and `out/PROFILE_release.cue`,
so it never overwrites the `out/PROFILE.iso` / `out/PROFILE.cue` pair a DEBUG
build produced from the same packed stream. Both discs can therefore exist
side by side and be compared.

Build the release disc, then verify:

```sh
sha256sum -c tmp/PROFILE/stream_hashes.txt
```

Every line must report `OK`. A changed byte means the release disc is not the
qualified stream; stop and find out what moved before recording. `DEBUG` selects
only the player build, so a difference here is a pipeline bug, not an expected
release/debug variation.

## Stage 2: Build and record

`record` owns the recording mechanics; this skill only selects the release
build and the same duration used for the baseline:

```sh
tools/record_movie.sh --config profiles/PROFILE.toml --release-build \
  --seconds N --tag STEM_rel --record-size 320x224
```

Keep the complete Mega-CD startup, use the default fixed-Replay offline
FFV1/FLAC path, and reserve at least 30 seconds beyond the source duration as
`record` requires. The Replay is regenerated for this disc; a Replay made for
the DEBUG disc belongs to a different binary and must not be reused.

Verify the capture exactly as `record` specifies: native 320x224, about
60000/1001 fps, bounded duration, a non-empty audio stream, the requested
packet and decoded-frame counts, and a RetroArch log that reaches
`Content ran for a total of` and `Unloading core`.

## Stage 3: Qualify with the LOGVDP DMA trace

Both builds run under the managed GPGX LOGVDP core, so both emit the core's DMA
timing trace. Compare the release capture with the gate-PASS DEBUG capture:

```sh
tools/python.sh .agents/skills/release/scripts/compare_logvdp.py \
  --baseline <DEBUG OUTDIR>/retroarch_<debug tag>.log \
  --release  <release OUTDIR>/retroarch_<release tag>.log \
  --json <release OUTDIR>/<tag>_logvdp_compare.json
```

The tool separates the player's own transfers, which run from 68000 work RAM,
from the BIOS and CD-player startup, and splits each by the accesses-per-line
rate the core reports: the highest rate a region used is its blanking rate and
anything lower is active display. It reports the core's own `access` counts and
deliberately does not translate them into VRAM words; the trace is a DMA timing
model, not the encoder's R2V accounting.

It fails when any of these hold:

- the core logged an error kind absent from the baseline;
- the release player's DMA reaches active display more than the baseline's does;
- the release player performs more total DMA than the DEBUG build, which also
  drew the HUD and therefore bounds it.

Judge the absolute amount of DMA that reaches active display, not its share.
Removing the HUD lowers the total, so an unchanged spill necessarily raises the
percentage; that is bookkeeping. What corrupts a frame is DMA running while the
raster is live. The default 5 percent tolerance absorbs the different Replay
start frame and bounded window; do not raise it to make a result pass.

Expect the name-table DMA to drop sharply between the two builds. That is the
HUD's Window-row and sprite-table work disappearing, and it is the difference
this build exists to make.

## Stage 4: Inspect the picture

The HUD is exactly what the automatic checks read, so its absence makes human
inspection part of the qualification rather than a courtesy. Extract named
stills from the lossless MKV and look at them:

```sh
tools/extract_verification_frames.sh "$LOSSLESS" \
  "$(dirname "$LOSSLESS")/record_check" \
  BOOT=3 CDPLAYER=10 EARLY=20 MID1=40 MID2=60 MID3=80 LATE=100 TAIL=118
```

Confirm in that invocation's own directory and montage:

- the Mega-CD startup and CD-player screens appear first;
- playback begins after the START transition and advances through the movie;
- no HUD row is present anywhere, which is what proves the release build ran;
- no torn tiles, stale patterns, dark 4-pixel dashes, or colour breakup;
- the tail is intact.

Never montage a shared check directory with `*.png`.

## Stage 5: Compile and upload

Hand the verified lossless MKV to `compilation` for the 2048x1568 square-pixel
transcode and the upload. Its normal HUD-gate precondition is satisfied by this
skill's chain instead: the byte-identical stream, the baseline gate, the LOGVDP
comparison, and the visual inspection. State that substitution when reporting;
do not present the release capture as carrying its own gate.

Title and description follow `AGENTS.md` "YouTube Upload Style". A release
capture is the plain `(playback)` video. When a DEBUG capture of the same
encode was already uploaded, retitle it to `(playback, DEBUG HUD)` so the two
stay distinguishable and the HUD-free one is the video a viewer is sent to.
Say in the description that no debug overlay is drawn.

## Report

Report the profile and stem, the release disc build, the packed-stream hash
result, the baseline recording and its gate maxima, the LOGVDP comparison
verdict with the player blanking/active-display split for both builds, the
visual inspection result, the final MP4 path with raster/SAR/DAR and duration,
and both YouTube URLs.
