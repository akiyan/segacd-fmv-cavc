EN / [JP](#jp)

# Sega CD Constraint-Aware Video Codec binary format

`HEADER.DAT` and `BODY.DAT` are the two on-disc files of the **Sega CD
Constraint-Aware Video Codec**. `tools/pack_stream.py` writes them from the
`tools/sim.py` decision log. `boot/movieplay_sp.s` streams them and
`boot/movieplay_ip.s` displays them.

The packer also writes `MOVIE.DAT = HEADER.DAT || BODY.DAT` for off-disc
analysis and regression tools. The disc contains only `HEADER.DAT` and
`BODY.DAT`.

All multi-byte integers are big-endian. Every region is sector-aligned. The Sub
CPU reads the static `HEADER.DAT`, reads and stops at the finite untimed
`BODY.DAT` arm, prepares and hands off frame 0, then waits for Main to display
it before issuing one continuous `ROM_READN` for the timed BODY suffix.

```text
SECTOR         = 2048            # one Mode-1 CD sector
MAGIC          = "TTRC"          # 0x54545243
VERSION        = 20
FRAME_SECTORS  = 5               # maximum useful sectors in a routing entry
PAT            = 32              # one 8x8 4bpp tile pattern
BASE           = 1               # VRAM tile index = BASE + physical slot
```

The player accepts version 20. Bitmap controls insert one zero byte after an
odd-sized bitmap so the following 16-bit entry array is word-aligned. List
controls are already word-aligned. This pad does not change the run-suffix
alignment or the complete even control length.

## File layout

```text
HEADER.DAT
+--------------------------------------------------+  sector 0
| HEADER (1 sector, zero-padded)                   |
+--------------------------------------------------+
| BOOT_STAGE (paltab_sec sectors)                  |  optional boot-VRAM sidecar records
+--------------------------------------------------+
| DIC_PRELOAD (dic_sec sectors)                    |  DicBuf staging
+--------------------------------------------------+
| ADPCM_TABLE (5 sectors)                          |  8,800 B lookup image
+--------------------------------------------------+
| WR0_PRELOAD (wr0_sec sectors)                    |  WordBuf0 patterns
+--------------------------------------------------+
| WR1_PRELOAD (wr1_sec sectors)                    |  WordBuf1 patterns
+--------------------------------------------------+
| ROUTING (routing_sec sectors)                    |  one byte per frame
+--------------------------------------------------+
| PREBUFFER (prebuf_sec sectors)                   |  frame-1 PrgBuf prefill
+--------------------------------------------------+

BODY.DAT
+--------------------------------------------------+  sector 0
| ARM_AUDIO (audio_preload_sec sectors)            |  one decoded chunk per sector
+--------------------------------------------------+
| ARM_FRAME0 (f0_ctrl_sec + f0_pat_sec sectors)    |  control, then patterns
+--------------------------------------------------+
| FRAME 1  (control, future payload, rate pad)     |
| ...                                              |
| FRAME nfr-1                                      |
+--------------------------------------------------+
```

Sub first stages BOOT_STAGE and DicBuf, hands that bank to Main, and takes it
back after Main copies the persistent palette, dictionary, and optional VRAM
sidecar. This handoff is an intentional `HEADER.DAT` read boundary: Sub stops
the current read before giving the bank away and restarts the remaining
sectors at the exact next LBA after taking it back. Sub then installs the ADPCM
and WordBuf preloads.

The same `CMD_STREAM` command remains asserted for the rest of startup. Sub
reads the finite BODY arm, writes its decoded audio while PCM is stopped,
stops the read at the declared arm boundary, and expands frame 0. Sub hands the
completed frame-0 bank to Main with `STAT_READY` while the timed suffix remains
stopped. Main shows the black player-only frame -1 (`F=FFFF`) and builds frame
0. Once frame 0 is visible as `F=0000`, Main clears the original `CMD_STREAM`.
That edge launches the continuous timed BODY read, but PCM remains stopped
during the initial `ROM_READN` latency. Sub starts PCM as soon as the first
frame-1 control sector proves that the 75-sector/s stream is flowing, drains
the remainder of frame 1's physical slot, and then clears `STAT_READY`. The
slot remainder plus the next VBlank places frame 1 at its ordinary
source-audio position instead of charging the CD startup interval to audio.
This is the delayed acknowledgement of the original command, not a second
startup-only handshake.

Frame 0 has no timed delivery budget. Its visible name table uses exact target
patterns only. Remaining resident VRAM slots may receive future patterns
through the frame-0 cold suffix and the boot VRAM sidecar. Analysis reports
frame-0 Cold, Pre, DMA, Run, and Band as zero because they describe timed work.

The routing table is staged in the not-yet-active APPLY ring and copied into a
sector-rounded allocation at the end of both physical 1M Word-RAM banks. Its
resident size is `routing_sec * 2048`. The two copies are required because the
Sub-owned bank follows the display handoff while delivery may run ahead.

Frame 0 patterns use the fixed 36 KiB boot-only staging area at PRG RAM
`0x72000..0x7B000`, which overlaps space that is not yet serving its timed
purpose. The finite BODY arm is stopped before frame 0 is expanded, and the
timed BODY suffix starts only after frame 0 is visible, so this area is
independent of the timed PrgBuf and its jitter reserve.

## Header

The first 22 bytes are `struct ">4sHHHHHHHHH"`.

| Off | Size | Field | Meaning |
|---:|---:|---|---|
| 0 | 4 | magic | `"TTRC"` |
| 4 | 2 | version | exactly `20` |
| 6 | 2 | frames | total frame count (`nfr`) |
| 8 | 2 | tcols | tile-grid columns |
| 10 | 2 | trows | tile-grid rows |
| 12 | 2 | cells | `tcols * trows` |
| 14 | 2 | pool | resident VRAM tile-pool size |
| 16 | 2 | base | tile index of physical slot 0 |
| 18 | 2 | frame_sectors | maximum useful sectors per routing entry, `5` |
| 20 | 2 | n_seg | palette-segment count, at most 16 (informational; the player's embedded paltab.bin is authoritative) |

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
| 40 | 4 | f0_ctrl_sec | BODY-arm FRAME 0 control sectors |
| 44 | 4 | f0_pat_sec | BODY-arm FRAME 0 pattern sectors |
| 48 | 4 | paltab_sec | BOOT_STAGE sectors |
| 52 | 2 | vsync_n | nearest display-VBlank interval |
| 54 | 2 | audio_bytes | even decoded samples per effective playback frame |
| 56 | 2 | fps_int | nominal content rate |
| 58 | 2 | audio_fd | RF5C164 frequency delta |
| 60 | 2 | audio_preload_sec | BODY-arm decoded-audio sectors |
| 62 | 2 | features | feature bits described below |
| 64 | 128 | pad | zero |
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
| 8 | `FEATURE_WORDBUF_RING` | routing entries may stage leading payload sectors to the parity WordBuf ring |

Unknown feature bits are rejected.

### PSUP extension

PSUP is `struct ">4s9H"`.

| Off | Size | Field | Meaning |
|---:|---:|---|---|
| 196 | 4 | magic | `"PSUP"` |
| 200 | 2 | version | exactly `3` |
| 202 | 2 | reserved | zero |
| 204 | 2 | wr0_patterns | WordBuf0 count, at most the generated Wr0 capacity |
| 206 | 2 | wr1_patterns | WordBuf1 count, at most the generated Wr1 capacity |
| 208 | 2 | dic_patterns | DicBuf count, at most 512 |
| 210 | 2 | wr0_sectors | WR0_PRELOAD sectors |
| 212 | 2 | wr1_sectors | WR1_PRELOAD sectors |
| 214 | 2 | dic_sectors | DIC_PRELOAD sectors |
| 216 | 2 | cold_cap | timed cold-pattern limit used to derive the Word-RAM map |

Each sector count must equal `ceil(patterns * 32 / 2048)`. Generated player
constants freeze the preload values, routing allocation, compact-tail offsets,
and parity-specific WordBuf starts, ends, and capacities.

## Player-embedded palette tables

Palette data does not ride the disc. The packer writes two build inputs
beside the split stream and the Main-IP player image embeds both in its
transient `.startup` section, copying them to Main RAM at entry before
generated code reuses that area:

- `paltab.bin` — all segment palettes, `n_seg * 128` bytes, copied to the
  2 KiB PALTAB at `0xFFB200..0xFFB9FF`. The capacity is a fixed 16 segments.
  Each 128-byte block contains four palette lines of 16 Genesis colour words
  (`0000BBB0GGG0RRR0`). Entry 0 of each line is transparent. Of the 60 usable
  entries, the darkest colour is placed at line 0/index 1 and the brightest at
  line 0/index 15 before quantisation. Only their positions change. The
  initial CRAM image is segment 0 (frame 0 always displays segment 0), and
  loop restarts reload it.
- `palidx.bin` — the palette-switch index PALIDX, 64 bytes: sixteen
  `(u16 switch_frame, u16 segment)` entries covering at most 15 switches,
  terminated by a `0xFFFF` frame sentinel that also fills unused entries.
  Switch frames are strictly ascending and segment numbers advance one at a
  time. The player copies the table to `0xFFBA00..0xFFBA3F` and performs each
  CRAM total-replace when its frame counter reaches the next entry, so
  palette data and switch timing are both independent of same-frame CD
  delivery.

## Boot stage

BOOT_STAGE is 24 KiB and is copied to Word-RAM bank offset `+0x0000`. It
carries only the optional boot-VRAM sidecar records.

When feature bit 7 is set, a directory at `+0x0FC0` contains `"BVRM"` and three
big-endian `u16` record counts. Each record is `u16 physical_slot` followed by
one 32-byte pattern. Records occupy these fixed preserved holes:

- `+0x0000..+0x0F00`
- `+0x1000..+0x3000`
- `+0x5000..+0x6000`

DicBuf is staged at `+0x6000..+0x9FFF`. Main copies the DicBuf and sidecar
records before returning the bank to Sub. Frame 0 and WordBuf may then reuse
these temporary ranges. `HEADER.DAT` is stopped at this handoff and resumed
from the exact first unread sector after the bank returns. The same sequence
runs on movie restart.

## ADPCM table

Five sectors follow DIC_PRELOAD. The first 8,800 bytes are immutable lookup
data. The current 216-byte position-fixed Sub boot extension follows in
existing padding, and the remaining 1,224 bytes are zero.

| Offset | Size | Contents |
|---:|---:|---|
| 0 | 2,848 B | `u16 next_index_x32[89][16]` |
| 2,848 | 5,696 B | `s32 signed_delta[89][16]` |
| 8,544 | 256 B | predictor-high-byte to RF5C164 output lookup |
| 8,800 | 216 B | boot-only Sub ADPCM-install, routing-prepare, and queue-initialization extension |
| 9,016 | 1,224 B | zero padding |

The first 88 extension bytes are copied to `0x76800` and run before routing is
staged. With a routing preload of at most 8 KiB, the second entry remains
outside the routing bytes and runs in place at staged address `0x7D2B8` after
prebuffer completes. Longer-route builds copy all 216 bytes first and run that
entry at `0x76858`.

Sub keeps the disc bytes unchanged. It copies the 2,848-byte next-index table
to PRG-RAM `0x0C000`, the 256-byte output table to `0x0CB20`, and the
5,696-byte signed-delta table to its generated fixed-tail offset in both
physical banks. The decoded PCM buffer is Sub-owned PRG-RAM at
`0x08000..0x085FF`. The generated Word-RAM tail retains the complete table and
PCM reservations, including the unused index/output holes, so player-only A/B
builds retain identical preload capacities and stream bytes.

## Pattern preload regions

WR0_PRELOAD and WR1_PRELOAD follow the ADPCM table. DIC_PRELOAD precedes it so
Main can consume all temporary front-of-bank data in the first boot handoff.
Each preload contains 32-byte patterns and zero padding to its declared sector
boundary.

WordBuf0 and WordBuf1 have generated, parity-specific starts and capacities.
Wr0 starts after the frame-0 `O_LOADS` envelope; Wr1 starts after the timed
cold/run envelope. Both capacities are rounded down to complete preload
sectors. Even timed frames consume WordBuf0 and odd timed frames consume
WordBuf1. Each preload is the initial content of that parity's WordBuf ring.
When the stream carries the WordBuf-ring feature, a slot's leading
`n_word_sec` payload sectors append 64 patterns each to the arriving frame's
parity ring; write and read cursors both advance forward and wrap at the
declared capacity, and the packer's replay proves every refill sector commits
before its frame begins expanding.

DicBuf holds at most 512 reusable patterns. It is staged at Word RAM
`+0x6000..+0x9FFF` and copied once to Main RAM `0xFFBA40..0xFFFA3F`. Run
descriptors address entries by a 9-bit index whose top bit rides the run
source field.

## BODY arm audio

Each ARM_AUDIO sector at the start of `BODY.DAT` begins with one decoded
`audio_bytes` PCM chunk and is zero-padded. Sub appends these source-leading
chunks to wave RAM at `SYNC_LEAD` while PCM is stopped. Live controls continue
the shifted source order. Frame 0 may already be visible while the first timed
`ROM_READN` is starting, but PCM remains stopped. Source sample zero starts
when the first frame-1 control sector arrives; the rest of that physical slot
positions frame 1 one source frame later.

## Routing table

ROUTING contains one byte per frame:

| Bits | Field | Meaning |
|---|---|---|
| 0-2 | `n_ctrl_sec` | control sectors at the start of the BODY slot; bit 2 is the WordBuf-4 escape, which narrows the control count to bits 0-1 |
| 3-5 | `total_sec` | useful control plus payload sectors |
| 6-7 | `n_word_sec` | leading payload sectors staged to the arriving frame's parity WordBuf ring (0-3; with the escape set these bits carry 3 and the staged count is 4) |

The byte is `(n_word_field << 6) | (total_sec << 3) | n_ctrl_field`;
`n_pay_sec = total_sec - n_ctrl_sec` and `n_word_sec <= n_pay_sec`. A stream
without the WordBuf-ring feature always encodes `n_word_sec = 0`. The player
requires
`n_ctrl_sec <= total_sec <= FRAME_SECTORS` and
`routing_sec = ceil(nfr / 2048)`. Frame 0's entry and unused tail bytes are
zero. The resident copy uses exactly `routing_sec` sectors and supports at most
16,384 frames.

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

`lead` increases by `fsec - ratedelta`. The accumulator is shared with the
player, but a qualified fixed-cadence stream keeps its peak at zero. A slot
cannot exceed its fresh allowance because the resulting elapsed display delay
cannot be recovered by a later light slot. Before image decisions, the encoder
limits every control/Prg prefix by both cumulative CD-1x time and the
routing-byte ceiling. The exact finite-PrgBuf schedule repeats the proof. The
packer fills same-slot unused allowance with future payload only while PrgBuf
space and all deadlines permit it.

The pump applies back-pressure according to the next sector's destination:
APPLY space for control, PrgBuf space for payload, and no buffer check for pad.
The scheduler limits the pre-consumption PrgBuf peak because payload may arrive
before the current frame consumes its patterns.

## Prebuffer

PREBUFFER contains the first `prebuf_pat` Prg patterns for frames 1 onward.
It is loaded before playback. Both PREBUFFER and the exact scheduled-delivery
ceiling use 378 KiB at 15 fps, 393 KiB at 24 fps, and 398 KiB at 30 fps. The
remaining 40/25/20 KiB to the 418 KiB observation boundary is reserved for
live sector-arrival variation.

## BODY frame slot

Frames 1 through `nfr - 1` use:

```text
[ n_ctrl_sec sectors : control ]  next bytes of the control stream
[ n_pay_sec sectors  : payload ]  next bytes of the future Prg stream
[ pad to fsec sectors ]
```

Useful control bytes, useful payload bytes, and pad sum to `fsec * 2048`.
The untimed BODY arm, including frame 0, is not part of timed BODY delivery.

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

Run source `0` is Prg and `1` is WordBuf. Sources `2` and `3` are both DicBuf:
`2` addresses dictionary entries 0..255 and `3` addresses entries 256..511, so
the descriptor carries a 9-bit index without growing. A Dic run never crosses
that 256-entry block boundary; the encoder splits it there.

Non-Dic runs require zero index bits. A source change starts another run. A Dic
run also splits unless both slot and dictionary index remain consecutive.
Without raw prefetch, masked run counts equal cold update entries. With raw
prefetch, they equal all physical loads and may include future Prg patterns
without same-frame name updates.

Audio is always checkpointed IMA ADPCM. Each chunk begins with `s16 predictor`,
`u8 step_index`, and a reserved zero byte, followed by one low-nibble-first code
per sample. Sub decodes exactly `audio_bytes` samples into its PRG-RAM work
buffer.

## Player reconstruction

Sub copies exactly `total_len` bytes from the APPLY ring into Word RAM and
advances by that even length. Main reloads CRAM from PALTAB whenever the
player-embedded PALIDX table's next switch frame has been reached, applies
source-aware physical pattern transfers to the resident VRAM pool, and updates
the shadow name table. Most reused cells require only a two-byte name entry.
Audio is decoded and written to the PCM chip. The two 1M Word-RAM banks swap at
frame boundaries.

<a id="jp"></a>

# Sega CD Constraint-Aware Video Codec バイナリ形式

`HEADER.DAT` と `BODY.DAT` は **Sega CD Constraint-Aware Video Codec** の
ディスク上の2ファイルです。`tools/pack_stream.py` が `tools/sim.py` の判断ログから
生成し、`boot/movieplay_sp.s` がストリーミング、`boot/movieplay_ip.s` が表示を
担当します。

packer はディスク外の解析・回帰確認用に
`MOVIE.DAT = HEADER.DAT || BODY.DAT` も生成します。ディスクに収録するのは
`HEADER.DAT` と `BODY.DAT` だけです。

複数バイト整数はすべてビッグエンディアンです。各領域は sector 境界に揃えます。
Sub CPUはstaticな `HEADER.DAT` を読み、有限でuntimedな `BODY.DAT` armだけを読んで
停止し、frame 0を準備してMainへ渡します。Mainがframe 0を表示するまで待ってから、
timed BODY suffixへ1回の連続 `ROM_READN`を発行します。

```text
SECTOR         = 2048            # Mode-1 CD sector 1個
MAGIC          = "TTRC"          # 0x54545243
VERSION        = 20
FRAME_SECTORS  = 5               # routing entry内の有効sector上限
PAT            = 32              # 8x8 4bpp tile pattern 1個
BASE           = 1               # VRAM tile index = BASE + physical slot
```

player が受け付ける version は20です。bitmap controlではbitmapサイズが奇数byteの
ときにzero byteを1つ置き、後続の16-bit entry配列をword境界に揃えます。list
controlは元からword境界にあります。このpadはrun suffixの境界とcontrol全体の
偶数長を変えません。

## ファイル配置

```text
HEADER.DAT
+--------------------------------------------------+  sector 0
| HEADER (1 sector, zero-padded)                   |
+--------------------------------------------------+
| BOOT_STAGE (paltab_sec sectors)                  |  optional boot-VRAM sidecar records
+--------------------------------------------------+
| DIC_PRELOAD (dic_sec sectors)                    |  DicBuf staging
+--------------------------------------------------+
| ADPCM_TABLE (5 sectors)                          |  8,800 B lookup image
+--------------------------------------------------+
| WR0_PRELOAD (wr0_sec sectors)                    |  WordBuf0 patterns
+--------------------------------------------------+
| WR1_PRELOAD (wr1_sec sectors)                    |  WordBuf1 patterns
+--------------------------------------------------+
| ROUTING (routing_sec sectors)                    |  one byte per frame
+--------------------------------------------------+
| PREBUFFER (prebuf_sec sectors)                   |  frame-1 PrgBuf prefill
+--------------------------------------------------+

BODY.DAT
+--------------------------------------------------+  sector 0
| ARM_AUDIO (audio_preload_sec sectors)            |  one decoded chunk per sector
+--------------------------------------------------+
| ARM_FRAME0 (f0_ctrl_sec + f0_pat_sec sectors)    |  control, then patterns
+--------------------------------------------------+
| FRAME 1  (control, future payload, rate pad)     |
| ...                                              |
| FRAME nfr-1                                      |
+--------------------------------------------------+
```

Subは最初にBOOT_STAGEとDicBufをstageし、そのbankをMainへ渡します。Mainがpersistent
palette、dictionary、任意のVRAM sidecarをcopyすると、Subはbankを取り戻します。この
handoffは意図した `HEADER.DAT` read境界です。Subはbankを渡す前にreadを停止し、bankを
取り戻した後に正確な次LBAから残りのsectorを再開します。続いてADPCMとWordBuf preloadを
配置します。

以後のstartupでは同じ `CMD_STREAM` commandをassertしたままにします。Subは有限の
BODY armを読み、PCM停止中にdecoded audioをwave RAMへ書き、宣言済みarm境界でreadを
停止してframe 0を展開します。完成したframe-0 bankを `STAT_READY` でMainへ渡しますが、
この時点ではtimed suffixを停止したままにします。Mainはplayer-onlyの黒いframe -1
（`F=FFFF`）を表示し、frame 0を構築します。frame 0が `F=0000` として表示された時点で
Mainが元の `CMD_STREAM` をclearします。このedgeでtimed BODYの連続readを起動しますが、
最初の `ROM_READN` latency中はPCMを停止したままにします。最初のframe-1 control
sectorが到着して75 sector/sのstream開始を確認した時点でPCMを開始し、frame 1の
physical slotの残りをdrainしてから `STAT_READY` をclearします。slotの残り時間と次の
VBlankにより、CD起動待ちを音声へ加算せず、frame 1を通常のsource-audio位置へ置きます。
これは元commandへの遅延acknowledgementであり、2個目のstartup専用handshakeではありません。

frame 0にはtimed delivery budgetがありません。表示name tableは正確なtarget
patternだけを参照します。空いているresident VRAM slotにはframe-0 cold suffixと
boot VRAM sidecarを使って将来patternを置けます。frame 0のCold、Pre、DMA、Run、
Bandはtimed workではないため解析では0とします。

routing tableは未使用のAPPLY ringへ一時配置し、両方の物理1M Word-RAM bank末尾の
sector丸めallocationへcopyします。Resident sizeは `routing_sec * 2048` です。表示
handoffに応じてSub所有bankが変わり、deliveryが先行し得るため、両bankに同一copyが
必要です。

frame 0 patternはPRG RAM `0x72000..0x7B000` の固定36 KiB boot-only staging
領域を使います。この領域はtimed用途がまだ始まっていない空間と重なります。有限の
BODY armはframe 0展開前に停止し、timed BODY suffixはframe 0表示後にだけ開始する
ため、timed PrgBufとそのjitter reserveから独立しています。

## Header

先頭22 byteは `struct ">4sHHHHHHHHH"` です。

| Off | Size | Field | 意味 |
|---:|---:|---|---|
| 0 | 4 | magic | `"TTRC"` |
| 4 | 2 | version | 必ず `20` |
| 6 | 2 | frames | 総frame数（`nfr`） |
| 8 | 2 | tcols | tile gridの列数 |
| 10 | 2 | trows | tile gridの行数 |
| 12 | 2 | cells | `tcols * trows` |
| 14 | 2 | pool | resident VRAM tile poolの大きさ |
| 16 | 2 | base | physical slot 0のtile index |
| 18 | 2 | frame_sectors | routing entry当たりの有効sector上限、`5` |
| 20 | 2 | n_seg | palette segment数、最大16（情報提供のみ。正典はplayer内蔵のpaltab.bin） |

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
| 40 | 4 | f0_ctrl_sec | BODY-arm FRAME 0 control sector数 |
| 44 | 4 | f0_pat_sec | BODY-arm FRAME 0 pattern sector数 |
| 48 | 4 | paltab_sec | BOOT_STAGE sector数 |
| 52 | 2 | vsync_n | 最も近いdisplay VBlank間隔 |
| 54 | 2 | audio_bytes | 実効playback frameごとの偶数decoded sample数 |
| 56 | 2 | fps_int | nominal content rate |
| 58 | 2 | audio_fd | RF5C164 frequency delta |
| 60 | 2 | audio_preload_sec | BODY-arm decoded-audio sector数 |
| 62 | 2 | features | 下記のfeature bit |
| 64 | 128 | pad | zero |
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
| 8 | `FEATURE_WORDBUF_RING` | routing entryが先頭payload sectorをparity WordBuf ringへstageし得る |

未知のfeature bitは拒否します。

### PSUP extension

PSUPは `struct ">4s9H"` です。

| Off | Size | Field | 意味 |
|---:|---:|---|---|
| 196 | 4 | magic | `"PSUP"` |
| 200 | 2 | version | 必ず `3` |
| 202 | 2 | reserved | zero |
| 204 | 2 | wr0_patterns | WordBuf0数、generated Wr0 capacity以下 |
| 206 | 2 | wr1_patterns | WordBuf1数、generated Wr1 capacity以下 |
| 208 | 2 | dic_patterns | DicBuf数、最大512 |
| 210 | 2 | wr0_sectors | WR0_PRELOAD sector数 |
| 212 | 2 | wr1_sectors | WR1_PRELOAD sector数 |
| 214 | 2 | dic_sectors | DIC_PRELOAD sector数 |
| 216 | 2 | cold_cap | Word-RAM map導出に使うtimed cold-pattern上限 |

各sector数は `ceil(patterns * 32 / 2048)` と一致する必要があります。生成する
player constantsがpreload値、routing allocation、compact-tail offset、parity別WordBufの
開始・終了・容量を固定します。

## Player内蔵palette table

palette dataはdiscに載せません。packerがsplit streamの隣に2つのビルド入力を
書き、Main-IP player imageが両方を一時`.startup` sectionへ内蔵します。生成
codeがその領域を再利用する前に、entry直後にMain RAMへcopyします。

- `paltab.bin` — 全segment palette。`n_seg * 128` byteで、2 KiBのPALTAB
  （`0xFFB200..0xFFB9FF`）へcopyします。上限は固定16 segmentです。各128-byte
  blockは、16個のGenesis colour word（`0000BBB0GGG0RRR0`）を持つpalette line
  4本です。各lineのentry 0は透明です。使用可能な60 entryのうち、最暗色を
  line 0/index 1、最明色をline 0/index 15へ置いてから量子化します。色の集合は
  変えず、位置だけを変えます。初期CRAM imageはsegment 0で（frame 0は必ず
  segment 0を表示）、loop再開時にも再loadします。
- `palidx.bin` — palette切替indexのPALIDX、64 byteです。16個の
  `(u16 switch_frame, u16 segment)` entryで最大15切替を持ち、`0xFFFF` frame
  番兵で終端します（未使用entryも番兵で埋めます）。switch frameは厳密に昇順で、
  segment番号は1ずつ進みます。playerは表を `0xFFBA00..0xFFBA3F` へcopyし、
  frame counterが次のentryへ達したときにCRAM総入替を実行します。palette data
  と切替タイミングの両方が同じframeのCD deliveryに依存しません。

## Boot stage

BOOT_STAGEは24 KiBで、Word-RAM bank offset `+0x0000` へcopyします。内容は
optionalなboot-VRAM sidecar recordのみです。

feature bit 7がsetなら、`+0x0FC0` のdirectoryに `"BVRM"` と3個のbig-endian
`u16` record countがあります。各recordは `u16 physical_slot` と32-byte pattern
です。recordは次の固定保存領域に配置します。

- `+0x0000..+0x0F00`
- `+0x1000..+0x3000`
- `+0x5000..+0x6000`

DicBufは `+0x6000..+0x9FFF` にstageします。MainはDicBufとsidecar recordを
copyしてからbankをSubへ返します。その後、frame 0とWordBufがtemporary rangeを
再利用できます。このhandoffで `HEADER.DAT` を停止し、bank返却後に最初の未読sector
から正確に再開します。movie restartでも同じ手順を実行します。

## ADPCM table

DIC_PRELOADの直後に5 sector置きます。先頭8,800 byteは不変のlookup dataです。
現在216-byteのposition-fixed Sub boot extensionを既存paddingへ続け、残り1,224 byteは
zeroです。

| Offset | Size | 内容 |
|---:|---:|---|
| 0 | 2,848 B | `u16 next_index_x32[89][16]` |
| 2,848 | 5,696 B | `s32 signed_delta[89][16]` |
| 8,544 | 256 B | predictor-high-byteからRF5C164 outputへのlookup |
| 8,800 | 216 B | boot-only Sub ADPCM-install・routing-prepare・queue-initialization extension |
| 9,016 | 1,224 B | zero padding |

extensionの先頭88 byteを`0x76800`へcopyし、routingをstageする前に実行します。
routing preloadが8 KiB以下なら、第2入口はrouting byteの外側に残るため、prebuffer
完了後にstage address `0x7D2B8`でそのまま実行します。長いroutingのbuildは先に216
byte全体をcopyし、第2入口を`0x76858`で実行します。

Subはdisc byteを変更せず、2,848-byte next-index tableをPRG-RAM `0x0C000`、
256-byte output tableを`0x0CB20`、5,696-byte signed-delta tableを両physical
bankのgenerated fixed-tail offsetへcopyします。Decoded PCM bufferはSub所有PRG-RAM
`0x08000..0x085FF`にあります。Generated Word-RAM tailは未使用のindex/output holeを
含むtable全体とPCMの予約を保持するため、player-only A/B buildのpreload容量とstream
byteを同一にします。

## Pattern preload領域

ADPCM tableの後にWR0_PRELOADとWR1_PRELOADを置きます。DIC_PRELOADは最初のboot
handoffでfront-of-bankのtemporary dataをすべてMainが消費できるようADPCMより前に
置きます。各preloadは32-byte patternを持ち、宣言したsector境界までzero padします。

WordBuf0とWordBuf1はgenerated parity別startとcapacityを持ちます。Wr0はframe-0
`O_LOADS` envelopeの直後、Wr1はtimed cold/run envelopeの直後から始まります。
両capacityとも完全なpreload sectorへ切り下げます。偶数timed frameはWordBuf0、
奇数timed frameはWordBuf1を消費します。各preloadは、そのparityのWordBuf ringの
初期内容です。WordBuf-ring featureを持つstreamでは、slot先頭の `n_word_sec`
payload sectorが到着frameのparity ringへ64 patternずつ追記されます。writeと
readのcursorはともに前進のみで宣言capacityでwrapし、packerのreplayは全refill
sectorがそのframeの展開開始前にcommitされることを証明します。

DicBufは最大512個の再利用可能patternを持ちます。Word RAM `+0x6000..+0x9FFF` に
一時配置し、Main RAM `0xFFBA40..0xFFFA3F` へ起動時に1回copyします。run descriptor
は9-bit indexでentryを参照し、その最上位bitはrun source fieldに載ります。

## BODY arm音声

`BODY.DAT` 先頭の各ARM_AUDIO sectorは、先頭にdecoded `audio_bytes` PCM chunkを
1個置き、残りをzero padします。SubはPCM停止中にsource先頭のchunkを
`SYNC_LEAD` からwave RAMへ追記します。live controlは続くsource順を維持します。
最初のtimed `ROM_READN` 起動中にはframe 0が先に表示されることがありますが、PCMは停止した
ままです。最初のframe-1 control sector到着時にsource sample 0を開始し、そのphysical
slotの残り時間でframe 1を1 source frame後へ配置します。

## Routing table

ROUTINGはframeごとに1 byteです。

| Bits | Field | 意味 |
|---|---|---|
| 0-2 | `n_ctrl_sec` | BODY slot先頭のcontrol sector数。bit 2はWordBuf-4 escapeで、この場合control数はbits 0-1 |
| 3-5 | `total_sec` | 有効なcontrol + payload sector数 |
| 6-7 | `n_word_sec` | 到着frameのparity WordBuf ringへstageする先頭payload sector数（0〜3。escape設定時はこのbitsに3を置き、実stage数は4） |

byte値は `(n_word_field << 6) | (total_sec << 3) | n_ctrl_field` で、
`n_pay_sec = total_sec - n_ctrl_sec`、`n_word_sec <= n_pay_sec` です。
WordBuf-ring featureを持たないstreamは常に `n_word_sec = 0` をencodeします。
playerは
`n_ctrl_sec <= total_sec <= FRAME_SECTORS` と
`routing_sec = ceil(nfr / 2048)` を要求します。frame 0のentryと末尾の未使用byteは
zeroです。Resident copyは正確に `routing_sec` sectorを使い、最大16,384 frameに
対応します。

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

`lead` は `fsec - ratedelta` だけ増えます。このaccumulatorはplayerと共有しますが、
認定済みfixed-cadence streamではpeakをzeroに保ちます。slotが新規allowanceを超えると
経過済みの表示遅延になり、後の軽いslotでは取り戻せないためです。encoderは画像決定前に、
control/Prgの全prefixを累積CD-1x時間とrouting-byte上限の両方で制限し、有限PrgBufを
含む正確なscheduleでも同じproofを繰り返します。packerはPrgBuf空きと全deadlineが
許す範囲で、同じslot内の未使用allowanceだけを将来payloadに置き換えます。

pumpのback-pressureは次sectorの行き先ごとに適用します。controlならAPPLY空き、
payloadならPrgBuf空き、padならbuffer checkなしです。payloadはcurrent frameが
patternを消費する前に届き得るため、schedulerは消費前のPrgBuf peakを制限します。

## Prebuffer

PREBUFFERはframe 1以降で最初に使う `prebuf_pat` 個のPrg patternを持ちます。playback
前に読み込みます。PREBUFFERと正確なscheduled-delivery上限は15 fpsで378 KiB、
24 fpsで393 KiB、30 fpsで398 KiBです。418 KiB観測境界までの40/25/20 KiBは
liveのsector到着変動専用です。

## BODY frame slot

frame 1から `nfr - 1` までは次の形式です。

```text
[ n_ctrl_sec sectors : control ]  control streamの次のbyte列
[ n_pay_sec sectors  : payload ]  将来Prg streamの次のbyte列
[ pad to fsec sectors ]
```

有効control byte、有効payload byte、padの合計は `fsec * 2048` です。frame 0を含む
untimed BODY armはtimed BODY deliveryに含みません。

payload patternは32-byteの `pack_key` です。8行×4 byteで、各byteは4-bit pixelを
2個持ちます。frameが消費するPrg patternはPREBUFFERまたは過去のBODY slotから
届いています。WordBufとDicBuf loadにはBODY payloadがありません。

### Control block

| Size | Field | 意味 |
|---:|---|---|
| 2 | total_len | このwordを含むblock全体の偶数長 |
| 2 | frame_seq | 期待frame sequenceの下位16 bit |
| 2 | n_upd/format | bits 0-14はupdate数、bit 15はcompleted list |
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

run source `0` はPrg、`1` はWordBufです。`2` と `3` はともにDicBufで、`2` は
dictionary entry 0..255、`3` は256..511を参照します。descriptorはサイズを変えずに
9-bit indexを運びます。Dic runはこの256-entry block境界を跨ぎません（encoderが
そこで分割します）。

Dic以外のrunはindex bitがzeroでなければなりません。sourceが変われば別runです。
Dic runはslotとdictionary indexの両方が連続しなければ分割します。raw prefetchなし
ではmasked run count合計がcold update数です。raw prefetchありでは全physical load
数であり、同frameのname updateを持たない将来Prg patternも含められます。

audioは常にcheckpointed IMA ADPCMです。chunk先頭に `s16 predictor`、
`u8 step_index`、reserved zero byteを置き、sampleごとにlow-nibble-first codeを
続けます。SubはPRG-RAM work bufferへ正確に `audio_bytes` sampleをdecodeします。

## Playerでの再構築

SubはAPPLY ringから正確に `total_len` byteをWord RAMへcopyし、その偶数長だけcursorを
進めます。Mainはplayer内蔵PALIDX表の次回switch frameへ達していればPALTABからCRAMを
切り替え、source-aware physical pattern transferをresident VRAM poolへ適用し、
shadow name tableを更新します。再利用cellの
大半は2-byte name entryだけで済みます。audioをdecodeしてPCM chipへ書き、frame境界
で2つの1M Word-RAM bankを交換します。
