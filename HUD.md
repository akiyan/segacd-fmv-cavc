# On-hardware DEBUG HUD

The DEBUG player writes a values-only hexadecimal HUD through the fixed top
Window row and one-tile sprites on the second row. It is
designed for native-resolution recording and deterministic OCR. The HUD has no
labels on the console; every decoded value is exposed to tools with a
descriptive field name.

## Enabling the HUD

Build a DEBUG disc:

```sh
make disc CONFIG=profiles/PROFILE.toml DEBUG=1
```

Release builds omit the HUD. A DEBUG build carries 43 hexadecimal digits. The
row wraps after 40 cells and uses three cells on a second row.

The first 40 digits are one-word Window name-table entries. Each second-row
digit is one four-word sprite-table record, so the cadence-final HUD DMAs
transfer 52 words. The movie Plane A table is not used as a HUD route.

## Physical layout

Each cell is an 8x8 hexadecimal glyph. The glyph's top scanline also contains
four two-pixel bars that encode the nibble directly. OCR reads the bars and
checks the visible glyph as an independent confidence signal.

The table lists logical cell offsets before native-width wrapping, which maps
`row = offset // 40` and `column = offset % 40`. `tools/read_frameno.py`
publishes that single layout as `HUD_LAYOUT`, its digit count as `HUD_CELLS`,
its 40-cell row width as `HUD_ROW_CELLS`, and returns it from `hud_layout()`.

| Stored value | Logical cells | Digits | Decoded field or packing |
|---|---:|---:|---|
| `frame` | 0-3 | 4 | Displayed movie frame |
| `palette_segment` | 4 | 1 | Active palette segment |
| `sector_slip` | 5 | 1 | Cumulative sector-delivery recovery count |
| `control_desync` | 6 | 1 | Cumulative control-stream recovery count |
| `audio_resync` | 7 | 1 | Cumulative audio-pointer recovery count |
| `audio_lead_256b` | 8-9 | 2 | Audio lead in 256-byte units |
| `cd_wait_count` | 10 | 1 | Blocking CD service operations this frame |
| `sub_wait_scanlines` | 11-12 | 2 | Residual Main wait for Sub after overlap, in approximate scanlines |
| `adpcm_decode_units` | 13-14 | 2 | Sub ADPCM work in 0.12288 ms units |
| packed transfer word | 15-18 | 4 | High nibble `vblank_spill`; low 12 bits `transfer_ticks` |
| `cold_runs` | 19-20 | 2 | Low byte of packed cold-run count |
| `prgbuf_jitter_peak_kib` | 21-22 | 2 | Sticky ceil-KiB excess above the normal PrgBuf ceiling |
| `flip_vcounter` | 23-24 | 2 | V-counter of the preceding displayed flip |
| `first_share_exit_vcounter` | 25-26 | 2 | First transfer-share exit V-counter |
| `pass2_delay_q4` | 27-28 | 2 | Pass2 delay in groups of four stopwatch ticks |
| packed pump word | 29-32 | 4 | Bit 15 `apply_backpressure`; low 12 bits `pump_gap_ticks` |
| `msf_gap_recoveries` | 33 | 1 | Cumulative MSF-gap recoveries |
| packed reader byte | 34-35 | 2 | High nibble `reader_ahead_frames`; low nibble `reader_slot_sector` |
| `transfer_vblanks` | 36 | 1 | Fresh transfer budgets opened this frame |
| `transfer_end_vcounter` | 37-38 | 2 | Final transfer exit V-counter |
| `pattern_dma_ready_vcounter` | 39-40 | 2 | Pattern-run ready V-counter before the fresh-blank wait |
| `name_table_dma_ready_vcounter` | 41-42 | 2 | Name-table path ready V-counter before the cadence-final VBlank wait |

The player-only pre-roll sentinel uses `frame=FFFF`. It is an OCR anchor, not a
stream frame, and is never written to the HUD TSV. Movie frame 0 remains in the
TSV for sequence alignment but is untimed boot staging.

