# Parallel profile-run qualification

This harness verifies that independent SEGA-CD FMV profiles can overlap without
sharing output paths, tmpfs leases, X displays, RetroArch system directories,
or fixed build intermediates.

The two profiles intentionally encode only the first eight seconds of Bad Apple
in H32 and H40. Eight seconds keeps repeated qualification practical while
still giving Extract, Palette, Quantize, Decide, pack, and recording stages
enough work to overlap visibly on this host. The distinct H32/H40 stems also
exercise independent build and video paths without making content itself
another qualification variable.

`tools/parallel_run.py` holds each profile's `videos/<stem>` lock for the whole
local pipeline. The sim transfers its live tmpfs lease to the parent before
exiting, so another allocation cannot evict the decision data between sim and
pack. CPU-heavy stages use shared CPU tokens, GPU stages use the GPU token, and
each `run_headless.sh` invocation uses an EMU token. Xvfb chooses a free display
with `-displayfd`; an explicitly requested display fails if another server owns
it.

Interactive `$run` uses this orchestrator even for one profile. That rule is
what preserves the pipeline-wide lock and lease when unrelated Codex sessions
start work independently:

```sh
tools/python.sh tools/parallel_run.py --jobs 1 --through hud \
  configs/PROFILE.toml
```

Run the local pipeline sequentially:

```sh
tools/python.sh tools/parallel_run.py \
  --sequential --through disc --force-reencode \
  harness/parallel_run/configs/issue73-bad-apple-h40-short.toml \
  harness/parallel_run/configs/issue73-bad-apple-h32-short.toml
```

Run the same work concurrently:

```sh
tools/python.sh tools/parallel_run.py \
  --jobs 2 --through disc --force-reencode \
  harness/parallel_run/configs/issue73-bad-apple-h40-short.toml \
  harness/parallel_run/configs/issue73-bad-apple-h32-short.toml
```

Snapshot the deterministic outputs after each run and compare the concurrent
result with the sequential baseline:

```sh
tools/python.sh harness/parallel_run/snapshot.py \
  --output logs/parallel-run/issue73-sequential/artifacts.tsv \
  harness/parallel_run/configs/issue73-bad-apple-h40-short.toml \
  harness/parallel_run/configs/issue73-bad-apple-h32-short.toml

tools/python.sh harness/parallel_run/snapshot.py \
  --output logs/parallel-run/issue73-parallel/artifacts.tsv \
  --compare logs/parallel-run/issue73-sequential/artifacts.tsv \
  harness/parallel_run/configs/issue73-bad-apple-h40-short.toml \
  harness/parallel_run/configs/issue73-bad-apple-h32-short.toml
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

## Qualified result

On the 26-CPU-token workstation, a clean sequential H40+H32 sim/disc run took
15.8 seconds and the two-job run took 9.9 seconds, a 37% wall-time reduction.
All eight deterministic artifacts (`decisions.pkl`, `HEADER.DAT`, `BODY.DAT`,
and `MOVIE.DAT` for each profile) had identical SHA-256 values.

The normal two-job pipeline completed through both HUD gates in 39.2 seconds
with the default two EMU tokens. H40 and H32 each recorded 2,880 raw packets,
produced a 2,278-frame bounded capture with 1,677,312 stereo PCM sample frames,
and passed `S/D/R=0`, `M=1`, `J=0`. Xvfb selected separate displays `:2` and
`:3`.

Two unrelated one-profile orchestrator processes were also started without a
shared job list. H40 passed through HUD in 46.7 seconds and H32 passed in 44.7
seconds. Both processes exited zero; shared resource pressure caused waiting,
not cancellation or a pipeline failure.

Same-Replay comparisons passed in all required directions:

- paced realtime FFV1/FLAC vs offline FFV1/FLAC;
- offline repeat vs offline baseline; and
- one-EMU baseline vs simultaneous H32/H40 two-EMU capture.

These comparisons include decoded frame hashes, decoded PCM SHA-256 and sample
count, packet PTS/DTS/durations, stream metadata, and total counts. A newly
generated Replay is not expected to be frame-identical to an older Replay
because the BIOS/CD-player START phase is recorded anew; determinism is
qualified by reusing the exact Replay file.
