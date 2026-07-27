# Parallel profile-run qualification

This harness verifies that independent SEGA-CD FMV profiles can overlap without
sharing output paths, tmpfs leases, X displays, RetroArch system directories,
or fixed build intermediates.

The two profiles intentionally encode only the first eight seconds of Bad Apple
and the Sonic Jam opening. Eight seconds keeps repeated qualification practical
while still giving Extract, Palette, Quantize, Decide, pack, and recording
stages enough work to overlap visibly on this host.

`tools/parallel_run.py` holds each profile's `videos/<stem>` lock for the whole
local pipeline. The sim transfers its live tmpfs lease to the parent before
exiting, so another allocation cannot evict the decision data between sim and
pack. CPU-heavy stages use shared CPU tokens, GPU stages use the GPU token, and
each `run_headless.sh` invocation uses an EMU token. Xvfb chooses a free display
with `-displayfd`; an explicitly requested display fails if another server owns
it.

Run the local pipeline sequentially:

```sh
tools/python.sh tools/parallel_run.py \
  --sequential --through disc --force-reencode \
  harness/parallel_run/configs/issue73-bad-apple-h40-short.toml \
  harness/parallel_run/configs/issue73-sonic-h40-short.toml
```

Run the same work concurrently:

```sh
tools/python.sh tools/parallel_run.py \
  --jobs 2 --through disc --force-reencode \
  harness/parallel_run/configs/issue73-bad-apple-h40-short.toml \
  harness/parallel_run/configs/issue73-sonic-h40-short.toml
```

Snapshot the deterministic outputs after each run and compare the concurrent
result with the sequential baseline:

```sh
tools/python.sh harness/parallel_run/snapshot.py \
  --output logs/parallel-run/issue73-sequential/artifacts.tsv \
  harness/parallel_run/configs/issue73-bad-apple-h40-short.toml \
  harness/parallel_run/configs/issue73-sonic-h40-short.toml

tools/python.sh harness/parallel_run/snapshot.py \
  --output logs/parallel-run/issue73-parallel/artifacts.tsv \
  --compare logs/parallel-run/issue73-sequential/artifacts.tsv \
  harness/parallel_run/configs/issue73-bad-apple-h40-short.toml \
  harness/parallel_run/configs/issue73-sonic-h40-short.toml
```

Use `--through hud` for the complete local sim, verified DEBUG disc, lossless
recording, and HUD-gate path. Public Gists, visual timeline review, and uploads
remain interactive `$run` stages rather than unattended harness work.

Every invocation writes one plain-text log per profile and a UTF-8 TSV summary
under `logs/parallel-run/`. A qualification run must also compare the
sequential and concurrent `decisions.pkl`, `HEADER.DAT`, `BODY.DAT`, and
`MOVIE.DAT` hashes. Recording qualification uses the same Replay with
`tools/compare_recordings.py`; decoded frames, PCM, timestamps, packet
durations, and stream metadata must match exactly.
