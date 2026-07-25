EN / [JP](#jp)

# HEADER.DAT / BODY.DAT binary format (TTRC)

`HEADER.DAT` and `BODY.DAT` are the two on-disc files of the **Tile Texture
Reuse Codec**. `tools/pack_stream.py` writes them from the `tools/sim.py`
decision log. `boot/movieplay_sp.s` streams them and `boot/movieplay_ip.s`
displays them.

The packer also writes `MOVIE.DAT = HEADER.DAT || BODY.DAT` for off-disc
analysis and regression tools. The disc contains only `HEADER.DAT` and
`BODY.DAT`.

All multi-byte integers are big-endian. Every region is sector-aligned. The Sub
CPU reads all of `HEADER.DAT`, prepares frame 0 while no timed read is active,
then issues one continuous `ROM_READN` for `BODY.DAT`.

```text
SECTOR         = 2048            # one Mode-1 CD sector
MAGIC          = "TTRC"          # 0x54545243
VERSION        = 16
FRAME_SECTORS  = 5               # maximum useful sectors in a routing entry
PAT            = 32              # one 8x8 4bpp tile pattern
BASE           = 1               # VRAM tile index = BASE + physical slot
```

The player accepts version 16. Bitmap controls insert one zero byte after an
odd-sized bitmap so the following 16-bit entry array is word-aligned. List
controls are already word-aligned. This pad does not change the run-suffix
alignment or the complete even control length.

## File layout

```text
HEADER.DAT
+--------------------------------------------------+  sector 0
| HEADER (1 sector, zero-padded)                   |
+--------------------------------------------------+
| BOOT_STAGE (paltab_sec sectors)                  |  PALTAB + optional VRAM sidecar
+--------------------------------------------------+
| ADPCM_TABLE (5 sectors)                          |  8,800 B lookup image
+--------------------------------------------------+
| WR0_PRELOAD (wr0_sec sectors)                    |  WordBuf0 patterns
+--------------------------------------------------+
| WR1_PRELOAD (wr1_sec sectors)                    |  WordBuf1 patterns
+--------------------------------------------------+
| DIC_PRELOAD (dic_sec sectors)                    |  DicBuf staging
+--------------------------------------------------+
| STARTUP_AUDIO (audio_preload_sec sectors)        |  one decoded chunk per sector
+--------------------------------------------------+
| FRAME 0 (f0_ctrl_sec + f0_pat_sec sectors)       |  control, then patterns
+--------------------------------------------------+
| ROUTING (routing_sec sectors)                    |  one byte per frame
+--------------------------------------------------+
| PREBUFFER (prebuf_sec sectors)                   |  frame-1 PrgBuf prefill
+--------------------------------------------------+

BODY.DAT
+--------------------------------------------------+  sector 0
| FRAME 1  (control, future payload, rate pad)     |
| ...                                              |
| FRAME nfr-1                                      |
+--------------------------------------------------+
```

The Sub CPU drains all of `HEADER.DAT` and writes STARTUP_AUDIO to wave RAM
while PCM is stopped. It expands frame 0 and hands the completed Word-RAM bank
to Main while `BODY.DAT` is still stopped. Main builds and displays frame 0,
then acknowledges BODY start. Sub starts `BODY.DAT`, pre-drains frame 1, and
only then begins timed handoffs. PCM starts with the first timed handoff.

Frame 0 has no timed delivery budget. Its visible name table uses exact target
patterns only. Remaining resident VRAM slots may receive future patterns
through the frame-0 cold suffix and the boot VRAM sidecar. Analysis reports
frame-0 Cold, Pre, DMA, Run, and Band as zero because they describe timed work.

The routing table is staged in the not-yet-active APPLY ring and copied into
the final 16 KiB of both physical 1M Word-RAM banks. The two copies are required
because the Sub-owned bank follows the display handoff while delivery may run
ahead.

Frame 0 patterns use the fixed 36 KiB boot-only staging area at PRG RAM
`0x71000..0x7A000`, which overlaps space that is not yet serving its timed
purpose. BODY does not start until frame 0 has been expanded, so this area is
independent of the timed PrgBuf and its jitter reserve.

## Header

The first 22 bytes are `struct ">4sHHHHHHHHH"`.

| Off | Size | Field | Meaning |
|---:|---:|---|---|
| 0 | 4 | magic | `"TTRC"` |
| 4 | 2 | version | exactly `16` |
| 6 | 2 | frames | total frame count (`nfr`) |
| 8 | 2 | tcols | tile-grid columns |
| 10 | 2 | trows | tile-grid rows |
| 12 | 2 | cells | `tcols * trows` |
| 14 | 2 | pool | resident VRAM tile-pool size |
| 16 | 2 | base | tile index of physical slot 0 |
| 18 | 2 | frame_sectors | maximum useful sectors per routing entry, `5` |
| 20 | 2 | n_seg | palette-segment count |

The next 16 bytes are `struct ">LLLL"`.

| Off | Size | Field | Meaning |
|---:|---:|---|---|
| 22 | 4 | prebuf_pat | number of Prg patterns prebuffered before frame 1 |
| 26 | 4 | routing_sec | sectors occupied by ROUTING |
| 30 | 4 | prebuf_sec | sectors occupied by PREBUFFER |
| 34 | 4 | ring_peak | peak physical PrgBuf use after delivery and before consumption |

The remaining fields are:

| Off | Size | Field | Meaning |
|---:|---:|---|---|
| 38 | 1 | display_mode | `0` H32, `1` H40, `2` mode4 |
| 39 | 1 | pad | zero |
| 40 | 4 | f0_ctrl_sec | FRAME 0 control sectors |
| 44 | 4 | f0_pat_sec | FRAME 0 pattern sectors |
| 48 | 4 | paltab_sec | BOOT_STAGE sectors |
| 52 | 2 | vsync_n | nearest display-VBlank interval |
| 54 | 2 | audio_bytes | even decoded samples per effective playback frame |
| 56 | 2 | fps_int | nominal content rate |
| 58 | 2 | audio_fd | RF5C164 frequency delta |
| 60 | 2 | audio_preload_sec | STARTUP_AUDIO sectors |
| 62 | 2 | features | feature bits described below |
| 64 | 128 | seg0 | frame-0 CRAM palette |
| 192 | 4 | player_signature | CRC-32 of bytes 0 through 63 |
| 196 | 20 | PSUP | pattern-supply extension when feature bit 3 is set |
| 216 | 1832 | pad | zero |

`vsync_n` is authoritative when `FEATURE_FIXED_N` is set. Otherwise it is a
display hint and delivery follows `75 / fps_int`. `audio_bytes` is normally
1472 at 15 fps, 920 at 24 fps, and 736 at 30 fps. A live ADPCM chunk occupies
`4 + audio_bytes / 2` bytes before alignment.

The player signature is generated from the same header sector as
`player_constants.inc` and baked into both player objects. A player/header
mismatch stops with a diagnostic.

### Feature bits

| Bit | Name | Meaning |
|---:|---|---|
| 0 | `FEATURE_COLD_RUNS` | every control ends with the cold-run suffix |
| 1 | `FEATURE_FIXED_N` | `vsync_n` controls display and CD cadence |
| 2 | reserved | must be clear |
| 3 | `FEATURE_PATTERN_SUPPLY` | source bits, PSUP, and boot preload regions are active |
| 4 | `FEATURE_SHADOW_UPDATE_LISTS` | completed shadow-update lists may occur |
| 5 | `FEATURE_VRAM_RAW_PREFETCH` | cold runs may load future Prg patterns without a same-frame name update |
| 6 | `FEATURE_DICBUF_INDEXED_RUNS` | DicBuf runs carry reusable dictionary indices |
| 7 | `FEATURE_BOOT_VRAM_SIDECAR` | BOOT_STAGE contains direct-to-VRAM records |

Unknown feature bits are rejected.

### PSUP extension

PSUP is `struct ">4s8H"`.

| Off | Size | Field | Meaning |
|---:|---:|---|---|
| 196 | 4 | magic | `"PSUP"` |
| 200 | 2 | version | exactly `2` |
| 202 | 2 | reserved | zero |
| 204 | 2 | wr0_patterns | WordBuf0 count, at most 880 |
| 206 | 2 | wr1_patterns | WordBuf1 count, at most 880 |
| 208 | 2 | dic_patterns | DicBuf count, at most 256 |
| 210 | 2 | wr0_sectors | WR0_PRELOAD sectors |
| 212 | 2 | wr1_sectors | WR1_PRELOAD sectors |
| 214 | 2 | dic_sectors | DIC_PRELOAD sectors |

Each sector count must equal `ceil(patterns * 32 / 2048)`. Generated player
constants freeze all six values.

The 128-byte CRAM block contains four palette lines of 16 Genesis colour words
(`0000BBB0GGG0RRR0`). Entry 0 of each line is transparent. Of the 60 usable
entries, the darkest colour is placed at line 0/index 1 and the brightest at
line 0/index 15 before quantisation. Only their positions change.

## Boot stage

BOOT_STAGE is 24 KiB and is copied to Word-RAM bank offset `+0xA000`. All
palette segments are stored consecutively at `+0xB000`, 128 bytes each. Main
copies them once to the 8 KiB PALTAB at `0xFFB000..0xFFD000`. The capacity is
64 segments. A timed palette switch reads PALTAB through the control block's
`pal` field, so CRAM data does not depend on same-frame CD delivery.

When feature bit 7 is set, a directory at `+0xAFC0` contains `"BVRM"` and three
big-endian `u16` record counts. Each record is `u16 physical_slot` followed by
one 32-byte pattern. Records occupy these preserved holes:

- `+0xA000..+0xAF00`
- the unused palette-table tail through `+0xD000`
- `+0xF000..+0x10000`

Main writes the records directly to unreferenced resident VRAM slots before Sub
starts BODY. The same sequence runs on movie restart.

## ADPCM table

Five sectors follow BOOT_STAGE. The first 8,800 bytes are immutable lookup data
and the remaining 1,440 bytes are zero.

| Offset | Size | Contents |
|---:|---:|---|
| 0 | 2,848 B | `u16 next_index_x32[89][16]` |
| 2,848 | 5,696 B | `s32 signed_delta[89][16]` |
| 8,544 | 256 B | predictor-high-byte to RF5C164 output lookup |

Sub copies exactly 2,200 longs to Word-RAM offset `+0x12800` in both physical
banks. The decoded PCM buffer is bank-local at `+0x14C00`.

## Pattern preload regions

WR0_PRELOAD, WR1_PRELOAD, and DIC_PRELOAD follow the ADPCM table in that order.
Each contains 32-byte patterns and zero padding to its declared sector boundary.

WordBuf0 and WordBuf1 each hold at most 880 different patterns at physical-bank
offset `+0x15200`. Even timed frames consume WordBuf0 and odd timed frames
consume WordBuf1. Their sequences advance monotonically and are never refilled.

DicBuf holds at most 256 reusable patterns. It is staged at Word RAM `+0xD000`
and copied once to Main RAM `0xFF6600..0xFF8600`. Controls address entries by
8-bit index.

## Startup audio

Each STARTUP_AUDIO sector begins with one decoded `audio_bytes` PCM chunk and is
zero-padded. Sub appends these source-leading chunks to wave RAM at `SYNC_LEAD`
while PCM is stopped. Live controls continue the shifted source order. PCM
starts after frame 0 is displayed, so source sample zero aligns with the first
visible movie frame.

## Routing table

ROUTING contains one byte per frame:

| Bits | Field | Meaning |
|---|---|---|
| 0-2 | `n_ctrl_sec` | control sectors at the start of the BODY slot |
| 3-5 | `total_sec` | useful control plus payload sectors |
| 6-7 | reserved | zero |

The byte is `(total_sec << 3) | n_ctrl_sec`; `n_pay_sec = total_sec -
n_ctrl_sec`. The player requires
`n_ctrl_sec <= total_sec <= FRAME_SECTORS` and
`routing_sec = ceil(nfr / 2048)`. Frame 0's entry and unused tail bytes are
zero. The 16 KiB resident copy supports at most 16,384 frames.

Control and payload are continuous streams split at sector boundaries. One
control sector may finish multiple future blocks, and payload normally
prefetches patterns for later frames. The physical schedule proves that:

- after a slot's control prefix arrives, its control block is complete in the
  APPLY ring;
- before a frame's control prefix is read, PREBUFFER and earlier BODY payload
  already contain every Prg pattern that frame consumes;
- control bytes, payload bytes, run descriptors, CRAM switches, and pad all fit
  the same physical-sector plan.

### Physical cadence

The physical slot size is:

```text
fsec = max(n_ctrl_sec + n_pay_sec, ratedelta - lead)
```

For fixed-N playback, packer and player use the reduced `1001*N/800` CD-sector
accumulator. N=2 produces 199 two-sector and 201 three-sector slots per cycle.
N=4 produces 199 five-sector and one six-sector slot; the sixth sector can only
be pad because the routing byte caps useful data at five sectors.

For delivery-paced playback:

```text
acc += 75
ratedelta = acc // fps_int
acc %= fps_int
```

`lead` increases by `fsec - ratedelta`. A necessary burst may exceed that
slot's fresh allowance; later light slots omit pad until the lead is repaid.
The packer fills unused rate allowance with future payload while PrgBuf space
and all deadlines permit it.

The pump applies back-pressure according to the next sector's destination:
APPLY space for control, PrgBuf space for payload, and no buffer check for pad.
The scheduler limits the pre-consumption PrgBuf peak because payload may arrive
before the current frame consumes its patterns.

## Prebuffer

PREBUFFER contains the first `prebuf_pat` Prg patterns for frames 1 onward.
It is loaded before playback and is capped below the physical delivery limit by
the frame-rate-specific jitter reserve: 382 KiB at 15 fps, 397 KiB at 24 fps,
and 402 KiB at 30 fps.

## BODY frame slot

Frames 1 through `nfr - 1` use:

```text
[ n_ctrl_sec sectors : control ]  next bytes of the control stream
[ n_pay_sec sectors  : payload ]  next bytes of the future Prg stream
[ pad to fsec sectors ]
```

Useful control bytes, useful payload bytes, and pad sum to `fsec * 2048`.
HEADER regions and frame 0 are not BODY delivery.

Payload patterns are 32-byte `pack_key` values: eight rows of four bytes, with
two 4-bit pixels per byte. Prg patterns consumed by a frame were delivered by
PREBUFFER or an earlier BODY slot. WordBuf and DicBuf loads have no BODY
payload.

### Control block

| Size | Field | Meaning |
|---:|---|---|
| 2 | total_len | complete even block length, including this word |
| 2 | frame_seq | expected frame sequence, low 16 bits |
| 2 | n_upd/format | bits 0-14 update count; bit 15 selects completed list |
| 2 | pal | PALTAB index plus one; zero means no CRAM change |
| variable | shadow updates | bitmap + optional alignment byte + 2-byte entries, or 4-byte completed items |
| `4 + audio_bytes/2` | audio | checkpoint then low-nibble-first IMA codes |
| 0/1 | audio pad | zero byte when needed for word alignment |
| 2 | n_runs | cold-run count |
| `n_runs * 4` | cold runs | source-aware physical transfer descriptors |

`frame_seq` detects a shifted control stream. Sector MSF continuity is checked
at the reader; a gap causes re-seek and exact re-read. A remaining sequence
mismatch holds the previous frame and increments the desync counter.

Bitmap updates use `ceil(cells / 8)` bytes, followed by a zero byte when that
size is odd. One 16-bit entry follows for each set bit in ascending cell order:

- bit 15: cold physical load;
- bits 13-14: palette line;
- bits 11-12: source (`0` Prg, `1` WordBuf, `2` DicBuf, `3` invalid);
- bits 0-10: VDP tile index, `base + physical_slot`.

The displayed name-table word is `entry & 0x67FF`.

A completed-list item contains `u16 shadow_byte_offset` and
`u16 final_name_entry`. The offset is even and below `cells * 2`; the final
entry contains no cold/source metadata. Frame 0 always uses bitmap controls.
The encoder selects a list only when it is faster and no larger than the
bitmap form, and the packer verifies that frozen choice.

The allocator's slot is the physical VRAM slot. Cold loads are consumed in
ascending physical-slot order. Run descriptors and all sector/deadline proofs
account for that exact order and byte cost.

A cold-run descriptor contains two words:

- word 0: physical slot in bits 0-10 and DicBuf index bits 3-7 in bits 11-15;
- word 1: count in bits 0-10, DicBuf index bits 0-2 in bits 11-13, and source in
  bits 14-15.

Non-Dic runs require zero index bits. A source change starts another run. A Dic
run also splits unless both slot and dictionary index remain consecutive.
Without raw prefetch, masked run counts equal cold update entries. With raw
prefetch, they equal all physical loads and may include future Prg patterns
without same-frame name updates.

Audio is always checkpointed IMA ADPCM. Each chunk begins with `s16 predictor`,
`u8 step_index`, and a reserved zero byte, followed by one low-nibble-first code
per sample. Sub decodes exactly `audio_bytes` samples into its bank-local
buffer.

## Player reconstruction

Sub copies exactly `total_len` bytes from the APPLY ring into Word RAM and
advances by that even length. Main optionally reloads CRAM from PALTAB, applies
source-aware physical pattern transfers to the resident VRAM pool, and updates
the shadow name table. Most reused cells require only a two-byte name entry.
Audio is decoded and written to the PCM chip. The two 1M Word-RAM banks swap at
frame boundaries.

<a id="jp"></a>

# HEADER.DAT / BODY.DAT バイナリ形式（TTRC）

`HEADER.DAT` と `BODY.DAT` は **Tile Texture Reuse Codec** のディスク上の
2ファイルです。`tools/pack_stream.py` が `tools/sim.py` の判断ログから生成し、
`boot/movieplay_sp.s` がストリーミング、`boot/movieplay_ip.s` が表示を担当します。

packer はディスク外の解析・回帰確認用に
`MOVIE.DAT = HEADER.DAT || BODY.DAT` も生成します。ディスクに収録するのは
`HEADER.DAT` と `BODY.DAT` だけです。

複数バイト整数はすべてビッグエンディアンです。各領域は sector 境界に揃えます。
Sub CPU は `HEADER.DAT` 全体を読み、時間制約のある読み出しを始める前に frame 0
を準備し、その後 `BODY.DAT` に対して1回の連続 `ROM_READN` を発行します。

```text
SECTOR         = 2048            # Mode-1 CD sector 1個
MAGIC          = "TTRC"          # 0x54545243
VERSION        = 16
FRAME_SECTORS  = 5               # routing entry内の有効sector上限
PAT            = 32              # 8x8 4bpp tile pattern 1個
BASE           = 1               # VRAM tile index = BASE + physical slot
```

player が受け付ける version は16です。bitmap controlではbitmapサイズが奇数byteの
ときにzero byteを1つ置き、後続の16-bit entry配列をword境界に揃えます。list
controlは元からword境界にあります。このpadはrun suffixの境界とcontrol全体の
偶数長を変えません。

## ファイル配置

```text
HEADER.DAT
+--------------------------------------------------+  sector 0
| HEADER (1 sector, zero-padded)                   |
+--------------------------------------------------+
| BOOT_STAGE (paltab_sec sectors)                  |  PALTAB + optional VRAM sidecar
+--------------------------------------------------+
| ADPCM_TABLE (5 sectors)                          |  8,800 B lookup image
+--------------------------------------------------+
| WR0_PRELOAD (wr0_sec sectors)                    |  WordBuf0 patterns
+--------------------------------------------------+
| WR1_PRELOAD (wr1_sec sectors)                    |  WordBuf1 patterns
+--------------------------------------------------+
| DIC_PRELOAD (dic_sec sectors)                    |  DicBuf staging
+--------------------------------------------------+
| STARTUP_AUDIO (audio_preload_sec sectors)        |  one decoded chunk per sector
+--------------------------------------------------+
| FRAME 0 (f0_ctrl_sec + f0_pat_sec sectors)       |  control, then patterns
+--------------------------------------------------+
| ROUTING (routing_sec sectors)                    |  one byte per frame
+--------------------------------------------------+
| PREBUFFER (prebuf_sec sectors)                   |  frame-1 PrgBuf prefill
+--------------------------------------------------+

BODY.DAT
+--------------------------------------------------+  sector 0
| FRAME 1  (control, future payload, rate pad)     |
| ...                                              |
| FRAME nfr-1                                      |
+--------------------------------------------------+
```

Sub CPUはPCM停止中に `HEADER.DAT` 全体を読み、STARTUP_AUDIOをwave RAMへ書きます。
`BODY.DAT` を止めたままframe 0を展開し、完成したWord-RAM bankをMainへ渡します。
Mainがframe 0を構築・表示してBODY開始を返答すると、Subは `BODY.DAT` を開始して
frame 1を先に読み切り、その後に時間制約のあるhandoffへ入ります。PCMは最初の
timed handoffで始まります。

frame 0にはtimed delivery budgetがありません。表示name tableは正確なtarget
patternだけを参照します。空いているresident VRAM slotにはframe-0 cold suffixと
boot VRAM sidecarを使って将来patternを置けます。frame 0のCold、Pre、DMA、Run、
Bandはtimed workではないため解析では0とします。

routing tableは未使用のAPPLY ringへ一時配置し、両方の物理1M Word-RAM bankの
末尾16 KiBへコピーします。表示handoffに応じてSub所有bankが変わり、deliveryが
先行し得るため、両bankに同一copyが必要です。

frame 0 patternはPRG RAM `0x71000..0x7A000` の固定36 KiB boot-only staging
領域を使います。この領域はtimed用途がまだ始まっていない空間と重なります。frame 0
展開完了までBODYを開始しないため、timed PrgBufとそのjitter reserveから独立しています。

## Header

先頭22 byteは `struct ">4sHHHHHHHHH"` です。

| Off | Size | Field | 意味 |
|---:|---:|---|---|
| 0 | 4 | magic | `"TTRC"` |
| 4 | 2 | version | 必ず `16` |
| 6 | 2 | frames | 総frame数（`nfr`） |
| 8 | 2 | tcols | tile gridの列数 |
| 10 | 2 | trows | tile gridの行数 |
| 12 | 2 | cells | `tcols * trows` |
| 14 | 2 | pool | resident VRAM tile poolの大きさ |
| 16 | 2 | base | physical slot 0のtile index |
| 18 | 2 | frame_sectors | routing entry当たりの有効sector上限、`5` |
| 20 | 2 | n_seg | palette segment数 |

次の16 byteは `struct ">LLLL"` です。

| Off | Size | Field | 意味 |
|---:|---:|---|---|
| 22 | 4 | prebuf_pat | frame 1より前にPrgBufへ置くpattern数 |
| 26 | 4 | routing_sec | ROUTINGのsector数 |
| 30 | 4 | prebuf_sec | PREBUFFERのsector数 |
| 34 | 4 | ring_peak | delivery後、消費前の物理PrgBuf最大使用量 |

残りのfieldは次の通りです。

| Off | Size | Field | 意味 |
|---:|---:|---|---|
| 38 | 1 | display_mode | `0` H32、`1` H40、`2` mode4 |
| 39 | 1 | pad | zero |
| 40 | 4 | f0_ctrl_sec | FRAME 0 control sector数 |
| 44 | 4 | f0_pat_sec | FRAME 0 pattern sector数 |
| 48 | 4 | paltab_sec | BOOT_STAGE sector数 |
| 52 | 2 | vsync_n | 最も近いdisplay VBlank間隔 |
| 54 | 2 | audio_bytes | 実効playback frameごとの偶数decoded sample数 |
| 56 | 2 | fps_int | nominal content rate |
| 58 | 2 | audio_fd | RF5C164 frequency delta |
| 60 | 2 | audio_preload_sec | STARTUP_AUDIO sector数 |
| 62 | 2 | features | 下記のfeature bit |
| 64 | 128 | seg0 | frame 0のCRAM palette |
| 192 | 4 | player_signature | byte 0〜63のCRC-32 |
| 196 | 20 | PSUP | feature bit 3がsetのときのpattern-supply extension |
| 216 | 1832 | pad | zero |

`FEATURE_FIXED_N` がsetなら `vsync_n` が正式なcadenceです。clearならdisplay
hintとして使い、deliveryは `75 / fps_int` に従います。`audio_bytes` は通常、
15 fpsで1472、24 fpsで920、30 fpsで736です。live ADPCM chunkはalignment前で
`4 + audio_bytes / 2` byteです。

player signatureは同じheader sectorから生成する `player_constants.inc` とともに
両player objectへ埋め込みます。playerとheaderが不一致なら診断表示で停止します。

### Feature bit

| Bit | Name | 意味 |
|---:|---|---|
| 0 | `FEATURE_COLD_RUNS` | 各control末尾にcold-run suffixがある |
| 1 | `FEATURE_FIXED_N` | `vsync_n` がdisplayとCD cadenceを決める |
| 2 | reserved | clearでなければならない |
| 3 | `FEATURE_PATTERN_SUPPLY` | source bit、PSUP、boot preload領域が有効 |
| 4 | `FEATURE_SHADOW_UPDATE_LISTS` | completed shadow-update listを使用できる |
| 5 | `FEATURE_VRAM_RAW_PREFETCH` | 同frameのname updateなしに将来Prg patternをcold runで置ける |
| 6 | `FEATURE_DICBUF_INDEXED_RUNS` | DicBuf runが再利用可能なdictionary indexを持つ |
| 7 | `FEATURE_BOOT_VRAM_SIDECAR` | BOOT_STAGEがdirect-to-VRAM recordを持つ |

未知のfeature bitは拒否します。

### PSUP extension

PSUPは `struct ">4s8H"` です。

| Off | Size | Field | 意味 |
|---:|---:|---|---|
| 196 | 4 | magic | `"PSUP"` |
| 200 | 2 | version | 必ず `2` |
| 202 | 2 | reserved | zero |
| 204 | 2 | wr0_patterns | WordBuf0数、最大880 |
| 206 | 2 | wr1_patterns | WordBuf1数、最大880 |
| 208 | 2 | dic_patterns | DicBuf数、最大256 |
| 210 | 2 | wr0_sectors | WR0_PRELOAD sector数 |
| 212 | 2 | wr1_sectors | WR1_PRELOAD sector数 |
| 214 | 2 | dic_sectors | DIC_PRELOAD sector数 |

各sector数は `ceil(patterns * 32 / 2048)` と一致する必要があります。生成する
player constantsが6値すべてを固定します。

128-byte CRAM blockは、16個のGenesis colour word
（`0000BBB0GGG0RRR0`）を持つpalette line 4本です。各lineのentry 0は透明です。
使用可能な60 entryのうち、最暗色をline 0/index 1、最明色をline 0/index 15へ
置いてから量子化します。色の集合は変えず、位置だけを変えます。

## Boot stage

BOOT_STAGEは24 KiBで、Word-RAM bank offset `+0xA000` へcopyします。全palette
segmentは `+0xB000` から128 byteずつ連続配置します。Mainは起動時に1回だけ
8 KiBのPALTAB（`0xFFB000..0xFFD000`）へcopyします。上限は64 segmentです。
timed palette switchはcontrol blockの `pal` でPALTABを参照するため、CRAM dataは
同じframeのCD deliveryに依存しません。

feature bit 7がsetなら、`+0xAFC0` のdirectoryに `"BVRM"` と3個のbig-endian
`u16` record countがあります。各recordは `u16 physical_slot` と32-byte pattern
です。recordは次の保存領域に配置します。

- `+0xA000..+0xAF00`
- palette tableの未使用末尾から `+0xD000`
- `+0xF000..+0x10000`

SubがBODYを開始する前に、Mainがrecordを未参照のresident VRAM slotへ直接書きます。
movie restartでも同じ手順を実行します。

## ADPCM table

BOOT_STAGEの直後に5 sector置きます。先頭8,800 byteは不変のlookup data、残り
1,440 byteはzeroです。

| Offset | Size | 内容 |
|---:|---:|---|
| 0 | 2,848 B | `u16 next_index_x32[89][16]` |
| 2,848 | 5,696 B | `s32 signed_delta[89][16]` |
| 8,544 | 256 B | predictor-high-byteからRF5C164 outputへのlookup |

Subは両方の物理bankのWord-RAM offset `+0x12800` へ2,200 longずつcopyします。
decoded PCM bufferは各bankの `+0x14C00` にあります。

## Pattern preload領域

ADPCM tableの後にWR0_PRELOAD、WR1_PRELOAD、DIC_PRELOADの順で置きます。各領域は
32-byte patternを持ち、宣言したsector境界までzero padします。

WordBuf0とWordBuf1は、それぞれ物理bank offset `+0x15200` に最大880個の異なる
patternを持ちます。偶数timed frameはWordBuf0、奇数timed frameはWordBuf1を
消費します。sequenceは単調に進み、補充しません。

DicBufは最大256個の再利用可能patternを持ちます。Word RAM `+0xD000` に一時配置し、
Main RAM `0xFF6600..0xFF8600` へ起動時に1回copyします。controlは8-bit indexで
entryを参照します。

## Startup audio

各STARTUP_AUDIO sectorは、先頭にdecoded `audio_bytes` PCM chunkを1個置き、残りを
zero padします。SubはPCM停止中にsource先頭のchunkを `SYNC_LEAD` からwave RAMへ
追記します。live controlは続くsource順を維持します。PCMはframe 0表示後に始まる
ため、source sample 0は最初のmovie表示frameと揃います。

## Routing table

ROUTINGはframeごとに1 byteです。

| Bits | Field | 意味 |
|---|---|---|
| 0-2 | `n_ctrl_sec` | BODY slot先頭のcontrol sector数 |
| 3-5 | `total_sec` | 有効なcontrol + payload sector数 |
| 6-7 | reserved | zero |

byte値は `(total_sec << 3) | n_ctrl_sec` で、
`n_pay_sec = total_sec - n_ctrl_sec` です。playerは
`n_ctrl_sec <= total_sec <= FRAME_SECTORS` と
`routing_sec = ceil(nfr / 2048)` を要求します。frame 0のentryと末尾の未使用byteは
zeroです。16 KiBのresident copyには最大16,384 frameが入ります。

controlとpayloadはsector境界で分割した連続streamです。1個のcontrol sectorが複数の
将来blockを完成させることがあり、payloadは通常、後のframeで使うpatternを先読み
します。物理scheduleは次を証明します。

- slotのcontrol prefix到着後、そのcontrol block全体がAPPLY ringにある
- frameのcontrol prefixを読む前に、PREBUFFERと過去のBODY payloadが、そのframeで
  消費する全Prg patternを届けている
- control byte、payload byte、run descriptor、CRAM switch、padが、同じ物理sector
  planに収まる

### 物理cadence

物理slot sizeは次の通りです。

```text
fsec = max(n_ctrl_sec + n_pay_sec, ratedelta - lead)
```

fixed-N playbackではpackerとplayerが `1001*N/800` を約分したCD-sector accumulator
を使います。N=2は1周期に2-sector slotを199個、3-sector slotを201個生成します。
N=4は5-sector slotを199個、6-sector slotを1個生成します。routing byteの有効data
上限は5 sectorなので、6個目はpadだけに使えます。

delivery-paced playbackでは次を使います。

```text
acc += 75
ratedelta = acc // fps_int
acc %= fps_int
```

`lead` は `fsec - ratedelta` だけ増えます。必要なburstはそのslotの新規allowanceを
超えられますが、後の軽いslotがpadを省いてleadを返済します。packerはPrgBuf空きと
全deadlineが許す範囲で未使用rate allowanceを将来payloadに置き換えます。

pumpのback-pressureは次sectorの行き先ごとに適用します。controlならAPPLY空き、
payloadならPrgBuf空き、padならbuffer checkなしです。payloadはcurrent frameが
patternを消費する前に届き得るため、schedulerは消費前のPrgBuf peakを制限します。

## Prebuffer

PREBUFFERはframe 1以降で最初に使う `prebuf_pat` 個のPrg patternを持ちます。playback
前に読み込み、物理delivery上限からframe rate別jitter reserveを引いた値に制限します。
15 fpsで382 KiB、24 fpsで397 KiB、30 fpsで402 KiBです。

## BODY frame slot

frame 1から `nfr - 1` までは次の形式です。

```text
[ n_ctrl_sec sectors : control ]  control streamの次のbyte列
[ n_pay_sec sectors  : payload ]  将来Prg streamの次のbyte列
[ pad to fsec sectors ]
```

有効control byte、有効payload byte、padの合計は `fsec * 2048` です。HEADER領域と
frame 0はBODY deliveryに含みません。

payload patternは32-byteの `pack_key` です。8行×4 byteで、各byteは4-bit pixelを
2個持ちます。frameが消費するPrg patternはPREBUFFERまたは過去のBODY slotから
届いています。WordBufとDicBuf loadにはBODY payloadがありません。

### Control block

| Size | Field | 意味 |
|---:|---|---|
| 2 | total_len | このwordを含むblock全体の偶数長 |
| 2 | frame_seq | 期待frame sequenceの下位16 bit |
| 2 | n_upd/format | bits 0-14はupdate数、bit 15はcompleted list |
| 2 | pal | PALTAB index + 1、zeroはCRAM変更なし |
| variable | shadow updates | bitmap + optional alignment byte + 2-byte entry、または4-byte completed item |
| `4 + audio_bytes/2` | audio | checkpointとlow-nibble-first IMA code |
| 0/1 | audio pad | word alignmentに必要なzero byte |
| 2 | n_runs | cold-run数 |
| `n_runs * 4` | cold runs | source-aware physical transfer descriptor |

`frame_seq` はcontrol streamのずれを検出します。readerはsector MSFの連続性を確認し、
gapがあればre-seekして正確に読み直します。それでもsequenceが一致しない場合は
前frameを保持し、desync counterを増やします。

bitmap updateは `ceil(cells / 8)` byteで、そのサイズが奇数ならzero byteを続けます。
set bitごとにcell昇順で16-bit entryを1個置きます。

- bit 15: cold physical load
- bits 13-14: palette line
- bits 11-12: source（`0` Prg、`1` WordBuf、`2` DicBuf、`3` invalid）
- bits 0-10: VDP tile index、`base + physical_slot`

表示name-table wordは `entry & 0x67FF` です。

completed-list itemは `u16 shadow_byte_offset` と `u16 final_name_entry` です。
offsetは偶数かつ `cells * 2` 未満で、final entryはcold/source metadataを持ちません。
frame 0は必ずbitmap controlを使います。encoderはbitmap形式以下のサイズで、かつ
高速な場合だけlistを選び、packerが固定済み選択を検証します。

allocatorのslotがそのまま物理VRAM slotです。cold loadはphysical slot昇順で消費
します。run descriptorと全sector・deadline proofは、その正確な順序とbyte costを
含めます。

cold-run descriptorは2 wordです。

- word 0: bits 0-10がphysical slot、bits 11-15がDicBuf indexのbits 3-7
- word 1: bits 0-10がcount、bits 11-13がDicBuf indexのbits 0-2、
  bits 14-15がsource

Dic以外のrunはindex bitがzeroでなければなりません。sourceが変われば別runです。
Dic runはslotとdictionary indexの両方が連続しなければ分割します。raw prefetchなし
ではmasked run count合計がcold update数です。raw prefetchありでは全physical load
数であり、同frameのname updateを持たない将来Prg patternも含められます。

audioは常にcheckpointed IMA ADPCMです。chunk先頭に `s16 predictor`、
`u8 step_index`、reserved zero byteを置き、sampleごとにlow-nibble-first codeを
続けます。Subはbank-local bufferへ正確に `audio_bytes` sampleをdecodeします。

## Playerでの再構築

SubはAPPLY ringから正確に `total_len` byteをWord RAMへcopyし、その偶数長だけcursorを
進めます。Mainは必要ならPALTABからCRAMを切り替え、source-aware physical pattern
transferをresident VRAM poolへ適用し、shadow name tableを更新します。再利用cellの
大半は2-byte name entryだけで済みます。audioをdecodeしてPCM chipへ書き、frame境界
で2つの1M Word-RAM bankを交換します。
