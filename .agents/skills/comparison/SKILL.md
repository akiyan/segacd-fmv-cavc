---
name: comparison
description: "Adjust a profile comparison layout, wording, footage or synchronization and show a real-footage preview when requested, including /comparison."
---

# Comparison preview

`[comparison]` in the profile owns text, footage, audio selection and timing.
`tools/comparison_layout.py` owns rectangles, aspect and drawing;
`tools/render_comparison.py` consumes those rectangles in FFmpeg.

Inspect current values with `tools/python.sh tools/comparison_layout.py PROFILE
--print-layout`. Change the owning layer. Derive dimensions from displayed
aspect (H40 320x224 PAR 32:35), not an assumed 4:3. Keep labels/spec lines clear
and positions derived from neighbouring panels.

```sh
tools/python.sh tools/render_comparison.py PROFILE \
  --still /path/to/selected/workspace/preview.png --at 45
```

Use a time with real footage, inspect the result and show the PNG. Use the dummy
`comparison_layout.py --preview PATH` only when footage is unavailable. Check
numeric aspect/alignment after geometry edits; wording alone needs no new tests.

For new footage, use its actual path; measure content start across several cuts
and a late segment. Black-end alone may precede motion. Set source offsets,
lead, input cadence and crop/pad in TOML; do not silently retime a master.
Render the full video only when requested. Preserve valid previous artifacts
until a replacement succeeds. Return preview, affected settings and unresolved
footage/alignment limitations. No uploader or special chat client is required.
