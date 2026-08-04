EN / [JP](#jp)

# Simulation Encoding Pipeline

This document describes the processing flow and measured time of
`tools/sim.py`. Disc packing and analysis rendering are outside this timing.

## Flow

```text
Extract -> Palette -> Quantize -> Forecast -> Decide -> Finalize
```

| Stage | Processing |
|---|---|
| **Extract** | Decode the source into encoder frames, comparison frames, and mono audio. |
| **Palette** | Divide the movie into palette segments, train each segment's CRAM palettes, and automatically detect spatially static shots with a black-bounded fade on one or both sides, without source-time inputs. |
| **Quantize** | Convert every frame into palette assignments and indexed 8x8 patterns; automatically detect source-wide hardware-scroll segments without source-time inputs, select the adopted scroll windows and their per-frame plane states, and quantize each window's world-mosaic guard edges; selected fades freeze one exact reference image and derive their inline CRAM steps. |
| **Forecast** | Calculate one-pass future demand, physical delivery limits, quality reserves, boot-preload use split between the frame-0 inline staging area and the boot-VRAM sidecar backside, and mandatory reference-prefetch room for one-sided fade-outs. |
| **Decide** | Select each frame's exact or reused patterns, keep the preceding display's slots live until the final name-table DMA and reject choices whose temporary old-plus-new pattern union would overflow VRAM, allocate slots, retain resident one-sided fade references and collect their cold preloads into a contiguous edge block, catch up any reclaimed entries, reserve each adopted scroll frame's guard-edge supply and clamp its cold and Prg ceilings to the single-run limit, assign pattern sources, and commit the physical budget. |
| **Finalize** | Plan the shadow update lists over the exact shared-sector pack route, add each scroll frame's rolling-plane name-table words, verify the complete physical schedule, and write the numeric traces and decision log. |

## Measured Time

The following measurement is a versioned historical reference taken at
encoder version `20260725.e124`, before automatic hardware-scroll adoption
existed: H40, 288x200 pixels, 30 fps, 2,714 frames, and GPU quantization on
an NVIDIA GeForce RTX 4090. It is a forced full encode with no cached
simulation artifact. This 36x25-cell geometry lacks the full-width 40-column
grid that hardware-scroll adoption requires, so its Quantize and Decide times
contain no scroll detection or guard work.

| Stage | Time | Time per frame |
|---|---:|---:|
| Extract | 7.3 s | 2.7 ms |
| Palette | 12.9 s | 4.7 ms |
| Quantize | 8.6 s | 3.2 ms |
| Forecast | 72.7 s | 26.8 ms |
| Decide | 114.3 s | 42.1 ms |
| Finalize | 0.9 s | 0.3 ms |
| **Total** | **216.9 s** | **79.9 ms** |

---

<a id="jp"></a>

# シミュレーション・エンコード工程

この文書は `tools/sim.py` の処理フローと実測時間を説明します。ディスクへの
パックと解析レンダリングは、この計測には含みません。

## 処理フロー

```text
Extract -> Palette -> Quantize -> Forecast -> Decide -> Finalize
```

| 工程 | 処理 |
|---|---|
| **Extract** | ソースをエンコーダ用フレーム、比較用フレーム、モノラル音声へ展開します。 |
| **Palette** | 映像をパレット区間に分け、区間ごとのCRAMパレットを学習し、sourceのtime指定なしで片側または両側が黒に接するfadeのうち、空間的に静止したshotを自動検出します。 |
| **Quantize** | 全フレームをパレット割り当てとインデックス形式の8x8パターンへ変換し、sourceのtime指定なしでハードウェアscroll区間を自動検出して採用windowと各frameのplane状態を決め、windowごとのworld-mosaic guard辺を量子化します。選択したfadeは1枚の正確なreference imageを固定してinline CRAMの段階を決めます。 |
| **Forecast** | 将来の需要、物理配信上限、画質用の予約量、起動時プリロード利用（frame 0のinline staging領域とboot-VRAM sidecarのbacksideへの振り分けを含む）、片側fade-outに必須のreference prefetch容量を1パスで計算します。 |
| **Decide** | 各フレームの正確パターンまたは再利用パターンを選び、最後のname-table DMAまで直前表示のslotを維持し、一時的な旧表示と新表示のpattern和集合がVRAMを越える選択を退けてslotを割り当て、片側fade referenceのresident分を維持しながらcold preloadを端の連続blockへ集約して回収されたentryを取り戻し、採用したscroll frameではguard辺の供給分を予約して単独runを前提にcoldとPrgの上限をクランプし、パターン供給元と物理予算を確定します。 |
| **Finalize** | packと同一の共有sector経路でshadow update listを計画し、scroll frameのrolling plane分のname-table wordを加算したうえで、全編の物理スケジュールを検証し、数値ログと決定ログを書き出します。 |

## 実測時間

次の計測は、エンコーダ版 `20260725.e124` 時点（ハードウェアscroll自動採用の
実装より前）の版数付き参考値です。H40、288x200ピクセル、30 fps、2,714フレーム、
NVIDIA GeForce RTX 4090によるGPU量子化を使用しています。既存のsim成果物を
再利用しない全編エンコードです。この36x25 cellの解像度はscroll採用に必要な
全幅40列gridを持たないため、QuantizeとDecideの時間にscroll検出やguard処理は
含まれません。

| 工程 | 時間 | 1フレームあたり |
|---|---:|---:|
| Extract | 7.3秒 | 2.7 ms |
| Palette | 12.9秒 | 4.7 ms |
| Quantize | 8.6秒 | 3.2 ms |
| Forecast | 72.7秒 | 26.8 ms |
| Decide | 114.3秒 | 42.1 ms |
| Finalize | 0.9秒 | 0.3 ms |
| **合計** | **216.9秒** | **79.9 ms** |
