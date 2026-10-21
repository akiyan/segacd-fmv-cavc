# Encoder planner equivalence

`compare.py` runs the actual planner modules from a frozen reference tools
directory and the current checkout in separate processes. It compares complete
schedule traces and rejection details, online per-frame limits, WordBuf source
choices and refill routes, quality reserves, and dictionary ordering.
It does not decode or encode source media.

The fixtures exercise sector boundaries, alternating cadence, finite PrgBuf
capacity, early spare delivery followed by a burst, tail drain, whole-run Word
selection, and separated quality-budget shortages. They catch decision changes
caused by cache keys, incremental counters, subset ordering, or skipped prefix
deadlines. Capacity trials return to their initial capacities after two other
layouts, comparing shared preparation against fresh reference plans to catch
leaked source assignments or counters. The existing unit suites retain
independent physical-deadline and packed-reader checks.

Export the reference code once, before editing:

```sh
mkdir -p /tmp/cavc-planner-reference
git archive HEAD tools | tar -x -C /tmp/cavc-planner-reference
tools/python.sh harness/encoder_planning/compare.py \
  --reference-tools /tmp/cavc-planner-reference/tools \
  --tsv logs/planner-reuse.tsv --json logs/planner-reuse.json
```

The default scaling case has 512 synthetic frames. Runtime is normally seconds
to about a minute, depending on the reference planner. Each case reports its
completion and elapsed time. Use `--frames` to select a larger planning-only
case explicitly. This is a component comparison; it is not an encoder
throughput benchmark or full-source memory qualification.

TSV timings describe one reference/current run per case, with no minimum speed
threshold. The JSON records source hashes, successful and rejected case counts,
and whether feasible WordBuf cases actually exercised timed refills. Only the
direct schedule fixtures and the reference's zero-boot-target WordBuf case
permit rejection; the online, reserve and dictionary cases must complete, and
at least one feasible WordBuf refill is required. The zero-boot case uses a
128-pattern bank entirely consumed by its two-sector reserve. Both revisions
reject the empty boot subset; this optimization does not repair that existing
edge case. Successful layout-reuse cases retain positive boot targets.
Compare matching evidence, and inspect the
first different result before changing either a fixture or production code.
Full-source qualification remains a separate tier described in
`harness/runtime_storage/README.md`.