## Field reference

| Field | Owner | Scope | Meaning |
|---|---|---|---|
| `frame` | Main | per frame | Displayed movie frame number |
| `palette_segment` | Main | per frame | Active CRAM segment |
| `sector_slip` | Sub | cumulative nibble | Sector-delivery recoveries; interpret transitions, including wrap |
| `control_desync` | Sub | cumulative nibble | Control parser recoveries |
| `audio_resync` | Sub | cumulative nibble | Audio read-pointer corrections |
| `audio_lead_256b` | Sub | per frame | Queued audio lead in 256-byte units |
| `cd_wait_count` | Sub | per frame | Blocking CD work on the current-frame path; diagnostic only |
| `sub_wait_scanlines` | Main | per frame | Residual blocking wait after Main starts completing the Sub handoff |
| `vblank_spill` | Main | per frame | Additional VBlank budgets consumed by pattern work |
| `adpcm_decode_units` | Sub | per frame | ADPCM decode work in 0.12288 ms units |
| `transfer_ticks` | Main | per frame | Main pattern-transfer time in 30.72 us ticks, modulo 12 bits |
| `cold_runs` | Main | per frame | Low byte of the packed cold-run count |
| `prgbuf_jitter_peak_kib` | Sub | sticky nibble pair | Highest ceil-KiB use of runtime jitter headroom |
| `flip_vcounter` | Main | per frame | V-counter of the flip that published the preceding frame |
| `first_share_exit_vcounter` | Main | per frame | Exit phase of the first transfer share |
| `pass2_delay_q4` | Main | per frame | Pass2 delay in four-tick units |
| `pump_gap_ticks` | Sub | per frame | Longest interval outside a CDC service opportunity |
| `apply_backpressure` | Sub | per frame | APPLY guard rejected a control-sector pump |
| `msf_gap_recoveries` | Sub | cumulative nibble | Sector-position gap recoveries |
| `reader_ahead_frames` | Sub | per frame | Complete future frame slots already read |
| `reader_slot_sector` | Sub | per frame | Sector position inside the current reader slot |
| `transfer_vblanks` | Main | per frame | Number of fresh transfer budgets opened |
| `transfer_end_vcounter` | Main | per frame | Final transfer exit phase |
| `pattern_dma_ready_vcounter` | Main | per frame | Raw V-counter when Main is ready to consume the first pattern run, immediately before waiting for a fresh blank head |
| `name_table_dma_ready_vcounter` | Main | per frame | Raw V-counter when the single-table DMA path is ready, immediately before waiting for the cadence-final VBlank |

`sector_slip`, `control_desync`, `audio_resync`, and
`msf_gap_recoveries` are four-bit cumulative counters. A transition is the
event; a repeated nonzero value is state. Their wrap from 15 to 0 is valid.
The transport-retry remainder is
`(sector_slip - msf_gap_recoveries) & 0xF`.

`prgbuf_jitter_peak_kib` is a sticky high-water value, not current occupancy.
`cd_wait_count`, `pump_gap_ticks`, and `apply_backpressure` diagnose why time
was spent; a larger wait can also mean the Sub path reached the next sector
earlier.

On every generic and specialized path, Main asserts `CMD_SWAP` without blocking
after the final pattern DMA and repair and after every read from the current
Word RAM bank. Main then continues the name-table, scroll, HUD, CRAM, and publication path while
Sub exchanges the banks, flushes pending WordBuf data, and pumps the CD. At the
next playback-loop head, `sub_wait_scanlines` measures only the time from
entering completion polling until Sub reports ready or end. Zero means the
handoff completed during the overlap; it does not mean that the physical bank
exchange took zero time. Frame 0 and the final-frame end request remain
synchronous because they have no safe future-frame bank request to overlap.

