# WordBuf Ring Measurement Gate

This harness preserves the pre-implementation evidence required before
converting WordBuf0 and WordBuf1 from finite boot-preload streams into
refillable rings.

## Short prospective profile

`profiles/issue64-bad-apple-short.toml` keeps the qualified Bad Apple H40
geometry, preprocessing, 30 fps cadence, cold cap 210, raw prefetch, and
MOSAIC-GM palette settings. Only the duration is shortened to 60 seconds and
the output directory is isolated for this harness. The qualified full encode
first reaches PrgBuf pressure at about 54 seconds, so this excerpt includes
both the long early delivery-spare interval and the start of the pressure
interval while avoiding the remaining 159 seconds.

`profiles/issue64-sonic-short.toml` is a 45-second secondary case with the
qualified Sonic settings. It reaches PrgBuf pressure but has far less early
delivery spare, making it useful as a negative/control case for policies that
move the boot WordBuf contents too early.

Run it with the managed GPU environment:

```sh
tools/python.sh tools/encode_config.py \
  harness/wordbuf_ring/profiles/issue64-bad-apple-short.toml --print-stem
tools/python.sh --gpu tools/sim.py \
  harness/wordbuf_ring/profiles/issue64-bad-apple-short.toml
```

## Baseline measurement

The measurement reads frozen decision logs, independently replays the physical
slot allocator, and writes one UTF-8 TSV row per case. It reports PrgBuf peak
and minimum occupancy, underflow/overflow counts, Prg and Word cold
distributions, run distributions, and the exact run cost caused only by
Prg/Word source boundaries. The last value is measured by mapping existing
Word sources back to Prg while preserving slot order and DicBuf boundaries.

```sh
tools/python.sh harness/wordbuf_ring/measure_baseline.py \
  --case bad-apple-full \
    videos/BadApple_H40_320x224_adpcm22_cold210/tmp/decisions.pkl \
  --case sonic-full \
    videos/SonicJamOp_H40_288x200_adpcm22_cold210/tmp/decisions.pkl \
  --case sonic-short \
    videos/SonicJamOp_H40_288x200_adpcm22_issue64_short/tmp/decisions.pkl \
  --case bad-apple-short \
    videos/BadApple_H40_320x224_adpcm22_issue64_short/tmp/decisions.pkl \
  --output harness/wordbuf_ring/baseline.tsv
```

`baseline.tsv` is generated evidence and is intentionally not committed.
Record stable conclusions below after each design-generation measurement.

## Refillable-ring model

`model_ring.py` replays a frozen encode without changing any image decision.
It merges the old finite Word credits back into the candidate cold stream,
keeps DicBuf and raw prefetch fixed, and assigns only complete physical
slot-contiguous runs to either PrgBuf or the parity-matched WordBuf. A source
choice therefore cannot introduce a new Main transfer run.

The model charges every refill as ordinary 32-byte BODY payload. The routing
byte's two reserved high bits carry zero to three complete Word payload
sectors at the front of that slot, so refill does not enlarge the control
stream or insert pad into either FIFO. Only the first capacity-limited contents
of each WordBuf are boot-free. Timed delivery fills PrgBuf first; complete
physical runs can use the currently owned WordBuf only when the next complete
Prg sector does not fit. Both WordBufs have independent occupancy and deadline
checks.

```sh
tools/python.sh harness/wordbuf_ring/model_ring.py \
  --decisions \
    videos/BadApple_H40_320x224_adpcm22_issue64_short/tmp/decisions.pkl \
  --output /tmp/issue64-ring-model.tsv
```

## Decision rule

Proceed with a refillable-ring implementation only when both conditions hold:

1. the full profiles show that PrgBuf time-shifting depth is genuinely tight,
   rather than merely full at startup; and
2. the short profile shows a planner policy that improves supply without
   creating a Main-CPU run increase large enough to erase that benefit.

Whole physical runs, not scattered individual patterns, are the preferred
unit for prospective WordBuf assignment because every Prg/Word boundary
creates another Main transfer run.

## Gate result

The qualified full encodes both reach a 64-pattern (2 KiB) PrgBuf evaluation
minimum without underflow. Their current individual-pattern Word assignment
adds 7,554 source-boundary runs in Bad Apple and 8,268 in Sonic.

The 60-second Bad Apple case reaches a 128-pattern (4 KiB) baseline minimum.
The sector-granular ring model completes every deadline while:

- retaining the 5,376-pattern boot WordBuf contents;
- staging and consuming another 5,376 WordBuf patterns from timed BODY;
- keeping every model source assignment on a complete physical run; and
- reducing 25,954 current runs to the 19,715 source-merged minimum, with zero
  model-added runs.

This passes the implementation gate. The Sonic case remains the adverse case:
its small early delivery spare cannot support moving the complete boot
allocation to the beginning, so the implementation must retain a
deadline-aware choice between finite boot contents and later refill rather
than applying one policy blindly to every source.
