---
name: record
description: "Capture Sega CD emulator playback as synchronized native lossless video. Use for /record or an explicit recording request. Recording alone does not request analysis, full HUD diagnostics, publication, or a fresh source encode."
---

# Record emulator playback

Use `tools/record_movie.sh` from the repository root. It owns resource locks,
leases, fixed frame-indexed input, native 320×224 FFV1/FLAC, and exit/count
checks. Use the SDL build of the `akiyan/blastem` fork and the matching
user-supplied BIOS. The repository README gives the pinned build instructions.

```sh
tools/runtime.sh --workspace-root /path/to/workspace \
  --scratch-root /path/to/scratch -- \
  tools/record_movie.sh --config profiles/PROFILE.toml --seconds N --tag STEM_emu
```

- Set N from actual movie length plus startup and tail. Allow at least 31
  additional seconds for the default Japanese BIOS.
- DEBUG is the default. A HUD-free request selects `--release-build`. Read
  `release` for publication qualification.
- For a matching disc, use `--disc CUE --no-build`. The recorder uses a
  deterministic START sequence. Use `--input-script FILE` when the BIOS or
  disc needs different input. Preserve startup and tail with `--trim 0`.
- Add `--vdp-event-log` when a matching VDP trace is needed. Keep the
  `BLASTEM_RECEIPT=` and `LOSSLESS=` paths and check successful completion,
  original frame and sample counts, and the final media streams.
- Inspect boot, content progression and tail with
  `tools/extract_verification_frames.sh` and its fresh manifest. Describe sound
  quality only if you listened to the recording.

A recording request is complete with its file and concise result. Do not create
HUD, timeline, mixline, Gist or upload outputs automatically.

## Conditional qualification

For upload or requested playback diagnosis, read
[qualification.md](references/qualification.md). Use the full DEBUG HUD loop,
or the release evidence chain, without inventing or transplanting a gate.
HUD images/publication are separate requested deliverables.
When the recorder/core/settings changed or a capture is suspect, the same
reference describes repeatability checks. Routine captures do not
repeat that qualification. Pass the lossless file to `compilation` only when
upload was requested. Report file, duration, raster, audio, startup preservation,
and any checks actually performed.
