# APPLY back-pressure replay

This harness checks whether a fixed-cadence BODY schedule can fill the Sub
CPU's APPLY control queue even though the packed route ends with zero CD-rate
lead.

The physical CD remains at 1x. A slot whose physical sector count exceeds its
cadence allowance takes extra real time and delays display. A later light slot
can remove the schedule's recorded sector debt, but it cannot remove elapsed
display time. The continuously pumped CD producer can then move ahead of the
fixed-cadence control consumer.

The harness replays that producer lead through the exact BODY order:
`control`, then `payload`, then `pad`. It advances APPLY by complete 2 KiB
control sectors and advances the consumer by each control block's exact
`total_len`. A predicted `apply_backpressure` event requires both:

- queued APPLY data is at or above the player's 30 KiB pump guard; and
- the next physical BODY sector is control.

With a HUD TSV, the default replay uses the measured extra emulator scanouts.
It converts each extra NTSC scanout to `1001/800` CD sectors and subtracts the
schedule's current rate debt. `--schedule-only` instead uses the conservative
`peak debt - current debt` producer lead and needs no HUD.

## Usage

Replay H40 Bad Apple against a diagnostic HUD:

```sh
SIM_OUT="$(tools/python.sh tools/encode_config.py \
  profiles/bad-apple.toml --print-sim-output)"
tools/python.sh harness/apply_backpressure/analyze.py \
  "$SIM_OUT/decisions.pkl" \
  --hud-tsv logs/HUD_hud.tsv \
  --output-tsv logs/HUD_apply_backpressure.tsv
```

Run the schedule-only proof:

```sh
tools/python.sh harness/apply_backpressure/analyze.py \
  "$SIM_OUT/decisions.pkl" \
  --schedule-only \
  --output-tsv logs/BadApple_schedule_apply_backpressure.tsv
```

Both outputs are UTF-8 TSV. Run the focused tests with:

```sh
tools/python.sh -m unittest harness/apply_backpressure/test_analyze.py
```
