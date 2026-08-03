# Edge-fringe dither A/B harness

This harness measures the one-pixel fringe around strong source-image edges.
It compares edge-attenuated Bayer quantization with no edge-map expansion and
with the active expansion radius, then compares two matching DEBUG recordings.

The recordings are aligned by content frame through their schema-16 HUD TSVs,
not by wall-clock timestamps. The top 16 raster lines are excluded because the
DEBUG HUD changes those pixels. Recording error is measured only at pixels
where expansion changes the RGB333 result toward ordinary nearest rounding.
This is a focused regression signal, not a general picture-quality score.

Run it with matching master inputs and recordings:

```sh
tools/python.sh harness/dither_flicker/analyze.py MASTER_DIR \
  --old-recording OLD.mkv --old-hud-tsv OLD_hud.tsv \
  --new-recording NEW.mkv --new-hud-tsv NEW_hud.tsv \
  --end-frame FRAME --tsv logs/RUN_dither_flicker.tsv
```

The TSV contains one row per content frame. The summary reports how many
nearest-rounding deviations and consecutive-frame deviation toggles remain,
plus the actual-recording luma error at the corrected fringe pixels.
