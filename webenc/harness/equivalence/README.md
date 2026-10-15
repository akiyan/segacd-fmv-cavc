# Normalized-input byte equivalence

## Mandatory scroll-list validation

`pack_validation.py` corrects the speed comparison in the browser/native
comparison adapters without editing shared repository codec files. A scroll
control must carry its position item through the shadow-list format, even when
the nominal bitmap path would be faster. Normal-frame lists remain optional
and must still improve speed. Frozen costs, required/forbidden list formats,
all stream writing and physical delivery verification remain unchanged.

Run `tools/python.sh webenc/harness/equivalence/test_pack_validation.py` for the
exact original/corrected validation predicates: dense scroll and zero-update
scroll reproduce the rejection, slow normal lists remain rejected, and fast
normal lists remain valid. An AST comparison requires every other statement in
the packer's main function to stay unchanged. The same tests run in Pyodide.

`scroll_pack_repro.py SOURCE.mp4` normalizes and simulates the complete source at
320x224, 30fps, preserve-aspect with source PAR 32:35 and cold cap 210. It runs
the original packer, captures the reported rejection, then repacks the identical
decisions with the corrected predicate and requires full `--verify`. Media and
decisions use a managed tmpfs lease; a persistent receipt goes under `logs/`.

## Shared input preparation

The comparison uses the original source and TOML profile, then performs profile
image/audio filters offline once. Inputs are lossless RGB PNG frame sequences
(master and raw) and 22.05 kHz mono signed-16 PCM. No WebCodecs or Canvas decoding
participates in the equivalence calculation. An archive carries data and settings,
not executable Python. Encoder code is independently bundled into the browser.

```sh
tools/python.sh --gpu webenc/harness/equivalence/prepare.py profiles/sonic-jam-op.toml
```

Use the printed managed tmpfs job path as `JOB`. The preparation snapshots the
encoder source, profile, and linked Sub extension, and records decoded-frame
SHA-256 values in a TSV. Generated source media stays private in tmpfs.

For iteration, create the exact first half (1,357 frames / 45.233333 s). Keep
geometry, fps and cold cap fixed. Once stable, require the full 2,714 frames.

```sh
tools/python.sh --gpu webenc/harness/equivalence/half.py "$JOB"
tools/python.sh --gpu webenc/harness/equivalence/native.py "$JOB/half"
node webenc/scripts/prepare-python-runtime.mjs
node webenc/harness/equivalence/wasm.mjs "$JOB/half"
tools/python.sh --gpu webenc/harness/equivalence/compare.py "$JOB/half"
```

The native comparison uses the locked CPU numerical path of the original codec;
GPU acceleration and multiprocessing are not required to encode the stream.
The browser uses Pyodide's Python/WebAssembly and NumPy/Pillow packages, all
self-hosted and pinned. Its platform adapter replaces Linux resource locking and
workspace bookkeeping, sets one CPU worker, and supplies normalized inputs.
Completed normalized inputs use explicit no-op master/raw filters so the reuse
path does not probe an absent source through FFmpeg. The manifest retains the
filters already applied offline.
Palette training, quantization, simulation decisions and packing remain the
original implementations. The final comparison checks every byte of HEADER.DAT,
BODY.DAT and MOVIE.DAT. It does not compare lossy MP4 or ZIP container bytes.

RGB333 comparison arithmetic uses fixed native-reference constants for the 512
hardware colours. Native BLAS and scalar WebAssembly dot products can differ in
their last floating-point bits and affect strict comparison decisions. The
runtime preparation generates these source-independent constants from the
locked native CPU environment. This contains no frame data, palettes learned
from video, update decisions, or reference encoded outputs. Rendered RGB333
dot products and colour-distance tables use these constants in WebAssembly.

Native-only phase caches retain independently computed palette/quantization
results keyed by normalized input, environment and encoder identity. Native
results are never supplied to the browser encoder. Observational per-stage
palette and per-frame quantization digests help locate the first divergence.

The full final check uses the same commands with `"$JOB"` instead of
`"$JOB/half"`. Only a complete full-profile byte match qualifies the goal.

## Qualified normalized profile

`sonic-jam-op.toml` passes both the 1,357-frame first-half comparison and the
complete 2,714-frame / 90.466667-second comparison. Every palette, frame-segment
and quantization digest matches. The full outputs are:

| Artifact | Bytes | Native and browser SHA-256 |
| --- | ---: | --- |
| HEADER.DAT | 651264 | `7247dfa5ced6f2c3219f029cc2f94211cf69a9deacf15d40e9a4c9ec155913c1` |
| BODY.DAT | 13977600 | `aeb0b7db7f53e3cdb2c311f59f7db729eef820bb01737072e21c0d8f5678744a` |
| MOVIE.DAT | 14628864 | `197d52f67c32ebb6cb5d95488345379714b3cc5cadd1c6208d50abb152282c52` |

This result covers the recorded source/profile/encoder fingerprints in the
persistent `logs/*_webenc_sonic-jam-op_full_byte_match.json` receipt, using common
offline-normalized frames and PCM. It does not qualify other profiles, source
decoders, native GPU arithmetic or a bootable disc image. The measured original
sim stages took 470.2 seconds natively and 1006.4 seconds in the browser; packing
and ZIP creation are additional work. Half-length iteration retains all target
quality settings and takes roughly half the processing time.