The pattern-ready and name-table-ready fields retain the raw eight-bit NTSC V28
V-counter. On the current raster, visible lines 0-223 use `00-DF`; blank starts
at raster line 224 with `E0`. A visible pattern-ready value `V` means Main
became ready `E0 - V` raster lines before the next blank head. `E0` means zero
lead. A value later than `E0` means the current blank head was already missed;
`bf_start_vbudget` waits for the following head instead of granting a partial
budget. Raw `E0-EA` first maps to blank offsets 0-10. The counter then jumps
back from `EA` to `E5`: the second `E5-EA` maps to blank offsets 11-16, and
`EB-FF` maps to offsets 17-37. Therefore `E5-EA` is ambiguous without sequence
context; resolve it from nearby samples and the operation order. Tools preserve
the raw value rather than silently choosing one occurrence.

`/hudline` converts the pattern-ready field into the derived
`pattern_dma_ready_pressure` row. A ready event on visible scanline `00..DF`
has the same pressure `00..DF`, so scanline 0 is pressure zero and larger
values mean later, more pressured readiness. A blank-phase ready sample within
one complete blank of the preceding flip still belongs to that preceding
blank; `pass2_delay_q4` identifies it and the pressure clamps to zero. `E0`
otherwise means the zero-margin first target-VBlank head. A later blank value
becomes the `0x100` missed-head sentinel; this avoids inventing an order for
the repeated `E5..EA` values. Frames with no cold run have no pressure point,
rather than a false zero. The row has an orange `E0` guide, and `0x100` points
are red. The raw `pattern_dma_ready_vcounter` remains unchanged in the TSV and
gate JSON.

`/hudline` also converts `name_table_dma_ready_vcounter` into the derived
`name_table_dma_ready_pressure` row. Its deadline is the cadence-final VBlank
head that carries the single-table DMA: VBlank 4 at 15 fps, alternating
VBlank 2/3 at 24 fps, and VBlank 2 at 30 fps. `transfer_vblanks` identifies
how many fresh pattern budgets have already opened. Readiness earlier than the
active raster immediately before that target clamps to pressure zero. In that final active raster, raw
scanlines `00..DF` map directly to pressure; scanline 0 is pressure zero and
`E0` is zero margin. On a scroll-control frame the same single-table DMA
carries the wider rolling-plane band instead of the visible-grid words, so an
identical raw V-counter value implies less real margin there.

That target head applies directly when PT fits before it. If PT splits into the
target budget, NT can start only after PT2; a ready sample in that same VBlank
keeps its physical `E0..FF` value so the remaining blank pressure stays
visible. A visible sample after the target budget opened, or a third PT budget
at 30 fps, becomes the `0x100` escaped-target-blank sentinel. A blank-phase raw
sample before the target belongs to the preceding budget and clamps to zero,
avoiding the repeated `E5..EA` ambiguity. The row has an orange `E0`
target-head guide, and values after it are red. Raw
`name_table_dma_ready_vcounter` remains
unchanged in the TSV and gate JSON.

## Upload gate

`harness/startup_resync/analyze.py` writes descriptive gate schema 16. The
binary `gate` is `PASS` or `FAIL`; `alert` is `NONE`, `WARNING`, or `FAIL`.
`NONE` and `WARNING` remain upload-capable.

The five gate fields are:

| Field | Limit |
|---|---|
| `sector_slip` | 0 |
| `control_desync` | 0 |
| `audio_resync` | 0 |
| `vblank_spill` | Authoritative cadence: one less than its largest interval; delivery-paced cadence: the available fields per content frame |
| `prgbuf_jitter_peak_kib` | Physical ring size minus the cadence-derived normal PrgBuf ceiling minus 1 KiB |

