EN / [JP](#jp)

# SEGA-CD FMV Budgets

This note collects the first-order tile, DMA, and CD raw-read budgets used when
choosing encoder targets. Numbers are estimates for NTSC 60 Hz playback.

## Assumptions

- Tile size: 8x8 pixels.
- Pattern payload: 32 bytes per 4bpp tile.
- Raw tile update from CD: 34 bytes per tile, counted as 32 bytes pattern plus
  2 bytes name-table entry.
- CD rate: 150 KiB/s = 153,600 bytes/s.
- ADPCM control audio uses about 11,150 bytes/s at the supported cadences.
  Exact per-frame sizes are documented in `CONFIG.md` and `ADPCM.md`.
- Raw video CD budget after that audio allowance: about 142,450 bytes/s.
- The theory table uses `tools/layout_preview.py` timing constants converted to
  pattern tiles.
- Tile counts below use pattern bytes only. Name-table DMA still needs to be
  budgeted separately in a real frame.
- H40's exact full-width 16:9 height is 180 pixels, which is 22.5 tile rows.
  The table uses the tile-aligned fit that stays under that height: 320x176.

## Screen Modes

| Mode | Visible resolution | Tile grid | Total tiles | Tile-aligned 16:9 area | 16:9 tiles |
|---|---:|---:|---:|---:|---:|
| H40 | 320x224 | 40x28 | 1,120 | 320x176 (40x22) | 880 |
| H32 | 256x224 | 32x28 | 896 | 256x144 (32x18) | 576 |
| mode4 | 256x192 | 32x24 | 768 | 256x144 (32x18) | 576 |

## Theory DMA Per VBlank

| Mode | Active lines | Blanking lines | Pattern tiles/VBlank |
|---|---:|---:|---:|
| H40 | 224 | 38 | 243 |
| H32 | 224 | 38 | 198 |
| mode4 | 192 | 70 | 365 |

The mode4 row is only a theory estimate for a 192-line SMS-style display. True
SMS Mode 4 changes the meaning of VDP registers; in particular, the bit used as
DMA enable in Mode 5 is a height-mode bit in SMS Mode 4. The practical measured
path below uses SMS Mode 4 for display, then switches to Mode 5 only during
VBlank to issue the DMA.

## DMA Update Budget Per Video Frame

This is the average DMA capacity available per encoded video frame, expressed
as pattern tiles and using the GPGX `dmabench` measured values below. At 24 fps,
the average is 2.5 VBlanks per video frame, so the real scheduler would
alternate shorter and longer gaps.

| Mode | 15 fps tiles/frame | 24 fps tiles/frame | 30 fps tiles/frame |
|---|---:|---:|---:|
| H40 | 916 | 572 | 458 |
| H32 | 745 | 465 | 372 |
| mode4 | 1,405 | 878 | 702 |

## CD Raw Read Budget Per Video Frame

The raw-read budget is independent of screen mode. This table is the CD budget
left after the ADPCM allowance above, expressed as raw tile updates; it is not a
replacement for the exact per-profile scheduler.

| Frame rate | Raw tiles/frame |
|---|---:|
| 15 fps | 279 |
| 24 fps | 174 |
| 30 fps | 139 |

## Empirical measurement — `dmabench`

Reusable measurement build. `make dmabench DMABENCH_MODE=0|1|2` (0=H32, 1=H40,
2=mode4) builds `out/DMABENCH.iso`. It binary-searches the largest
`Main-RAM → VRAM` DMA that finishes inside one VBlank and prints, top-left:

- `W xxxx` = max words per VBlank (hex)
- `F xxxx` = derived tiles/frame ≈ `(W/16) * 3`

Source: `boot/dmabench_ip.s` (+ `dmabench_boot.s`, stub SP = `cdcbench_sp`).
**Run it on ares / real hardware for authoritative numbers** — Genesis Plus GX
is lenient and over-reports.

### Measured (Genesis Plus GX)

| Mode  | Pattern tiles/VBlank | note |
|-------|---------------------:|------|
| H32   | 186                  | `W 0BA6`; `out/DMABENCH_mode0.cue`, screenshot `tmp/dmabench_h32_clean_sheet.jpg` |
| H40   | 229                  | `W 0E50`; `out/DMABENCH_mode1.cue`, screenshot `tmp/dmabench_h40_clean_sheet.jpg` |
| mode4 | 351                  | `W 15F4`; `out/DMABENCH_mode2.cue`, screenshot `tmp/dmabench_mode4_clean_sheet.jpg`; SMS Mode 4 display, VBlank-only Mode 5 DMA, with a white proof block showing the DMA destination tile was written |
| *ares* | TBD                 | run the ISO to fill in |

The GPGX result `0x0F98` for every mode is invalid. A harness using
`reg1 = 0x8144` for mode4 leaves Mode 5 selected, does not enable Mode 5 DMA,
and calls a BIOS display-enable routine that can restore register 1. That setup
measures a Mode 5-like display rather than true 192-line SMS Mode 4.

A direct "stay in SMS Mode 4 and issue Main-RAM to VRAM DMA" test did not give a
credible budget in GPGX: the reported value was far above the 192-line theory
and had to be treated as a no-op/status artifact. The usable path is to keep
SMS Mode 4 for active display, switch to Mode 5 at VBlank start, issue the DMA,
then switch back to SMS Mode 4 before active display resumes.

### The binding limit is the complete pipeline

The pure-DMA ceiling is **not** a sufficient playback limit. Each frame also
includes:

- Sub-CPU `expand_frame`: 16 PRG→Word-RAM words per cold pop plus interleaved
  `pump_poll` CD drain.
- Main-CPU: Word-RAM→Main-RAM stage copy, shadow blit, VBlank-split tile DMA
  (a full-frame wait each time the per-VBlank word budget `md_vbudget` is
  exhausted), flip.
- The two CPUs serialize at the swap handshake.

The cold cap must therefore be qualified with the complete encoder, stream,
Sub-CPU, Main-CPU, audio, and CD-pump path. A pure DMA benchmark cannot justify
raising it by itself.

### Encoder cap

Every encode profile supplies its cold-tile ceiling as the required
`[encoder].cold_cap` value. There is no fps-derived fallback or separate
diagnostic override. A lower temporary comparison value is expressed by an
ordinary profile and follows the same artifact and pipeline handoff as the
qualified profile. Raising a qualified value requires a new source-specific
full-path qualification.

The pack asserts that every timed frame's realized new-tile loads stay within
the effective encoded cap and does not re-cap the stream. Frame 0 is exempt
because `HEADER.DAT` loads it before timed playback. Cells that cannot be
updated within the cap appear as Miss in the analysis category map.

`boot/movieplay_ip.s` sets a per-mode VBlank word budget (`md_vbudget`):
`VB_WORDS_H32` = 2800 and `VB_WORDS_H40` = 3400. Both are below the GPGX
ceilings (H32 2982 words/VBlank, H40 3664 words/VBlank). Re-check against the
ares `dmabench` value before raising them.

The mode4 player path uses true SMS Mode 4 for display with VBlank-only Mode 5
DMA. Re-prove it on ares or hardware before raising player limits.

## Empirical measurement — `cpuvrambench`

Reusable measurement build for the CPU side of the same budget:
`make cpuvrambench CPUVRAMBENCH_MODE=0|1` (0=H32, 1=H40) builds
`out/CPUVRAMBENCH.iso`. It binary-searches the largest CPU data-port write
burst that finishes inside one VBlank, using the player's transfer form
(`move.l (a0)+,(VDP_DATA).l` in 8-word blocks plus a `move.w` tail, the
`bf_bw` / `bf_bword` shape), and prints the same top-left rows as `dmabench`:

- `W xxxx` = max CPU-written words per VBlank (hex)
- `F xxxx` = derived tiles/frame ≈ `(W/16) * 3`

Active-display writes are deliberately not measured: the VDP FIFO is only
4 words deep, so active-scan CPU writes stall on FIFO slots almost
immediately and are not a budget path.

Source: `boot/cpuvrambench_ip.s` (+ `cpuvrambench_boot.s`, stub SP =
`cdcbench_sp`). **Run it on ares / real hardware for authoritative numbers.**

### Measured (Genesis Plus GX)

| Mode | CPU words/VBlank | `dmabench` DMA words/VBlank | DMA/CPU ratio | note |
|------|-----------------:|----------------------------:|--------------:|------|
| H32  | 1,168            | 2,982                       | 2.55          | `W 0490`; `out/CPUVRAMBENCH_mode0.cue`, screenshot `tmp/cpuvrambench_h32_result.png` |
| H40  | 1,160            | 3,664                       | 3.16          | `W 0488`; `out/CPUVRAMBENCH_mode1.cue`, screenshot `tmp/cpuvrambench_h40_result.png` |
| *ares* | TBD            |                             |               | run the ISO to fill in |

Both modes measure the same within the 8-word search granularity: the limiter
is 68000 instruction time (measured ≈ 16 cycles/word against the move.l
loop's theoretical ≈ 14.5 plus poll and command-setup overhead), not VDP
slot supply, which is far above the CPU's demand during blanking.

`CPU_VDP_WORD_COST = 4` in `boot/movieplay_ip.s` charges one CPU-written VDP
word as four DMA words inside the VBlank budget. The measured GPGX ratios are
2.6-3.2, so the constant over-charges CPU words and stays on the safe side in
both modes. Re-measure the ratio on ares / real hardware before lowering it.

---

<a id="jp"></a>

# SEGA-CD FMVの予算

この文書は、encoder targetを選ぶときに使うtile、DMA、CD raw-readの一次予算を
まとめます。数値はNTSC 60 Hz再生の見積もりです。

## 前提

- Tile sizeは8x8 pixelです。
- Pattern payloadは4bpp tileあたり32 byteです。
- CDからのRaw tile updateは、32-byte patternと2-byte name-table entryを合わせて
  1 tileあたり34 byteとして数えます。
- CD rateは150 KiB/s、つまり153,600 byte/sです。
- ADPCM control audioは、対応cadenceで約11,150 byte/sを使います。正確な
  frameごとのsizeは`CONFIG.md`と`ADPCM.md`に記載します。
- このaudio allowanceを引いたRaw videoのCD予算は約142,450 byte/sです。
- 理論表は`tools/layout_preview.py`のtiming constantをpattern tileへ換算します。
- 下記のtile数はpattern byteだけを数えます。実frameではname-table DMAを別に
  予算化する必要があります。
- H40で横幅全体を使う正確な16:9の高さは180 pixel、つまり22.5 tile rowです。
  表では、その高さ以下に収まるtile-aligned fitの320x176を使います。

## Screen mode

| Mode | Visible resolution | Tile grid | Total tiles | Tile-aligned 16:9 area | 16:9 tiles |
|---|---:|---:|---:|---:|---:|
| H40 | 320x224 | 40x28 | 1,120 | 320x176 (40x22) | 880 |
| H32 | 256x224 | 32x28 | 896 | 256x144 (32x18) | 576 |
| mode4 | 256x192 | 32x24 | 768 | 256x144 (32x18) | 576 |

## VBlankあたりの理論DMA

| Mode | Active lines | Blanking lines | Pattern tiles/VBlank |
|---|---:|---:|---:|
| H40 | 224 | 38 | 243 |
| H32 | 224 | 38 | 198 |
| mode4 | 192 | 70 | 365 |

mode4の行は、192-line SMS-style displayに対する理論値です。SMS Mode 4ではVDP
registerの意味が変わり、特にMode 5でDMA enableに使うbitは、SMS Mode 4では
height-mode bitになります。下記の実測経路は、表示にSMS Mode 4を使い、DMA発行時の
VBlank中だけMode 5へ切り替えます。

## Video frameあたりのDMA update予算

下表は、encode済みvideo frameごとに使える平均DMA capacityをpattern tileで表します。
値は下記GPGX `dmabench`の実測値を使います。24 fpsではvideo frameあたり平均2.5 VBlank
なので、実schedulerは短い間隔と長い間隔を交互に使います。

| Mode | 15 fps tiles/frame | 24 fps tiles/frame | 30 fps tiles/frame |
|---|---:|---:|---:|
| H40 | 916 | 572 | 458 |
| H32 | 745 | 465 | 372 |
| mode4 | 1,405 | 878 | 702 |

## Video frameあたりのCD raw-read予算

Raw-read予算はscreen modeに依存しません。下表は上記ADPCM allowanceを引いたCD予算を
raw tile update数で表したもので、profileごとの正確なschedulerの代わりではありません。

| Frame rate | Raw tiles/frame |
|---|---:|
| 15 fps | 279 |
| 24 fps | 174 |
| 30 fps | 139 |

## 実測 — `dmabench`

再利用可能なmeasurement buildです。`make dmabench DMABENCH_MODE=0|1|2`
（0=H32、1=H40、2=mode4）は`out/DMABENCH.iso`をbuildします。1 VBlank内に完了する
最大の`Main-RAM → VRAM` DMAをbinary searchし、左上に次を表示します。

- `W xxxx` = VBlankあたりの最大word数（hex）
- `F xxxx` = 導出したtiles/frame、約`(W/16) * 3`

Sourceは`boot/dmabench_ip.s`です（`dmabench_boot.s`と、stub SP =
`cdcbench_sp`も使用）。**権威ある数値にはaresまたは実機で実行してください。**
Genesis Plus GXは判定が緩く、大きすぎる値を報告します。

### 実測値（Genesis Plus GX）

| Mode | Pattern tiles/VBlank | note |
|---|---:|---|
| H32 | 186 | `W 0BA6`、`out/DMABENCH_mode0.cue`、screenshot `tmp/dmabench_h32_clean_sheet.jpg` |
| H40 | 229 | `W 0E50`、`out/DMABENCH_mode1.cue`、screenshot `tmp/dmabench_h40_clean_sheet.jpg` |
| mode4 | 351 | `W 15F4`、`out/DMABENCH_mode2.cue`、screenshot `tmp/dmabench_mode4_clean_sheet.jpg`。SMS Mode 4表示、VBlank中だけMode 5 DMA。DMA destination tileへのwriteを示すwhite proof block付き |
| *ares* | TBD | ISOを実行して記入 |

全modeで`0x0F98`となるGPGX結果は無効です。mode4で`reg1 = 0x8144`を使うharnessは
Mode 5を選んだままにし、Mode 5 DMAをenableせず、さらにregister 1を復元し得るBIOS
display-enable routineを呼びます。この構成が測るのは、真の192-line SMS Mode 4ではなく
Mode 5に近い表示です。

SMS Mode 4のままMain-RAMからVRAMへのDMAを発行する直接testは、GPGX上で信頼できる
予算を示しません。報告値が192-lineの理論値を大幅に超えるため、no-opまたはstatusの
artifactとして扱う必要があります。利用可能な経路は、active displayをSMS Mode 4に
保ち、VBlank開始時にMode 5へ切り替えてDMAを発行し、active display再開前にSMS Mode 4へ
戻す方法です。

### 制約になるのはpipeline全体

Pure-DMA ceilingだけでは再生上限を決められません。各frameには次の処理も含まれます。

- Sub CPUの`expand_frame`: cold popごとに16 wordをPRGからWord-RAMへ送り、その間に
  `pump_poll`でCDをdrainします。
- Main CPU: Word-RAMからMain-RAMへのstage copy、shadow blit、VBlankに分割したtile DMA、
  flipを行います。VBlankごとのword予算`md_vbudget`を使い切るたびに1 display frame
  待ちます。
- 2つのCPUはswap handshakeで直列化されます。

したがってcold capは、encoder、stream、Sub CPU、Main CPU、audio、CD pumpを含む
完全な経路でqualificationする必要があります。Pure DMA benchmarkだけではcap引き上げの
根拠になりません。

### Encoder cap

すべてのencode profileが、必須の`[encoder].cold_cap`としてcold-tile ceilingを指定
します。fps由来fallbackや別の診断overrideはありません。比較用に小さい値を使う場合も
通常のprofileへ書き、qualification済みprofileと同じartifact・pipeline handoffを通し
ます。Qualification済みの値を引き上げる場合は、source固有の全経路qualificationを
新しく行います。

Packは各timed frameの実new-tile loadがencode時のeffective cap以内にあることをassertし、
streamへ別のcapをかけません。Frame 0は`HEADER.DAT`によってtimed playback前にload
されるため対象外です。Cap内で更新できないcellは、解析category mapでMissとして表示します。

`boot/movieplay_ip.s`はmodeごとのVBlank word予算`md_vbudget`を設定します。
`VB_WORDS_H32`は2800、`VB_WORDS_H40`は3400です。どちらもGPGX ceiling
（H32は2982 word/VBlank、H40は3664 word/VBlank）より小さい値です。引き上げる前に、
aresの`dmabench`値と照合してください。

Mode4 playerでは、上記実測経路、つまり表示に真のSMS Mode 4を使い、VBlank中だけ
Mode 5 DMAを行います。Player limitを引き上げる前に、aresまたは実機で再証明してください。

## 実測 — `cpuvrambench`

同じ予算のCPU側を測る再利用可能なmeasurement buildです。
`make cpuvrambench CPUVRAMBENCH_MODE=0|1`（0=H32、1=H40）が
`out/CPUVRAMBENCH.iso`をbuildします。1VBLANKに収まる最大のCPU data port書き込みを
二分探索します。転送形はplayerの実経路（`move.l (a0)+,(VDP_DATA).l`の8語ブロック +
`move.w`端数、`bf_bw` / `bf_bword`と同形）で、`dmabench`と同じ左上表示を出します:

- `W xxxx` = VBlankあたりの最大CPU書き込み語数（hex）
- `F xxxx` = 換算タイル/コマ ≈ `(W/16) * 3`

Active中は意図的に測りません: VDP FIFOは4語深しかなく、active scan中のCPU書きは
ほぼ即座にFIFO slot待ちになるため、予算経路ではありません。

Sourceは`boot/cpuvrambench_ip.s`です（`cpuvrambench_boot.s`と、stub SP =
`cdcbench_sp`）。**Authoritativeな値はares / 実機で測り直してください。**

### 実測値（Genesis Plus GX）

| Mode | CPU語/VBlank | `dmabench` DMA語/VBlank | DMA/CPU比 | note |
|------|-------------:|------------------------:|----------:|------|
| H32  | 1,168        | 2,982                   | 2.55      | `W 0490`、`out/CPUVRAMBENCH_mode0.cue`、screenshot `tmp/cpuvrambench_h32_result.png` |
| H40  | 1,160        | 3,664                   | 3.16      | `W 0488`、`out/CPUVRAMBENCH_mode1.cue`、screenshot `tmp/cpuvrambench_h40_result.png` |
| *ares* | TBD        |                         |           | ISOを実行して記入 |

両modeは探索粒度（8語）の範囲で同値です。律速はVDP slot供給ではなく68000の命令時間
（実測 ≈ 16 cycle/語。move.lループの理論値 ≈ 14.5にpollとcommand設定のoverheadが
乗った値）で、blanking中のslot供給はCPUの需要を大きく上回ります。

`boot/movieplay_ip.s`の`CPU_VDP_WORD_COST = 4`は、CPUで書く1 VDP語をVBlank予算上
DMA 4語としてchargeします。GPGX実測の比は2.6〜3.2なので、この定数は両modeで
CPU語を多めにchargeする安全側です。引き下げる前にares / 実機で比を測り直して
ください。
