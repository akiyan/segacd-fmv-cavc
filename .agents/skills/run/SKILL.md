---
name: run
description: "Coordinate encoding, playback recording and publication when the user explicitly requests an end-to-end delivery or invokes /run. Do not trigger on a vague request to run a command or inspect an existing artifact."
---

# Complete delivery

Resolve the requested outputs first. `/run SOURCE` means the normal analysis
and playback delivery; explicit omissions such as no HUD, no analysis, timeline
only, no upload, or no re-encode override that default. Do not expand those
omissions back through a child skill. Git operations are not implied.

Keep one source/profile/stem and an artifact record containing resolved paths,
versions, commands, logs and stage results. Read `sim` for a new encode,
`record` for a requested capture, `release` for HUD-free playback, and
`compilation` for publication, only when reaching that stage. Read YOUTUBE.md
when preparing upload metadata.

For the standard DEBUG pipeline, the existing orchestrator retains the stem
lock and artifact lease across stages:

```sh
tools/python.sh --workspace-root /path/to/workspace \
  --scratch-root /path/to/ssd/scratch --array-storage disk \
  tools/parallel_run.py --jobs 1 --through hud profiles/PROFILE.toml
```

Choose `--through` from the actual requested scope. For multiple requested
profiles, pass them together with appropriate `--jobs`; shared resource locks
coordinate independent processes. For a reduced/custom workflow use the
individual tools and retain their locks/leases across handoffs. Do not run a
larger pipeline solely to fit this command template.

Inspect source geometry and current profile once. Reuse authenticated completed
sim artifacts and matching existing recordings. Failed/absent decisions are
not a completed encode. Inspect a failure and resume the affected stage; do not
blindly restart all upstream work or lower quality to hide a model failure.

For a timeline, use `render_analysis.py PROFILE --tsv-only` and `timeline`.
Generate a full analysis MP4, HUD image or mixed image only when requested.
Publication follows the recording/stream evidence contract, and already given
upload permission survives intermediate gate checks. Optional Gist publication
requires that output to be requested; it is not an unavoidable side effect of
showing a timeline.

Complete when every requested output exists and requested uploads return URLs.
Report those artifacts and the checks actually performed. Keep any remaining
failure explicit; do not lead with starvation percentages or routine internal
counter dumps. Preserve incomplete artifacts/logs for diagnosis.
