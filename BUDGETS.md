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

| Mode | Active lines | Blanking lines | DMA words/VBlank | Pattern tiles/VBlank |
|---|---:|---:|---:|---:|
| H40 | 224 | 38 | 3,888 | 243 |
| H32 | 224 | 38 | 3,168 | 198 |
| mode4 | 192 | 70 | 5,840 | 365 |

The mode4 row is only a theory estimate for a 192-line SMS-style display. True
SMS Mode 4 changes the meaning of VDP registers; in particular, the bit used as
DMA enable in Mode 5 is a height-mode bit in SMS Mode 4. The practical measured
path below uses SMS Mode 4 for display, then switches to Mode 5 only during
VBlank to issue the DMA.

## DMA Update Budget Per Video Frame

This is the average DMA capacity available per encoded video frame, using the
GPGX `dmabench` measured values below. Each cell gives exact average DMA words,
then the number of complete 16-word pattern tiles. At 24 fps, the average is
2.5 VBlanks per video frame, so the real scheduler would alternate shorter and
longer gaps.

| Mode | 15 fps words / tiles | 24 fps words / tiles | 30 fps words / tiles |
|---|---:|---:|---:|
| H40 | 14,656 / 916 | 9,160 / 572 | 7,328 / 458 |
| H32 | 11,928 / 745 | 7,455 / 465 | 5,964 / 372 |
| mode4 | 22,480 / 1,405 | 14,050 / 878 | 11,240 / 702 |

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
2=mode4) builds `out/DMABENCH.iso`. With the default `DMABENCH_RUNS=0`, it
binary-searches the largest `Main-RAM → VRAM` DMA that finishes inside one
VBlank and prints, top-left:

- `W xxxx` = max words per VBlank (hex)
- `F xxxx` = derived tiles/frame ≈ `(W/16) * 3`

Source: `boot/dmabench_ip.s` (+ `dmabench_boot.s`, stub SP = `cdcbench_sp`).
**Run it on ares / real hardware for authoritative numbers** — Genesis Plus GX
is lenient and over-reports.

### Measured (Genesis Plus GX)

| Mode  | DMA words/VBlank | Pattern tiles/VBlank | note |
|-------|-----------------:|---------------------:|------|
| H32   | 2,982 | 186 | `W 0BA6`; `out/DMABENCH_mode0.cue`, screenshot `tmp/dmabench_h32_clean_sheet.jpg` |
| H40   | 3,664 | 229 | `W 0E50`; `out/DMABENCH_mode1.cue`, screenshot `tmp/dmabench_h40_clean_sheet.jpg` |
| mode4 | 5,620 | 351 | `W 15F4`; `out/DMABENCH_mode2.cue`, screenshot `tmp/dmabench_mode4_clean_sheet.jpg`; SMS Mode 4 display, VBlank-only Mode 5 DMA, with a white proof block showing the DMA destination tile was written |
| *ares* | TBD | TBD | run the ISO to fill in |

The GPGX result `0x0F98` for every mode is invalid. A harness using
`reg1 = 0x8144` for mode4 leaves Mode 5 selected, does not enable Mode 5 DMA,
and calls a BIOS display-enable routine that can restore register 1. That setup
measures a Mode 5-like display rather than true 192-line SMS Mode 4.

A direct "stay in SMS Mode 4 and issue Main-RAM to VRAM DMA" test did not give a
credible budget in GPGX: the reported value was far above the 192-line theory
and had to be treated as a no-op/status artifact. The usable path is to keep
SMS Mode 4 for active display, switch to Mode 5 at VBlank start, issue the DMA,
then switch back to SMS Mode 4 before active display resumes.

### Mid-VBlank DMA start (measured)

`make dmabench DMABENCH_MODE=0|1|2 DMABENCH_DELAY=N` waits N raster lines
after the VBlank rise (calibrated busy-wait, ~49 dbra iterations per line)
before issuing the DMA, then binary-searches the largest transfer that still
completes inside the same VBlank.

The fits check needs more than the VBlank flag: a huge transfer crosses the
whole active display and completes inside the **next** frame's VBlank with the
flag set again, so the delayed search converges on an impossible wrap solution
(H32 delay 10 first reported 7,022 words). `dmabench` therefore also proves
same-window completion with a Gate-Array stopwatch bound (`FIT_MAX_TICKS`);
the guard reproduces the full-window numbers within the 8-word search
granularity (H32 `W 0B9D` vs `0BA6`, H40 `0E43` vs `0E50`).

