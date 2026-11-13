# Player constants build matrix

This harness verifies the disc-specific Main/Sub assembly path without
reusing stale packed movies. It creates current CAVC headers at 15, 24 and
30 fps on the full 40x28 grid, plus a centered 36x25 case at 30 fps and a
15 fps 40x18 scroll/WordBuf-ring build with cold cap 480 and a full-height
24 fps scroll/WordBuf-ring build, and a 19,038-frame 30 fps scroll/WordBuf-ring
build combining long routing with audio-rate dithering. The long combined case
catches resident Sub overflow missed by testing those features separately.
The harness generates `player_constants.inc`, then assembles and links both the generic and
specialized DEBUG players.

For every case it requires:

- the full 64-segment PALTAB and 64-entry PALIDX fit the transient IP image,
  with the relocated Main-RAM tables below the unchanged DicBuf;
- specialized IP images retain the generic image size; Sub's scroll/WordBuf
  combination is checked against the resident limit even when it exceeds the
  generic reference image;
- the specialized resident SP binary stays within the 5-KiB disc-system
  allocation and the boot header names its exact linked size;
- the extension is linked into the boot-only timed-ring tail, its generated
  size/hash/address contract matches, and its bytes fit after the 8,800-byte
  ADPCM table inside the existing five-sector HEADER preload;
- the specialized SP contains the exact HEADER signature immediate and the
  `0xBAD1` mismatch diagnostic;
- every player publishes one staged movie table without a Plane A reg2 write,
  with NT DMA, DEBUG HUD DMA, optional CRAM, and cadence commit in order;
- every specialized geometry stages only the encoded row width and transfers
  the exact centered 64-pitch band, 1,768 words for the full 40x28 grid and
  1,572 words for the centered 36x25 grid;
- every case starts each weighted transfer budget only at a proven
  VBlank head, withholds the cadence-final name-table/HUD/CRAM reserve before
  pattern work, and retains status, terminal-line, and fresh-VBlank fallback
  guards, and admits publication against the actual remaining blank time
  measured from the physical budget's stopwatch origin;
- CPU-written VDP words cost four DMA-word units, including Word-RAM DMA
  first-word repairs; every pattern run uses DMA and every run crossing the
  residual budget is split at that boundary;
- removed split-off and short-run CPU-transfer symbols are absent from every
  linked player, and named live state ends exactly at the BSS section boundary;
- the cadence is generated as N4 at 15 fps, periodic N2/N3 at 24 fps, and N2
  at 30 fps, and the
  DEBUG snapshot preserves contiguous runtime word counters for transfer
  VBlanks 1 through 4;
- fixed-N builds call the assembled debt-repayment path, preserve one VBlank
  of lateness and retain the one-VBlank minimum interval; whole-frame admission runs before any shortened
  display reservation, includes one bounded active allowance, and existing
  DMA admission checks still apply;
- the DEBUG reserve includes the 52-word Window/SAT HUD workload, while
  release omits it;
- generic and specialized builds begin the next bank exchange after their last
  Word-RAM access; final-only runs retain the bank through their publication
  blank, and the empty final path never reads a bank already returned early;
- fixed and periodic EAT/LAT admission uses the physical publication-blank origin,
  rejects expired intervals and repeated grants in one physical active period,
  starts without a flip-arm/midpoint wait,
  and retains the 672-unit cap and late-line cutoff;
  shared-blank time admission includes the complete deferred pattern/setup
  cost, and the deferred tail has no refill/wait path after destructive writes begin;
- single-movie replay publishes black frame -1 before waiting for the boot
  stage, whose sidecar writes would otherwise overwrite the live final display;
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


## Full BBB playback qualification

The e202/p176 DEBUG player reuses the same 19,038-frame Big Buck Bunny stream
as p174: 320x224, 30 fps, cold cap 210. No source encode or transfer-budget
increase was used. BODY.DAT is byte-identical
(`3446d5edd6762b2688895e1f21000aa66f8cb3bfb329fb62da8fbb37a7e0bcf3`).

The p174 display accumulated 37 VBlanks of lateness before APPLY blocked the
continuous CD reader at frame 9359. Sector slip followed at frame 9361.
Including active capacity in recovery admission and sharing a sufficiently
large final blank alone did not fix this: the p175 trial still slipped.
Reducing Main's repeated run setup in p176 keeps the maximum observed debt at
11 VBlanks and returns it to one by the final frame. The physical CD schedule
has zero cumulative rate lead; no buffer capacity was increased.

| Complete first-loop result | p174 | p176 |
|---|---:|---:|
| Sector-slip peak | 6 | 0 |
| Control-desync peak | 0 | 0 |
| Audio-resync peak | 2 | 0 |
| APPLY backpressure observed | Yes | No |
| Interior irregular display intervals | 3895 | 191 |
| Edge irregular display intervals | 2 | 0 |
| HUD gate | FAIL | PASS / WARNING |

The remaining 191 intervals consist of 96 three-VBlank holds and 95
one-VBlank recovery steps. This is not uniform two-VBlank cadence. The exact
recording's LOGVDP trace covers all 19,038 frames and matches the encoded final
tail loads. Final-tail, movie-table, HUD and CRAM writes have zero active or
ambiguous-boundary words. Native FFV1/FLAC capture, frame counts and
representative startup/content/credits/loop frames were checked; this does not
establish real-hardware timing.

Local evidence is indexed by `logs/bbb-p176-result.json`, with the untouched
failed p175 gate alongside the successful p176 gate. The p176 recording wrapper
was interrupted during post-capture frame counting after a normal emulator
shutdown. Its existing native capture was verified and remuxed with stream
copy; the recovery receipt preserves both the interruption and completed
checks. No second capture or source encode was needed for that recovery.
