---
name: hudline
description: "Plot an existing DEBUG HUD TSV and its matching gate for requested playback diagnostics or /hudline. A normal recording does not automatically invoke this skill."
---

# Playback HUD timeline

Require the TSV and schema-16 gate from the same lossless capture. Failed gates
may be plotted honestly; an incomplete loop retains the expected axis and
shades missing frames. Do not create another recording to make an image.

```sh
tools/python.sh .agents/skills/hudline/scripts/render_hudline.py \
  logs/RUN_hud.tsv --gate-json logs/RUN_hud_gate.json \
  --config profiles/PROFILE.toml --label "run label"
```

For a matching LOGVDP trace, extract its frame TSV with
`harness/gpgx_logvdp/extract_frame_tsv.py` and pass `--gpgx-vdp-tsv` only with
valid identity/alignment evidence. Inspect the printed PNG, expected/observed
frames, labels and limits, then show the image and link its persistent receipt.
Frame 0 is excluded from timed statistics; terminal hold is not cadence data.

Use `scripts/report_overages.py` when an event list is needed. Read
[rendering.md](references/rendering.md) for the detailed row/gate contract when
interpreting warnings or editing rendering. Wait/decode counters are diagnostics;
compare their distributions rather than equating waiting with failure.

Invoke `mixline` only when the combined view is requested and an exact matching
codec timeline is available. Publish images only within explicitly requested
publication scope; showing a local diagnostic does not authorize a public Gist.
