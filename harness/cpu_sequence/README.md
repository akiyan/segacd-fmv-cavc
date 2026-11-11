EN / [JP](#jp)

# CPU sequence slide illustration

`build.mjs` generates the Japanese slide diagram of steady-state 30 fps
playback. It includes the Main/Sub CPU flows, the hardware compartments,
icons, the two Word-RAM banks, and theoretical transfer-rate annotations.
It uses Node.js built-ins and inline SVG shapes; no npm packages, reference
images, source movie, encode, or emulator capture are required.

## Generate

Requirements: Node.js 18 or later, `rsvg-convert` for PNG output, and the
Noto Sans CJK JP font for rendering the Japanese labels. On Debian/Ubuntu,
the renderer and font packages are `librsvg2-bin` and `fonts-noto-cjk`.
SVG text remains editable and uses the viewer's installed fonts.

From the repository root:

```sh
node harness/cpu_sequence/build.mjs
```

This writes `cpu-sequence.svg` and `cpu-sequence.png`, both 2560 x 1440,
to `harness/cpu_sequence/out/`. That directory is already Git-ignored.
The script prints the output paths. PNG generation failure returns a nonzero
exit status and leaves the generated SVG available.

```sh
# SVG only; rsvg-convert is not required.
node harness/cpu_sequence/build.mjs --svg-only

# Relative output paths are resolved from the current working directory.
node harness/cpu_sequence/build.mjs --out-dir tmp/cpu_sequence
```

## Edit and verify

Edit the labels, positions, colors, and inline icon paths in `build.mjs`.
`cpu()` owns CPU tasks and phase bands, `common()` owns the hardware
compartments, `shared()` owns Word RAM and the communication registers,
and `transfers()` owns the horizontal links and RAM-copy annotations.
The current output uses the dark theme and the enclosing Word-RAM box.

Regenerate and inspect the PNG after a layout edit, checking text overlap,
arrow endpoints, and whether each link reaches the intended resource.
This is a reversible illustration change; an encoder test or capture is
not needed to verify its layout.

## Meaning and limits

- ODD/EVEN mean the first/second approximately 60 Hz display periods in one
  30 fps movie-frame interval. They do not select physical Word-RAM banks.
- Each CPU owns a different 128 KiB bank in 1M/1M mode. The curved SWAP
  arrows mean exchange of ownership, not copying bytes between banks.
  Word RAM and the communication registers physically belong to Mega CD.
- Process names and downward arrows stay inside the CPU areas. Horizontal
  solid links show data access/transfer relationships; dashed links show
  command/status communication. CPU-to-VRAM links denote DMA initiated by
  Main, not staging through CPU RAM. Not every source or operation is drawn.
- Active is 224 lines and VBlank approximately 38 lines. VBlank is enlarged
  for readability; both VBlank bands use the same height.
  Task boundaries and idle durations are not measured. Sub's sector handling
  and audio processing are interleaved, not a once-per-frame serial schedule.
- The diagram depicts a two-VBlank transfer example, omits HUD work, and
  excludes startup and EOF. Light frames can require only one transfer budget.
  The Even Active interval still shows waiting; speculative Active DMA is
  not part of this diagram.
- The 97.7/159.2 B/line RAM-copy labels use consecutive `MOVE.L`, no loop
  overhead or extra waits, and the project's nominal `60000/1001` display
  frames/s with 262 lines/frame. They are reference copy rates, not measured
  speeds of the adjacent control-read/preparation routines. The 205 B/line
  label is H40 VBlank memory-to-VRAM DMA capacity, before setup and repair
  costs. These annotations are maintained explicitly, not read from logs.

[`PLAYER.md`](../../PLAYER.md) owns the sequence, memory maps, and copy-rate
assumptions. The matching runtime paths are `build_frame`,
`bf_next_vbudget`, and `swap_begin` in
[`movieplay_ip.s`](../../boot/movieplay_ip.s), and `stream_loop` in
[`movieplay_sp.s`](../../boot/movieplay_sp.s). Use those references when
changing the diagram's meaning; this illustration is not timing qualification.

<a id="jp"></a>

# CPU sequence のスライド図

`build.mjs` は、30 fps の定常再生を示す日本語のスライド図を生成します。
Main/Sub CPU の処理、ハードウェアの区分、アイコン、Word-RAM の 2 バンク、理論転送量を含みます。
Node.js の標準機能と SVG 図形を使うため、npm パッケージ、参照画像、元動画、エンコード、エミュレータ録画は不要です。

## 生成

Node.js 18 以降、PNG 出力用の `rsvg-convert`、日本語描画用の Noto Sans CJK JP フォントが必要です。
Debian/Ubuntu での描画ツールとフォントのパッケージ名は `librsvg2-bin` と `fonts-noto-cjk` です。
SVG の文字は編集可能で、表示する環境のフォントを使います。

リポジトリのルートで実行します。

```sh
node harness/cpu_sequence/build.mjs
```

`harness/cpu_sequence/out/` に、2560 x 1440 の `cpu-sequence.svg` と `cpu-sequence.png` を出力します。
このディレクトリは既存の Git 除外設定の対象です。
スクリプトは出力先を表示します。
PNG の生成に失敗すると終了ステータスは非ゼロになり、生成済みの SVG は残ります。

```sh
# SVG のみ。rsvg-convert は不要。
node harness/cpu_sequence/build.mjs --svg-only

# 相対出力先は実行時のカレントディレクトリを基準に解決。
node harness/cpu_sequence/build.mjs --out-dir tmp/cpu_sequence
```

## 編集と確認

ラベル、座標、色、アイコンのパスは `build.mjs` で編集します。
`cpu()` は CPU の処理と表示期間、`common()` はハードウェアの区分、`shared()` は Word RAM と通信レジスタ、`transfers()` は横方向の接続と RAM コピーの注記を描きます。
現在の出力は黒背景で、Word-RAM の外枠に 2 バンクを内包します。

レイアウトを変えたら PNG を再生成し、文字の重なり、矢印の端点、接続先のリソースを目視で確認します。
修正可能な説明図の変更なので、レイアウト確認にエンコーダのテストや録画は不要です。

## 図の意味と制約

- ODD/EVEN は、30 fps の動画 1 フレームに対応する約 60 Hz 表示の前半と後半です。物理 Word-RAM バンクを指定するものではありません。
- 1M/1M モードでは各 CPU が別々の 128 KiB バンクを所有します。湾曲した SWAP 矢印は所有権の交換を示し、バンク間のデータコピーを示しません。Word RAM と通信レジスタは、物理的にはメガCD側のリソースです。
- 処理名と下向き矢印は CPU 内に置きます。横の実線はデータアクセスや転送の関係、破線はコマンドと状態の通信です。CPU から VRAM への接続は Main が開始する DMA を示し、CPU の RAM を経由する意味ではありません。すべての転送元や処理を描いてはいません。
- Active は 224 ライン、VBlank は約 38 ラインです。読みやすくするため VBlank を拡大し、前半と後半の VBlank を同じ高さで描きます。処理境界と待ち時間は未計測です。Sub のセクタ処理と音声処理は細かく交互に進み、図の順で毎フレーム 1 回ずつ実行する意味ではありません。
- 2 回の VBlank で転送する例です。HUD 処理、起動時、終端は省略しています。軽いフレームでは 1 回の転送予算で完了する場合があります。Even の Active は待機として描いており、検討中の Active DMA は含みません。
- RAM コピーの 97.7/159.2 B/line は、`MOVE.L` の連続実行、ループ制御と追加待ちなし、プロジェクトの公称表示周期 `60000/1001` フレーム/秒、262 ライン/フレームで換算した値です。隣にある参照や準備処理の実測速度ではありません。205 B/line は H40 の VBlank 中のメモリから VRAM への DMA 容量で、設定と修復のコストを含みません。注記の数値はコード内で管理し、ログから読み取るものではありません。

処理順、メモリマップ、コピー速度の前提は [`PLAYER.md`](../../PLAYER.md) が管理します。
対応する実行経路は [`movieplay_ip.s`](../../boot/movieplay_ip.s) の `build_frame`、`bf_next_vbudget`、`swap_begin` と、[`movieplay_sp.s`](../../boot/movieplay_sp.s) の `stream_loop` です。
図の意味を変える場合はこれらを参照します。
この図は実行時間の検証結果ではありません。
