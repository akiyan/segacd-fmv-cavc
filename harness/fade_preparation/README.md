# Progressive fade preparation

This opt-in qualification runs the production encoder, packer and player on a
generated source. It catches reference preparation being silently discarded,
restarting from frame zero, CRAM/list audio-offset mistakes, and divergence
between committed display decisions and actual player output. It is not a
natural-footage quality test or a substitute for the affected full movie.

Generate three static, textured shots with fades and a 440-Hz tone:

```sh
tools/python.sh harness/fade_preparation/fixture.py tmp/fade-preparation
CBRSIM_GPU=0 tools/python.sh \
  --workspace-root /path/to/workspace --scratch-root /path/to/scratch \
  --array-storage disk tools/sim.py tmp/fade-preparation/fixture.toml
tools/runtime.sh --workspace-root /path/to/workspace \
  --scratch-root /path/to/scratch -- \
  make movieplay CONFIG=tmp/fade-preparation/fixture.toml
```

The entire 77-frame source is 320x224 at 30fps, SAR 32:35. Its cold cap of 64
deliberately forces preparation to continue after the single black frame
between shots. This setting belongs only to the fixture. Retain the encoder
log, printed artifact path and completion status; do not force a completed
artifact to re-encode. A first encode takes roughly 20 seconds on the measured
host. Inspect `decisions.pkl`'s `fade.preparation_log` or the matching TSV:
both anchors 26 and 51 must have pending cells and later reach zero within
their own shot. The log must contain only one preprocessing/decision pass.
Packing must independently validate display slots and physical deadlines.

Record the built release CUE with `tools/record_movie.sh --disc CUE --no-build
--seconds 40 --tag fade_preparation --record-size 320x224 --trim 0`, using the
same explicit workspace/scratch options. This is a separate emulator tier.
Pass its printed LOSSLESS path and the completed decision log to:

```sh
tools/python.sh harness/fade_preparation/verify_capture.py \
  /path/to/sim/decisions.pkl /path/to/lossless.mkv \
  --tsv logs/fade-preparation-capture.tsv
```

The checker reconstructs each committed image from pattern keys and CRAM,
independently of the packed reader. It requires an ordered occurrence of every
image in the native HUD-free capture, mapping GPGX's normal RGB levels back to
RGB333. Identical holds share a match; this checks pixels and order, not cadence,
audio quality, every loop, or publication eligibility. The TSV and adjacent JSON
are persistent evidence. Retain the exact disc, core, replay and recording
identities with the run receipt. Inspect fresh stills with
`tools/extract_verification_frames.sh` as well.

The e201/p173 fixture completed in 17.5 seconds. At both deadlines, 497 cells
remained; both references completed eight frames later without restarting.
The maximum whole-image RGB MAE against the ideal quantized fade reference was
6.25/255 after the first deadline and 6.12/255 after the second. The real packed
stream passed all 77 frames, and all 77 RGB333 images occurred in order in the
emulator recording. A recorded tone sample peaked at 439.49 Hz; this is a signal
check, not a listening assessment. The generic/specialized 15/24/30fps assembly
matrix and local unit suites also passed.

The fixture exposed a separate short-stream accounting boundary: the boot
prebuffer's last sector can contain padding after the final real pattern.
Raw-funding accounting now checks the complete real load count and advances
only through real preload entries, excluding those pad patterns.

Before adopting the behavior for natural footage, keep its original raster,
cadence, cold cap, filters and palette policy. Compare before/during/after the
fade, measure visible pending cells and completion time, and verify the exact
packed player. The existing full-movie result can serve as the ordinary-frame
fallback comparison. New source encoding requires the user's authorization.

Render selected comparison windows from either completed simulation without
encoding or modifying its stored decisions:

```sh
tools/python.sh harness/fade_preparation/render_windows.py \
  /path/to/completed-sim /path/to/comparison/baseline \
  --range 9070:9180 --range 13910:14020
```

Ranges are half-open diagnostic selections, not encoder adoption ranges. The
script leases the completed input, uses the production display reader, and
writes preview/category PNGs plus `windows.json` outside the source artifact.
Choose identical windows for baseline/current, and compare the previews with
their matching `raw/` source frames. These simulated images do not replace
actual packed-player capture evidence.

Compare matching windows against their correctly aligned extracted source:

```sh
tools/python.sh harness/fade_preparation/compare_windows.py \
  /path/to/comparison/baseline /path/to/comparison/current \
  --tsv logs/fade-comparison.tsv --montage /path/to/comparison/selected.png \
  --frames 9097,9104,13955
```