An excess in `vblank_spill` is a warning. An excess in the other four fields
is a failure. At an authoritative cadence, a `transfer_vblanks` value larger
than the schedule's largest interval is also a warning. The analyzer derives
each timed frame's visible duration from consecutive `capture_first` values
and compares it with that frame's schedule step. For 24 fps the expected steps
are exactly `2, 3, 2, 3, ...`; the expected pattern is stored in
`display_vblank_expected`. A mismatch is a warning outside the cadence edge
exception. The first and last four content frames at 30 fps, three at 24 fps,
and two at 15 fps remain in the measurements but do not raise this derived
ALERT. This exception does not apply to gate fields or `transfer_vblanks`.
When periodic 24 fps recovery repays a late VBlank, the compensating two-VBlank
interval remains visible as a phase mismatch warning. The histogram and the
gate therefore preserve both the missed target and its long-term clock repair.

Frame 0 and the terminal hold are excluded from gate maxima, statistics,
events, dynamic scales, and cadence measurements. `cd_wait_count` and
`adpcm_decode_units` always retain minimum, mean, median, maximum, and sample
count over timed first-loop frames. `pump_gap_ticks` receives the same
statistics when present. The gate also stores the APPLY back-pressure frame
count and maxima for reader lead and transfer phase.

## OCR and TSV

Run the complete recording analyzer with the exact profile:

```sh
tools/python.sh harness/startup_resync/analyze.py \
  "$LOSSLESS" profiles/PROFILE.toml \
  --expected-frames FRAME_COUNT
```

The analyzer finds the `frame=FFFF` to `frame=0000` transition when present,
reads one complete first loop, and writes:

```text
logs/<datetime>_<profile>_<sha10>_eNN_pNN_hud.tsv
logs/<datetime>_<profile>_<sha10>_eNN_pNN_hud_gate.json
```

The TSV uses descriptive columns. Its decoded HUD columns are:

```text
frame palette_segment sector_slip control_desync audio_resync
audio_lead_256b cd_wait_count sub_wait_scanlines vblank_spill
adpcm_decode_units transfer_ticks cold_runs prgbuf_jitter_peak_kib
flip_vcounter first_share_exit_vcounter pass2_delay_q4 pump_gap_ticks
apply_backpressure msf_gap_recoveries reader_ahead_frames
reader_slot_sector transfer_vblanks transfer_end_vcounter
pattern_dma_ready_vcounter name_table_dma_ready_vcounter
```

It also stores capture timing, OCR confidence, sample counts, derived
milliseconds, audio-resync transition context, and
`transport_retry_recoveries`.

`/hudline` renders the descriptive values and their gate lines.
`/timeline` renders encoder decisions, including exact Main-to-VDP words and a
cold-cap guide in the REQ row. `/mixline` validates their shared frame axis and
combines both images without resizing either graph.

The optional GPGX LOGVDP extractor aligns physical VDP writes to the HUD frame
axis. The retired per-VBlank logical word-share HUD fields are not available
for a HUD-side total; the extraction receipt therefore proves input hashes and
frame alignment, while the codec timeline independently checks its exact R2V
components.

## Maintenance contract

When field order, width, or packing changes, update these together:

- `boot/movieplay_ip.s`
- `tools/read_frameno.py`
- `harness/startup_resync/analyze.py`
- `.agents/skills/hudline/scripts/render_hudline.py`
- `.agents/skills/hudline/scripts/report_overages.py`
- `.agents/skills/mixline/scripts/render_mixline.py`
- `tools/r2v_model.py`
- this document and the related tests

Keep OCR output, TSV and JSON keys, receipts, documentation, and renderer row
keys descriptive. One-letter display aliases are not part of the public
diagnostic interface.

---

# 実機 DEBUG HUD

DEBUG playerは値だけの16進HUDを、固定top Window rowと2行目の1-tile spriteで
書きます。Native-resolution
recording から deterministic に OCR するための HUD です。実機画面には label を
出さず、tool が decode した値はすべて説明的な field name で公開します。

## HUD の有効化

DEBUG disc を build します。

```sh
make disc CONFIG=profiles/PROFILE.toml DEBUG=1
```

