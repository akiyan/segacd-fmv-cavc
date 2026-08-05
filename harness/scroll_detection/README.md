# Automatic scroll detector harness

This harness runs the production axis-only motion detector over an ordered PNG
sequence and writes every transition as TSV. It does not accept or store manual
adoption ranges: `--first-frame` only maps a disposable extracted clip back to
the source frame number while iterating.

The detector lets textured 16-by-16 source blocks vote for integer horizontal
or vertical motion up to 24 pixels per frame. Flat fields and black bars do not
vote. A pair must have enough support, improve the zero-motion residual, beat a
non-adjacent runner-up, and stay below the cut residual. Temporal grouping can
bridge at most two holds or missed pairs, stops at cuts, and validates accepted
segments again over two-frame spans.

```sh
tools/python.sh harness/scroll_detection/analyze.py \
  /dev/shm/segacd-fmv-ttrc/issue29/source \
  --first-frame 1056 \
  --backend cpu \
  --tsv /dev/shm/segacd-fmv-ttrc/issue29/lunar-scroll.tsv
```

The production encoder always scans the complete source. A short extracted
sequence is only a fast detector-development loop.

## 日本語

このharnessは、productionのaxis-only motion detectorを時系列PNGへ実行し、各遷移を
TSVへ書き出します。手動の採用範囲は受け取らず保存もしません。`--first-frame`は、
使い捨ての短尺clipを元sourceのframe番号へ対応付けるためだけに使います。

Detectorはtextureのある16x16 source blockに、1 frameあたり最大24 pixelの整数の
水平または垂直motionを投票させます。平坦面とblack barは投票しません。各pairは、
十分なsupport、zero-motion residualからの改善、隣接候補以外のrunner-upとの差、cut未満の
residualを満たす必要があります。Temporal groupingは最大2 frameのholdまたは検出漏れを
橋渡しし、cutで終了し、採用候補を2-frame spanでも再検証します。

```sh
tools/python.sh harness/scroll_detection/analyze.py \
  /dev/shm/segacd-fmv-ttrc/issue29/source \
  --first-frame 1056 \
  --backend cpu \
  --tsv /dev/shm/segacd-fmv-ttrc/issue29/lunar-scroll.tsv
```

Production encoderは常にsource全編を走査します。短尺の展開sequenceは、検出器を高速に
開発するためだけに使います。
