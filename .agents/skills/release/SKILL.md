---
name: release
description: "Build a HUD-free release disc or record HUD-free playback when explicitly requested, including /release. Publication qualification applies only when the capture will be uploaded."
---

# HUD-free build and recording

`DEBUG=0` selects the HUD-free player; it does not change encoded video.
Use the existing matching decisions/stream. An ISO-only request ends with the
ISO/cue; it does not require a recording or a fresh encode.

```sh
make disc CONFIG=profiles/PROFILE.toml DEBUG=0
```

Release images use `out/PROFILE_release.iso` and `.cue`. For recording:

```sh
tools/record_movie.sh --config profiles/PROFILE.toml --release-build \
  --seconds N --tag STEM_rel
```

Follow `record` for capture mechanics. Use the same BIOS, fork binary and
frame-indexed input for the DEBUG and release qualification runs.

## Publication evidence

For upload, retain a complete-loop PASS DEBUG capture of the same stream and
player version, its gate, and both BlastEm run receipts. Capture both with
`--vdp-event-log` and startup/tail intact. Compare the hashes of HEADER.DAT,
BODY.DAT, paltab.bin and palidx.bin from the DEBUG and release disc builds.

```sh
tools/python.sh .agents/skills/release/scripts/compare_blastem.py \
  --baseline "$DEBUG_RECEIPT" --release "$RELEASE_RECEIPT" \
  --baseline-gate "$DEBUG_GATE" --header "$HEADER" \
  --json logs/STEM_release_vdp.json
```

The receipts identify the recordings and their VDP logs. The trace aligns
movie publications, and the comparison checks their recorded pixels with the
DEBUG overlay area masked. Review
any cadence differences and inspect lossless boot, advancing content and tail
to confirm the HUD is absent. Retain the report and the stream hashes.
If evidence is missing, report the scope actually verified. For an authorized
upload, pass the evidence and lossless file to `compilation`.
