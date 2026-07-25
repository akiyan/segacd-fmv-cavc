# Removed Features

This document preserves engineering information for features that are absent
from the active encoder, packer, and player. Active behavior belongs in the
dedicated reference documents such as `ENCODE.md`, `CONFIG.md`, `MOVIE.md`,
`ANALYSIS.md`, and `HUD.md`.

Each removed-feature entry records:

1. the feature boundary and user-visible purpose;
2. the data flow and algorithms it used;
3. every source, configuration, cache, format, test, and documentation
   dependency it required;
4. the invariants and failure modes a clean reimplementation must handle; and
5. the minimum validation needed before rejoining the active pipeline.

Entries describe the feature as a self-contained design. They do not present a
release history or narrate transitions between versions.

## Movie-wide slot locality

### Repository reference

The removal diff is fixed at commit
[`85fa2c838bae480931a30c806613ce1841219b4f`](https://github.com/akiyan/segacd-fmv-ttrc/commit/85fa2c838bae480931a30c806613ce1841219b4f).

### Boundary and purpose

Movie-wide slot locality defines one bijection from logical allocator slots to
physical VRAM slots for an entire movie. The shared allocator remains the sole
owner of residency, eviction, prefetch pinning, and cold/reuse decisions. The
bijection changes only the numeric position of each resident pattern. Its goal
is to place slots that are often loaded together next to each other, reducing
the maximum number of cold-run descriptors and player transfer boundaries in
demanding frames.

This feature is separate from cold-run descriptors. Run descriptors, exact
descriptor-byte accounting, Prg/Wr/Dic source splitting, the 488-record player
limit, and physical CD/PrgBuf scheduling remain valid without it.

### Data flow and algorithm

1. A seed encode freezes every frame's logical placements and successful raw
   prefetch requests.
2. Frame 0 is excluded from the optimization objective because its transfers
   are boot work without a display deadline.
3. Cold slots are partitioned into groups that may form physical runs:
   visible Prg, raw-prefetch Prg, WordBuf, and individual DicBuf sequences.
   Runs never cross a source boundary or a non-consecutive DicBuf index.
4. Frames whose cold count is at least 85% of the configured cold cap form the
   deadline-heavy set. The target for this set is at most 30 source-aware runs.
5. An adjacency matrix accumulates weight for logical slots that occur in the
   same group. A deterministic maximum-weight, degree-two spanning forest is
   completed into one Hamiltonian path. Path order becomes physical slot order.
6. The objective compares, in order: run excess above 30 on deadline-heavy
   frames, maximum estimated transfer cost, and the 99th percentile estimated
   cost. The transfer estimate is `0.7 * cold + 9.5 * runs`.
7. The predictive map search uses 20 iterations. The completed-decision search
   uses a fixed 160-iteration budget. The value 160 is an empirical search
   budget rather than a bound or convergence proof; any reimplementation must
   replace it with a measured stopping rule or document a reproducible reason
   for the fixed budget.
8. An accounting encode pays the selected map's exact descriptor bytes while
   making quality decisions. A map derived from the completed trace may request
   another accounting encode only when it improves the heavy-frame maximum and
   changes the funded run-byte distribution. The orchestration allows at most
   four accounting passes.

### Dependencies

- Profile key: `[encoder].slot_locality`.
- Internal environment: `CBRSIM_SLOT_LOCALITY`,
  `CBRSIM_SLOT_LOCALITY_STAGE`, `CBRSIM_SLOT_LOCALITY_MAP`,
  `CBRSIM_SLOT_LOCALITY_RETRY_MAP`,
  `CBRSIM_SLOT_LOCALITY_RETRY_ALLOWED`, and
  `CBRSIM_SLOT_LOCALITY_REUSE`.
- Modules: `tools/slot_locality_pipeline.py`,
  `tools/sim_pass_cache.py`, and the locality/replay helpers in
  `tools/tile_alloc.py`.
- Encoder orchestration: seed, map derivation, exact accounting, bounded retry,
  and invocation-local reuse of palette, quantization, and future-demand data.
- Decision-log record: `slot_locality` schema, map, baseline/optimized run
  traces, risk-frame mask, and player execution mode.
- Packer behavior: logical-to-physical placement remapping and display
  equivalence checks.
- Diagnostics: timeline locality metadata and
  `harness/cold_cap_model/verify_slot_locality.py`.
- Tests: permutation validation, display equivalence, source-aware run groups,
  optimizer behavior, pass-cache identity, and multi-pass orchestration.

### Required invariants

- The map is a complete bijection over the configured VRAM pool.
- Logical cold/reuse membership, eviction order, and prefetch success do not
  change.
- Every displayed cell reads the same pattern and palette on every frame.
- Visible cold payload and raw-prefetch payload use their respective ascending
  physical-slot orders; name updates remain in cell order.
- Frame 0 inline/sidecar partitioning follows the final physical order but does
  not contribute to timed run optimization.
- Prg, WordBuf, and DicBuf boundaries split descriptors exactly as the player
  executes them.
- The final descriptor trace is fully funded by the whole-movie quality budget
  and every shared-sector prefix.
- The player run-table limit and VBlank transfer limits pass for every frame.
- A retry must make measurable progress and may not reuse an identical map.

### Minimum reimplementation validation

1. Replay all frames with identity and candidate maps and prove equal displayed
   cell-to-pattern states, equal cold counts, and zero tearing.
2. Compare sim and pack run counts, source splits, control bytes, and physical
   prefix margins for every frame.
3. Verify frame 0 inline/sidecar membership and every raw-prefetch deadline.
4. Run focused tests for malformed maps, source boundaries, retry convergence,
   and cache identity.
5. Complete a full DEBUG playback gate and compare HUD `N` with the packed run
   trace before treating lower run counts as a usable improvement.

---

# 削除済み機能

この文書は、現行のencoder、packer、playerには存在しない機能について、実装上の情報を
保存します。現行の動作は、`ENCODE.md`、`CONFIG.md`、`MOVIE.md`、
`ANALYSIS.md`、`HUD.md`などの専用referenceへ記載します。

削除済み機能の各項目には、次を記録します。

1. 機能の境界と利用者から見た目的
2. 使用していたdata flowとalgorithm
3. 必要としていたsource、configuration、cache、format、test、documentationの全依存
4. cleanに再実装するときに守るinvariantとfailure mode
5. 現行pipelineへ再参加する前に必要な最小validation

各項目は、機能単体で理解できる設計情報として記述します。release historyやversion間の
移行経緯は記述しません。

## 全編slot locality

### Repository上の参照先

削除diffはcommit
[`85fa2c838bae480931a30c806613ce1841219b4f`](https://github.com/akiyan/segacd-fmv-ttrc/commit/85fa2c838bae480931a30c806613ce1841219b4f)
で固定されています。

### 境界と目的

全編slot localityは、logical allocator slotからphysical VRAM slotへのbijectionを
動画全体で1つ定義します。residency、eviction、prefetch pinning、cold/reuse判定は
shared allocatorだけが管理し続けます。bijectionが変えるのはresident patternの番号上の
位置だけです。同時にloadされやすいslot同士を隣接させ、負荷の高いframeにおける
cold-run descriptor数とplayerの転送境界数の最大値を減らすことが目的です。

この機能はcold-run descriptorそのものとは別です。run descriptor、正確なdescriptor
byte会計、Prg/Wr/Dicのsource分割、playerの488 record上限、物理CD/PrgBuf scheduleは、
この機能がなくても有効です。

### Data flowとalgorithm

1. seed encodeで、全frameのlogical placementと成功したraw prefetch requestを固定します。
2. Frame 0の転送はdisplay deadlineを持たないboot workなので、最適化の目的から外します。
3. cold slotをphysical runにできるgroupへ分けます。visible Prg、raw-prefetch Prg、
   WordBuf、個別のDicBuf sequenceです。source境界や不連続なDicBuf indexをまたぐrunは
   作りません。
4. cold数が設定cold capの85%以上のframeをdeadline-heavy setとします。このsetの目標は
   source-aware runを30以下にすることです。
5. 同じgroupに現れるlogical slot同士へ重みを加えたadjacency matrixを作ります。
   deterministicなmaximum-weight degree-two spanning forestを1本のHamiltonian pathへ
   完成させ、そのpath順をphysical slot順にします。
6. 目的関数は、heavy frameで30を超えたrun数、推定転送costの最大値、推定転送costの
   99 percentileの順で比較します。転送推定は`0.7 * cold + 9.5 * runs`です。
7. 予測map探索は20反復、完了済みdecisionからの探索は固定160反復です。160はboundや
   convergence proofから導いた値ではなく、経験的な探索予算です。再実装では測定可能な
   停止条件へ置き換えるか、固定値の再現可能な根拠を文書化する必要があります。
8. accounting encodeは、選んだmapの正確なdescriptor byteを払いながらquality decisionを
   行います。完了済みtraceから得たmapがheavy frameの最大値を改善し、fund済みrun byte
   配分も変える場合だけ、次のaccounting encodeを要求できます。orchestrationの上限は
   4 accounting passです。

### 依存関係

- Profile key: `[encoder].slot_locality`
- Internal environment: `CBRSIM_SLOT_LOCALITY`、
  `CBRSIM_SLOT_LOCALITY_STAGE`、`CBRSIM_SLOT_LOCALITY_MAP`、
  `CBRSIM_SLOT_LOCALITY_RETRY_MAP`、
  `CBRSIM_SLOT_LOCALITY_RETRY_ALLOWED`、`CBRSIM_SLOT_LOCALITY_REUSE`
- Module: `tools/slot_locality_pipeline.py`、`tools/sim_pass_cache.py`、
  `tools/tile_alloc.py`内のlocality/replay helper
- Encoder orchestration: seed、map導出、正確なaccounting、上限付きretry、
  palette・quantization・future-demand dataのinvocation-local reuse
- Decision log: `slot_locality` schema、map、baseline/optimized run trace、
  risk-frame mask、player execution mode
- Packer: logical-to-physical placement remapとdisplay equivalence check
- Diagnostic: timelineのlocality metadata、
  `harness/cold_cap_model/verify_slot_locality.py`
- Test: permutation検証、display equivalence、source-aware run group、optimizer、
  pass-cache identity、multi-pass orchestration

### 必須invariant

- mapは設定VRAM pool全体に対する完全なbijectionであること
- logicalなcold/reuse membership、eviction順、prefetch成功可否を変えないこと
- 全frameの全display cellが同じpatternとpaletteを読むこと
- visible cold payloadとraw-prefetch payloadは、それぞれphysical slot昇順にし、
  name updateはcell順を維持すること
- Frame 0のinline/sidecar分割は最終physical順に従うが、timed run最適化には
  加えないこと
- Prg、WordBuf、DicBufの境界がplayerの実行どおりdescriptorを分割すること
- 最終descriptor traceがwhole-movie quality budgetと全shared-sector prefixで
  完全にfundされること
- 全frameがplayer run-table上限とVBlank転送上限を通ること
- retryは測定可能な前進を伴い、同一mapを再利用しないこと

### 再実装時の最小validation

1. identity mapとcandidate mapで全frameをreplayし、display cell-to-pattern stateが
   同一、cold数が同一、tearingが0であることを証明します。
2. 全frameでsimとpackのrun数、source分割、control byte、physical prefix marginを
   比較します。
3. Frame 0のinline/sidecar membershipと全raw-prefetch deadlineを検証します。
4. malformed map、source境界、retry convergence、cache identityのfocused testを
   実行します。
5. full DEBUG playback gateを完了し、HUD `N`とpacked run traceを比較してから、
   run数低下を利用可能な改善として扱います。
