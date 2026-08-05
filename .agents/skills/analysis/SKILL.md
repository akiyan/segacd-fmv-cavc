# /analysis: update the analysis overlay as one atomic set

Use this whenever you change ANYTHING in the analysis frame (a meter, a colour,
a category, a timeline, a heading, the effective-Band definition, etc.). It
keeps the code, its specification comments, and the user notification in
lockstep so the "what does this number mean" understanding never drifts again.

The analysis frame is 1920x1080, drawn by `tools/render_analysis.py` using the
drawing functions and layout constants in `tools/layout_preview.py`
(the layout source of truth). Semantic colours and category-border styles live
only in `tools/analysis_style.py` and are shared with the sim category map and
the whole-movie timeline. Those source files and their comments are the
reference; there is no separate analysis Markdown specification.

## The set (do both, in order)

1. **Change the layout in `tools/layout_preview.py`** (the source of truth).
   Change semantic colours or category-border styles in
   `tools/analysis_style.py`, never as renderer-local constants.
   Then propagate the same change to `tools/render_analysis.py`, which reuses
   `layout_preview`'s drawing helpers on real encoder data. Anything the real
   renderer needs that the encoder must supply (a new per-frame value, etc.)
   goes into `tools/sim.py` and its saved `stats.npz` /
   `buffer_remaining.npz`, and is read back in `render_analysis.py`.
   `.agents/skills/timeline/scripts/render_timeline.py` imports
   `analysis_style.LEGEND_ORDER` and `REQ_TIMELINE_CATS` directly, so any
   category change must be propagated there (TSV columns, required/optional
   column sets) in the same change.

2. **Regenerate and eyeball the dummy preview**:
   ```sh
   tools/python.sh tools/layout_preview.py     # writes tmp/layout_preview.png
   ```
   Crop and view the changed region to confirm it looks right. If the change
   depends on real encoder values (e.g. a value newly saved by the sim), also
   render one real frame to verify - respecting the shared-machine tokens
   (see AGENTS.md "Shared-Machine Resource Tokens and Profile Isolation"):
   ```sh
   tools/python.sh tools/render_analysis.py profiles/PROFILE.toml <N> <N+1>
   # frame range only: PNGs, no mp4
   ```
   The profile TOML is a required first positional argument; it also selects the
   sim working directory through its `[output].directory`. Do not substitute a
   working directory with `CBRSIM_OUT`.

   Update the owning source comments in the same change.  Keep panel-reading
   rules and scales in `layout_preview.py`, category meanings and colours in
   `analysis_style.py`, and real-data/TSV/mux timing in `render_analysis.py`.
   Be especially precise about the tile categories (Raw/Same/Near/Flbk/Miss,
   Scrl on a scroll movie, and the physical sources) plus the hardware-scroll
   indicator: their meaning, byte cost, thresholds, and
   selection order.

Show the preview image in the chat response so the layout change can be
reviewed there.

## Then

- Commit `tools/analysis_style.py`, `tools/layout_preview.py`,
  `tools/render_analysis.py`, and any `tools/sim.py` change together (Japanese
  commit message per AGENTS.md). Push only if asked.

## Notes

- Do not move the specification away from the code that implements it.
- Layout edits start in `layout_preview.py`; `render_analysis.py` mirrors them.
- Meter widths are each label-width (no unified width). Band is useful
  `BODY.DAT` delivery in the physical slot (payload + control, excluding pad,
  HEADER, and frame 0) divided by that slot's physical CD read time. Full-scale
  is CD 1x (150 KiB/s), with pad shown as blank bandwidth.
- If a new value must come from the encoder, add it to the sim's saved npz and
  read it in `render_analysis.py`. Do not infer physical delivery metrics from
  older sim outputs; require a re-sim when the trace is absent.
