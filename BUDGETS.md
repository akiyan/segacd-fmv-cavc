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

### The binding limit is the complete pipeline

The pure-DMA ceiling is **not** a sufficient playback limit. Each frame also
includes:

- Sub-CPU `expand_frame`: 16 PRG→Word-RAM words per cold pop plus interleaved
  `pump_poll` CD drain.
- Main-CPU: Word-RAM control decode and shadow updates, Main-RAM
  `shadow`→`nt_stage` copy, VBlank-split tile DMA (a full-frame wait each time
  the per-VBlank word budget `md_vbudget` is exhausted), name-table DMA, flip.
- The two CPUs serialize at the swap handshake.

The cold cap must therefore be qualified with the complete encoder, stream,
Sub-CPU, Main-CPU, audio, and CD-pump path. A pure DMA benchmark cannot justify
raising it by itself.

### Main work before pattern-transfer readiness (H40)

The current standard specialized H40 DEBUG path samples
`pattern_dma_ready_vcounter` after Main has prepared the frame but immediately
before `bf_start_vbudget` waits for the first fresh pattern-transfer VBlank.
This section accounts for the complete timed-frame path from the preceding
accepted flip through that sample. Frame 0 and frames with no pattern run do
not take this path.

The estimates use about 488 Main-CPU cycles per scanline, matching `dmabench`.
"Nominal" means an MC68000 instruction timing estimate without platform bus
wait states. "Measured" comes from the matching full-playback HUD. One
independent check is `pass2_delay_q4`: it measures from the preceding flip to
entry at `bf_dma`, before the ready sample.

| Order | Object, operation, and memory domain | Estimated scanlines | Reduction reading |
|---:|---|---:|---|
| 1 | Finish the preceding `do_flip`, restore `build_frame`, re-enter `play_loop`, sample the request V-counter, and write `CMD_SWAP` through the Gate Array | about 0.8 nominal | Small fixed work; DEBUG flip sampling is not a release-build saving |
| 2 | Poll Gate Array `STAT_READY` while Sub finishes the Word-RAM handoff | measured per frame; Bad Apple p50 2.0, p90 81.0, p95 92.0 | Main is spinning, but the duration is owned by Sub scheduling, CD/audio work, and bank handoff |
| 3 | Accept READY, record the approximate wait, clear `CMD_SWAP`, wait for status clear, return, and call `build_frame` | about 0.5 nominal, plus any status-clear wait | Small fixed work; a long tail is a cross-CPU handshake problem |
| 4 | Save Main registers, clear per-frame DEBUG counters, load `n_runs`, and decode the Word-RAM control header's update count and bitmap/list tag | about 0.5 nominal | Small; DEBUG clearing does not improve the release path |
| 5 | Apply completed name entries from the swapped Word-RAM control block to the persistent Main-RAM `shadow`, using the selected generated-bitmap or list walker | data-dependent; Bad Apple p50 29.7, p95 42.4, max 60.1 nominal | Large CPU target; bitmap frames dominate the sample |
| 6 | Compute the inactive name-table base retained for the later flip | about 0.2 nominal | Too small to lead the work |
| 7 | Copy all 40x28 `shadow` words into the centered 64-word-pitch Main-RAM `nt_stage` | 24.1 nominal every frame | Large fixed target; this is Main-RAM→Main-RAM name work, not pattern staging |
| 8 | At `bf_dma`, record `pass2_delay_q4`, clear PT/NT DEBUG state, compute the final-VBlank reserve including palette lookahead, clear the budget-origin flag, test `n_runs`, and set the Word-RAM `O_LOADS` cursor | about 0.8 nominal | Small fixed bookkeeping |
| 9 | Zero the DEBUG logical-word counter, read `VDP_HV`, and store `pattern_dma_ready_vcounter` | about 0.1 nominal | This store is the endpoint |

On the one-time frame-0-to-frame-1 transition, `start_playback` also clears
the startup `CMD_STREAM` and waits for Sub status clear before the next
`CMD_SWAP`. Bad Apple frame 1 has no pattern run, so this startup-only wait is
not part of the PT sample below. If `n_upd` is zero, order 5 is only the bypass
branch; every sampled Bad Apple PT frame has at least one update. Main runs
with interrupts masked (`SR = 0x2700`), so there is no asynchronous Main
interrupt handler omitted from the list.

