# Recording qualification

## Complete DEBUG loop for publication or diagnosis

```sh
tools/python.sh harness/startup_resync/analyze.py \
  "$LOSSLESS" profiles/PROFILE.toml --expected-frames FRAME_COUNT
```

Use the printed persistent TSV/gate paths. The descriptive schema-16 gate must
match this recording's path, size and mtime and include every expected frame.
`PASS` permits alert NONE or WARNING; FAIL must not be described as qualified.
`sector_slip`, `control_desync` and `audio_resync` stay zero. The checker owns
cadence-specific jitter and warning limits; do not duplicate or loosen them.
Keep the frame-minus-one anchor as evidence of complete startup, not a trim cue.
`cd_wait_count` is diagnostic. When discussing waits, preserve minimum, mean,
median and maximum together with `adpcm_decode_units` and `pump_gap_ticks`.
Report relevant warnings; do not hand-edit gates to continue a pipeline.

Use `hudline` or `mixline` when those images are requested. A local gate failure
does not authorize publishing private source images to a public Gist. A
HUD-free capture uses the `release` chain and has no HUD gate of its own.

## Recorder requalification

Only when RetroArch/core/recording timing/settings change or results are
suspect: record one realtime-lossless and two offline captures of the **same
Replay**, disc and configuration. Compare each offline result to the realtime
capture using:

```sh
tools/python.sh tools/compare_recordings.py "$REALTIME" "$OFFLINE" \
  --json /path/to/comparison.json
```

The comparator checks every decoded video frame, PCM sample, packet timing,
metadata and counts without alignment/trimming. The Replay-generation run is
not the realtime baseline: its initial-state audio boundary may differ by a
sample. Before increasing emulator concurrency, compare concurrent runs with
the one-instance baseline in the same way.