Release build は HUD を省きます。DEBUG build は 43 桁の 16 進値を持ちます。
行は 40 cell の後で折り返し、2 行目の 3 cell を使います。

先頭40桁は1-word Window name-table entryです。2行目の各桁は4-word
sprite-table recordなので、cadence-final HUD DMAは52 wordを転送します。
Movie Plane A tableはHUD routeに使いません。

## 物理 layout

各 cell は 8x8 の 16 進 glyph です。Glyph の最上 scanline には nibble を直接
表す 2 pixel 幅の bar も 4 本あります。OCR は bar を読み、表示 glyph を独立した
confidence check に使います。

表の cell は native width で折り返す前の logical offset で、
`row = offset // 40`、`column = offset % 40` を使います。
`tools/read_frameno.py` はこの単一 layout を `HUD_LAYOUT`、その桁数を
`HUD_CELLS`、40 cell の行幅を `HUD_ROW_CELLS` として公開し、`hud_layout()`
で返します。

| Stored value | Logical cells | Digits | Decoded field または packing |
|---|---:|---:|---|
| `frame` | 0-3 | 4 | 表示中の movie frame |
| `palette_segment` | 4 | 1 | Active palette segment |
| `sector_slip` | 5 | 1 | Cumulative sector-delivery recovery count |
| `control_desync` | 6 | 1 | Cumulative control-stream recovery count |
| `audio_resync` | 7 | 1 | Cumulative audio-pointer recovery count |
| `audio_lead_256b` | 8-9 | 2 | 256-byte 単位の audio lead |
| `cd_wait_count` | 10 | 1 | この frame の blocking CD service 回数 |
| `sub_wait_scanlines` | 11-12 | 2 | 重なり実行後に残った Main の Sub 待ち。approximate scanline 単位 |
| `adpcm_decode_units` | 13-14 | 2 | 0.12288 ms 単位の Sub ADPCM work |
| packed transfer word | 15-18 | 4 | High nibble が `vblank_spill`、low 12 bit が `transfer_ticks` |
| `cold_runs` | 19-20 | 2 | Packed cold-run count の low byte |
| `prgbuf_jitter_peak_kib` | 21-22 | 2 | Normal PrgBuf ceiling 超過分の sticky ceil-KiB |
| `flip_vcounter` | 23-24 | 2 | 直前の displayed flip の V-counter |
| `first_share_exit_vcounter` | 25-26 | 2 | First transfer-share の exit V-counter |
| `pass2_delay_q4` | 27-28 | 2 | 4 stopwatch tick 単位の Pass2 delay |
| packed pump word | 29-32 | 4 | Bit 15 が `apply_backpressure`、low 12 bit が `pump_gap_ticks` |
| `msf_gap_recoveries` | 33 | 1 | Cumulative MSF-gap recovery count |
| packed reader byte | 34-35 | 2 | High nibble が `reader_ahead_frames`、low nibble が `reader_slot_sector` |
| `transfer_vblanks` | 36 | 1 | この frame で開いた fresh transfer budget 数 |
| `transfer_end_vcounter` | 37-38 | 2 | Final transfer exit V-counter |
| `pattern_dma_ready_vcounter` | 39-40 | 2 | Fresh-blank 待ち直前の pattern-run ready V-counter |
| `name_table_dma_ready_vcounter` | 41-42 | 2 | Cadence-final VBlank待ち直前のname-table path ready V-counter |

Player-only pre-roll sentinel は `frame=FFFF` です。OCR anchor であり stream frame
ではなく、HUD TSV にも書きません。Movie frame 0 は sequence alignment のため
TSV に残しますが、untimed boot staging です。

## Field reference