The small work in orders 1, 3, 4, and 6 is also checked as one group rather
than trusted only as separate static estimates. After subtracting the measured
Sub wait, the selected shadow-update model, and the fixed NT-stage copy from
`pass2_delay_q4`, the Bad Apple remainder is 2.3 scanlines at p50 and 3.6 at
p95. Its negative minimum and high p99 outliers come from stopwatch
quantization and the approximate 8-bit V-counter wait, so those endpoints must
not be interpreted as real negative work or a 100-line fixed path. Order 8-9
adds 448 nominal cycles, or 0.92 scanline, after the `pass2_delay_q4` sample.

The matching Bad Apple H40 320x224, 30 fps, cold-cap-210 capture contains 6,396
timed PT frames:

| Work or observation | Samples | min | p50 | p90 | p95 | p99 | max |
|---|---:|---:|---:|---:|---:|---:|---:|
| Updated cells | 6,396 | 1 | 171 | 319 | 385.25 | 643.05 | 1,120 |
| Measured Sub wait, scanlines | 6,396 | 0.0 | 2.0 | 81.0 | 92.0 | 102.0 | 187.0 |
| Selected shadow update, nominal scanlines | 6,396 | 0.18 | 29.67 | 39.51 | 42.39 | 52.35 | 60.06 |
| Bitmap shadow update, nominal scanlines | 5,861 | 17.04 | 30.43 | 39.87 | 42.69 | 52.71 | 60.06 |
| List shadow update, nominal scanlines | 535 | 0.18 | 4.80 | 6.57 | 6.87 | 6.97 | 6.97 |
| Shadow update + NT-stage copy, nominal scanlines | 6,396 | 24.26 | 53.75 | 63.59 | 66.47 | 76.43 | 84.14 |
| Preceding flip to `bf_dma`, measured scanlines | 6,396 | 25.11 | 67.60 | 141.00 | 152.58 | 166.10 | 243.36 |
| Preceding flip to ready, measured + nominal tail scanlines | 6,396 | 26.03 | 68.52 | 141.91 | 153.50 | 167.02 | 244.28 |

The raw ready-pressure value is a physical V-counter phase, not elapsed work.
For the same PT frames its p50 is scanline 54, p95 is 137.25, and p99 is 154.
One of 6,396 frames missed the first VBlank head and is represented by the
`0x100` sentinel. For a visible ready phase `x`, the remaining time before
VBlank starts at `E0` is `224 - x` scanlines.

The strongest benchmark candidates, without choosing an implementation yet,
are:

1. Move name-side work off the pre-PT critical path and into an active-display
   interval after the first PT VBlank. This can move readiness earlier by the
   combined name-work distribution: 53.75 scanlines at p50, 66.47 at p95, and
   up to 84.14 in this capture. It does not reduce total CPU work and can make
   NT readiness worse, so both PT and NT pressure must be benchmarked.
2. Remove or fuse the full `shadow`→`nt_stage` copy. Making the 64-pitch stage
   authoritative, or writing the final stage form while decoding updates, are
   examples to test rather than a selected design. The fixed opportunity is
   24.08 scanlines and reduces total Main work, so it can help both PT and NT.
3. Reduce the bitmap shadow-update cost or replace the representation. Bitmap
   frames use 30.43 scanlines at p50 versus 4.80 for selected list frames.
   Lists cannot simply be forced: the encoder currently accepts them only when
   the exact BODY route preserves PrgBuf/readiness margins and does not grow
   control data.
4. Return or request the next Word-RAM bank earlier enough to overlap more Sub
   work. This targets the measured p90 81-line wait tail, not Main instruction
   cost. It changes cross-CPU ownership and must preserve CD pumping, audio,
   startup, and both 15/30 fps handoffs.

Fixed bookkeeping is only a few scanlines and is lower priority. The
`bf_start_vbudget` fresh-head wait, pattern-run parsing and DMA, full HUD
formatting, CRAM work, NT DMA, cadence-final wait, and flip all occur after the
ready sample. Optimizing them may improve PT completion or NT readiness but
cannot move this particular ready measurement earlier.

`harness/pt_prework/analyze.py` reproduces these tables from a matching packed
stream and HUD TSV. Every experiment must keep the packed stream and target
quality fixed, then report PT readiness, PT completion, NT readiness, playback
cadence, and the HUD safety fields separately.

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

### 制約になるのはpipeline全体

Pure-DMA ceilingだけでは再生上限を決められません。各frameには次の処理も含まれます。

- Sub CPUの`expand_frame`: cold popごとに16 wordをPRGからWord-RAMへ送り、その間に
  `pump_poll`でCDをdrainします。