The SPA import/start/cancel check runs `node webenc/harness/equivalence/ui.mjs
"$JOB/half"`; set `WEBENC_URL` to check the deployed Funnel URL. The production
ZIP builder can be checked against completed browser outputs with
`node webenc/harness/equivalence/package.mjs "$JOB"`. It verifies every packaged
stream byte and the HEADER+BODY compatibility concatenation.

A 60-frame / two-second cut exposes diagnostic handling of unused boot-prefill
padding. Frame 0 transfers 1,372 patterns; 9,885 subsequent Prg patterns fit
entirely in the boot prebuffer, which rounds to 9,920 patterns (155 sectors).
There is no timed pattern payload. The original diagnostic cursor counts 35
unused padded patterns and raises at 11292/11257. `prebuffer_trace.py` bounds this
diagnostic cursor only when zero timed payload and exact sector rounding prove
that case. It changes no decisions, physical schedule or packed fields. Both
native and Wasm use the same diagnostic correction; all packing/decode checks
remain active. Qualified half-source HEADER/BODY/MOVIE bytes are unchanged.

## Playback and disc checks

The browser runs the canonical display portion of render_analysis.py on its own
decisions, active CRAM and scroll metadata. `replay.mjs` checks every RGB pixel
against native canonical frame hashes; all 1,357 half-source frames match. The
browser's pre-AAC playback WAV is byte-identical to native ADPCM/RF5C164 output.
The ordinary 90-second MP4 path completes all 2,714 frames with Playback and a
downloadable ISO/CUE ZIP. Exported AAC has zero measured lag and 0.99866
correlation against its canonical PCM waveform after rate conversion.

`compiler.mjs` checks the actual browser GNU assembler/linker against native
Binutils on the same original sources, palette data, stream constants and region.
The 1,108-byte extension and 32,768-byte boot system area match completely.
ISO9660 extraction checks the stream bytes, and an emulator boot check verifies
moving movie images. The player source is compiled per generated stream;
there are no patched generic placeholders or prebuilt input-specific discs.

`qualify.py "$JOB"` renders the native canonical display, checks every browser
RGB frame hash, compares reconstructed PCM bytes and scroll/fade/CRAM arrays,
extracts both stream files from the ISO and checks its CUE filename. It writes a
per-frame feature TSV and persistent qualification receipt. `compiler_fixture.py
"$JOB"` compiles the original release player natively using the generated stream
contract, compares its complete boot system area against the browser ISO, and
creates the input archive for `compiler.mjs`. These checks require completed
independent native and browser encodes.

## Lunar full-profile qualification

`profiles/lunar-ss-op.toml` is qualified across all 2,535 frames at 320x224,
24 fps, with the unchanged `2:180,3:230` cold cap. Common offline-normalized
inputs include the profile's image and audio filters. The browser independently
trains MOSAIC-GM palettes, quantizes frames and computes every update decision.

| Artifact | Bytes | SHA-256 (native and browser) |
| --- | ---: | --- |
| HEADER.DAT | 636928 | `309000f98497f18a0e639a2baab50893817fae6feec8e77c0a028d88d9b6287f` |
| BODY.DAT | 16304128 | `8090c59d95aad11ecf251506c1579029378022fb8a981c10d270301935ead594` |
| MOVIE.DAT | 16941056 | `b08640fbcc14eb8e05f28d5627e23282fbd36458a05e1d0729432bde8e8bd2cf` |

Every canonical RGB replay frame and reconstructed PCM WAV byte matches.
Horizontal scroll controls cover frames 1118-1333 and vertical controls 1922-1957;
all 252 scroll controls and positions match. The ending uses 22 fade-out CRAM
controls; all per-frame active CRAM values match. The native PCM SHA-256 is
`b8e0c52888ef7506ec5bc7cd148cc31ca57a5c6a1d3ce33c08b9ad3a4203365e`.

The browser MP4 decodes completely and plays/seeks in Chromium. AAC measures
zero sample lag and 0.99974 correlation against resampled canonical PCM.
ISO extraction, CUE naming and the complete 32,768-byte boot system area match
the independently compiled native player. ZIP creation preserves every generated
file. Native sim stages took 661.5 seconds and browser stages 1542.5 seconds;
packing, canonical rendering, MP4 creation and disc compilation are additional
work. Persistent byte and playback receipts are in `logs/` with source, profile
and encoder identities. MP4 is a lossy viewing container; its bytes are not the
CAVC binary equivalence target.

## Live selected-decision summaries

`features.py` reads original palettes, frame-segment assignments, scroll flags
and fade control types without changing them. Palette channels remain RGB333
in `encode-summary.json`; the GUI displays each channel multiplied by 36, as
the canonical renderer does. Source processing emits planned results at the
Palette/Quantize boundaries and verified results after the packer succeeds.
Scroll/fade intervals use actual output-frame controls, with inclusive starts
and exclusive ends. Fade summaries retain controls in the held black tail.

The completed Lunar Wasm decisions qualify all nine palette sets, scroll controls
at 1118-1333 and 1922-1957, and 22 fade controls spanning 2476-2517. A
`summary-fixture/decisions.pkl` hard link to `wasm-decisions.pkl` lets the reader
render its JSON without another encode. `summary_ui.mjs "$JOB"` verifies the
color conversion, palette list, effect list and event click handling against
that completed independent browser data. No native learned results are supplied
to a browser encode.
