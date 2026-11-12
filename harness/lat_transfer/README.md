# LAT and final-VBlank qualification

This diagnostic checks actual Genesis Plus GX LOGVDP writes, rather than a
Python model of the assembly. It detects a final-only pattern write or movie
name-table, HUD or CRAM write outside VBlank. It reads the first complete movie
loop, including final HUD/CRAM updates, and excludes the next loop's clearing.
Ambiguous scanline edges are reported separately and fail admission evidence.
The parser's address is the first hexadecimal operand of `VRAM ... write ->`;
the second operand is data. Managed input artifacts are leased while reading.

```sh
tools/python.sh harness/lat_transfer/check_trace.py \
  /absolute/path/retroarch_RUN.log /absolute/path/gpgx_logvdp_RUN.log.gz \
  --frames 2714 --tsv logs/RUN-vdp.tsv --sim-out /absolute/path/completed-sim
```

The JSON beside the TSV records input paths and hashes, frame count, the
inferred movie-table DMA site/length, actual write counts, and failing frames.
The matching SIM supplies per-frame scroll-band lengths and final-tail load
counts; the checker requires the actual writes to match those counts. Supply
`--sim-out` for scrolling movies. A shortened/truncated trace cannot pass merely
because no offending write was seen.
Use the logs produced by the matching lossless recording when checking that
capture. The Replay-generation log is a separate execution and must be labeled
as such. A HUD gate checks frame progression, cadence and synchronization;
representative capture frames check the rendered output. Neither this script
nor an emulator recording proves real-hardware DMA timing.

The twelve final-only slots occupy VRAM `0xD880..0xD9FF`. They are destination
storage, not additional CD service or a larger PrgBuf. Compare equal cold caps
first, then test a raised-cap profile without changing raster, cadence,
filters or palette policy. Report request volume alongside Miss distributions:
a larger transfer ceiling can change whole-movie spending without reducing
Miss everywhere.

`harness/player_constants/verify.py` checks actual generic/specialized assembly
and memory bounds at 15, 24 and 30 fps. `tools/test_tile_alloc.py` exercises
old-only reclamation versus next-frame reuse; `tools/test_pattern_supply.py`
checks the real run builder at the phase boundary. Full source encodes,
verified packing and native lossless captures are the explicit qualification
tier; do not repeat them after documentation-only changes.

## Qualified e198/p168 examples

Native 320x224 FFV1/FLAC captures on 2026-11-11 used the unchanged LOGVDP core
`51cfd71f338865288e274b271b8ce0d9a1d3dc415688f14db963a29555d9b4ac`.
All three sources passed verified packing, including cumulative CD-1x prefixes,
physical delivery deadlines, finite buffers, previous-display protection and
the final publication bundle. The trace matched every final-tail word against
the SIM and found zero final-tail, NT, HUD or CRAM writes outside VBlank,
including zero ambiguous edge writes.

| Profile | Cadence / cold cap | Complete frames | DEBUG gate | Cadence warnings outside edge exemption |
|---|---|---:|---|---:|
| `sonic-jam-op-lat` | 30 fps / 240 | 2 x 2,714 | PASS / WARNING | 15 in first loop |
| `lunar-ss-op` | 24 fps / 2:180,3:230 | 2,535 | PASS / WARNING | 247 |
| `machi-op` | 15 fps / 480 | 2,293 | PASS / WARNING | 16 |

Sector slip, control desync and audio resync remain zero in every observed
loop. These are complete-playback and transfer-safety results, not a claim of
perfect cadence. Lunar includes horizontal and vertical scroll windows and
an automatic fade; Machi retains its original crop and automatic fades.
The Sonic player still has the accepted short/long display intervals. Its
first loop has 2,695 two-VBlank, nine three-VBlank and eight one-VBlank interior
intervals. Frame 0 and the terminal hold are excluded from that histogram.

The Sonic transfer peak rises from 210 to 240 patterns (+14.3%); 44 timed
frames actually reach 240. Its source, 288x200 raster, 30 fps, source-dither
filter and palette policy are unchanged. The final-only tail carries 2,207
patterns, with 13 old-only slot reclaims. The current standard Sonic profile selects 230;
the separate `sonic-jam-op-lat.toml` retains the 240 comparison setting.

| Sonic encoder / cap | Req mean | Miss mean | Miss median | Miss p95 | Miss max |
|---|---:|---:|---:|---:|---:|
| e197 / 210 | 613.35 | 85.15 | 44 | 287.4 | 512 |
| e198 / 210 | 612.97 | 84.26 | 43 | 283.0 | 483 |
| e198 / 240 | 614.43 | 87.08 | 45 | 294.0 | 521 |

Frame 0 is excluded. The raised ceiling is a measured transfer result; it
does not improve whole-movie Miss. CD service and the whole-movie quality
budget remain finite, so a different spending pattern can increase Miss.

The persistent local receipt is
`logs/lat-final-vblank-qualification-20261111.json`. It records SIM paths,
gate/trace receipts, capture paths, ISO hashes and per-loop counters. Matching
before/after mixline layout receipts and the source TSVs are also in `logs/`.
No hardware qualification or listening result is claimed by these checks.

## Sonic cold cap 230 with p169

The standard `sonic-jam-op.toml` profile uses cold cap 230. Matching source,
raster, cadence, filters and palette settings were qualified with
`sonic-jam-op-cold230.toml`: 2,714 frames, verified packing, and two complete
loops in a 230-second native FFV1/FLAC capture. The source encode took 185.7
seconds. The HUD gate passes with cadence/spill warnings; sector slip,
control desync and audio resync remain zero in both loops.

