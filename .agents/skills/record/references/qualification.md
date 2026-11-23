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

When the fork build, recorder, or timing settings change, or the result is
suspect, record two offline captures of the same disc, BIOS, fork binary and
frame-indexed input. Request `--vdp-event-log` for both. Compare the files:

```sh
tools/python.sh tools/compare_recordings.py "$CAPTURE_A" "$CAPTURE_B" \
  --json /path/to/comparison.json
cmp "$VDP_A" "$VDP_B"
```

The comparator checks decoded video, PCM, packet timing, metadata, and counts
from startup through the final scanout. Use the run receipts to verify that the
captures used the same inputs. The launcher receipt binds the final bounded
MKV under `lossless_recording` and names the VDP trace under `vdp_event_log`.
Use untrimmed captures to match scanouts directly. For a concurrency change,
compare against the single-instance result using the same method.
