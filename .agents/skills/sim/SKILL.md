---
name: sim
description: "Encode a requested source/profile with the CAVC encoder. Use for /sim or an explicit encode/analysis request; do not invoke for an ISO rebuild, playback-only task, or a general codec question."
---

# Source encoding

Use one profile and retain the printed sim path, command, log and completion
status. `CONFIG.md` owns profile settings; `ENCODE.md` owns stage behavior.

1. Inspect source raster, SAR/DAR, cadence, duration, audio and a content frame.
   Default to H40 320x224 and HAR 32:35-aware fit/pad. Crop detection is needed
   only when removing bars; confirm fixed black margins across separated scenes.
   Keep native cadence and the requested quality settings.
2. Read the profile and explain material changes before expensive work. Validate
   with `tools/encode_config.py`. Use exact intended duration; do not silently
   substitute a short diagnostic clip. Do not add fixed pipeline features as
   profile knobs.
3. Use the pinned environment and explicit storage for long runs:

```sh
tools/python.sh --gpu --workspace-root /path/to/workspace \
  --scratch-root /path/to/ssd/scratch --array-storage disk \
  tools/sim.py profiles/PROFILE.toml
```

CPU mode is available deliberately via `CBRSIM_GPU=0`; do not treat sandbox GPU
invisibility as a host driver failure. Resource/stem locks coordinate jobs.
Reuse authenticated completed artifacts. Never manually clean them or force a
fresh encode unless requested. An incomplete result is not usable pack input;
inspect the failure before deciding whether a restart is necessary.

Completion means the encoder exited successfully and produced its completed
artifact/decision data. Keep physical-prefix or final packing failures visible;
reducing cold cap does not repair an invalid schedule. Do not routinely report
starved-frame percentages. For tuning, compare request and Miss distributions
at the same quality target.

## Optional requested outputs

- Timeline only: `tools/python.sh tools/render_analysis.py PROFILE --tsv-only`,
  then the `timeline` skill. This does not render a full analysis video.
- Analysis video: `tools/python.sh --gpu tools/render_analysis.py PROFILE`.
  Inspect representative frames and media metadata. Layout/colours are owned
  by `layout_preview.py` and `analysis_style.py`, not this prompt.
- Audio panels/mux use `stats.npz:audio_playback_file`, the modeled RF5C164 output;
  never choose the first audio filename alphabetically.
- Upload only within the requested scope, using `YOUTUBE.md`. An encode-only
  request ends with the sim artifacts; it does not imply recording or upload.

Report actual frame count, raster/cadence, elapsed time and requested artifact
links. Explain limitations separately from completed results.
