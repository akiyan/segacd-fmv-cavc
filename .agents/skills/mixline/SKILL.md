---
name: mixline
description: "Combine matching codec timeline and playback HUD images when requested or via /mixline. Publication is separate from local rendering."
---

# Combined timeline

Use both PNGs and their content-keyed layout receipts from the same encode and
recording. Regenerate an evicted image from its TSV; a receipt alone is not an
image. The renderer rejects mismatched hashes, frame count, fps and geometry.
Never resize or shift graphs to disguise an alignment mismatch.

```sh
tools/python.sh .agents/skills/mixline/scripts/render_mixline.py \
  "$TIMELINE_PNG" "$HUDLINE_PNG" \
  --timeline-layout logs/RUN_timeline-layout.json \
  --hudline-layout logs/RUN_hudline-layout.json
```

Inspect the printed PNG for a shared frame axis, the timeline/optional LOGVDP/
HUD order and visible gate status. Show the local image and receipt. Read
[rendering.md](references/rendering.md) only when changing the compositor or
investigating its row/header contract; source renderers own their geometry.

When public publication is requested, use
`.agents/skills/timeline/scripts/publish_gist.py` and return the Gist receipt/URL.
A local comparison request does not itself authorize external writes.
