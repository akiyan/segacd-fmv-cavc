# Multipart qualification

The quick checks catch dropped/duplicated output frames, fractional audio-boundary
drift, invalid part selection and a source-range environment leaking into a later
single-movie encode, plus tampered or mismatched completed parts. FFmpeg actually
extracts the small frame fixture. An independent ISO reader rejects an oversized
root directory and modified payload bytes in an actual generated ISO.
Count selection checks cover TOML defaults, CLI overrides, invalid counts and
part numbers. A six-frame source verifies that moving the same count between
TOML and CLI preserves generated profile bytes and the reusable plan; it does
not run the codec encoder.

```sh
tools/python.sh -m unittest discover -s harness/multipart -p 'test_*.py'
```

Full playback is an explicit emulator tier. First prepare the requested source
with `tools/multipart.py ... --parts N --debug`; this is a real encode if parts
are absent. Encoding one selected part first and rerunning without `--part`
exercises deferred ISO creation and completed-part reuse. A build manifest is
written under `out/<multipart-stem>/multipart.json`.

```sh
tools/python.sh --workspace-root /path/to/workspace \
  --scratch-root /path/to/ssd/scratch --array-storage disk \
  harness/multipart/run.py out/<multipart-stem>/multipart.json --max-frames 10000
```

The example frame limit covers Sonic Jam OP split into three parts, including
startup/loading and the next cycle. Increase it for longer sources. This runs
the existing ISO; it never encodes or records A/V. Logs and exit receipts remain
in `logs/`, with the ISO snapshot and complete compressed LOGVDP trace in a
leased workspace artifact. The receipt binds the ISO, manifest, trace and SIM
decision hashes. Its TSV is a diagnostic result, not a recording/publication
HUD gate. A failed parser check can be rerun on the retained trace with the same
runtime roots and `harness/multipart/verify_trace.py --receipt logs/<run>.json`.

`verify_trace.py` checks actual assembled dispatcher markers in order, every
movie frame number, zero recovery counters, and every displayed RGB333 pixel
against the corresponding independent SIM decisions. It requires all parts to
finish and the next cycle to display frame 0. This catches stale palette/pattern
state, skipped tails, a wrong module or stream selection, and failure to loop.
Only non-scrolling DEBUG parts are supported by this pixel comparator; reject
other cases explicitly rather than claiming that an unobserved path passed.

This proves behavior in the managed Genesis Plus GX core, not physical drive
timing or audio quality. The ordinary player build/disassembly matrix owns
single-movie regression checks. Maximum part-table sizing can be checked by
assembling `multipart_build.main_include`/`sub_include` with 64 entries and
checking the linked Main/Word loader sizes. It needs no maximum-length encode.

## Requested recording and publication

Record an existing disc with `tools/record_movie.sh --disc <cue> --no-build
--seconds N --trim 0 --record-size 320x224`. Generate a separate input Replay
for each disc. Bind the recording, complete trace, manifest and ISO hashes in
the capture receipt. `analyze_recording.py --capture-receipt <json> --json
logs/<run>-hud.json` reads its `captures.debug` entry and applies the existing
schema-16 HUD gate separately to each completed movie visit. It requires the
actual frame-minus-one/frame-zero anchor for every visit and all parts plus the
next cycle's frame zero. A bounded recording can end before the trace's extra
ten-second tail; only observed recorded visits receive a gate. Boundary timings
are written to a TSV, not used to trim the recording.

For HUD-free publication, compare the matching DEBUG/release stream hashes and
recording DMA logs using the `release` skill, then follow `compilation` and
`YOUTUBE.md`. These stages are only run when recording/publication is requested.
