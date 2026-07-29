# Player constants build matrix

This harness verifies the disc-specific Main/Sub assembly path without
reusing stale packed movies. It creates current TTRC headers for H32 and H40
at 15, 24 and 30 fps, plus a centered H40 36x25 case, generates
`player_constants.inc`, then assembles and links both the generic and
specialized DEBUG players.

For every case it requires:

- specialized IP and SP binaries do not grow relative to the generic build;
- the specialized resident SP binary stays within the 8,192-byte disc-system
  allocation and the boot header names its exact linked size;
- the extension is linked into the boot-only timed-ring tail, its generated
  size/hash/address contract matches, and its bytes fit after the 8,800-byte
  ADPCM table inside the existing five-sector HEADER preload;
- the specialized SP contains the exact HEADER signature immediate and the
  `0xBAD1` mismatch diagnostic;
- Main's specialized flip branches stay inside their local regions, and the
  final guard performs status, V-counter tail, second-status, fresh-wait, then
  the Plane A reg2 write in that order;
- fixed-N H40 name-table DMA stages only the encoded row width at the
  generated center offset and transfers the complete zero-bordered 40x28
  visible aperture;
- fixed-N H40 starts each 3,200-unit weighted transfer budget only at a proven
  VBlank head, withholds the cadence-final name-table/CRAM/flip reserve before
  pattern work, and retains status, terminal-line, and fresh-VBlank fallback
  guards;
- CPU-written VDP words cost four DMA-word units, including Word-RAM DMA
  first-word repairs; every pattern run uses DMA and every run crossing the
  residual budget is split at that boundary;
- removed split-off and short-run CPU-transfer symbols are absent from every
  linked player, and named live state ends exactly at the BSS section boundary;
- the fixed cadence is generated as N2 at 30 fps and N4 at 15 fps, and the
  DEBUG snapshot preserves contiguous runtime word counters for transfer
  VBlanks 1 through 4;
- the fixed-N H40 DEBUG reserve includes the complete 39-cell HUD staging
  allowance;
- the specialized 15 fps ADPCM decoder services the CDC during its long decode,
  while the 30 fps decoder contains no such call or counter overhead;
- all geometry/timing/audio/supply combinations assemble and link
  successfully.

Run it with the project Python environment:

```sh
tools/python.sh harness/player_constants/verify.py
```

The script uses a temporary directory under `tmp/` and removes it after the
matrix completes. It does not depend on copyrighted source video or a prior
simulation.

Measure the conservative instruction-cycle saving over a real fixed-N2 packed
stream with:

```sh
tools/python.sh harness/player_constants/measure_cycles.py \
  --header out/sonic-jam-op/HEADER.DAT \
  --body out/sonic-jam-op/BODY.DAT
```

The cycle model uses the MC68000 User's Manual Section 8 timings. It counts all
real packed cold runs but deliberately excludes variable extra savings from
CDC polling, wave-chunk boundaries, DMA-budget refills and palette switches.
The result is therefore a lower bound for the current player, not the stale
1,400-cycles-per-frame estimate from before Main code generation was added.
