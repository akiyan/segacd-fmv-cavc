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
  --seconds N --tag STEM_rel --record-size 320x224
```

Follow `record` for capture mechanics. Generate a Replay for this disc rather
than reusing the DEBUG binary's Replay. Use configured runtime roots.

## Publication evidence

For a qualified upload, retain the complete-loop PASS DEBUG baseline of the
same stream/player version, its gate, and both recordings' logs. Record hashes
of HEADER.DAT, BODY.DAT, paltab.bin and palidx.bin before building release;
require the rebuilt stream bytes to match. A discrepancy needs investigation,
not an automatic source re-encode.

```sh
tools/python.sh .agents/skills/release/scripts/compare_logvdp.py \
  --baseline "$DEBUG_LOG" --release "$RELEASE_LOG" \
  --json /path/to/release_logvdp_compare.json
```

This compares actual player DMA/error traces. Keep the tool's tolerance;
removing HUD lowers total DMA, so active-display percentage alone is not a
regression measure. Inspect lossless boot, advancing content and tail, and
confirm the HUD is absent. Preserve matching stream hashes, baseline gate,
LOGVDP comparison and visual evidence. A release capture has no HUD gate of
its own. If the baseline is absent, report the missing qualification and act
within the user's recording/validation scope; do not add an unrequested full
pipeline. For authorized publication, pass the evidence and lossless file to
`compilation` without a redundant approval pause.
