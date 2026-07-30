# Main pre-pattern-transfer work

This harness measures the current H40 Main-CPU critical path before
`pattern_dma_ready_vcounter` is sampled. The boundary is the point where Main
has finished the current frame's pre-transfer work and can wait for the first
fresh VBlank pattern budget. The VBlank wait itself and `bf_run_lp` are after
the boundary.

The analyzer combines three sources:

- the packed `HEADER.DAT` and `BODY.DAT`, which select the real bitmap/list
  shadow-update path for every frame;
- the nominal MC68000 instruction-cycle model in `tools/shadow_updates.py`;
- a matching full-playback HUD TSV, which supplies the measured Sub handoff
  wait, `pass2_delay_q4`, and raw pattern-ready V-counter.

It converts nominal CPU work with the same approximately 488 CPU
cycles/scanline used by `dmabench`. Platform wait states remain outside the
nominal shadow/stage model. The observed `pass2_delay_q4` row is independent
and therefore exposes whether the static decomposition is credible.

Run it against a matching H40 packed stream and full HUD:

```sh
tools/python.sh harness/pt_prework/analyze.py \
  --header out/bad-apple/HEADER.DAT \
  --body out/bad-apple/BODY.DAT \
  --hud-tsv logs/MATCHING_hud.tsv \
  --output-tsv logs/MATCHING_pt_prework.tsv
```

The output is UTF-8 TSV. It reports:

- the measured Main-side `CMD_SWAP` polling interval;
- the selected bitmap/list shadow-update cost;
- the fixed 40x28 `shadow` to 64-pitch `nt_stage` copy;
- their combined name-side work;
- the observed previous-flip-to-`bf_dma` interval;
- the nominal `bf_dma` bookkeeping tail through the ready sample;
- their estimated previous-flip-to-ready total;
- the remaining fixed work/quantization residual;
- pattern-ready pressure and first-VBlank margin.

The residual is not a new player metric. It subtracts an approximate 8-bit
V-counter wait and nominal instruction costs from a quantized stopwatch
interval. Large outliers can therefore come from V-counter wrap or phase
ambiguity; use its middle percentiles only as a check on the small fixed-cost
remainder.
