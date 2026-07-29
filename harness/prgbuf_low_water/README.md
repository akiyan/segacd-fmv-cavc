# PrgBuf low-water / playback-slip correlation

This harness correlates the packer's modeled end-of-frame PrgBuf occupancy
(`status_prg`) with retained playback diagnostics from the descriptive HUD
TSV. It does not claim that the model is a live ring measurement.

The playback side uses:

- `sector_slip` and `audio_resync` cumulative transitions;
- `pump_gap_ticks`, the longest interval outside a Sub CDC pump opportunity;
- `apply_backpressure`, which records an APPLY queue rejection;
- `msf_gap_recoveries`, the MSF-gap subset of `sector_slip`;
- `capture_first`, which reveals extra display scanouts.

The tool derives transport retry recoveries from
`sector_slip - msf_gap_recoveries` modulo the one-digit counter. All retained
fields are diagnostic and do not change playback behavior.

## Usage

Analyze the timed part of H40 Bad Apple while excluding the terminal drain:

```sh
tools/python.sh harness/prgbuf_low_water/analyze.py \
  logs/TIMELINE_timeline.tsv logs/HUD_hud.tsv \
  --evaluation-end-frame 6422 \
  --low-patterns 256 \
  --normal-vblanks 2 \
  --ranges-tsv tmp/bad-apple/prgbuf_low_ranges.tsv \
  --events-tsv tmp/bad-apple/prgbuf_slip_events.tsv
```

The range table reports each modeled low-water interval and the next
`sector_slip` / `audio_resync` transition. The event table preserves the model
state and retained diagnostics at every transition. When the optional pump
and capture columns are present, the report also includes pump-gap statistics,
APPLY back-pressure frames, recovery causes, and extra capture scanouts. Both
outputs are UTF-8 TSV.

Run the focused tests with:

```sh
tools/python.sh -m unittest harness/prgbuf_low_water/test_analyze.py
```
