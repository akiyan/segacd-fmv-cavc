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
