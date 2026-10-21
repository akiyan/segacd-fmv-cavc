# Project guidance

This is the Sega CD Constraint-Aware Video Codec. The active path is
`tools/sim.py -> tools/pack_stream.py -> boot/movieplay_*.s`. Keep work on this
encoder/player unless the user explicitly asks for another project.

For multipart requests or an enabled `[multipart].parts` setting, use the CLI
`tools/multipart.py PROFILE [--parts N] [--part K]`. It encodes independent
movies and builds their menu-free looping ISO when all parts are complete.
`README.md` (Multipart encoding) owns usage and `CONFIG.md` owns TOML/CLI
precedence. The single-movie `sim.py`/`parallel_run.py` entry points do not
select this workflow. This is also an available option for long-source planning.

## Scope, completion, and long jobs

- Follow the requested outcome and existing authorization. A skill is a scoped
  procedure, not permission to add unrelated stages. Read only the skills and
  references needed for the current task.
- Reuse completed, matching artifacts. Building an ISO, recording, rendering a
  timeline, or investigating a failure does not itself authorize a fresh encode.
  A request not to re-encode remains binding until the user changes it.
- Before expensive work, identify the input, required output, expected duration,
  and completion evidence. After a failure, inspect its logs and reuse valid
  upstream results. Do not repeatedly restart an unchanged long experiment.
- For routine long-source memory qualification, use the actual 16,384-frame
  source in `harness/runtime_storage/README.md`. It must run all encoder stages;
  a short clip is not a substitute. Maximum-index tests use synthetic packed
  fixtures unless a full-capacity source encode is explicitly needed.
- Keep long jobs observable: retain their command, process/service identity,
  current log, and exit status. Report fresh progress and meaningful changes;
  when continuous reports are requested, continue through completion. A stale
  receipt, missing process, or last progress line is not proof of success.
- Use existing resource/stem locks and artifact leases. Stop only task-owned
  processes. Do not bypass coordination or evict another live job's files.
- User-facing explanations should use plain language. If an ambiguous term
  would change format, memory ownership, buffering, cycle analysis, or branch,
  ask one short question naming the object, operation, and memory domain first.

## Terms that must stay distinct

| Object | Meaning |
|---|---|
| routing table | One byte per delivery slot recording sector counts; no pattern payload. |
| PrgBuf (`Prg`) | Streamed PRG-RAM circular buffer of prefetched 32-byte cold patterns. `RING_*` describes its implementation. |
| WordBuf0 / WordBuf1 (`Wr0` / `Wr1`) | Distinct boot-preloaded pattern sequences in the two physical 1M Word-RAM banks, selected by parity. |
| DicBuf (`Dic`) | 512-entry boot-preloaded Main-RAM dictionary, reusable by index without consumption. |
| APPLY ring | PRG-RAM queue of continuous control blocks. |
| resident pattern | A pattern currently retained in the VRAM tile pool. |
| whole-movie quality budget | Encoder spending accounting, not physical memory. Do not call it Tank. |
| Buf category | Funding class for an exact cold load, not a buffer meter. |
| Word RAM output bank | Sub/Main frame handoff area, not simultaneously owned by both CPUs. |

After a terminology correction, discard conclusions based on the wrong object.

## Validation by value

For each retained or proposed test, identify the realistic bug it would catch.
Compare that protection with runtime, flakiness, and maintenance cost. Do not
preserve test counts or coverage percentages for their own sake.

- Prefer externally visible results and independent data/reader checks.
- Remove implementation copies, mock self-checks, library/type guarantees,
  duplicate cases, and incidental private-shape assertions. Consolidate shared
  fixtures while preserving genuinely different failure modes.
- A Python copy of assembly is not evidence that the assembled player is right.
  Use actual disassembly or trace/capture evidence for that claim.
- Run the checks appropriate to the change once. Repeat after a relevant fix or
  new concern, not as a ritual. Cosmetic edits do not need new unit tests.
