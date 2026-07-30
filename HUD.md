# On-hardware DEBUG HUD

The DEBUG player writes a values-only hexadecimal HUD into Plane A. It is
designed for native-resolution recording and deterministic OCR. The HUD has no
labels on the console; every decoded value is exposed to tools with a
descriptive field name.

## Enabling the HUD

Build a DEBUG disc:

```sh
make disc CONFIG=profiles/PROFILE.toml DEBUG=1
```

Release builds omit the HUD. H32 and H40 DEBUG builds carry the same 43
hexadecimal digits. H32 wraps after 32 cells and uses 11 cells on a second
row. H40 wraps after 40 cells and uses three cells on a second row.

## Physical layout

Each cell is an 8x8 hexadecimal glyph. The glyph's top scanline also contains
four two-pixel bars that encode the nibble directly. OCR reads the bars and
checks the visible glyph as an independent confidence signal.

The table lists logical cell offsets before native-width wrapping. H32 maps
`row = offset // 32` and `column = offset % 32`. H40 maps
`row = offset // 40` and `column = offset % 40`.

| Stored value | Logical cells | Digits | Decoded field or packing |
|---|---:|---:|---|
| `frame` | 0-3 | 4 | Displayed movie frame |
| `palette_segment` | 4 | 1 | Active palette segment |
| `sector_slip` | 5 | 1 | Cumulative sector-delivery recovery count |
| `control_desync` | 6 | 1 | Cumulative control-stream recovery count |
| `audio_resync` | 7 | 1 | Cumulative audio-pointer recovery count |
| `audio_lead_256b` | 8-9 | 2 | Audio lead in 256-byte units |
| `cd_wait_count` | 10 | 1 | Blocking CD service operations this frame |
| `sub_wait_scanlines` | 11-12 | 2 | Main wait for Sub, in approximate scanlines |
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
| `pattern_dma_start_vcounter` | 39-40 | 2 | First pattern run-loop entry V-counter |
| `name_table_dma_start_vcounter` | 41-42 | 2 | Name-table DMA pre-trigger V-counter; zero when that path is absent |

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
| `sub_wait_scanlines` | Main | per frame | Approximate wait for the Sub handoff |
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
| `pattern_dma_start_vcounter` | Main | per frame | Raw V-counter before entering the first pattern run loop from a proven blank head |
| `name_table_dma_start_vcounter` | Main | per frame | Raw V-counter immediately before the fixed-N H40 name-table DMA trigger |

`sector_slip`, `control_desync`, `audio_resync`, and
`msf_gap_recoveries` are four-bit cumulative counters. A transition is the
event; a repeated nonzero value is state. Their wrap from 15 to 0 is valid.
The transport-retry remainder is
`(sector_slip - msf_gap_recoveries) & 0xF`.

`prgbuf_jitter_peak_kib` is a sticky high-water value, not current occupancy.
`cd_wait_count`, `pump_gap_ticks`, and `apply_backpressure` diagnose why time
was spent; a larger wait can also mean the Sub path reached the next sector
earlier.

The two DMA-start fields retain the raw eight-bit NTSC V28 V-counter. On the
current raster, visible lines 0-223 use `00-DF`; blank starts at raster line 224
with `E0`. Raw `E0-EA` first maps to blank offsets 0-10. The counter then jumps
back from `EA` to `E5`: the second `E5-EA` maps to blank offsets 11-16, and
`EB-FF` maps to offsets 17-37. Therefore `E5-EA` is ambiguous without sequence
context; resolve it from nearby samples and the operation order. Tools preserve
the raw value rather than silently choosing one occurrence.

## Upload gate

`harness/startup_resync/analyze.py` writes descriptive gate schema 12. The
binary `gate` is `PASS` or `FAIL`; `alert` is `NONE`, `WARNING`, or `FAIL`.
`NONE` and `WARNING` remain upload-capable.

The five gate fields are:

| Field | Limit |
|---|---|
| `sector_slip` | 0 |
| `control_desync` | 0 |
| `audio_resync` | 0 |
| `vblank_spill` | Fixed cadence: one less than the VBlank interval; delivery-paced cadence: the available fields per content frame |
| `prgbuf_jitter_peak_kib` | Physical ring size minus the cadence-derived normal PrgBuf ceiling minus 1 KiB |

An excess in `vblank_spill` is a warning. An excess in the other four fields
is a failure. At fixed cadence, a `transfer_vblanks` value larger than the
cadence interval is also a warning. The analyzer derives each timed frame's
visible duration from consecutive `capture_first` values; a duration different
from the fixed cadence is a warning outside the cadence edge exception. The
first and last four content frames at 30 fps and two at 15 fps remain in the
measurements but do not raise this derived ALERT. This exception does not apply
to gate fields or `transfer_vblanks`.

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
pattern_dma_start_vcounter name_table_dma_start_vcounter
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

