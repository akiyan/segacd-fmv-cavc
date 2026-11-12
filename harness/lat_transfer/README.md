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