- Main CPU: Word-RAM controlのdecodeとshadow update、Main-RAMの
  `shadow`→`nt_stage` copy、VBlankに分割したtile DMA、name-table DMA、flipを行います。
  VBlankごとのword予算`md_vbudget`を使い切るたびに1 display frame待ちます。
- 2つのCPUはswap handshakeで直列化されます。

したがってcold capは、encoder、stream、Sub CPU、Main CPU、audio、CD pumpを含む
完全な経路でqualificationする必要があります。Pure DMA benchmarkだけではcap引き上げの
根拠になりません。

### Pattern転送ready前のMain処理（H40）

現在のstandard specialized H40 DEBUG経路は、Mainがframe準備を終え、
`bf_start_vbudget`が最初のfreshなpattern-transfer VBlankを待つ直前に
`pattern_dma_ready_vcounter`をsampleします。この節は、1つ前に受理したflipから
そのsampleまでのtimed-frame経路をすべて数えます。Frame 0とpattern runがないframeは
この経路を通りません。

見積もりは`dmabench`と同じく、Main CPUの約488 cycleを1 scanlineへ換算します。
「Nominal」はplatformのbus waitを含めないMC68000命令timingの見積もりです。
「Measured」は対応するfull-playback HUDから得ます。独立した照合値として、
`pass2_delay_q4`が1つ前のflipから`bf_dma` entryまで、ready sampleより前の時間を
測っています。

| 順番 | Object、operation、memory domain | 見込みscanline数 | 削減の読み方 |
|---:|---|---:|---|
| 1 | 1つ前の`do_flip`を終え、`build_frame`をrestoreし、`play_loop`へ戻り、request時V-counterをsampleしてGate Arrayへ`CMD_SWAP`を書く | nominalで約0.8 | 小さい固定処理。DEBUGのflip sampleを消してもrelease buildの削減にはならない |
| 2 | SubがWord-RAM handoffを終えるまでGate Arrayの`STAT_READY`をpollする | frameごとの実測。Bad Appleはp50 2.0、p90 81.0、p95 92.0 | Mainはspinするが、時間のownerはSub scheduling、CD/audio処理、bank handoff |
| 3 | READYを受理し、approximate waitを記録し、`CMD_SWAP`をclearし、status clearを待ち、returnして`build_frame`をcallする | nominalで約0.5 + status-clear待ち | 小さい固定処理。長いtailならcross-CPU handshakeの問題 |
| 4 | Main registerをsaveし、frame単位DEBUG counterをclearし、`n_runs`をloadし、Word-RAM control headerのupdate countとbitmap/list tagをdecodeする | nominalで約0.5 | 小さい。DEBUG clearを削ってもrelease経路は改善しない |
| 5 | Swap済みWord-RAM control blockの完成name entryを、選択済みgenerated-bitmap walkerまたはlist walkerでMain-RAMの永続`shadow`へ反映する | data依存。Bad Appleはp50 29.7、p95 42.4、最大60.1 nominal | 大きいCPU target。sampleの大半はbitmap frame |
| 6 | 後のflipまで保持するinactive name-table baseを計算する | nominalで約0.2 | 小さすぎるため先に扱う対象ではない |
| 7 | 40x28の`shadow` wordをすべて、中央配置された64-word-pitchのMain-RAM `nt_stage`へcopyする | 毎frame nominalで24.1 | 大きい固定target。Pattern stagingではなくMain-RAM→Main-RAMのname処理 |
| 8 | `bf_dma`で`pass2_delay_q4`を記録し、PT/NT DEBUG stateをclearし、palette先読みを含む最終VBlank reserveを計算し、budget origin flagをclearし、`n_runs`をtestしてWord-RAM `O_LOADS` cursorを設定する | nominalで約0.8 | 小さい固定bookkeeping |
| 9 | DEBUG logical-word counterをzeroにし、`VDP_HV`を読み、`pattern_dma_ready_vcounter`へstoreする | nominalで約0.1 | このstoreが終点 |

一度だけ通るframe 0からframe 1への遷移では、`start_playback`がstartup時の
`CMD_STREAM`もclearし、次の`CMD_SWAP`より前にSub status clearを待ちます。
Bad Appleのframe 1にはpattern runがないため、このstartup専用waitは下記PT sampleに
入りません。`n_upd`がzeroなら順番5はbypass branchだけですが、sample対象のBad Apple
PT frameはすべて1つ以上のupdateを持ちます。Mainはinterrupt mask状態
（`SR = 0x2700`）で動くため、一覧から漏れたasynchronousなMain interrupt handlerは
ありません。