- Investigate failed checks before changing them. Test cleanup is not permission
  to hide a production failure. State any intentionally dropped guarantee.
- `harness/test_audit/README.md` lists test ownership, costs, and entrypoints.
  Expensive recordings, browser encodes, hardware checks, and maximum-length
  fixtures are explicit qualification tiers, not the default quick suite.

## Encoder and player invariants

The display aperture is H40 320x224; source aspect/rate and inner raster are
per-source settings. The DMA budget limits changes per frame, not canvas size.
Use HAR-aware fit/pad unless cropping is requested or fixed black bars are
confirmed. Audio is checkpointed 22.05 kHz mono IMA ADPCM.

Keep target quality fixed during regression work: raster, cadence, cold cap,
filters, and palette policy. A lower workload that stops a failure is a
workaround, not a repaired model. Starvation is an intended CD-1x outcome.
Do not report starved-frame percentages routinely. Report Miss distributions
alongside request volume only for codec tuning or quality comparisons.

- CD 1x is an absolute 75-sector/s service clock at **every cumulative prefix**.
  A later light slot cannot repay an already missed display deadline. Prove
  route capacity, each physical deadline, and finite buffer bounds separately.
  Fix an invalid schedule before spending PrgBuf/APPLY capacity to absorb it.
- Keep player frame -1 outside the timed suffix. Start that read after the
  visible frame-0 flip; first frame-1 control proves service before PCM starts.
  CD startup latency must not become audio lead.
- Keep CDC reads continuous. Pump while Main is working/idle, but service an
  arrived or cleared CMD_SWAP before optional future-data work. Long drain gaps
  can silently drop sectors. All apply/control total lengths stay even.
- Separate disc SP source, BIOS-loaded resident PRG, and boot-only scratch.
  Never infer safe scratch from an address gap; use the checked PLAYER map.
- Word-RAM DMA uses `src+2`, full length, normal destination, then CPU repair of
  the destination's **first** word for every chunk. Main-RAM DMA needs no repair.
  Enable DMA, rewrite length/autoincrement for every transfer, poll completion,
  and keep chunks within the VBlank word budget.
- Sounding RF5C164 wave writes need at least 16 Sub CPU cycles; register writes
  need 384. An emulator accepting faster writes is not hardware proof.
- When changing a shared stream layout, update every writer/reader together.
  Guard counts against corrupt data; zero/end and remaining-length bounds must
  not turn into runaway reads. On-disc backward compatibility is not maintained.

For failures, locate the first divergence across data, model, assembly, and
playback. Compare exact stream states, built instructions, and matching captures
as needed. Keep correctness, non-regression, and measured benefit separate.
Read waiting counters with cadence, slip/desync/resync, and buffer levels; a
higher wait count alone is neither failure nor improvement. A graph near zero
is not an exact signed balance. If tuning cannot make hardware reproduce the
sim, question the model before reducing quality again.

## Runtime paths and environments

Select storage explicitly for substantial jobs:

```sh
tools/python.sh --gpu --workspace-root /path/to/workspace \
  --scratch-root /path/to/ssd/scratch --array-storage disk \
  tools/sim.py profiles/PROFILE.toml
```

`tools/runtime.sh` accepts the same three storage options followed by `--` and
any command, including `make` and shell harnesses. Default workspace is
`tmp/workspace` under this checkout; scratch defaults to its `scratch/` child
(or an explicit TMPDIR). `/dev/shm` is opt-in. Disk-backed arrays on tmpfs still
consume RAM. Artifact leases/eviction cover managed entries only. Use the
printed artifact paths, not guessed locations. Build staging and ISO outputs
remain `tmp/PROFILE/` and `out/PROFILE{,_release}.{iso,cue}`.