Measured (Genesis Plus GX), words per VBlank against the delay:

| Mode | delay 0 | 10 lines | 19 lines | 29 lines | per-line slope |
|------|--------:|---------:|---------:|---------:|---------------:|
| H32  | 2,973 (`W 0B9D`) | 2,135 (`W 0857`) | 1,388 (`W 056C`) | 553 (`W 0229`) | 83.0-83.8 |
| H40  | 3,651 (`W 0E43`) | 2,622 (`W 0A3E`) | 1,708 (`W 06AC`) | 679 (`W 02A7`) | 101.6-102.9 |

Screenshots: `tmp/dmabench_h32_d{10,19,29}_result.png`,
`tmp/dmabench_h40_d{10,19,29}_result.png`.

- Capacity falls **linearly** with the start delay. The consecutive-point
  slopes are constant within measurement granularity and equal the theory
  per-line rate (H32 3,168 words / 38 lines = 83.4; H40 3,888 / 38 = 102.3).
  The per-line DMA rate of the remaining window does not degrade: a mid-VBlank
  start has no extra rate penalty beyond the lines already lost.
- The delay-0 total sits about 200-250 words below `slope x 38`: a fixed
  per-window overhead (VBlank-rise poll latency, DMA register setup, and the
  completion margin), not a rate effect.
- Player consequence: the `bf_start_vbudget` rule "full budget only from a
  proven blank head" stays correct and is not overly pessimistic — a late
  start loses exactly the elapsed lines' capacity, and there is no cliff
  beyond that loss. As with every `dmabench` number, confirm on ares / real
  hardware before relying on the absolute values.

### Repaired Word-RAM multi-run DMA (measured)

The multi-run mode measures the current Main-player whole-run path instead of a
single Main-RAM DMA:

```sh
make dmabench DMABENCH_MODE=1 DMABENCH_RUNS=N DMABENCH_REPAIR=1
make dmabench DMABENCH_MODE=1 DMABENCH_RUNS=N DMABENCH_REPAIR=0
```

The shared Sub benchmark program establishes 1M/1M mode and hands a settled
physical Word-RAM bank to Main. Before timing, Main divides the total payload
as evenly as possible into `N` 22-byte `O_LOADS v2` records. The timed loop pops
the pre-swizzled registers from Word RAM, issues each DMA as `src+2` with the
full length and normal destination, waits for completion, restores the normal
destination command, and CPU-writes the destination's first word. This matches
the DEBUG player's unsplit Word-RAM whole-run path, including its logical-word
accounting and four-unit budget bookkeeping. `DMABENCH_REPAIR=0` keeps the same
run division, records, source offset, DMA setup, trigger, and completion wait,
but omits the repair-specific bookkeeping, command restore, source load/check,
and CPU write.

`W` is the maximum total payload words that complete inside one H40 VBlank.
`E` is the direct Gate-Array stopwatch result for a fixed 1,024-word payload,
in 30.72 us ticks, so its slope is independent of the shrinking `W` ceiling.
All values below are decimal even though the benchmark displays hexadecimal.
The binary search leaves a range of at most seven words, so 2,495 and an
earlier 2,499 reading for 16 repaired runs are the same measurement bucket.

| Runs | Repaired `W` words/VBlank | No-repair `W` words/VBlank | Repaired `E` ticks | No-repair `E` ticks |
|---:|---:|---:|---:|---:|
| 1 | 3,656 | 3,668 | 22 | 22 |
| 4 | 3,427 | 3,475 | 27 | 26 |
| 8 | 3,114 | 3,225 | 34 | 32 |
| 16 | 2,495 | 2,714 | 46 | 42 |
| 24 | 1,883 | 2,205 | 59 | 52 |
| 32 | 1,265 | 1,687 | 72 | 62 |

Linear fits over all six points give:

- Repaired elapsed time: `E = 20.625 + 1.603 * runs` ticks, `R² = 0.99976`.
  The slope is 49.24 us/run and differs by only 1.3% from the independently
  observed Bad Apple full-playback HUD coefficient of 1.624 ticks/run.