| Field | Owner | Scope | 意味 |
|---|---|---|---|
| `frame` | Main | per frame | Displayed movie frame number |
| `palette_segment` | Main | per frame | Active CRAM segment |
| `sector_slip` | Sub | cumulative nibble | Sector-delivery recovery。Transition と wrap を読む |
| `control_desync` | Sub | cumulative nibble | Control parser recovery |
| `audio_resync` | Sub | cumulative nibble | Audio read-pointer correction |
| `audio_lead_256b` | Sub | per frame | 256-byte 単位の queued audio lead |
| `cd_wait_count` | Sub | per frame | Current-frame path 上の blocking CD work。Diagnostic 専用 |
| `sub_wait_scanlines` | Main | per frame | Main が Sub handoff の完了待ちを始めた後に残った blocking wait |
| `vblank_spill` | Main | per frame | Pattern work が消費した追加 VBlank budget |
| `adpcm_decode_units` | Sub | per frame | 0.12288 ms 単位の ADPCM decode work |
| `transfer_ticks` | Main | per frame | 30.72 us tick 単位の Main pattern-transfer time。12 bit wrap |
| `cold_runs` | Main | per frame | Packed cold-run count の low byte |
| `prgbuf_jitter_peak_kib` | Sub | sticky nibble pair | Runtime jitter headroom の最大 ceil-KiB 使用量 |
| `flip_vcounter` | Main | per frame | 直前の frame を publish した flip の V-counter |
| `first_share_exit_vcounter` | Main | per frame | First transfer share の exit phase |
| `pass2_delay_q4` | Main | per frame | 4 tick 単位の Pass2 delay |
| `pump_gap_ticks` | Sub | per frame | CDC service opportunity 外の最長 interval |
| `apply_backpressure` | Sub | per frame | APPLY guard が control-sector pump を拒否 |
| `msf_gap_recoveries` | Sub | cumulative nibble | Sector-position gap recovery |
| `reader_ahead_frames` | Sub | per frame | Read 済みの complete future frame slot 数 |
| `reader_slot_sector` | Sub | per frame | Current reader slot 内の sector position |
| `transfer_vblanks` | Main | per frame | 開いた fresh transfer budget 数 |
| `transfer_end_vcounter` | Main | per frame | Final transfer exit phase |
| `pattern_dma_ready_vcounter` | Main | per frame | Main が最初の pattern run を consume 可能になり、fresh blank head を待つ直前の raw V-counter |
| `name_table_dma_ready_vcounter` | Main | per frame | single-table DMA pathがreadyになり、cadence-final VBlankを待つ直前のraw V-counter |

`sector_slip`、`control_desync`、`audio_resync`、
`msf_gap_recoveries` は 4-bit cumulative counter です。Transition が event で、
同じ nonzero value の繰り返しは state です。15 から 0 への wrap は正常です。
Transport-retry remainder は
`(sector_slip - msf_gap_recoveries) & 0xF` です。

`prgbuf_jitter_peak_kib` は sticky high-water であり current occupancy では
ありません。`cd_wait_count`、`pump_gap_ticks`、`apply_backpressure` は時間を
使った理由の diagnostic です。Wait の増加は Sub path が次 sector へ早く到達した
結果でもあり得ます。

すべてのgeneric / specialized pathで、Mainは最後のpattern DMAと
先頭word補修、および現在のWord RAM bankに対する全readを終えた後、
blockingせず`CMD_SWAP`をassert
します。その後Mainがname-table、scroll、HUD、CRAM、publication pathを進む間に、Subはbank交換、
pending WordBuf dataのflush、CD pumpを行います。次のplayback-loop先頭で、
`sub_wait_scanlines`は完了pollingに入ってからSubがreadyまたはendを返すまでの
時間だけを測ります。ゼロはhandoffが重なり実行中に完了したという意味であり、
物理bank交換の所要時間がゼロという意味ではありません。Frame 0とfinal-frameの
end requestは、安全に重ねられるfuture-frame bank requestがないため同期のままです。

