# PrgBuf low-water / playback-slip correlation

This harness separates two similarly shaped but different measurements:

- Timeline `status_prg` is the packer's modeled end-of-frame PrgBuf occupancy.
- H40 DEBUG HUD `Q` is the player's live signed minimum logical balance reached
  during that frame, in exact 32-byte patterns.

The timeline can look like zero on its fixed whole-movie scale while still
holding a small positive amount. Only `Q=0000` proves that the live logical
balance reached exactly empty. Raw `Q=FFFF` means -1 pattern, not a nearly full
ring.

## Why signed live balance matters

The physical player uses circular head and tail pointers. If consumption gets
ahead of delivery by one pattern, unsigned modulo subtraction aliases that
logical -1 balance to `RING_PATTERNS - 1`, which looks almost full. Pump
back-pressure may then reject later payload sectors and turn one short
Sub-CPU service delay into a later `S` / reseek event. The `Q` tracker records
the signed balance independently so this possibility can be confirmed or
rejected without changing playback scheduling or image-quality settings.

`Q` is diagnostic only. It does not change the `S/D/R/M/J` upload gate.

## Usage

Analyze the timed part of H40 Bad Apple while excluding the terminal drain:

```sh
tools/python.sh harness/prgbuf_low_water/analyze.py \
  logs/TIMELINE_timeline.tsv logs/HUD_hud.tsv \
  --evaluation-end-frame 6422 \
  --low-patterns 256 \
  --ranges-tsv tmp/bad-apple-h40/prgbuf_low_ranges.tsv \
  --events-tsv tmp/bad-apple-h40/prgbuf_slip_events.tsv
```

The range table reports each modeled low-water interval and the next cumulative
`S` / `R` transition. The event table preserves the model and live `Q` values
at every transition. The console summary separately reports every contiguous
live-`Q` low-water interval and the distance from its end to the next `S`
transition. Both file outputs are UTF-8 TSV.

Run the focused tests with:

```sh
tools/python.sh -m unittest harness/prgbuf_low_water/test_analyze.py
```
