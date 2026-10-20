---
name: timeline
description: "Render a whole-movie codec timeline when requested, including /timeline, or as a requested visual tuning comparison. Do not trigger automatically on every encoder edit."
---

# Codec timeline

Use the TSV from the exact encode and its matching profile/sim metadata. If
only the timeline is needed, produce the TSV without an analysis MP4:

```sh
tools/python.sh tools/render_analysis.py profiles/PROFILE.toml --tsv-only
tools/python.sh .agents/skills/timeline/scripts/render_timeline.py \
  logs/RUN_timeline.tsv --config profiles/PROFILE.toml \
  --sim-out "$SIM_OUT" --label "comparison label"
```

Use printed workspace PNG and persistent layout receipt paths. Inspect the
image and show it with a clickable file link. Keep complete frame coverage and
comparable Req/Supply/Band scales; frame 0 is untimed. `--evaluation-end-frame`
marks an intentional excluded tail without dropping it. An optional matching
`--r2v-workload-tsv` cross-checks packed transfer work.

Read [rendering.md](references/rendering.md) when changing renderer semantics or
interpreting detailed rows. The canonical renderer and analysis_style.py own
geometry/colours; do not rebuild them with a one-off plot. Prg is physical
occupancy; the quality budget is not a buffer meter.

Only for requested publication, use `scripts/publish_gist.py PNG --description
TEXT` and retain its receipt. A show-timeline request alone does not publish
source imagery. For authorized video-description updates use
`scripts/sync_youtube_description.py`; read YOUTUBE.md for metadata placement.
`--local-only` prepares a description without editing a live video.