DEBUG player は値だけの 16 進 HUD を Plane A へ書きます。Native-resolution
recording から deterministic に OCR するための HUD です。実機画面には label を
出さず、tool が decode した値はすべて説明的な field name で公開します。

## HUD の有効化

DEBUG disc を build します。

```sh
make disc CONFIG=profiles/PROFILE.toml DEBUG=1
```

Release build は HUD を省きます。H32 と H40 の DEBUG build は同じ 43 桁の
16 進値を持ちます。H32 は 32 cell の後で折り返し、2 行目の 11 cell を使います。
H40 は 40 cell の後で折り返し、2 行目の 3 cell を使います。

## 物理 layout

各 cell は 8x8 の 16 進 glyph です。Glyph の最上 scanline には nibble を直接
表す 2 pixel 幅の bar も 4 本あります。OCR は bar を読み、表示 glyph を独立した
confidence check に使います。

表の cell は native width で折り返す前の logical offset です。H32 は
`row = offset // 32`、`column = offset % 32`、H40 は
`row = offset // 40`、`column = offset % 40` を使います。

| Stored value | Logical cells | Digits | Decoded field または packing |
|---|---:|---:|---|
| `frame` | 0-3 | 4 | 表示中の movie frame |
| `palette_segment` | 4 | 1 | Active palette segment |
| `sector_slip` | 5 | 1 | Cumulative sector-delivery recovery count |
| `control_desync` | 6 | 1 | Cumulative control-stream recovery count |
| `audio_resync` | 7 | 1 | Cumulative audio-pointer recovery count |
| `audio_lead_256b` | 8-9 | 2 | 256-byte 単位の audio lead |
| `cd_wait_count` | 10 | 1 | この frame の blocking CD service 回数 |
| `sub_wait_scanlines` | 11-12 | 2 | Approximate scanline 単位の Main の Sub 待ち |
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
| `pattern_dma_start_vcounter` | 39-40 | 2 | 最初の pattern run-loop entry の V-counter |
| `name_table_dma_start_vcounter` | 41-42 | 2 | Name-table DMA trigger 直前の V-counter。該当 path がなければ 0 |

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
| `sub_wait_scanlines` | Main | per frame | Sub handoff の approximate wait |
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
| `pattern_dma_start_vcounter` | Main | per frame | 証明済み blank head から最初の pattern run loop へ入る直前の raw V-counter |
| `name_table_dma_start_vcounter` | Main | per frame | fixed-N H40 name-table DMA trigger 直前の raw V-counter |

`sector_slip`、`control_desync`、`audio_resync`、
`msf_gap_recoveries` は 4-bit cumulative counter です。Transition が event で、
同じ nonzero value の繰り返しは state です。15 から 0 への wrap は正常です。
Transport-retry remainder は
`(sector_slip - msf_gap_recoveries) & 0xF` です。

`prgbuf_jitter_peak_kib` は sticky high-water であり current occupancy では
ありません。`cd_wait_count`、`pump_gap_ticks`、`apply_backpressure` は時間を
使った理由の diagnostic です。Wait の増加は Sub path が次 sector へ早く到達した
結果でもあり得ます。

2 個の DMA start field は NTSC V28 の raw 8-bit V-counter を保持します。現在の
raster では visible line 0-223 が `00-DF`、blank は raster line 224 の `E0` から
始まります。最初の `E0-EA` は blank offset 0-10 です。その後 counter は `EA`
から `E5` へ戻り、2 回目の `E5-EA` は blank offset 11-16、`EB-FF` は offset
17-37 です。このため `E5-EA` は sequence context なしでは二通りに解釈できます。
Nearby sample と operation order で決め、tool は一方を暗黙に選ばず raw 値を保持
します。

## Upload gate

`harness/startup_resync/analyze.py` は descriptive gate schema 12 を書きます。
Binary `gate` は `PASS` / `FAIL`、`alert` は `NONE` / `WARNING` / `FAIL` です。
`NONE` と `WARNING` は upload 可能です。

5 個の gate field は次のとおりです。

| Field | Limit |
|---|---|
| `sector_slip` | 0 |
| `control_desync` | 0 |
| `audio_resync` | 0 |
| `vblank_spill` | Fixed cadence では VBlank interval より 1 少ない値。Delivery-paced cadence では 1 content frame に使える field 数 |
| `prgbuf_jitter_peak_kib` | Physical ring size から cadence-derived normal PrgBuf ceiling と 1 KiB を引いた値 |

`vblank_spill` 超過は warning、ほか 4 field の超過は failure です。Fixed cadence
では `transfer_vblanks` が cadence interval を超えた場合も warning です。
Analyzer は連続する `capture_first` から各 timed frame の表示時間を求め、
fixed cadence と異なる表示時間を cadence edge exception の外側で warning に
します。30 fps では先頭と末尾の各 4 content frame、15 fps では各 2 content
frame を measurement には残しますが、この derived ALERT の対象外にします。
この例外は gate field と `transfer_vblanks` には適用しません。

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
pattern_dma_start_vcounter name_table_dma_start_vcounter
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