- No-repair elapsed time: `E = 21.110 + 1.286 * runs` ticks,
  `R² = 0.99938`, or 39.52 us/run.
- Repaired payload ceiling: `W = 3732.84 - 77.14 * runs` words,
  `R² = 0.999994`.
- No-repair payload ceiling: `W = 3733.11 - 63.82 * runs` words,
  `R² = 0.999984`.

The 1.603-tick slope is therefore the cost of one complete repaired run, not
the repair alone. Subtracting the paired no-repair control isolates the repair
sequence at 0.317 tick = 9.73 us per run, or 13.32 words/run of lost H40 payload
capacity. The remaining 1.286 ticks/run and 63.82 words/run are the common
record-pop, DMA-register, trigger, and completion-poll cost of another run.

The H40 player payload budget is 3,200 words. In this isolated measurement, four
repaired runs still allow 3,427 words, while eight allow only 3,114. The fitted
crossing is about seven runs, so the fixed 3,200-word budget is not by itself a
proof that an arbitrarily fragmented transfer fits one VBlank. The existing
four-unit `CPU_VDP_WORD_COST` charges the one CPU data-port write; it is not a
complete time model for the whole repair sequence or the common per-run setup.

These are Genesis Plus GX results with no simultaneous Sub access to the other
Word-RAM bank. The managed LOGVDP core SHA-256 is
`51cfd71f338865288e274b271b8ce0d9a1d3dc415688f14db963a29555d9b4ac`.
Re-measure on ares and real hardware before turning either fitted slope into a
production budget or run cap.

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
`VB_WORDS_H32` = 2800 and `VB_WORDS_H40` = 3200. Both are below the GPGX
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

| Mode | Active lines | Blanking lines | DMA words/VBlank | Pattern tiles/VBlank |
|---|---:|---:|---:|---:|
| H40 | 224 | 38 | 3,888 | 243 |
| H32 | 224 | 38 | 3,168 | 198 |
| mode4 | 192 | 70 | 5,840 | 365 |

mode4の行は、192-line SMS-style displayに対する理論値です。SMS Mode 4ではVDP
registerの意味が変わり、特にMode 5でDMA enableに使うbitは、SMS Mode 4では
height-mode bitになります。下記の実測経路は、表示にSMS Mode 4を使い、DMA発行時の
VBlank中だけMode 5へ切り替えます。

## Video frameあたりのDMA update予算

下表は、encode済みvideo frameごとに使える平均DMA capacityです。値は
下記GPGX `dmabench`の実測値を使います。各cellは、正確な平均DMA word数、
その次に16 wordの完全なpattern tile数を示します。24 fpsではvideo frameあたり
平均2.5 VBlankなので、実schedulerは短い間隔と長い間隔を交互に使います。

| Mode | 15 fps words / tiles | 24 fps words / tiles | 30 fps words / tiles |
|---|---:|---:|---:|
| H40 | 14,656 / 916 | 9,160 / 572 | 7,328 / 458 |
| H32 | 11,928 / 745 | 7,455 / 465 | 5,964 / 372 |
| mode4 | 22,480 / 1,405 | 14,050 / 878 | 11,240 / 702 |

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
（0=H32、1=H40、2=mode4）は`out/DMABENCH.iso`をbuildします。既定の
`DMABENCH_RUNS=0`では、1 VBlank内に完了する最大の`Main-RAM → VRAM` DMAを
binary searchし、左上に次を表示します。

- `W xxxx` = VBlankあたりの最大word数（hex）
- `F xxxx` = 導出したtiles/frame、約`(W/16) * 3`

Sourceは`boot/dmabench_ip.s`です（`dmabench_boot.s`と、stub SP =
`cdcbench_sp`も使用）。**権威ある数値にはaresまたは実機で実行してください。**
Genesis Plus GXは判定が緩く、大きすぎる値を報告します。

### 実測値（Genesis Plus GX）

