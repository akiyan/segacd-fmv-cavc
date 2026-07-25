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
| **Palette** | Divide the movie into palette segments and train each segment's CRAM palettes. |
| **Quantize** | Convert every frame into palette assignments and indexed 8x8 patterns. |
| **Forecast** | Calculate one-pass future demand, physical delivery limits, quality reserves, and boot-preload use. |
| **Decide** | Select each frame's exact or reused patterns, allocate VRAM slots, assign pattern sources, and commit the physical budget. |
| **Finalize** | Verify the complete physical schedule and write the numeric traces and decision log. |

## Measured Time

The following measurement uses the current encoder version
`20260725.e124`: H40, 288x200 pixels, 30 fps, 2,714 frames, and GPU
quantization on an NVIDIA GeForce RTX 4090. It is a forced full encode with no
cached simulation artifact.

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
| **Palette** | 映像をパレット区間に分け、区間ごとのCRAMパレットを学習します。 |
| **Quantize** | 全フレームをパレット割り当てとインデックス形式の8x8パターンへ変換します。 |
| **Forecast** | 将来の需要、物理配信上限、画質用の予約量、起動時プリロード利用を1パスで計算します。 |
| **Decide** | 各フレームの正確パターンまたは再利用パターンを選び、VRAMスロットを割り当て、パターン供給元を決め、物理予算を確定します。 |
| **Finalize** | 全編の物理スケジュールを検証し、数値ログと決定ログを書き出します。 |

## 実測時間

次の計測は、現在のエンコーダ版 `20260725.e124`、H40、288x200ピクセル、
30 fps、2,714フレーム、NVIDIA GeForce RTX 4090によるGPU量子化を使用して
います。既存のsim成果物を再利用しない全編エンコードです。

| 工程 | 時間 | 1フレームあたり |
|---|---:|---:|
| Extract | 7.3秒 | 2.7 ms |
| Palette | 12.9秒 | 4.7 ms |
| Quantize | 8.6秒 | 3.2 ms |
| Forecast | 72.7秒 | 26.8 ms |
| Decide | 114.3秒 | 42.1 ms |
| Finalize | 0.9秒 | 0.3 ms |
| **合計** | **216.9秒** | **79.9 ms** |
