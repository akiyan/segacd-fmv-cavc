# Strict playback-frame cadence verifier

This harness proves that every movie frame in a native DEBUG playback recording
first appears at its exact step in an authoritative repeating VBlank cadence.
It covers the 15 fps `(4)`, 24 fps `(2, 3)`, and 30 fps `(2)` schedules.

`verify.py` decodes the recording sequentially at its native 320x224
geometry.  It sends only the top-left 40x24 pixels to
`tools/read_frameno.py:read_frameno`, so no other DEBUG field influences the
result. A plausible exact sequence beginning at `frame=0000` anchors the movie.
From that point the verifier rejects:

- a skipped F value;
- a high-confidence F value that moves backwards;
- a first appearance that is earlier or later than the required number of
  capture frames;
- a recording that ends before the requested final F value.

The complete proof uses the frame count, nominal fps, feature bit, and first
VBlank interval from the matching packed `HEADER.DAT`. For 24 fps, frame 1 must
appear two capture frames after frame 0, frame 2 three later, then the pattern
repeats:

```sh
tools/python.sh harness/frame_cadence/verify.py \
  "$LOSSLESS" \
  --header out/bad-apple/HEADER.DAT
```

Override the header with one repeated interval when diagnosing a fixed target:

```sh
tools/python.sh harness/frame_cadence/verify.py RECORDING.mkv \
  --header out/PROFILE/HEADER.DAT --vblanks 2
```

For a short capture, stop the proof at an inclusive decimal or hexadecimal
movie-frame number:

```sh
tools/python.sh harness/frame_cadence/verify.py RECORDING.mkv \
  --header out/bad-apple/HEADER.DAT --through-frame 0x0386
```

Once the requested final F first appears, later recording frames are outside
the proof.  This deliberately excludes the normal held tail after the movie or
after a bounded diagnostic capture.  The initial anchor still uses four movie
frames by default so an isolated startup OCR match cannot impersonate
`frame=0000`.

The default confidence threshold is `0.90`.  `--crop-x N` shifts the OCR crop
origin N pixels right for a capture whose playfield does not start at the left
edge.  Do not run this against the enlarged
upload compilation: the verifier requires the approximately 60 fps native
lossless recording so one capture frame corresponds to one emulator VBlank.

Run the unit tests with the pinned project environment:

```sh
tools/python.sh -m unittest discover -s harness/frame_cadence -p 'test_*.py'
```

This DEBUG HUD is a diagnostic signal only.  It must not be used to trim an
upload or to place any timestamp in an upload description.
