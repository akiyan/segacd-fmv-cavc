# Pattern supply replay

This harness independently verifies the version-23 boot-preloaded pattern
supplies and the O_LOADS v2 handoff.
It does not import the production packer, scheduler, or planner.

The player has four pattern sources:

- `PrgBuf`: the existing streamed PRG-RAM circular buffer.
- `WordBuf0`: immutable patterns in the physical Word-RAM bank handed to Main
  for even movie frames.
- `WordBuf1`: the corresponding bank for odd movie frames.
- `DicBuf`: a persistent 512-entry dictionary copied once into Main RAM.

On-disc cold entries use the otherwise unused name-table flip bits to identify
`Prg`, `Wr`, or `Dic`. Cold-run descriptor source `2` addresses Dic entries
0--255 and source `3` addresses entries 256--511. Together with the remaining
index bits, the descriptor carries a 9-bit DicBuf start index without growing.
A Dic run must split at the 256-entry boundary.
`Wr` resolves to `Wr0` or `Wr1` from movie-frame parity.
Timed raw-prefetch records have no corresponding name-table update. They follow
the visible cold records as a separately slot-sorted Prg suffix. The verifier
requires that suffix and every 32-byte pattern to match the frozen request slot
and key in `decisions.pkl`; frame-0 inline and boot-sidecar records are split
and checked independently.

Run the independent whole-stream proof against an already packed profile:

```sh
SIM_OUT="$(tools/python.sh tools/encode_config.py \
  profiles/bad-apple.toml --print-sim-output)"
tools/python.sh harness/pattern_supply/verify.py \
  --header out/bad-apple/HEADER.DAT \
  --body out/bad-apple/BODY.DAT \
  --decisions "$SIM_OUT/decisions.pkl"
```

The verifier parses every HEADER and BODY sector, reproduces rate-slot
boundaries, validates source-coded visible and raw-prefetch runs, consumes each
physical source in exact player order, and checks every cold and reused VRAM
pattern against the decision log. It also requires every consumptive preload
and every useful Prg pattern to be consumed exactly once, while DicBuf entries
may be reused by index.

Run this proof again after every current full encode.