| Mode | DMA words/VBlank | Pattern tiles/VBlank | note |
|---|---:|---:|---|
| H32 | 2,982 | 186 | `W 0BA6`、`out/DMABENCH_mode0.cue`、screenshot `tmp/dmabench_h32_clean_sheet.jpg` |
| H40 | 3,664 | 229 | `W 0E50`、`out/DMABENCH_mode1.cue`、screenshot `tmp/dmabench_h40_clean_sheet.jpg` |
| mode4 | 5,620 | 351 | `W 15F4`、`out/DMABENCH_mode2.cue`、screenshot `tmp/dmabench_mode4_clean_sheet.jpg`。SMS Mode 4表示、VBlank中だけMode 5 DMA。DMA destination tileへのwriteを示すwhite proof block付き |
| *ares* | TBD | TBD | ISOを実行して記入 |

全modeで`0x0F98`となるGPGX結果は無効です。mode4で`reg1 = 0x8144`を使うharnessは
Mode 5を選んだままにし、Mode 5 DMAをenableせず、さらにregister 1を復元し得るBIOS
display-enable routineを呼びます。この構成が測るのは、真の192-line SMS Mode 4ではなく
Mode 5に近い表示です。

SMS Mode 4のままMain-RAMからVRAMへのDMAを発行する直接testは、GPGX上で信頼できる
予算を示しません。報告値が192-lineの理論値を大幅に超えるため、no-opまたはstatusの
artifactとして扱う必要があります。利用可能な経路は、active displayをSMS Mode 4に
保ち、VBlank開始時にMode 5へ切り替えてDMAを発行し、active display再開前にSMS Mode 4へ
戻す方法です。

### VBlank途中開始のDMA（実測）

`make dmabench DMABENCH_MODE=0|1|2 DMABENCH_DELAY=N`は、VBlank立ち上がりから
Nライン（較正済みbusy-wait、約49 dbra/ライン）待ってからDMAを発行し、同じVBlank内に
完了する最大転送をbinary searchします。

fits判定はVBlankフラグだけでは不十分です。巨大な転送はactive display全体を跨いで
**次の**frameのVBlank中に完了し、フラグが再び立っているため、遅延ありの探索は
物理的に不可能なwrap解に収束します（H32 delay 10で最初に7,022語と報告）。そのため
`dmabench`はGate Array stopwatchの上限（`FIT_MAX_TICKS`）で同一window内完了も
証明します。このguardは全window値を探索粒度（8語）以内で再現します
（H32 `W 0B9D` vs `0BA6`、H40 `0E43` vs `0E50`）。

実測（Genesis Plus GX）、遅延に対するVBlankあたり語数:

| Mode | delay 0 | 10ライン | 19ライン | 29ライン | ラインあたり傾き |
|------|--------:|---------:|---------:|---------:|-----------------:|
| H32  | 2,973 (`W 0B9D`) | 2,135 (`W 0857`) | 1,388 (`W 056C`) | 553 (`W 0229`) | 83.0〜83.8 |
| H40  | 3,651 (`W 0E43`) | 2,622 (`W 0A3E`) | 1,708 (`W 06AC`) | 679 (`W 02A7`) | 101.6〜102.9 |

Screenshot: `tmp/dmabench_h32_d{10,19,29}_result.png`、
`tmp/dmabench_h40_d{10,19,29}_result.png`。

- 容量は開始遅延に対して**線形**に減ります。隣接点の傾きは測定粒度内で一定で、
  理論のラインあたりレート（H32は3,168語/38ライン = 83.4、H40は3,888/38 = 102.3）と
  一致します。残りwindowのラインあたりDMAレートは劣化しません。VBlank途中開始に、
  失ったライン分を超える追加のレートペナルティはありません。
- delay 0の合計は`傾き × 38`より約200〜250語小さい値です。これはwindowあたりの
  固定overhead（VBlank立ち上がりのpoll遅れ、DMA register設定、完了margin）であり、
  レートの効果ではありません。
- Playerへの帰結: `bf_start_vbudget`の「証明されたblank headからのみ全budget」の
  ruleは正しく、過度に悲観的でもありません。遅い開始は経過ライン分の容量を正確に
  失うだけで、それを超える崖はありません。他の`dmabench`値と同様、絶対値に依存する
  前にares / 実機で確認してください。

### 先頭word補修付きWord RAM多run DMA（実測）

多run modeは、単一のMain-RAM DMAではなく、現行Main playerのwhole-run経路を
測ります。