順番1、3、4、6の小さい処理は、個別の静的見積もりだけでなく1つのgroupとしても
照合します。`pass2_delay_q4`から、実測Sub wait、選択されたshadow-update model、
固定NT-stage copyを引くと、Bad Appleの残りはp50で2.3 scanline、p95で3.6です。
負の最小値と大きいp99外れ値は、stopwatch量子化とapproximateな8-bit V-counter waitから
生じるため、実際の負の処理や100-lineの固定経路とは解釈しません。
順番8〜9は`pass2_delay_q4` sampleの後に448 nominal cycle、つまり0.92 scanlineを
追加します。

対応するBad Apple H40 320x224、30 fps、cold cap 210のcaptureには、timed PT frameが
6,396あります。

| 処理または観測 | Sample数 | min | p50 | p90 | p95 | p99 | max |
|---|---:|---:|---:|---:|---:|---:|---:|
| 更新cell数 | 6,396 | 1 | 171 | 319 | 385.25 | 643.05 | 1,120 |
| Sub待ち実測、scanline | 6,396 | 0.0 | 2.0 | 81.0 | 92.0 | 102.0 | 187.0 |
| 選択済みshadow update、nominal scanline | 6,396 | 0.18 | 29.67 | 39.51 | 42.39 | 52.35 | 60.06 |
| Bitmap shadow update、nominal scanline | 5,861 | 17.04 | 30.43 | 39.87 | 42.69 | 52.71 | 60.06 |
| List shadow update、nominal scanline | 535 | 0.18 | 4.80 | 6.57 | 6.87 | 6.97 | 6.97 |
| Shadow update + NT-stage copy、nominal scanline | 6,396 | 24.26 | 53.75 | 63.59 | 66.47 | 76.43 | 84.14 |
| 1つ前のflipから`bf_dma`まで、実測scanline | 6,396 | 25.11 | 67.60 | 141.00 | 152.58 | 166.10 | 243.36 |
| 1つ前のflipからreadyまで、実測 + nominal tail scanline | 6,396 | 26.03 | 68.52 | 141.91 | 153.50 | 167.02 | 244.28 |

Raw ready pressure値はphysical V-counter上のphaseで、経過処理時間ではありません。
同じPT frameでp50はscanline 54、p95は137.25、p99は154です。6,396 frame中1 frameは
最初のVBlank headを逃し、`0x100` sentinelで表します。Visible上のready phaseを`x`と
すると、VBlankが`E0`で始まるまでの残りは`224 - x` scanlineです。

実装方法をまだ決めずにbenchmarkする候補は、強い順に次のとおりです。

1. Name側の処理をpre-PT critical pathから外し、最初のPT VBlank後のactive-display
   intervalへ移します。このcaptureでは、readyを前倒しできる候補量がname処理の合計、
   p50で53.75、p95で66.47、最大84.14 scanlineです。Total CPU処理は減らず、NT readyを
   悪化させる可能性があるため、PTとNTのpressureを両方benchmarkします。
2. `shadow`→`nt_stage`全copyをなくすか融合します。64-pitch stageをauthoritativeにする、
   update decode中に最終stage形式へ書く、といった案は選択済み設計ではなくtest候補です。
   固定の候補量は24.08 scanlineで、Mainのtotal処理も減るためPTとNTの両方へ寄与できます。
3. Bitmap shadow-update costを減らすか表現を置き換えます。Bitmap frameのp50は
   30.43 scanline、選択済みlist frameは4.80です。ただしlistの強制はできません。
   現在のencoderは、正確なBODY routeがPrgBuf/readiness marginを維持し、control dataを
   増やさない場合だけlistを採用します。
4. 次のWord-RAM bankをより早く返す、またはrequestし、Sub処理とのoverlapを増やします。
   これはMain命令costではなく、実測p90 81-lineのwait tailが対象です。Cross-CPU ownershipを
   変えるため、CD pump、audio、startup、15/30 fps両方のhandoffを維持する必要があります。

固定bookkeepingは数scanlineだけなので優先度が低いです。`bf_start_vbudget`のfresh-head待ち、
pattern-run parseとDMA、HUD全体のformat、CRAM処理、NT DMA、cadence-final待ち、flipはすべて
ready sampleより後です。これらの最適化はPT完了やNT readyを改善し得ますが、このready値を
早めることはできません。

`harness/pt_prework/analyze.py`は、対応するpacked streamとHUD TSVからこれらの表を再生成します。
各experimentはpacked streamとtarget qualityを固定し、PT ready、PT完了、NT ready、
playback cadence、HUD safety fieldを分けて報告する必要があります。

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
