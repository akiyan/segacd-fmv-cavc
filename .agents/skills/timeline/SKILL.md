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

Gist publication is optional. Use `scripts/publish_gist.py PNG --description
TEXT` only when the user explicitly requests Gist as the destination; retain
its receipt. Showing a timeline or uploading a video to YouTube does not
request a Gist upload. Local rendering needs no GitHub credentials. Read
YOUTUBE.md for optional links to already published images on any host.
`scripts/sync_youtube_description.py` is a separate helper for explicitly
requested updates from an existing Gist receipt; `--local-only` avoids editing
a live video.