Pattern-ready field と name-table-ready field は NTSC V28 の raw 8-bit
V-counter を保持します。現在の raster では visible line 0-223 が `00-DF`、
blank は raster line 224 の `E0` から始まります。Visible 中の pattern-ready
値を `V` とすると、Main は次の blank head の `E0 - V` raster line 前に ready
になっています。`E0` は lead 0 です。`E0` より後なら現在の blank head をすでに
逃しており、`bf_start_vbudget` は partial budget を認めず次の head を待ちます。
最初の `E0-EA` は blank offset 0-10 です。その後 counter は `EA` から `E5`
へ戻り、2 回目の `E5-EA` は blank offset 11-16、`EB-FF` は offset 17-37
です。このため `E5-EA` は sequence context なしでは二通りに解釈できます。
Nearby sample と operation order で決め、tool は一方を暗黙に選ばず raw 値を保持
します。

`/hudline` は pattern-ready field を、導出値
`pattern_dma_ready_pressure` の row へ変換します。Visible scanline
`00..DF` の ready event は同じ `00..DF` の逼迫度になり、scanline 0 が
逼迫度 0、値が大きいほど遅く逼迫した ready です。直前のflipから1 blank以内の
blank-phase readyはまだその直前blankに属します。`pass2_delay_q4`でこれを判定し、
逼迫度を0へclampします。それ以外の`E0`は最初のtarget VBlank headまでの余裕が
0の位置です。それより後のblank値はheadを逃した`0x100` sentinelにします。
これにより、繰り返す`E5..EA`の順序を捏造せずに済みます。Cold runがないframeは
偽の0ではなく、逼迫度の点自体を表示しません。Rowにはorangeの`E0` guideを引き、
`0x100`の点はredにします。TSVとgate JSONのraw
`pattern_dma_ready_vcounter`は変更しません。

`/hudline` は `name_table_dma_ready_vcounter` も導出値
`name_table_dma_ready_pressure`のrowへ変換します。Deadlineはsingle-table DMAを
実行するcadence-final VBlank headで、15 fpsは4回目、24 fpsは2/3回目を交互、
30 fpsは2回目です。`transfer_vblanks`で、すでに開いたfresh pattern
budget 数を判定します。Target 直前の active raster より早く ready なら逼迫度 0
へ clamp します。その最後の active raster では raw scanline `00..DF` をそのまま
逼迫度にし、scanline 0 が逼迫度 0、`E0` が余裕 0 です。scroll-control frameでは
同じsingle-table DMAがvisible gridのwordではなくより広いrolling plane bandを
運ぶため、同じraw V-counter値でも実際の余裕はそれより小さくなります。

このtarget headをそのまま使うのは、PTがその前に収まる場合です。PTがtarget
budgetへ分割された場合、NT開始可能点はPT2の後です。同じVBlank内のready sampleは
physicalな`E0..FF`をそのまま残し、残りblankの逼迫を見えるようにします。Target
budgetを開いた後のvisible sample、または30 fpsで3本目のPT budgetまで進んだ場合は
target blankを抜けた`0x100` sentinelにします。Targetより前のblank-phase raw
sampleは一つ前のbudgetに属するため0へclampし、繰り返す`E5..EA`の曖昧さを
持ち込みません。Rowにはorangeの`E0` target-head guideを引き、それより後の値は
redにします。TSVとgate JSONのraw `name_table_dma_ready_vcounter`は変更しません。

## Upload gate

`harness/startup_resync/analyze.py` は descriptive gate schema 16 を書きます。
Binary `gate` は `PASS` / `FAIL`、`alert` は `NONE` / `WARNING` / `FAIL` です。
`NONE` と `WARNING` は upload 可能です。

5 個の gate field は次のとおりです。

| Field | Limit |
|---|---|
| `sector_slip` | 0 |
| `control_desync` | 0 |
| `audio_resync` | 0 |
| `vblank_spill` | 正式なcadenceでは最大VBlank intervalより1少ない値。Delivery-paced cadenceでは1 content frameに使えるfield数 |
| `prgbuf_jitter_peak_kib` | Physical ring size から cadence-derived normal PrgBuf ceiling と 1 KiB を引いた値 |

