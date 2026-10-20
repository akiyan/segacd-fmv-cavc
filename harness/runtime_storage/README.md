# Runtime storage and long-source memory

This harness checks the actual CLI, child-process environment, artifact leases,
resource locks and numeric caches. It does not require `/dev/shm`, systemd, or a
particular home directory. The tools target POSIX; Linux memory/filesystem probes
are optional. There is no native Windows qualification.

## Small storage check

```sh
tools/python.sh --workspace-root /path/to/workspace \
  --scratch-root /path/to/ssd/scratch harness/runtime_storage/smoke.py
```

The check uses paths containing spaces and Japanese characters, launches the
real Python wrapper from another working directory, checks child tempfile paths,
contends for a real resource lock, evicts an inactive managed artifact while
preserving a live lease and unrelated file, and checks mapped-array values and
cleanup. It leaves no test media. `memory` is the default array mode; disk mode
is explicit. RAM-backed scratch still uses physical RAM.

## Full-source comparison: 16,384 frames

Use the same actual source/profile for both runs. This is a full encode, not a
short-duration substitute. The low-motion 320x224 source is 682.667 seconds at
24 fps, with visible index markers and silent audio. It limits pattern-history
complexity so cache lifetime can be measured without hours of motion search.
It does not measure worst-case memory for a high-motion movie.

```sh
tools/python.sh --workspace-root /path/to/source-workspace \
  harness/frame_capacity/make_source.py --frames 16384 \
  --profile tmp/memory16384.toml
```

Freeze the parent implementation in an isolated checkout/snapshot before the
comparison and give it its pinned environment. Use the absolute same profile
path. For a parent predating runtime options, select its disk artifact root
with `SEGACD_TMPFS_ROOT`, `SEGACD_TMPFS_ALLOW_NON_TMPFS=1`, and TMPDIR. Keep source
quality settings, GPU/CPU choice and worker policy the same. Never compare two
copies of the changed implementation as a substitute for the parent.

Measure each command separately, with distinct workspace/scratch directories:

```sh
tools/python.sh --gpu --workspace-root /path/to/candidate-workspace \
  --scratch-root /path/to/ssd/scratch --array-storage disk \
  harness/runtime_storage/measure.py --tsv logs/memory16384.tsv -- \
  tools/python.sh --gpu tools/sim.py /absolute/path/to/tmp/memory16384.toml
```

Do not overlap the two encodes. Use the same `SEGACD_RESOURCE_ROOT` if they have
different workspaces and share devices. Completed caches must not make a timing
measurement silently skip encoding; fresh workspaces avoid that without forcing
unrelated jobs to re-encode. Keep stdout/stderr and normal exit status.

`measure.py` records sampled process-tree RSS, system Shmem/MemAvailable/swap
when Linux exposes them, and selected filesystem usage. Its JSON includes
sampled tree peak and OS high-water RSS of the largest child. The tree sum can
count shared pages twice, and sampled peaks can miss short spikes. On Linux,
`/usr/bin/time -v` around the encoder additionally records its process peak.
System Shmem and filesystem usage include other processes. Do not add these
figures together or describe cgroup file cache as encoder heap.
Repeat `--watch-filesystem PATH` before `--` to sample additional filesystems,
for example explicit `/tmp` and `/dev/shm` paths on Linux. Their numbered TSV
columns map to paths in the JSON receipt. This observes usage without selecting
those filesystems as artifact or array storage.
Pressing Ctrl-C stops the command's process group, including wrappers
and their child encoder, instead of leaving an unobserved encode running.

Compare completed outputs without re-encoding:

```sh
tools/python.sh harness/runtime_storage/compare.py \
  /path/to/parent-sim/data /path/to/candidate-sim/data \
  --tsv logs/memory16384-equivalence.tsv
```

The comparator reads every saved decision and numeric field plus audio/palette
bytes; it ignores no quality metrics. Pickles must be trusted local outputs.
Then pack each decision log through its corresponding implementation with the
same boot extension and full normal pack verification. Compare HEADER.DAT,
BODY.DAT, MOVIE.DAT, paltab.bin and palidx.bin hashes. This separates encoder
identity from container metadata and proves actual stream output. Maximum-index
and 65,536-frame WordBuf boundaries have separate synthetic tests under
`harness/frame_capacity`; they do not require another 83,520-frame encode here.

## Recorded comparison: 2026-10-20

Both full encodes completed normally on Linux x86-64, an i9-13900KF and RTX
4090, using the same Python 3.13.14 / NumPy 2.3.5 GPU environment and default
stage worker policy. The parent was frozen at `8cc7bea`; both workspaces and
scratch were on ext4. The same absolute profile selected 16,384 frames,
320x224, 24 fps, pad, mosaic-gm and cold cap 210. Each run used a fresh
workspace, so neither reused a completed encode.

| Measurement | Parent, RAM arrays | Current, disk arrays |
|---|---:|---:|
| Wall time (`time -v`) | 31:27.24 | 31:33.98 |
| Maximum RSS (`time -v`) | 7.143 GiB | 4.616 GiB |
| Cgroup peak, including charged file cache | 7.231 GiB | 7.149 GiB |
| Cgroup peak swap | 0 | 0 |

`results.tsv` preserves exact values and units. The 5-second sampled process
tree peak was only 3.997 GiB; the OS high-water RSS captures a brief peak the
sampler missed. The 35.38% reduction describes process RSS. Disk-backed pages
also use reclaimable filesystem cache, included in the cgroup peak above. System
Shmem ranged from 14.252 to 14.592 GiB and includes unrelated jobs; it is not
encoder-owned memory. GPU device memory was not measured. The scratch arrays
occupied about 5.90 GiB during Decide and their directories were removed on
normal exit. This is one observed run per variant, not a throughput benchmark
or a worst-case bound for complex footage.

All saved decisions for all 16,384 frames, every stats/buffer/palette numeric
field, miss masks and both audio files match (`decisions-equivalence.tsv`).
Each implementation's real packer passed its full display, audio, physical
deadline and BODY-slot verification using the same boot extension. HEADER.DAT,
BODY.DAT, MOVIE.DAT, paltab.bin and palidx.bin are byte-identical;
`packed-equivalence.tsv` contains their SHA-256 values. Verification covers
native encoding and complete packed-stream replay.

Identity of the measured input and runtime code:

```text
source SHA-256: 3e01b37763678a9c2883eec7ded75e71524eba6543478f6d7640b63201699479
sim.py SHA-256: c6dcb908874a90a28a3ae8802b222a18bdecdc9c6561d5141a159622e75c9520
array_storage.py SHA-256: 9d9453589d45cb88a6c5919b97e66e5d857a4c77f95ba9830d82352f34224bb1
```

Local raw evidence is under `logs/test-audit-{baseline,disk}*`, with the
candidate's sampled TSV and JSON, GNU time reports, and full pack logs. Storage
smoke and Ctrl-C child cleanup also passed. Portable storage does not depend
on systemd; the cgroup figures are additional evidence from this Linux host.