```sh
make dmabench DMABENCH_MODE=1 DMABENCH_RUNS=N DMABENCH_REPAIR=1
make dmabench DMABENCH_MODE=1 DMABENCH_RUNS=N DMABENCH_REPAIR=0
```

共有Sub benchmark programが1M/1M modeを設定し、settle済みの物理Word-RAM bankをMainへ
渡します。Mainは計時前に総payloadをできるだけ均等な`N`本の22-byte
`O_LOADS v2` recordへ分けます。計時loopはWord RAMからpre-swizzle済みregisterを
popし、各DMAを`src+2`、full length、normal destinationで発行します。そして完了を
待ち、normal destination commandを復元し、destinationの先頭wordをCPU writeします。
これはDEBUG playerの未分割Word-RAM whole-run経路と同じで、logical-word集計と4-unitの
budget簿記も含みます。`DMABENCH_REPAIR=0`はrun分割、record、source offset、
DMA setup、trigger、完了待ちを同じに保ち、補修固有のbudget簿記、command復元、
source load/check、CPU writeだけを省いた対照です。

`W`は、1回のH40 VBlank内に完了する総payloadの最大word数です。`E`は、固定
1,024-word payloadに対するGate-Array stopwatchの直接値で、単位は30.72 us tickです。
そのため、その傾きは縮小する`W` ceilingに影響されません。Benchmarkの画面表示は
16進ですが、下表はすべて10進値です。Binary searchには最大7 wordの幅が残るため、
補修あり16 runの2,495と、先に得た2,499は同じ測定bucketです。

| Runs | 補修あり`W` words/VBlank | 補修なし`W` words/VBlank | 補修あり`E` ticks | 補修なし`E` ticks |
|---:|---:|---:|---:|---:|
| 1 | 3,656 | 3,668 | 22 | 22 |
| 4 | 3,427 | 3,475 | 27 | 26 |
| 8 | 3,114 | 3,225 | 34 | 32 |
| 16 | 2,495 | 2,714 | 46 | 42 |
| 24 | 1,883 | 2,205 | 59 | 52 |
| 32 | 1,265 | 1,687 | 72 | 62 |

6点すべての直線fitは次の値です。

- 補修ありの経過時間: `E = 20.625 + 1.603 * runs` ticks、`R² = 0.99976`。
  傾きは49.24 us/runで、別に観測したBad Apple全編再生HUDの1.624 ticks/runとの差は
  1.3%だけです。
- 補修なしの経過時間: `E = 21.110 + 1.286 * runs` ticks、
  `R² = 0.99938`、または39.52 us/runです。
- 補修ありのpayload ceiling: `W = 3732.84 - 77.14 * runs` words、
  `R² = 0.999994`です。
- 補修なしのpayload ceiling: `W = 3733.11 - 63.82 * runs` words、
  `R² = 0.999984`です。

したがって1.603-tickの傾きは、完全な補修付きrun 1本のcostであり、補修だけの
costではありません。対の補修なし結果を引くと、補修sequence固有分はrunあたり
0.317 tick = 9.73 us、H40 payload capacityの減少では13.32 words/runと分かります。
残る1.286 ticks/runと63.82 words/runは、別runに共通のrecord pop、DMA register、trigger、
完了pollのcostです。

H40 playerのpayload budgetは3,200 wordです。この単独実測では、補修あり4 runは
3,427 wordを許しますが、8 runは3,114 wordしか許しません。Fitの交点は約7 runであり、
固定3,200-word budgetだけでは、任意に分断された転送が1 VBlankに収まる証明には
なりません。現行の4-unit `CPU_VDP_WORD_COST`は、CPU data-port write 1語をchargeします。
これは補修sequence全体や共通のrunごとのsetupを表す完全な時間modelではありません。

これらは、Subが反対側のWord-RAM bankを同時accessしていないGenesis Plus GXでの結果です。
管理LOGVDP coreのSHA-256は
`51cfd71f338865288e274b271b8ce0d9a1d3dc415688f14db963a29555d9b4ac`です。どちらのfit傾きも、
production budgetまたはrun capへ変える前にaresと実機で測り直してください。

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
`VB_WORDS_H32`は2800、`VB_WORDS_H40`は3200です。どちらもGPGX ceiling
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