Keep TSV logs and JSON receipts in git-ignored `logs/`. Delimited project data
uses UTF-8, a header, tabs, LF, and `.tsv`; use `--tsv` names. Media and temporary
arrays belong to the selected workspace/scratch. Completed sim reuse checks
source bytes, effective settings, and the public encoder version; interrupted
outputs have no completion marker. Bump the encoder version for output-affecting
changes; individual source-file hashes do not define this identity. Force
re-encode only when requested.

Use `tools/python.sh` with the pinned CPU environment, `--gpu` with its separate
CUDA environment. Bootstrap via `tools/bootstrap_python.sh`; no silent system
Python/NumPy fallback. A live CUDA parent requires spawned loader processes.
Read `CONFIG.md` for CPU/GPU/EMU tokens and shared resource roots. Separate
workspaces sharing one GPU need the same explicit `SEGACD_RESOURCE_ROOT`.

The encoder/storage harness targets POSIX systems. Emulator/Xvfb and burner
harnesses have Linux dependencies; do not claim native Windows support. Check
host device access before treating sandbox-only CUDA failure as a broken driver.

## Recording and publication

A plain record request ends with the requested recording. Analysis, HUD OCR,
HUD/mixed timelines, and uploads are separate outputs; generate them when
requested or needed by the selected publication/diagnostic workflow. Gist
publication is always opt-in and requires an explicit request for that
destination. Showing a timeline or uploading a video to YouTube does not imply
a Gist upload. Local results and YouTube descriptions must work without Gist
credentials or a public timeline URL. Already authorized publication does not
need a second approval after checks.

Use emulator-synchronized A/V and explicit native 320x224 FFV1/FLAC capture.
Keep startup and tail unless trimming is requested. Reuse the exact disc only
when its identity/mode is known; DEBUG is the recording default and HUD-free
requests select release. Replays belong to the exact disc/core/settings.
A normal capture checks counts, media, logs and representative frames. Requalify
same-Replay realtime/offline equivalence when the recording path changes or is
suspect, not on every capture. Follow `record` for commands and `release` for
HUD-free publication evidence. Never fabricate or transplant a gate JSON.

Use `extract_verification_frames.sh` and its fresh manifest; do not mix stale
stills via shared globs. Do not replace recorded audio with source audio or
claim sound quality without listening. Publication transcode settings belong
to `compilation`; metadata belongs solely to `YOUTUBE.md`. Link video/audio in
chat as ordinary clickable Markdown links, never inline embeds.

## Repository text and Git

- English for code, comments and general repository text; Japanese for commits,
  GitHub issues and PR comments. Author and committer are the human owner
  `akiyan`; no AI Co-Authored-By or session trailers.
- Keep unrelated changes intact. Branch from the requested base; push/merge and
  publication scope follow the user's authorization. Do not force-push main.
- Public root Markdown is English first, followed by a complete structurally
  matching Japanese version. Describe current behavior, not chronology. Only
  REMOVED.md holds absent-feature implementation notes.
- Keep public docs self-contained; do not name/link issues from Markdown.
  No scattered root notes. Diagnostic scripts and their README belong under
  `harness/<topic>/`; maintenance instructions belong here or scoped skills.
- `.claude/skills` aliases `.agents/skills`; edit the canonical copy once.
- Keep PROMPTS.md Japanese originals verbatim; fix translations only for errors.

Read and update the owner of changed behavior:

| Reference | Owns |
|---|---|
| README.md | Public setup and usage |
| MOVIE.md | HEADER/BODY format, matching packer and player |
| CONFIG.md | Knobs, runtime paths, buffers and limits |
| PLAYER.md | Memory map, boot and Main/Sub handoff |
| HUD.md | Fields, rendering and OCR |
| ENCODE.md | Stage flow and measured timing |
| ADPCM.md | Audio/hardware constraints |
| YOUTUBE.md | Upload metadata and version rules |
| tools/layout_preview.py | Analysis layout and reading rules |
| tools/analysis_style.py | Category semantics and colours |
| tools/render_analysis.py | Real-data/TSV/mux timing |

Do not create ANALYSIS.md or duplicate these specifications in skill prompts.