`vblank_spill` 超過は warning、ほか 4 field の超過は failure です。正式なcadence
では`transfer_vblanks`がscheduleの最大intervalを超えた場合もwarningです。
Analyzerは連続する`capture_first`から各timed frameの表示時間を求め、そのframeの
schedule stepと比較します。24 fpsの期待stepは厳密に`2, 3, 2, 3, ...`で、
`display_vblank_expected`にpatternを保存します。不一致はcadence edge exceptionの
外側でwarningになります。30 fpsでは先頭と末尾の各4 content frame、24 fpsでは
各3 frame、15 fpsでは各2 frameをmeasurementには残しますが、このderived ALERTの
対象外にします。この例外はgate fieldと`transfer_vblanks`には適用しません。
Periodic 24 fps recoveryがlate VBlankを返済すると、補償用の2 VBlank intervalも
位相mismatch warningとして表示に残ります。したがってhistogramとgateは、外したtargetと
long-term clock修復の両方を保存します。

Frame 0 と terminal hold は gate maximum、statistics、event、dynamic scale、
cadence measurement から除外します。`cd_wait_count` と `adpcm_decode_units` は
timed first loop の minimum、mean、median、maximum、sample count を常に保存します。
`pump_gap_ticks` も存在する場合は同じ statistics を保存します。Gate は APPLY
back-pressure frame count と reader lead / transfer phase の maximum も保存します。

## OCR と TSV

正確な profile を渡して complete recording analyzer を実行します。

```sh
tools/python.sh harness/startup_resync/analyze.py \
  "$LOSSLESS" profiles/PROFILE.toml \
  --expected-frames FRAME_COUNT
```

Analyzer は存在すれば `frame=FFFF` から `frame=0000` への transition を見つけ、
complete first loop を読み、次を出力します。

```text
logs/<datetime>_<profile>_<sha10>_eNN_pNN_hud.tsv
logs/<datetime>_<profile>_<sha10>_eNN_pNN_hud_gate.json
```

TSV は descriptive column を使います。Decoded HUD column は次のとおりです。

```text
frame palette_segment sector_slip control_desync audio_resync
audio_lead_256b cd_wait_count sub_wait_scanlines vblank_spill
adpcm_decode_units transfer_ticks cold_runs prgbuf_jitter_peak_kib
flip_vcounter first_share_exit_vcounter pass2_delay_q4 pump_gap_ticks
apply_backpressure msf_gap_recoveries reader_ahead_frames
reader_slot_sector transfer_vblanks transfer_end_vcounter
pattern_dma_ready_vcounter name_table_dma_ready_vcounter
```

さらに capture timing、OCR confidence、sample count、derived milliseconds、
audio-resync transition context、`transport_retry_recoveries` を保存します。

`/hudline` は descriptive value と gate line を描画します。`/timeline` は exact
Main-to-VDP word と REQ row の cold-cap guide を含む encoder decision を描画します。
`/mixline` は shared frame axis を検証し、どちらの graph も resize せず合成します。

Optional GPGX LOGVDP extractor は physical VDP write を HUD frame axis へ align
します。廃止した per-VBlank logical word-share HUD field から HUD-side total は
得られません。そのため extraction receipt は input hash と frame alignment を
証明し、codec timeline が独立して exact R2V component を検証します。

## Maintenance contract

Field order、width、packing を変える場合は次を同時に更新します。

- `boot/movieplay_ip.s`
- `tools/read_frameno.py`
- `harness/startup_resync/analyze.py`
- `.agents/skills/hudline/scripts/render_hudline.py`
- `.agents/skills/hudline/scripts/report_overages.py`
- `.agents/skills/mixline/scripts/render_mixline.py`
- `tools/r2v_model.py`
- この文書と関連 test

OCR output、TSV / JSON key、receipt、documentation、renderer row key は descriptive
name に統一します。1 文字の display alias は public diagnostic interface では
ありません。
