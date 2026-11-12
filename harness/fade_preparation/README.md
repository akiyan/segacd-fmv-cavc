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
