# Full-source planning optimization comparison

This harness compares frozen encoder revisions on Sonic Jam OP's complete
2,714-frame profile: 288x200, 30 fps, cold cap 210, including the profile's
source filters and audio normalization. It does not lower quality settings.

Prepare one normalized input with `harness/equivalence/prepare.py`, using an
explicit managed workspace and scratch root. Keep its printed job directory.
Before modifying the encoder further, freeze each revision under
`JOB/revisions/REVISION/{tools,boot,cfg}`. Include all Python modules and
`tools/av_version.txt`; no native palettes, quantization or decisions are
provided to a browser run.

The native runner uses the pinned GPU environment's numerical libraries with
`CBRSIM_GPU=0` and one CPU worker. The browser uses a fresh Chromium Worker,
the self-hosted Pyodide runtime, and the production Python adapter, including
its source-independent RGB333 constants and progress instrumentation.
Both independently train palettes, quantize every frame, make decisions and
verify the packed stream. Native stage caches are disabled.

```sh
tools/python.sh --gpu \
  --workspace-root /dev/shm/segacd-fmv-cavc \
  --scratch-root /dev/shm/segacd-fmv-cavc/scratch \
  --array-storage memory \
  webenc/harness/equivalence/prepare.py profiles/sonic-jam-op.toml

# Set JOB to the printed managed path, after freezing the revisions.
tools/python.sh --gpu \
  --workspace-root /dev/shm/segacd-fmv-cavc \
  --scratch-root /dev/shm/segacd-fmv-cavc/scratch \
  --array-storage memory \
  webenc/harness/planning/run.py "$JOB" \
  native-before native-stage1 wasm-before wasm-stage1

tools/python.sh --gpu --workspace-root /dev/shm/segacd-fmv-cavc \
  webenc/harness/planning/compare.py \
  "$JOB" native-before native-stage1
tools/python.sh --gpu --workspace-root /dev/shm/segacd-fmv-cavc \
  webenc/harness/planning/compare.py \
  "$JOB" wasm-before wasm-stage1
```

Prepare the self-hosted browser runtime with
`node webenc/scripts/prepare-python-runtime.mjs` before browser runs. A browser
benchmark bundles the selected frozen `tools` independently and binds the
unchanged normalized input to that revision's source fingerprint. Each run
starts a local server and loads the encoder page before starting its Worker.
It retains the original source frame count. Browser output uploads in this
harness go only to that local test server.

Runs execute serially under workspace leases and existing resource/stem locks.
Commands, process identifiers, exit status, logs and completion receipts stay
in `logs/encoder-reuse-sonic-*`. Images, inputs, snapshots and encoder outputs
stay in the managed workspace. A previous run is never silently overwritten.
A complete run normally takes several minutes. Inspect a failure before
rerunning; retain successful upstream inputs and outputs.

`compare.py` checks every saved decision and numeric trace, reconstructed PCM,
all HEADER/BODY/MOVIE bytes, palette/quantization digests and all canonical RGB
replay frame hashes. It records input/source fingerprints, exact measured
encode and pack durations, and the encoder's printed per-stage timings.
Canonical replay is performed after the timed encode/pack operations.
Comparisons within a runtime require identical array dtypes and values.
Native/Wasm comparisons accept only integer-width differences with exactly
equal values and shapes, recording each affected field in the receipt.
Packed bytes, RGB frame hashes, PCM, and noninteger fields remain exact.

Each timing is one execution of that revision. Input normalization, runtime
download, MP4 encoding, ISO construction and ZIP creation are outside these
measurements. The results measure the original encoder running under native
Python and browser WebAssembly; they are not timings of clicking Generate on
an ordinary compressed input or of a GPU-accelerated CLI encode.

## Recorded full-profile comparison

The complete Sonic Jam OP comparison used a Core i9-13900KF on Linux x86_64.
Native Python was 3.13.14 with NumPy 2.3.5, GPU disabled and one worker.
Chromium 156.0.8078.4 used Pyodide 314.0.7, Python 3.14.2 and NumPy 2.4.6.
All runs retained 288x200, 30 fps, cold cap 210 and encoder/player version
`20261020.e194.p157`. The source-independent numeric constants were identical.

| Runtime | Revision | Encode | Verified pack | Encode reduction from before |
|---|---|---:|---:|---:|
| Native CPU | Before | 461.996 s | 39.134 s | — |
| Native CPU | First stage | 415.340 s | 39.156 s | 10.10% |
| Native CPU | Complete | 411.670 s | 39.017 s | 10.89% |
| Browser | Before | 1006.314 s | 104.133 s | — |
| Browser | First stage | 840.521 s | 103.955 s | 16.48% |
| Browser | Complete | 856.194 s | 105.888 s | 14.92% |

The first stage already included incremental prefix validation, lightweight
candidate predicates, sector-count memoization, potential-Prg counters,
WordBuf room checks and bounded candidate scans, and quality-reserve reuse.
The complete revision adds persistent candidate-prefix arrays, per-frame
non-Word demand and shared preparation across layout trials.

Each row is one execution, without an estimated timing distribution. The
additional changes reduced native encode time by 3.670 seconds (0.88%), while
the browser total increased by 15.674 seconds (1.86%). Browser Palette time,
whose computation was unchanged, increased from 289.2 to 306.7 seconds;
Quantize increased from 133.6 to 136.0 and Forecast from 61.0 to 61.7.
Decide decreased from 349.5 to 345.4 and Finalize from 6.7 to 5.8.
These single samples do not establish an overall browser speed benefit for
the additional changes. They do show the recorded complete revision faster
than the original reference at the same quality target.

Within each runtime, all decisions and saved numeric fields matched exactly,
including dtype. Across runtimes, only the recorded int64/int32 storage widths
differed; their values and shapes were exact. HEADER/BODY/MOVIE bytes,
palette/quantization digests, all 2,714 canonical RGB frames and source/modeled
PCM matched across all three revisions and both runtimes.

Sonic retains the reference's WordBuf refill fallback at frame 1256. The
independent planner comparison also covers six feasible WordBuf refill cases,
plus repeated layout capacities to detect mutable-state leakage.

Reproduction identities:

| Object | Identity |
|---|---|
| Reference commit | `f751c994fe4ac7f78a3619ac9fc29705bc989d7e` |
| Source SHA-256 | `3b53e66452bcdeebc195373f6c5e4effa5da97b6f4406e3e2a9bef848b636296` |
| Profile SHA-256 | `98d6c36ed9459a5a68983645c4fc3aa602fdb01335fd030ae6c1b98cb1bcac38` |
| Reference encoder fingerprint | `346f93720173a6b65f063f017ccc020980325f9a42f1913c885849fc5b6f9d1d` |
| First-stage encoder fingerprint | `a33701adb2d8624b5fcd337248ab05231923405bfb21d279db15de0a3c87e136` |
| Complete encoder fingerprint | `edcb6c0864c85ba1be2fa6816bb9dba3f14423ed36fbf6c5248d255448297ed7` |
| Common MOVIE.DAT SHA-256 | `25f03e7dd99cf6254cad5b0b3a54cefbec364bc633bf6542400cf3cabc0fcd22` |

Local persistent evidence is in `logs/encoder-reuse-sonic-summary.json`,
`logs/encoder-reuse-sonic-summary.tsv`, per-run command/completion JSON and
the corresponding before/candidate comparison receipts. Encoder fingerprints
identify the measured source snapshots; they do not replace the public encoder
version used for completed-sim reuse.
