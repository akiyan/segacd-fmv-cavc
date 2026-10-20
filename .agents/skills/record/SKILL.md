---
name: record
description: "Capture Sega CD emulator playback as synchronized native lossless video. Use for /record or an explicit recording request. Recording alone does not request analysis, full HUD diagnostics, publication, or a fresh source encode."
---

# Record emulator playback

Use `tools/record_movie.sh` from the repository root. It owns resource locks,
leases, fixed input Replay, FFV1/FLAC capture and normal exit/count checks.
Linux prerequisites: RetroArch, the configured Genesis Plus GX core, Xvfb,
xdotool, ImageMagick, FFmpeg/ffprobe, the pinned Python environment and a
user-supplied region-appropriate BIOS. Read tool errors before changing setup.

```sh
tools/runtime.sh --workspace-root /path/to/workspace \
  --scratch-root /path/to/scratch -- \
  tools/record_movie.sh --config profiles/PROFILE.toml \
    --seconds N --tag STEM_emu --record-size 320x224
```

- Set N from actual movie length plus startup/tail. The default Japanese BIOS
  normally needs at least 30 extra seconds; a short boot check is not a full
  playback qualification.
- DEBUG is the default. A HUD-free request selects `--release-build`; read
  `release` only for its additional publication qualification.
- For an existing matching disc, use `--disc CUE --no-build`. Building/recording
  must not silently trigger an unauthorized source re-encode.
- Preserve boot and tail (`--trim 0`). Preview MP4 (`--preview`), trimming, and
  paced recording (`--realtime-lossless`) are explicit options, not defaults.
- Always set native size 320x224; the BIOS startup geometry must not choose the
  recorder raster. Use automatic X display allocation and a short SYSTEM_DIR
  path (the core's filename buffer is bounded).
- Reuse an input Replay only with the same disc/core/settings. Replay EOF is a
  failed capture. Let the harness stop RetroArch and finalize Matroska normally.

Check the printed LOSSLESS file, harness counts, audio presence, duration and
exit status. A healthy log reaches `Content ran for a total of` and `Unloading
core`; a log ending at SET_GEOMETRY is not a usable recording. Inspect boot,
content progression and tail via `tools/extract_verification_frames.sh` and its
fresh manifest. Do not make listening claims from waveform/packet checks.

A recording request is complete with its file and concise result. Do not create
HUD, timeline, mixline, Gist or upload outputs automatically.

## Conditional qualification

For upload or requested playback diagnosis, read
[qualification.md](references/qualification.md). Use the full DEBUG HUD loop,
or the release evidence chain, without inventing or transplanting a gate.
HUD images/publication are separate requested deliverables.
When the recorder/core/settings changed or a capture is suspect, the same
reference describes exact realtime/offline comparisons. Routine captures do not
repeat that qualification. Pass the lossless file to `compilation` only when
upload was requested. Report file, duration, raster, audio, startup preservation,
and any checks actually performed.
