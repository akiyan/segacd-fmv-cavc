# Test ownership and instruction audit

The review asks: **which realistic bug would escape if this check disappeared?**
Test count and coverage are not acceptance targets. Project-owned Python/Node
suites, browser verification scripts, diagnostic readers and hardware experiment
entrypoints are in scope; vendored dependencies and generated artifacts are not.

- `inventory.tsv`: each reviewed entrypoint/support file, execution tier,
  disposition, failure/scope rationale and remaining Python test methods.
- `candidates.tsv`: each removed/consolidated case or whole verifier, its cost
  or coupling problem, and the remaining guarantee or explicitly accepted loss.
- `instructions.tsv`: AGENTS/skill entrypoint sizes and the reason for each
  revision. Optional renderer/qualification references retain specific contracts.

## What is consolidated

Repeated configuration literals, private array shapes, simple arithmetic,
serialization/library guarantees, and tests which call only their own mocks are
removed. Real malformed-stream guards, physical-prefix/finite-buffer cases,
VRAM display preservation, ADPCM checkpoints, cache identity and lease ownership
remain. Palette and frame maximums use real packed fixtures, not a second
Python copy of assembly or a current packer called twice with different limits.

One fixture exercises both real run readers. Source geometry has one unit-suite
owner. Region README/licence cases share one meaningful contract. Browser UI
checks interactions and cancellation; `test:encode` owns actual ZIP/media output
and stale-download invalidation. Long/stress browser fixtures share one shell
entrypoint while preserving distinct workloads. Temporal tests run once.

Copied instruction-loop models, a second Python handler generator and unsupported
monolithic/routing migration verifiers are removed. Those models could stay green
while production assembly changed. Built instructions and matching LOGVDP or
capture evidence are the appropriate owners. Host tests no longer claim old
monolithic-format compatibility. Hardware microbench programs remain opt-in:
they access real registers/memory and measure behavior host libraries do not
promise; they are not ordinary unit tests.

## Run the appropriate tier

| Tier | Entry point | Use/cost |
|---|---|---|
| Local units | `tools/python.sh harness/test_audit/run.py` | Seconds; tools and harness units plus real streaming-log integration. Requires the project environment and m68k tools for palette fixtures. No long encode/emulator. |
| Planner equivalence | `harness/encoder_planning/README.md` | Seconds to about a minute; compare real reference/current planners on synthetic delivery data. No source encode; requires a frozen reference tools directory. |
| Full Sonic planning comparison | `webenc/harness/planning/README.md` | Explicit opt-in; complete 2,714-frame native/browser encodes on common normalized inputs, packed bytes, every replay frame and PCM. Tens of minutes. |
| Storage | `tools/python.sh harness/runtime_storage/smoke.py` | Real paths, subprocess locks, leases, mapped values and cleanup; seconds. |
| Log compaction | `bash harness/gpgx_logvdp/test_compact_log.sh` | Real byte-preserving archive; seconds. |
| Browser algorithms | `npm run test:sites`, `test:audio`, `test:temporal`, `test:admission`, `test:kernel`, `test:schedule` in `webenc/` | Actual worker/kernel/scheduler contracts; no source-movie encode. Kernel uses its native reference. |
| Browser UI | `npm run test:cold-cap` and `npm run test:ui` | Needs Playwright and a local server via WEBENC_URL; no full encode in UI suite. |
| Browser output | `npm run test:encode` | One actual sample encode, ZIP, playback MP4/audio and settings invalidation. |
| Browser workload | `npm run test:encode:long` or `test:encode:stress` | Explicit opt-in, defaults to 60 seconds of source; not repeated by UI/unit suites. |
| Full native memory/output | `harness/runtime_storage/README.md` | Actual 16,384-frame encode against a frozen parent; minutes, not a shortened video. |
| Player/recording/hardware | Topic-specific harness README | Only for affected behavior. Preserve real disassembly/capture evidence and matching identities. |

Do not rerun passing unrelated tiers after a wording edit. A failed assertion
is investigated before deletion: the UI suite's retired output-caption assertion
is replaced with the actual computed rate control, preserving the intended
source-rate override check.

## Instruction design

The guidance follows the [OpenAI skill/prompt design article](https://developers.openai.com/blog/rethinking-skills-and-prompts-for-gpt-6-astra):
keep triggers specific, load technical details when needed, and define outcomes
instead of forcing every task through a large itinerary. AGENTS retains the
project's non-obvious memory/physical-clock invariants and points to their owners.
Skills own scoped commands and conditional evidence, not duplicated constants.

Task history showed that a playback request could expand into expensive
re-encoding, full diagnostics and publication, and that already authorized work
could stop for another approval. The revised prompts preserve requested stage
omissions, existing authorization, valid upstream artifacts and concrete failure
state. They do not automatically publish a Gist merely to show a local image.
A complete-loop publication gate remains meaningful evidence, not another
permission checkpoint. The `.claude/skills` alias uses the same canonical files.

Runtime storage is explicit and independent of codec quality. The memory harness
separates process RSS from filesystem/system memory and records realistic limits
of the low-motion test source. A small test count or a lower sampled RSS alone
is not proof of correct encoding; the full output comparison is a separate check.

## Completed qualification

The inventory accounts for 221 test/diagnostic entrypoints and support files.
The candidate list records 177 deletion/consolidation decisions with their
replacement or accepted loss; removed Python test methods were checked against
that list for omissions.

The remaining local Python/harness suites, actual streaming-log integration,
log compaction, storage smoke and monitor child cleanup passed. The browser
build, Sites worker, audio, temporal, admission, native/Wasm kernel, scheduler,
cold-cap, UI, actual sample encode and exact frame-range RGB/PCM checks passed.
Long/stress workloads and unaffected hardware experiments remain opt-in.

The complete 16,384-frame parent/current encode and packed-stream comparison
also passed. Measured memory, timing, source identity and equality receipts are
in `harness/runtime_storage/README.md` and its adjacent TSVs. All 16 skill
entrypoints passed metadata validation. Detailed local execution logs use the
`logs/test-audit-` prefix.
