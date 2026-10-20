---
name: analysis
description: "Edit the codec analysis overlay layout, labels, colours or metric presentation when requested, including /analysis. Not a trigger for general investigation or every encoder change."
---

# Analysis overlay edits

Edit the owner of the requested presentation:

- `tools/layout_preview.py`: layout and reading rules.
- `tools/analysis_style.py`: category semantics/colours shared with timelines.
- `tools/render_analysis.py`: real data, TSV and mux timing.

Change owning comments with the implementation. If the metric needs new sim
output, update its writer/readers together; never infer absent physical traces
from unrelated old fields. An unavailable trace requires reporting that limit,
not an unauthorized re-encode.

Render `tools/python.sh tools/layout_preview.py` for the dummy preview. When
existing matching data is available and the change depends on it, render a
single real frame with `tools/render_analysis.py PROFILE N N+1`. Inspect and
show the changed region. A layout edit does not require a full video render.
Keep aligned category/TSV consumers in sync. Commit/push only under the user's
Git scope; editing the overlay does not imply publication.
