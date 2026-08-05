EN / [JP](#jp)

# Removed Features

This document preserves engineering information for features that are absent
from the active encoder, packer, and player. Active behavior belongs in the
dedicated reference documents such as `ENCODE.md`, `CONFIG.md`, `MOVIE.md`,
and `HUD.md`, plus source comments beside analysis-overlay code.

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
[`85fa2c838bae480931a30c806613ce1841219b4f`](https://github.com/akiyan/segacd-fmv-cavc/commit/85fa2c838bae480931a30c806613ce1841219b4f).

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
5. Complete a full DEBUG playback gate and compare HUD `cold_runs` with the
   packed run trace before treating lower run counts as a usable improvement.

## H32 display mode

### Repository reference

The removal diff is fixed at commits
[`a7b185d`](https://github.com/akiyan/segacd-fmv-cavc/commit/a7b185d),
[`6b6f0b1`](https://github.com/akiyan/segacd-fmv-cavc/commit/6b6f0b1), and
[`78613a6`](https://github.com/akiyan/segacd-fmv-cavc/commit/78613a6).

### Boundary and purpose

H32 is the Mega Drive's 256-pixel-wide display mode: a 32x28 cell aperture with
a 8:7 dot ratio, which describes the same 64:49 visible NTSC area as H40's
320x224 at 32:35. Supporting it let a source be encoded into 896 cells instead
of 1,120, a 20% smaller tile grid for the same visible picture.

That saving does not survive contact with the rest of the codec. A wider dot
makes an ordered dither read as coarse texture rather than as a tone, which is
the opposite of what this codec's palette and dither stages are tuned for. H32
also has a narrower per-VBlank transfer budget — a conservative 2,800
DMA-word-equivalents against H40's 3,200 — so the cold cap that keeps a
schedule feasible is lower. Fewer cells to fill is cancelled by fewer patterns
deliverable per frame.

### Data flow and algorithm

The mode was a per-source encoder setting carried end to end:

1. `[video].mode` in the profile TOML selected `H32`, `H40`, or `MODE4`.
2. The encoder used the mode to pick the native horizontal raster (256 or 320)
   and the dot ratio used by the HAR-aware pad/crop conversion.
3. The mode governed the per-frame Main-CPU publication cost, because the DEBUG
   HUD's 43 digits split at the screen width: a 32-cell row left 11 spill
   digits at four sprite-table words each, while a 40-cell row leaves three.
4. The packer wrote the mode as one byte at `HEADER.DAT` offset 36, encoded
   `0` = H32, `1` = H40, `2` = mode4.
5. A generic player read that byte at startup and chose VDP register 12
   (`0x8C00` for H32, `0x8C81` for H40), the screen column count, and the
   VBlank word budget. A specialized player resolved the same three values at
   build time from `PC_MODE` in the generated `player_constants.inc`.
6. The centring offsets followed: `col0 = (screen_cols - tcols) / 2`, with
   `screen_rows` fixed at 28 in both modes.

mode4 — the Master System 192-line Mode 4 display — was never a player path. It
existed only as a name in three validation lists and as a measured DMA budget
in the `dmabench` diagnostic, which displayed in SMS Mode 4 and switched back
to Mode 5 inside VBlank to issue each DMA. Reaching it from a profile would
have failed at player-constant generation, at the analysis renderer, and at the
recorder's native-size lookup.

### Dependencies

- `[video].mode` in every profile TOML, and the `CBRSIM_MODE` environment
  variable it mapped to.
- A dot-ratio and default-raster table in the source-geometry helper, keyed by
  mode, plus a `mode` parameter on its plan and filter functions and a
  `--mode` CLI option.
- A screen-width and VBlank-budget table in the player-constant generator,
  keyed by the `HEADER.DAT` mode byte.
- A screen-geometry, dot-ratio, and theoretical-DMA table in the analysis
  layout module, read by the analysis renderer and the straight-sim exporter.
- A `mode` parameter on the name-table word model, which split the DEBUG HUD
  workload at the screen width.
- Two byte-identical HUD OCR layouts distinguished only by object identity,
  plus a width-to-layout selector, in the frame reader.
- A mode-to-native-recording-size dispatch in the parallel-run orchestrator.
- The `VB_WORDS_H32` / `VB_WORDS_H40` constant pair, the `md_mode` runtime
  variable, the startup mode branch, and the mode-conditional VDP register-12
  writes in the Main-CPU player.
- A `MODE` assembler symbol on the `dmabench` and `cpuvrambench` diagnostics,
  reached through `DMABENCH_MODE` and `CPUVRAMBENCH_MODE` in the Makefile.
- The artifact stem's display-mode component, which is now the fixed literal
  `H40`.

### Required invariants

- The mode must be frozen in the sim decision log and read from there by the
  packer. Reading it from the shell environment at pack time lets a changed
  variable relabel a stream that was encoded for the other mode.
- The `HEADER.DAT` mode byte, the packed geometry, and the player's VDP
  register-12 write must agree. A player that infers the width from anything
  else — the frame pacing interval, for instance — silently displays every
  stream in one mode.
- A grid must fit its mode's aperture: `tcols <= screen_cols` and
  `trows <= 28`. The centring offsets are derived, never stored.
- Rolling-plane scroll requires the full-width 40-column grid. HScroll shifts
  every scanline, so a narrower centered grid rolls its own side borders.
- The DEBUG HUD reserve must be computed from the screen width, not assumed:
  the spill-digit sprite records are the larger cost and they grow as the
  screen narrows.
- Every consumer of the mode must be updated together. A single stale lookup
  table — one keyed `mode4` in lowercase while the profile layer upper-cases —
  is a runtime `KeyError` rather than a rejected profile.

### Minimum reimplementation validation

1. Encode one source at both modes and confirm each produces a schedule that
   meets the CD 1x deadline at every prefix, with the cold cap qualified
   separately per mode rather than inherited.
2. Build the player-constant matrix for both modes at 15, 24 and 30 fps, in
   generic and specialized form, and confirm the generated screen width,
   VBlank budget, and centring offsets.
3. Prove the DEBUG HUD OCR layout for both screen widths: cell count, the wrap
   column, and that the unused row-1 width stays movie-visible.
4. Record a full DEBUG playback per mode and pass the complete HUD gate; a mode
   that only assembles is not qualified.
5. Confirm the analysis renderer and the upload transcode bake the correct dot
   ratio per mode, and verify any new mode's pixel aspect in the geometry
   harness before adding it.

---

<a id="jp"></a>

# 削除済み機能

この文書は、現行のencoder、packer、playerには存在しない機能について、実装上の情報を
保存します。現行の動作は、`ENCODE.md`、`CONFIG.md`、`MOVIE.md`、
`HUD.md`などの専用referenceとanalysis-overlay code直近のsource commentへ記載します。

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
[`85fa2c838bae480931a30c806613ce1841219b4f`](https://github.com/akiyan/segacd-fmv-cavc/commit/85fa2c838bae480931a30c806613ce1841219b4f)
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
5. full DEBUG playback gateを完了し、HUD `cold_runs`とpacked run traceを比較してから、
   run数低下を利用可能な改善として扱います。

## H32 display mode

### Repository上の参照先

削除diffはcommit
[`a7b185d`](https://github.com/akiyan/segacd-fmv-cavc/commit/a7b185d)、
[`6b6f0b1`](https://github.com/akiyan/segacd-fmv-cavc/commit/6b6f0b1)、
[`78613a6`](https://github.com/akiyan/segacd-fmv-cavc/commit/78613a6)
で固定されています。

### 境界と目的

H32はMega Driveの横256画素のdisplay modeです。32x28 cellのapertureにドット比8:7で、
H40の320x224・32:35と同じ64:49の可視領域を表します。これを使うと、同じ見た目の絵を
1,120 cellではなく896 cellへencodeでき、tile gridが20%小さくなります。

しかしこの節約はcodecの他の部分と噛み合いません。ドットが大きいと、ordered ditherは
階調ではなく粗いテクスチャとして見えます。これはこのcodecのpaletteとdither段が想定
している方向と逆です。さらにH32はVBlank当たりのtransfer budgetが狭く、H40の3,200
DMA-word相当に対して安全側で2,800しかないため、scheduleを成立させるcold capも下がり
ます。埋めるcellが減っても、1コマで供給できるpatternがそれ以上に減って相殺されます。

### Data flowとalgorithm

modeはsourceごとのencoder設定として端から端まで運ばれていました。

1. profile TOMLの `[video].mode` が `H32` / `H40` / `MODE4` を選ぶ。
2. encoderはmodeからnativeな横raster(256または320)と、HAR対応のpad/crop変換に使う
   ドット比を決める。
3. modeはframeごとのMain-CPU publication costを左右する。DEBUG HUDの43桁が画面幅で
   分割されるためで、32 cell行では11桁がsprite table 4 wordずつのspillになり、
   40 cell行では3桁で済む。
4. packerはmodeを1 byteとして `HEADER.DAT` offset 36へ書く。`0`=H32、`1`=H40、
   `2`=mode4。
5. 汎用playerは起動時にこのbyteを読み、VDP register 12(`0x8C00`=H32、`0x8C81`=H40)、
   画面列数、VBlank word budgetを選ぶ。specialized playerは生成した
   `player_constants.inc` の `PC_MODE` から同じ3値をbuild時に解決する。
6. 中央寄せoffsetはそこから導出する。`col0 = (screen_cols - tcols) / 2` で、
   `screen_rows` はどちらのmodeでも28固定。

mode4(Master Systemの192ライン Mode 4表示)はplayer経路として存在したことがありません。
3つのvalidation listに名前があるのと、`dmabench` 診断でDMA budgetを実測していただけ
です。この診断はSMS Mode 4で表示し、VBlank内だけMode 5へ戻してDMAを出していました。
profileからmode4へ到達しても、player constant生成、analysis renderer、recorderの
native size解決のいずれかで失敗します。

### 依存関係

- 全profile TOMLの `[video].mode` と、それが対応していた環境変数 `CBRSIM_MODE`。
- source geometry helper内の、mode keyのドット比・既定raster表と、plan/filter関数の
  `mode` 引数、および `--mode` CLI option。
- player constant generator内の、`HEADER.DAT` mode byteをkeyにした画面幅・VBlank
  budget表。
- analysis layout module内の、画面geometry・ドット比・理論DMA表。analysis renderer
  とstraight-sim exporterが参照していた。
- name-table word modelの `mode` 引数。DEBUG HUDの負荷を画面幅で分割していた。
- frame reader内の、object identityでしか区別できないbyte同一なHUD OCR layout 2本と、
  幅からlayoutを選ぶ関数。
- parallel-run orchestrator内の、modeからnative recording sizeを引く分岐。
- Main-CPU player内の `VB_WORDS_H32` / `VB_WORDS_H40` 定数対、`md_mode` 実行時変数、
  起動時のmode分岐、mode条件つきのVDP register 12書き込み。
- `dmabench` / `cpuvrambench` 診断のassembler symbol `MODE` と、Makefileの
  `DMABENCH_MODE` / `CPUVRAMBENCH_MODE`。
- artifact stemのdisplay mode成分。現在は固定literal `H40`。

### 必須invariant

- modeはsim decision logで凍結し、packerはそこから読むこと。pack時にshell環境から
  読むと、変数の変更だけで別modeでencodeしたstreamにラベルを付け替えられてしまう。
- `HEADER.DAT` のmode byte、packされたgeometry、playerのVDP register 12書き込みが
  一致すること。playerが他の値(例えばframe pacing interval)から幅を推測すると、
  全streamが黙って片方のmodeで表示される。
- gridは自分のmodeのapertureに収まること。`tcols <= screen_cols` かつ
  `trows <= 28`。中央寄せoffsetは導出値であり、保存しない。
- rolling-plane scrollは全幅40列gridを要求すること。HScrollは全scanlineをずらすため、
  幅の狭い中央寄せgridでは自分の左右borderが流れてしまう。
- DEBUG HUDのreserveは画面幅から計算すること。spill桁のsprite recordの方が高価で、
  画面が狭いほど増える。
- modeの利用者は全て同時に更新すること。lookup表が1つでも古いと(profile層が大文字化
  する一方で表のkeyが小文字の `mode4` のまま、など)、profileが拒否されるのではなく
  実行時の `KeyError` になる。

### 再実装時の最小validation

1. 同一sourceを両modeでencodeし、どちらも全prefixでCD 1x deadlineを満たす
   scheduleになることを確認します。cold capはmodeごとに個別にqualifyし、
   もう一方から引き継ぎません。
2. 15/24/30 fpsについて両modeのplayer constant matrixをgenericとspecialized両方で
   buildし、生成された画面幅、VBlank budget、中央寄せoffsetを確認します。
3. 両方の画面幅についてDEBUG HUD OCR layoutを証明します。cell数、折り返し列、
   および行1の未使用幅がmovie表示のまま残ることを確認します。
4. modeごとにfull DEBUG playbackを録画し、HUD gateを完全に通します。assembleが
   通るだけのmodeはqualified扱いにしません。
5. analysis rendererとupload transcodeがmodeごとに正しいドット比を焼き込むことを
   確認します。新しいmodeを追加する場合は、先にgeometry harnessでpixel aspectを
   検証します。
