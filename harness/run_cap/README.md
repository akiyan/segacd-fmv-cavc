# Transfer-run cap experiment

The native Sonic experiment uses `profiles/sonic-jam-op-run40.toml`: 288x200,
30 fps, cold cap 240 and packed run cap 40. CONFIG.md defines admission and
its current limitations. This is a whole-frame cap; separate EAT, EVB, LAT
and LVB caps are not implemented. PLAYER.md defines those timing terms.

Before an encode, `tools/test_run_budget.py` checks that contiguous loads can
exceed the numeric run cap, source switches can reject an update, warm reuse
cannot silently fragment an accepted batch, and final physical counts reject
an over-limit frame while exempting boot. Profile tests catch an inherited
run-cap setting leaking into another profile.

## Allocation equivalence without encoding

`compare_allocator.py` replays existing Sonic decisions through a frozen
allocator and the current implementation. It compares placements, prefetch
results, state digests and eviction counters after every frame. It then times
repeated allocation trials on an actually populated cache. This catches clock
order, stale-pin and previous-display protection changes introduced by a
faster slot search; it does not encode source footage or model assembly.

```sh
tools/python.sh harness/run_cap/compare_allocator.py \
  /absolute/path/decisions.pkl /absolute/path/reference_tile_alloc.py \
  --json logs/run-cap-allocation.json
```

The frozen reference must come from before the optimization. The diagnostic
currently accepts normal-frame sources with six-field prefetch records and at
least 202 frames. Managed decision artifacts are leased during the read.
Reference snapshots and machine-readable results belong in ignored `logs/`.

## Playback comparison

Use the same player for capped and uncapped streams. Pack independently
reconstructs every timed frame's actual run count, including WordBuf ring
wraps. Capture two complete Sonic loops, run the DEBUG HUD checker, and use
`harness/lat_transfer/check_trace.py` with that capture's own LOGVDP logs and
SIM. Compare long and short display intervals separately, retain startup/tail
exceptions, and require zero slip/desync/resync counters. Compare request
volume alongside Miss distributions; a lower run count is not automatically
a visual-quality improvement. Source encoding and full captures are explicit
qualification work, not part of the quick tests.

After the matching HUD gates pass, `summarize.py` reads both SIM directories
and HUD TSVs. Pass `--baseline-sim`, `--candidate-sim`, `--baseline-hud`,
`--candidate-hud` and a persistent `--json logs/RESULT.json`. It accepts the
30 fps comparison only, reports complete loops, excludes frame 0's untimed
hold and the last frame's terminal hold from interval counts, and lists the
new frame at each long/short transition. Startup/end exceptions inside those
intervals remain visible; the matching gate owns their warning classification.

## Sonic result with p169

The e199 capped stream completed all 2,714 frames and verified packing. Two
complete loops in a 230-second native FFV1/FLAC capture passed the HUD check
with no warnings. Slip, control desync and audio resync stayed zero. The actual
VDP trace matched every final-tail load and found no final-tail, movie-table,
HUD or CRAM writes outside VBlank, including no ambiguous edge writes.

| Metric | e198, no run cap | e199, run cap 40 |
|---|---:|---:|
| Cold cap / actual maximum | 240 / 240 | 240 / 240 |
| Actual maximum packed runs | 79 | 39 |
| Frames reaching 240 cold patterns | 44 | 42 |
| Non-two-VBlank intervals, loop 1 / loop 2 | 6 / 6 | 1 / 0 |
| Interior late / catch-up transitions per loop | 2 / 2 | 0 / 0 |
| Request mean | 614.43 | 614.21 |
| Miss mean / median / p95 / max | 87.08 / 45 / 294 / 521 | 87.46 / 47 / 294 / 527 |

Only the first loop's startup transition to frame 2 remains one VBlank late.
Both sources use the same p169 player, raster, cadence, filters and palette
policy. The cap is conservative: admission reserves one record for a possible
WordBuf ring-end split, so this encode's maximum is 39, not 40. At frames
1315 and 1377, cold loads fall from 240/240 to 147/191 and Miss rises from
23/135 to 122/175; a small whole-movie mean change does not imply unchanged
quality at those cuts. Representative capture frames were inspected.

The source encode took 1,909.4 seconds (1,819.3 in Decide). One initial scalar
allocation trial was interrupted with user approval; the completed run used
native-array clock scans. Frozen/current allocation replay matched every
frame's placements and state in both baseline and capped decisions. This
experiment demonstrates playback benefit, not acceptable encoder throughput.

Persistent local evidence is in `logs/sonic-run40-experiment-20261112.json`,
`logs/sonic-run40-comparison-20261112.json`,
`logs/sonic-run40-p169-hud-20261112_gate.json`, and
`logs/sonic-run40-p169-vdp-20261112.json`.
