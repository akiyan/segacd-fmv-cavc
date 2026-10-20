# Single name-table playback diagnostics

## Lossless-recording tearing detector

`detect_tearing.py` uses the exact `capture_first..capture_last` spans in a
matching DEBUG HUD TSV and the frame-aligned transfer TSV extracted from that
recording's GPGX LOGVDP sidecar. It excludes the two HUD rows and records
within-group visual changes as a diagnostic. The pass/fail result checks the
specific single-table risk directly: every name-table DMA word must transfer
in blanking, with zero words in active display. This avoids misclassifying
pattern DMA, palette work, or a capture-boundary transition as an NT tear. The
video input must be the native FFV1 lossless recording, not a compressed
preview.

```sh
tools/python.sh harness/single_name_table/detect_tearing.py \
  /path/to/printed/PROFILE_emu_lossless.mkv \
  logs/<run>_hud.tsv \
  --gpgx-vdp-tsv logs/<run>_gpgx_vdp.tsv \
  --output logs/<run>_single_nt_tearing.tsv
```

The output is a per-movie-frame TSV. `PASS` means that frame's name-table DMA
has zero active-display words. `TEAR` records a nonzero active-display count.
`visual_status`, the unique-raster count, outlier count, and maximum changed
pixels preserve the independent image diagnostic without changing the NT
result.

## Saved aggregate comparison

`compare_aggregates.py` compares two already-recorded builds without running
the simulator or emulator. It validates equal frame axes, then emits one TSV
containing every numeric column's count, sum, mean, median, minimum, maximum,
last value, and nonzero-frame count for both the complete movie and timed
frame scopes. It also flattens every HUD gate JSON field and preserves the
simulator's final summary lines, including `starved_frames`.

```sh
tools/python.sh harness/single_name_table/compare_aggregates.py \
  --main-timeline logs/MAIN_timeline.tsv \
  --candidate-timeline logs/CANDIDATE_timeline.tsv \
  --main-hud logs/MAIN_hud.tsv \
  --candidate-hud logs/CANDIDATE_hud.tsv \
  --main-gate logs/MAIN_hud_gate.json \
  --candidate-gate logs/CANDIDATE_hud_gate.json \
  --main-sim-log logs/parallel-run/MAIN/PROFILE.log \
  --candidate-sim-log logs/parallel-run/CANDIDATE/PROFILE.log \
  --candidate-sim-report /path/to/completed-sim/data/report.txt \
  --output logs/PROFILE_main_vs_candidate_aggregates.tsv
```

When a pipeline reused a completed sim and therefore did not repeat its final
summary in the pipeline log, pass that existing sim's `report.txt` with the
optional `--main-sim-report` or `--candidate-sim-report`. Report values
supplement the log; no encode is started.

The adjacent JSON receipt records every input hash and explicitly states that
no simulation was rerun.