There are four irregular display intervals per loop, versus six with cold
cap 240 on the same p169 player. Loop 1 is one VBlank late at new frames 2,
1315 and 2713 and catches up at 1326. Loop 2 is late at 218, 1315 and 2713
and catches up at 1326. Interior irregular intervals total two and three,
respectively. The delay at 1377 disappears, but cadence is not uniform.

The actual cold maximum is 230 and the packed run maximum is 86. Request
mean is 613.96; Miss mean/median/p95/max are 86.21/44/287/526. At frame 1315,
Miss rises from 23 to 41; at 1377, from 135 to 147. Aggregate Miss alone does
not establish better picture quality.

`harness/lat_transfer/summarize_cadence.py` compares complete 30 fps SIM/HUD
loops using `--baseline-sim`, `--candidate-sim`, `--baseline-hud`,
`--candidate-hud` and `--json`. It reports request/Miss distributions and
long/short display intervals, excluding frame 0 and the terminal hold while
retaining startup/end transitions. The matching HUD gate owns qualification.
Local evidence is in `logs/sonic-cold230-experiment-20261112.json`,
`logs/sonic-cold230-comparison-20261112.json` and
`logs/sonic-cold230-p169-hud-20261112_gate.json`.

## Early LAT admission

The p171 player anchors LAT to the physical head of the preceding publication
VBlank and the current cadence target. It can begin at line 0 as soon as the
source is ready, retains a usable EVB head, and waits through the VBlank-flag
and line-counter transition. It rejects expired intervals. The limit remains
672 DMA-word-equivalent units including repairs, additionally bounded by six
units per remaining active line; entry at or after line 208 is rejected.
PLAYER.md owns the byte/pattern conversion and state allocation.

`check_trace.py` distinguishes actual DMA command starts from scanline
continuations and CPU repair writes. Its `active_dma_start_line_histogram`
and `early_active_dma_start_frames` must be read alongside matched-frame
comparisons: early active writes or starts alone can also follow a VBlank
transfer and do not establish the LAT admission path. `test_trace.py` uses an
independent log fixture to catch this misclassification and interrupted DMA
continuations. Actual assembled instructions and matching captures establish
player behavior; the fixture is not an assembly model.

The p171 qualification reuses the existing encoded streams byte-for-byte:
Sonic cold cap 230 (e199), Lunar 24 fps (e198), and Machi 15 fps (e198).
All three complete captures pass the HUD gate with cadence warnings, zero
sector-slip/control-desync/audio-resync, and matching final-tail writes with
zero final-tail/NT/HUD/CRAM writes outside VBlank or on ambiguous edges.
Representative startup, content and tail stills were inspected. Sonic has
two complete loops; Lunar and Machi each have one complete loop.

For Sonic, 39 matched frames move their first active DMA command from line
112 or later to before line 112; frames 201, 218 and 845 move from line 113
to line 1. Its two loops retain four irregular intervals each, as with p169;
the startup/218 delay changes loop assignment. Lunar's interior cadence
warning count falls from 247 (p168) to 113. Machi's count rises from three
(p169) to ten. Early admission is established, but improved cadence is not
a universal result and the Machi regression remains visible. These checks
are emulator evidence, not real-hardware DMA timing proof.

The receipt `logs/lat-early-p171-20261112.json` links the capture identities,
unchanged-stream hashes, matched-frame start comparison, HUD/VDP checks and
fresh still manifests. No source re-encode is part of this qualification.

## EAT and LAT admission

The current player admits protected pattern work in each EAT as well as LAT.
It derives a one-based physical active-period ordinal from the preceding
publication blank and rejects an ordinal already used by this movie frame.
Each period retains the 672-unit maximum and remaining-line limit; the actual
cadence target bounds all grants. A usable blank head still takes precedence,
and final-only destinations remain deferred to LVB. This changes player timing
without changing the encoded cold cap, payload, allocation or stream format.

The p172 qualification reuses the same Sonic, Lunar and Machi streams as p171.
The HEADER, BODY and palette hashes match. Native 320x224 FFV1/FLAC captures
use the same LOGVDP core, with two complete Sonic loops and one complete Lunar
and Machi loop. All captures pass the HUD gate with zero sector slip, control
desync and audio resync. Actual final-tail words match the SIM. Final-tail,
movie-table, HUD and CRAM active/ambiguous-edge write counts are all zero.
Fresh startup, content and tail stills were inspected.

| Source | Complete frames | p171 interior cadence warnings | p172 interior cadence warnings | p172 alert |
|---|---:|---:|---:|---|
| Machi, 15 fps | 2,293 | 10 | 0 | NONE |
| Lunar, 24 fps | 2,535 | 113 | 50 | WARNING |
| Sonic cold cap 230, 30 fps | 2 x 2,714 | 3 in first loop | 0 in both loops | NONE |

Machi's 2,291 observed intervals excluding frame 0 and the terminal hold are
all four VBlanks. Sonic retains two long edge intervals per loop (new frames
2 and 2713), compared with four irregular intervals per loop in p171. Lunar's
periodic cadence still has timing irregularities; this is an improvement,
not perfect cadence or real-hardware qualification.

The assembled Machi admission HVC read returns at PC `0xFF1006`. Matching
full LOGVDP reads at that PC with returned V-counter below 208 establish
actual grants, rather than DMA continuations from VBlank. Among 2,292 timed
frames, 322 receive one grant, 1,830 receive two and 38 receive three; 102
receive none. These are grant counts, not absolute EAT ordinal measurements.
The disassembly and per-frame samples are retained in
`logs/eat-p172-machi-disassembly-20261112.txt` and
`logs/eat-p172-machi-admissions-20261112.json`.

`logs/eat-p172-20261112.json` links exact inputs, output identities, exit
statuses, gates, traces, still manifests and the assembled-player matrix.
The matrix checks both the physical ordinal comparison and its rejection
branch, guarding against repeated active-budget grants.