The e201/p173 full Big Buck Bunny encode completed 19,038 frames in 3,437.3
seconds with no replanning. The previous failing fade deadline at frame 9097
completed its reference with 190 visible cold loads rather than reserving 94
loads for a later reference first. Across 411 fade diagnostic frames, the
committed display matched its ideal quantized fade reference exactly; seven
black preparation frames still had pending cells. This movie did not need
visible catch-up beyond a reference deadline.

Across 590 selected source-aligned frames, mean RGB MAE was 10.164 for e197
and 10.149 for e201 (0..255 channels). This is not a clean parent-only A/B:
intervening encoder changes also affect placement. The newly adopted fade
around frame 9104 has flatter gray shadow gradations than the earlier
ordinary-frame fallback. Zero error against the planned reference does not
mean unchanged source fidelity.

Independent e201 packing rejected
frame 235: display reserve 2,372 + 11 patterns * 16 + 7 runs * 96 = 3,220,
above 3,200 units. Exactly one frame failed that cost audit. This exposed a
missing construction-time final-publication constraint, separately from fade
preparation. The e202 allocator reserves singleton costs before placement;
Finalize checks final source runs, while the independent packed-reader check
remains unchanged. Replaying the actual pre-frame-235 state preserved all 515
visible updates and their 197 cold loads, moving four of the 11 tail loads to
ordinary slots without tearing. That isolated replay excludes subsequent
prefetch and is not evidence for the full changed movie.

The e202 natural-footage series encoded Sonic OP, Lunar, Machi OP, Machi ED,
then full Big Buck Bunny without changing their source profiles. Every encode
used one physical planning pass and had zero whole-movie replanning restarts.
This count excludes internal WordBuf layout convergence. BBB completed in
3,653.6 seconds; its independent packed reader passed all 19,038 frames,
including frame 235. All seven fade preparation deadlines had zero pending
cells. Its 411 fade diagnostic frames still matched the ideal quantized fade
reference, which does not prove unchanged source fidelity.

The BBB DEBUG build exposed a separate resident Sub size failure: 5,130 bytes
of text exceeded the fixed 5,120-byte allocation. p174 folds the constant boot
WordBuf cursor wrap at assembly time; the actual linked BBB image is 5,104
bytes. The memory map and timed transfer routines are unchanged. The assembly
matrix now includes long routing, audio-rate dithering and scroll/WordBuf-ring
features together, so this combination must fit before recording.

All five completed e202 encodes were reused for fresh p174 DEBUG captures in
the same order. Each capture contains every first-loop frame. The counts below
are abnormal display intervals, not independent stalls; ordinary 24fps cadence
alternates two and three VSyncs. Edge exceptions are kept separately, and
untimed frame zero and the terminal hold are outside the interval measurement.

| Movie | Encode seconds | Interior irregular intervals | Edge irregular intervals | Playback gate |
|---|---:|---:|---:|---|
| Sonic OP | 175.2 | 0 | 1 | PASS / NONE |
| Lunar | 386.1 | 249 | 0 | PASS / WARNING |
| Machi OP | 215.9 | 0 | 0 | PASS / NONE |
| Machi ED | 337.4 | 1 | 1 | PASS / WARNING |
| Big Buck Bunny | 3653.6 | 3895 | 2 | FAIL |

Lunar has 237 two/three-VSync phase deviations, eleven four-VSync holds and
one five-VSync hold. Its earlier p173 capture of the same e202 encode had 89
irregular intervals; the increase is retained as an unresolved playback result.
Machi ED's interior deviation is frame 416 held for two rather than four VSyncs.
The first four movies have zero sector slip, control desync and audio resync.

BBB has sector-slip peak six, control-desync peak zero and audio-resync peak
two. APPLY backpressure first appears at frame 9359; the first sector-gap
recovery and audio resync appear at frame 9361, capture time 329.379 seconds.
Frames 9360, 9362, 9365, 9367 and 9369 each hold for fifteen VSyncs (about
250 ms). Most other cadence deviations occur in the late scrolling section.
These observations locate a playback failure but do not establish its root
cause. The failed HUD gate remains failed; no further source encode was run.

Actual VDP traces pass for all five movies: final-tail, name-table and display
control writes have zero active-display or boundary-crossing words. That proves
this transfer-safety check, not successful CD/audio playback. BBB is therefore
not qualified for publication. Matching logs, gates, recordings and disc hashes
are retained in `logs/issue127-e202p174-series.json`; the compact result table is
`logs/issue127-e202p174-summary.tsv` with detailed JSON beside it.
