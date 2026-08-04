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
MAGIC          = "CAVC"          # 0x43415643
FRAME_SECTORS  = 5               # maximum useful sectors in a routing entry
PAT            = 32              # one 8x8 4bpp tile pattern
BASE           = 1               # VRAM tile index = BASE + physical slot
```

The magic is identifying data; the runtime player does not branch on it.
Bitmap controls insert one zero byte after an odd-sized bitmap so the following
16-bit entry array is word-aligned. List controls are already word-aligned. This
pad does not change the run-suffix alignment or the complete even control length.

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
stopped. Main shows the black player-only frame -1 (`frame=FFFF`) and builds
frame 0. Once frame 0 is visible as `frame=0000`, Main clears the original `CMD_STREAM`.
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

The first 20 bytes are `struct ">4sHHHHHHHH"`. There is no independent
format-version field.

| Off | Size | Field | Meaning |
|---:|---:|---|---|
| 0 | 4 | magic | `"CAVC"` |
| 4 | 2 | frames | total frame count (`nfr`) |
| 6 | 2 | tcols | tile-grid columns |
| 8 | 2 | trows | tile-grid rows |
| 10 | 2 | cells | `tcols * trows` |
| 12 | 2 | pool | resident VRAM tile-pool size |
| 14 | 2 | base | tile index of physical slot 0 |
| 16 | 2 | frame_sectors | maximum useful sectors per routing entry, `5` |
| 18 | 2 | n_seg | palette-segment count, at most 16 (informational; the player's embedded paltab.bin is authoritative) |

The next 16 bytes are `struct ">LLLL"`.

| Off | Size | Field | Meaning |
|---:|---:|---|---|
| 20 | 4 | prebuf_pat | number of Prg patterns prebuffered before frame 1 |
| 24 | 4 | routing_sec | sectors occupied by ROUTING |
| 28 | 4 | prebuf_sec | sectors occupied by PREBUFFER |
| 32 | 4 | ring_peak | peak physical PrgBuf use after delivery and before consumption |

The remaining fields are:

| Off | Size | Field | Meaning |
|---:|---:|---|---|
| 36 | 1 | display_mode | `0` H32, `1` H40, `2` mode4 |
| 37 | 1 | pad | zero |
| 38 | 4 | f0_ctrl_sec | BODY-arm FRAME 0 control sectors |
| 42 | 4 | f0_pat_sec | BODY-arm FRAME 0 pattern sectors |
| 46 | 4 | paltab_sec | BOOT_STAGE sectors |
| 50 | 2 | vsync_n | first authoritative display-VBlank interval, or a hint when bit 1 is clear |
| 52 | 2 | audio_bytes | even decoded samples per effective playback frame |
| 54 | 2 | fps_int | nominal content rate |
| 56 | 2 | audio_fd | RF5C164 frequency delta |
| 58 | 2 | audio_preload_sec | BODY-arm decoded-audio sectors |
| 60 | 2 | features | feature bits described below |
| 62 | 130 | pad | zero |
| 192 | 4 | player_signature | CRC-32 of contract bytes 4 through 61; magic is excluded |
| 196 | 26 | PSUP | pattern-supply extension when feature bit 3 is set |
| 222 | 1826 | pad | zero |

When `FEATURE_VBLANK_CADENCE` is set, `fps_int` selects a qualified repeating
schedule and `vsync_n` must equal its first interval: 15 fps is `(4)`, 24 fps
is `(2, 3)`, 30 fps is `(2)`, and 60 fps is `(1)`. Frame 1 uses the first
interval. When the bit is clear, `vsync_n` is only a display hint and delivery
follows `75 / fps_int`. `audio_bytes` is normally 1472 at 15 fps, 920 at 24
fps, and 736 at 30 fps. A live ADPCM chunk occupies `4 + audio_bytes / 2`
bytes before alignment.

The player signature is generated from the same header sector as
`player_constants.inc` and baked into both player objects. A player/header
mismatch stops with a diagnostic.

### Feature bits

| Bit | Name | Meaning |
|---:|---|---|
| 0 | `FEATURE_COLD_RUNS` | every control ends with the cold-run suffix |
| 1 | `FEATURE_VBLANK_CADENCE` | `fps_int` and `vsync_n` select an authoritative repeating display/CD cadence |
| 2 | reserved | must be clear |
| 3 | `FEATURE_PATTERN_SUPPLY` | source bits, PSUP, and boot preload regions are active |
| 4 | `FEATURE_SHADOW_UPDATE_LISTS` | completed shadow-update lists may occur |
| 5 | `FEATURE_VRAM_RAW_PREFETCH` | cold runs may load future Prg patterns without a same-frame name update |
| 6 | `FEATURE_DICBUF_INDEXED_RUNS` | DicBuf runs carry reusable dictionary indices |
| 7 | `FEATURE_BOOT_VRAM_SIDECAR` | BOOT_STAGE contains direct-to-VRAM records |
| 8 | `FEATURE_WORDBUF_RING` | routing entries may stage leading payload sectors to the parity WordBuf ring |

Unknown feature bits are rejected.

### PSUP extension

PSUP is `struct ">4s11H"`.

| Off | Size | Field | Meaning |
|---:|---:|---|---|
| 196 | 4 | magic | `"PSUP"` |
| 200 | 2 | version | exactly `4` |
| 202 | 2 | reserved | zero |
| 204 | 2 | wr0_patterns | WordBuf0 count, at most the generated Wr0 capacity |
| 206 | 2 | wr1_patterns | WordBuf1 count, at most the generated Wr1 capacity |
| 208 | 2 | dic_patterns | DicBuf count, at most 512 |
| 210 | 2 | wr0_sectors | WR0_PRELOAD sectors |
| 212 | 2 | wr1_sectors | WR1_PRELOAD sectors |
| 214 | 2 | dic_sectors | DIC_PRELOAD sectors |
| 216 | 2 | cold_cap | timed cold-pattern limit used to derive the Word-RAM map |
| 218 | 2 | wr0_load_bytes | exact even-frame `O_LOADS v2` peak, excluding the four-byte output header |
| 220 | 2 | wr1_load_bytes | exact odd-frame `O_LOADS v2` peak, excluding the four-byte output header |

Each sector count must equal `ceil(patterns * 32 / 2048)`. Generated player
constants freeze the preload values, routing allocation, compact-tail offsets,
and parity-specific WordBuf starts, ends, and capacities. The packer
independently recomputes both `O_LOADS v2` peaks from the materialized runs and
rejects a mismatch with the decision log.

## Player-embedded palette tables

Ordinary segment-palette data does not ride the disc. The packer writes two build inputs
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

Typed fade controls are separate from PALIDX. Each selected fade frame carries
one exact 128-byte CRAM image inside its timed control. Main copies that image
to `M-FCRAM` before returning Word RAM, then performs the full CRAM replacement
atomically with the display flip. These inline images do not occupy PALTAB or
PALIDX entries.

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
data. The 940-byte position-fixed Sub boot extension follows in existing
padding, and the remaining 500 bytes are zero.

| Offset | Size | Contents |
|---:|---:|---|
| 0 | 2,848 B | `u16 next_index_x32[89][16]` |
| 2,848 | 5,696 B | `s32 signed_delta[89][16]` |
| 8,544 | 256 B | predictor-high-byte to RF5C164 output lookup |
| 8,800 | 940 B | boot-only Sub table install, PCM initialization, routing preparation, and queue initialization extension |
| 9,740 | 500 B | zero padding |

The first 88 extension bytes are copied to `0x76800` and run before routing is
staged. With a routing preload of at most 8 KiB, the second entry remains
outside the routing bytes and runs in place at staged address `0x7D2B8` after
prebuffer completes. Longer-route builds copy all 940 bytes first and run that
entry at `0x76858`. The fixed third entry at extension offset `+0x300` runs in
place at `0x7D560` to clear and initialize wave RAM before routing can reuse
the staged area.

Sub keeps the disc bytes unchanged. It copies the 2,848-byte next-index table
to PRG-RAM `0x07400`, the 256-byte output table to `0x09600`, and the
5,696-byte signed-delta table to PRG-RAM `0x0C000`. Each table is installed
once; no ADPCM lookup or PCM reservation remains in either Word-RAM bank. The
decoded PCM buffer is Sub-owned PRG-RAM at `0x08000..0x085FF`.

## Pattern preload regions

WR0_PRELOAD and WR1_PRELOAD follow the ADPCM table. DIC_PRELOAD precedes it so
Main can consume all temporary front-of-bank data in the first boot handoff.
Each preload contains 32-byte patterns and zero padding to its declared sector
boundary.

WordBuf0 and WordBuf1 have generated, parity-specific starts and capacities.
Each start first reserves that parity's exact `O_LOADS v2` peak:
`32 * inline Prg patterns + 22 * runs`, recomputed over every even or odd
frame. Only the residual space becomes WordBuf, rounded down to complete
preload sectors. Even timed frames consume WordBuf0 and odd timed frames
consume WordBuf1. Each preload is the initial content of that parity's WordBuf
ring.
When the stream carries the WordBuf-ring feature, a slot's leading
`n_word_sec` payload sectors append 64 patterns each to the arriving frame's
parity ring; write and read cursors both advance forward and wrap at the
declared capacity, and the packer's replay proves every refill sector commits
before its frame begins expanding. A compact Wr source run that reaches the
declared physical ring end is split there into adjacent descriptors before the
control block is written. The VRAM destination remains contiguous, while the
extra descriptor, `O_LOADS v2` record, DMA first-word repair, and control bytes
are included in every capacity and work model. No linear Word-RAM DMA source
range crosses the ring end.

DicBuf holds at most 512 reusable patterns. It is staged at Word RAM
`+0x6000..+0x9FFF` and copied once to Main RAM `0xFFBA40..0xFFFA3F`. Run
descriptors address entries by a 9-bit index whose top bit rides the run
source field.

### Player `O_LOADS v2` handoff

The four-byte cold-run descriptors in `BODY.DAT` remain compact transport
data. They are not the Main-facing run plan. While expanding a frame, Sub
writes `O_NRUN` and `O_NLOAD` at bank offsets `+0` and `+2`, then writes
interleaved 22-byte records from `O_LOADS` at `+4`:

| Record offset | Size | Meaning |
|---:|---:|---|
| `+0` | 2 | DMA length in words |
| `+2`, `+4` | 2 each | VDP registers 93 and 94 |
| `+6` | 4 | destination VDP command |
| `+10` | 2 | raw destination byte address |
| `+12`, `+14`, `+16` | 2 each | VDP source registers 95, 96, and 97 |
| `+18` | 4 | resolved raw source address |

A Prg record is followed immediately by `count * 32` inline pattern bytes,
and its raw source points to those bytes in Main's Word-RAM view. Wr and Dic
records carry no inline payload and point directly at WordBuf or DicBuf.
Main consumes this single cursor in place, including split DMA continuation;
it does not construct a Main-RAM run table.

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

For a one-interval cadence, packer and player use the reduced `1001*N/800`
CD-sector accumulator. N=2 produces 199 two-sector and 201 three-sector slots
per cycle. N=4 produces 199 five-sector and one six-sector slot; the sixth
sector can only be pad because the routing byte caps useful data at five
sectors.

The 24 fps cadence starts with two VBlanks for frame 1 and alternates `(2, 3)`.
Its CD accumulator uses matching numerators `(2002, 3003)` with modulus 800,
in the same phase. This is 24000/1001 fps over each two-frame cycle. Using only
the average `1001/320` would incorrectly give the first short interval more
physical CD time than it has.

The Main display clock treats `(2, 3)` as a phase target rather than resetting
the clock after a late flip. Whole-VBlank lateness is repaid only by changing a
later nominal three-VBlank display interval to two; the physical CD steps stay
in their original frame phase. The late display has already delivered the
extra sectors needed for that catch-up. This recovery never grants a slot
bytes from a future physical deadline.

For delivery-paced playback:

```text
acc += 75
ratedelta = acc // fps_int
acc %= fps_int
```

`lead` increases by `fsec - ratedelta`. The accumulator is shared with the
player, but a qualified VBlank-cadence stream keeps its peak at zero. A slot
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
ceiling use 374 KiB at 15 fps, 389 KiB at 24 fps, and 394 KiB at 30 fps. The
remaining 40/25/20 KiB to the 414 KiB observation boundary is reserved for
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
| 2 | n_upd/format | bit 15 selects a completed list; bits 14-13 are frame type; bits 12-0 are the update count |
| variable | normal shadow updates | type 0: bitmap + optional alignment byte + 2-byte entries, or 4-byte completed items |
| 128 | inline CRAM | type 1/2: four complete 16-word CRAM lines; replaces the shadow-update field |
| `4 + audio_bytes/2` | audio | checkpoint then low-nibble-first IMA codes |
| 0/1 | audio pad | zero byte when needed for word alignment |
| 2 | n_runs | cold-run count |
| `n_runs * 4` | cold runs | source-aware physical transfer descriptors |

`frame_seq` detects a shifted control stream. Sector MSF continuity is checked
at the reader; a gap causes re-seek and exact re-read. A remaining sequence
mismatch holds the previous frame and increments the desync counter.

Frame type 0 is normal, 1 is fade-in, 2 is fade-out, and 3 is reserved. Types
1 and 2 require an update count of zero and a clear list bit. They leave the
name table unchanged while replacing all 64 CRAM words from the inline image.
Audio decoding and the cold-run suffix still run, so future patterns can be
prefetched during a static fade. The two fade directions have the same player
operation; the tag preserves the encoder's detected direction for validation
and analysis.

The run descriptors immediately follow `n_runs`. Sub resolves them into
`O_LOADS v2` while preserving its CDC polling cadence. Main schedules those
expanded records at runtime with the guarded residual VBlank budget. Every
pattern run uses DMA. Any run crossing the current residual is split at that
boundary and continues at the next fresh VBlank head. The stream carries no
encoded VBlank boundary.

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
MAGIC          = "CAVC"          # 0x43415643
FRAME_SECTORS  = 5               # routing entry内の有効sector上限
PAT            = 32              # 8x8 4bpp tile pattern 1個
BASE           = 1               # VRAM tile index = BASE + physical slot
```

magicは識別用dataであり、runtime playerはmagicで分岐しません。bitmap controlでは
bitmapサイズが奇数byteのときにzero byteを1つ置き、後続の16-bit entry配列をword
境界に揃えます。list controlは元からword境界にあります。このpadはrun suffixの
境界とcontrol全体の偶数長を変えません。

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
（`frame=FFFF`）を表示し、frame 0を構築します。frame 0が `frame=0000` として表示された時点で
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

先頭20 byteは `struct ">4sHHHHHHHH"` です。独立したformat version fieldは
ありません。

| Off | Size | Field | 意味 |
|---:|---:|---|---|
| 0 | 4 | magic | `"CAVC"` |
| 4 | 2 | frames | 総frame数（`nfr`） |
| 6 | 2 | tcols | tile gridの列数 |
| 8 | 2 | trows | tile gridの行数 |
| 10 | 2 | cells | `tcols * trows` |
| 12 | 2 | pool | resident VRAM tile poolの大きさ |
| 14 | 2 | base | physical slot 0のtile index |
| 16 | 2 | frame_sectors | routing entry当たりの有効sector上限、`5` |
| 18 | 2 | n_seg | palette segment数、最大16（情報提供のみ。正典はplayer内蔵のpaltab.bin） |

次の16 byteは `struct ">LLLL"` です。

| Off | Size | Field | 意味 |
|---:|---:|---|---|
| 20 | 4 | prebuf_pat | frame 1より前にPrgBufへ置くpattern数 |
| 24 | 4 | routing_sec | ROUTINGのsector数 |
| 28 | 4 | prebuf_sec | PREBUFFERのsector数 |
| 32 | 4 | ring_peak | delivery後、消費前の物理PrgBuf最大使用量 |

残りのfieldは次の通りです。

| Off | Size | Field | 意味 |
|---:|---:|---|---|
| 36 | 1 | display_mode | `0` H32、`1` H40、`2` mode4 |
| 37 | 1 | pad | zero |
| 38 | 4 | f0_ctrl_sec | BODY-arm FRAME 0 control sector数 |
| 42 | 4 | f0_pat_sec | BODY-arm FRAME 0 pattern sector数 |
| 46 | 4 | paltab_sec | BOOT_STAGE sector数 |
| 50 | 2 | vsync_n | 最初の正式なdisplay VBlank間隔。bit 1 clear時はhint |
| 52 | 2 | audio_bytes | 実効playback frameごとの偶数decoded sample数 |
| 54 | 2 | fps_int | nominal content rate |
| 56 | 2 | audio_fd | RF5C164 frequency delta |
| 58 | 2 | audio_preload_sec | BODY-arm decoded-audio sector数 |
| 60 | 2 | features | 下記のfeature bit |
| 62 | 130 | pad | zero |
| 192 | 4 | player_signature | contract byte 4〜61のCRC-32。magicは対象外 |
| 196 | 26 | PSUP | feature bit 3がsetのときのpattern-supply extension |
| 222 | 1826 | pad | zero |

`FEATURE_VBLANK_CADENCE` がsetなら、`fps_int` が認定済みの反復scheduleを選び、
`vsync_n` はその最初の間隔と一致しなければなりません。15 fpsは`(4)`、24 fpsは
`(2, 3)`、30 fpsは`(2)`、60 fpsは`(1)`で、frame 1が最初の間隔を使います。
bitがclearなら`vsync_n`はdisplay hintだけになり、deliveryは`75 / fps_int`に
従います。`audio_bytes`は通常、15 fpsで1472、24 fpsで920、30 fpsで736です。
live ADPCM chunkはalignment前で`4 + audio_bytes / 2` byteです。

player signatureは同じheader sectorから生成する `player_constants.inc` とともに
両player objectへ埋め込みます。playerとheaderが不一致なら診断表示で停止します。

### Feature bit

| Bit | Name | 意味 |
|---:|---|---|
| 0 | `FEATURE_COLD_RUNS` | 各control末尾にcold-run suffixがある |
| 1 | `FEATURE_VBLANK_CADENCE` | `fps_int`と`vsync_n`が正式な反復display/CD cadenceを選ぶ |
| 2 | reserved | clearでなければならない |
| 3 | `FEATURE_PATTERN_SUPPLY` | source bit、PSUP、boot preload領域が有効 |
| 4 | `FEATURE_SHADOW_UPDATE_LISTS` | completed shadow-update listを使用できる |
| 5 | `FEATURE_VRAM_RAW_PREFETCH` | 同frameのname updateなしに将来Prg patternをcold runで置ける |
| 6 | `FEATURE_DICBUF_INDEXED_RUNS` | DicBuf runが再利用可能なdictionary indexを持つ |
| 7 | `FEATURE_BOOT_VRAM_SIDECAR` | BOOT_STAGEがdirect-to-VRAM recordを持つ |
| 8 | `FEATURE_WORDBUF_RING` | routing entryが先頭payload sectorをparity WordBuf ringへstageし得る |

未知のfeature bitは拒否します。

### PSUP extension

PSUPは `struct ">4s11H"` です。

| Off | Size | Field | 意味 |
|---:|---:|---|---|
| 196 | 4 | magic | `"PSUP"` |
| 200 | 2 | version | 必ず `4` |
| 202 | 2 | reserved | zero |
| 204 | 2 | wr0_patterns | WordBuf0数、generated Wr0 capacity以下 |
| 206 | 2 | wr1_patterns | WordBuf1数、generated Wr1 capacity以下 |
| 208 | 2 | dic_patterns | DicBuf数、最大512 |
| 210 | 2 | wr0_sectors | WR0_PRELOAD sector数 |
| 212 | 2 | wr1_sectors | WR1_PRELOAD sector数 |
| 214 | 2 | dic_sectors | DIC_PRELOAD sector数 |
| 216 | 2 | cold_cap | Word-RAM map導出に使うtimed cold-pattern上限 |
| 218 | 2 | wr0_load_bytes | 4-byte output headerを除く、偶数frameの正確な`O_LOADS v2`ピーク |
| 220 | 2 | wr1_load_bytes | 4-byte output headerを除く、奇数frameの正確な`O_LOADS v2`ピーク |

各sector数は `ceil(patterns * 32 / 2048)` と一致する必要があります。生成する
player constantsがpreload値、routing allocation、compact-tail offset、parity別WordBufの
開始・終了・容量を固定します。Packerはmaterialize済みrunから2つの
`O_LOADS v2`ピークを独立再計算し、decision logとの不一致を拒否します。

## Player内蔵palette table

通常のsegment palette dataはdiscに載せません。packerがsplit streamの隣に2つのbuild入力を
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

typed fade controlはPALIDXと別物です。選択した各fade frameは、timed control内に
正確な128-byte CRAM imageを1個持ちます。MainはWord RAMを返却する前にそのimageを
`M-FCRAM`へcopyし、display flipと同じ原子的な処理でCRAMを総入替します。
これらのinline imageはPALTABやPALIDX entryを使いません。

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
940-byteのposition-fixed Sub boot extensionを既存paddingへ続け、残り500 byteは
zeroです。

| Offset | Size | 内容 |
|---:|---:|---|
| 0 | 2,848 B | `u16 next_index_x32[89][16]` |
| 2,848 | 5,696 B | `s32 signed_delta[89][16]` |
| 8,544 | 256 B | predictor-high-byteからRF5C164 outputへのlookup |
| 8,800 | 940 B | boot-only Sub table install・PCM initialization・routing preparation・queue initialization extension |
| 9,740 | 500 B | zero padding |

extensionの先頭88 byteを`0x76800`へcopyし、routingをstageする前に実行します。
routing preloadが8 KiB以下なら、第2入口はrouting byteの外側に残るため、prebuffer
完了後にstage address `0x7D2B8`でそのまま実行します。長いroutingのbuildは先に940
byte全体をcopyし、第2入口を`0x76858`で実行します。Extension offset `+0x300`の
固定第3入口は、routingがstaged areaを再利用する前に`0x7D560`で実行し、wave RAMを
clear・初期化します。

Subはdisc byteを変更せず、2,848-byte next-index tableをPRG-RAM `0x07400`、
256-byte output tableを`0x09600`、5,696-byte signed-delta tableをPRG-RAM
`0x0C000`へcopyします。各tableは1回だけinstallし、Word-RAM bankにはADPCM
lookupもPCM予約も残しません。Decoded PCM bufferはSub所有PRG-RAM
`0x08000..0x085FF`にあります。

## Pattern preload領域

ADPCM tableの後にWR0_PRELOADとWR1_PRELOADを置きます。DIC_PRELOADは最初のboot
handoffでfront-of-bankのtemporary dataをすべてMainが消費できるようADPCMより前に
置きます。各preloadは32-byte patternを持ち、宣言したsector境界までzero padします。

WordBuf0とWordBuf1はgenerated parity別startとcapacityを持ちます。各startは
そのparityの正確な`O_LOADS v2`ピーク
`32 * inline Prg patterns + 22 * runs`を全偶数または奇数frameから再計算して
先に予約します。残余だけがWordBufとなり、完全なpreload sectorへ切り下げます。
偶数timed frameはWordBuf0、奇数timed frameはWordBuf1を消費します。各preloadは、
そのparityのWordBuf ringの初期内容です。WordBuf-ring featureを持つstreamでは、
slot先頭の `n_word_sec`
payload sectorが到着frameのparity ringへ64 patternずつ追記されます。writeと
readのcursorはともに前進のみで宣言capacityでwrapし、packerのreplayは全refill
sectorがそのframeの展開開始前にcommitされることを証明します。CompactなWr
source runが宣言済みphysical ring末尾へ達する場合、control blockを書き出す前に
その位置で隣接descriptorへ分割します。VRAM destinationは連続したままで、追加の
descriptor、`O_LOADS v2` record、DMA first-word repair、control bytesを全capacity
およびwork modelへ含めます。LinearなWord-RAM DMA source rangeがring末尾を
またぐことはありません。

DicBufは最大512個の再利用可能patternを持ちます。Word RAM `+0x6000..+0x9FFF` に
一時配置し、Main RAM `0xFFBA40..0xFFFA3F` へ起動時に1回copyします。run descriptor
は9-bit indexでentryを参照し、その最上位bitはrun source fieldに載ります。

### Player `O_LOADS v2` handoff

`BODY.DAT`の4-byte cold-run descriptorはcompactなtransport dataのままであり、
Main向けrun計画ではありません。Subはframe展開時にbank offset `+0`と`+2`へ
`O_NRUN`、`O_NLOAD`を書き、`+4`の`O_LOADS`から22-byte recordをinterleaveして
書きます。

| Record offset | Size | 意味 |
|---:|---:|---|
| `+0` | 2 | word単位DMA length |
| `+2`, `+4` | 各2 | VDP register 93、94 |
| `+6` | 4 | destination VDP command |
| `+10` | 2 | raw destination byte address |
| `+12`, `+14`, `+16` | 各2 | VDP source register 95、96、97 |
| `+18` | 4 | 解決済みraw source address |

Prg recordの直後には`count * 32` byteのinline patternが続き、raw sourceはMainの
Word-RAM viewでそのbyte列を指します。WrとDic recordはinline payloadを持たず、
WordBufまたはDicBufを直接指します。Mainはsplit DMA継続を含め、この単一cursorを
in-placeで消費し、Main-RAM run tableを構築しません。

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

単一間隔cadenceではpackerとplayerが`1001*N/800`を約分したCD-sector accumulator
を使います。N=2は1周期に2-sector slotを199個、3-sector slotを201個生成します。
N=4は5-sector slotを199個、6-sector slotを1個生成します。routing byteの有効data
上限は5 sectorなので、6個目はpadだけに使えます。

24 fps cadenceはframe 1を2 VBlankで始め、`(2, 3)`を交互に繰り返します。CD
accumulatorも同じ位相でmodulus 800、numerator `(2002, 3003)`を使います。2 frame
周期の実効速度は24000/1001 fpsです。平均`1001/320`だけを使うと、最初の短い
間隔へ実在しないCD時間を与えるため使用しません。

Main display clockはlate flip後にclockをresetせず、`(2, 3)`を位相targetとして扱います。
VBlank単位の遅れは、後の名目3 VBlank display intervalを2へ変える場合だけ返済し、物理CD
stepは元のframe位相を維持します。Late display中にcatch-upに必要な追加sectorはすでに
配送済みです。このrecoveryが将来の物理deadlineからslot byteを前借りすることはありません。

delivery-paced playbackでは次を使います。

```text
acc += 75
ratedelta = acc // fps_int
acc %= fps_int
```

`lead` は `fsec - ratedelta` だけ増えます。このaccumulatorはplayerと共有しますが、
認定済みVBlank-cadence streamではpeakをzeroに保ちます。slotが新規allowanceを超えると
経過済みの表示遅延になり、後の軽いslotでは取り戻せないためです。encoderは画像決定前に、
control/Prgの全prefixを累積CD-1x時間とrouting-byte上限の両方で制限し、有限PrgBufを
含む正確なscheduleでも同じproofを繰り返します。packerはPrgBuf空きと全deadlineが
許す範囲で、同じslot内の未使用allowanceだけを将来payloadに置き換えます。

pumpのback-pressureは次sectorの行き先ごとに適用します。controlならAPPLY空き、
payloadならPrgBuf空き、padならbuffer checkなしです。payloadはcurrent frameが
patternを消費する前に届き得るため、schedulerは消費前のPrgBuf peakを制限します。

## Prebuffer

PREBUFFERはframe 1以降で最初に使う `prebuf_pat` 個のPrg patternを持ちます。playback
前に読み込みます。PREBUFFERと正確なscheduled-delivery上限は15 fpsで374 KiB、
24 fpsで389 KiB、30 fpsで394 KiBです。414 KiB観測境界までの40/25/20 KiBは
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
| 2 | n_upd/format | bit 15はcompleted list、bits 14-13はframe type、bits 12-0はupdate数 |
| variable | 通常shadow updates | type 0: bitmap + optional alignment byte + 2-byte entry、または4-byte completed item |
| 128 | inline CRAM | type 1/2: 完全な16-word CRAM line×4。shadow-update fieldの代わりに置く |
| `4 + audio_bytes/2` | audio | checkpointとlow-nibble-first IMA code |
| 0/1 | audio pad | word alignmentに必要なzero byte |
| 2 | n_runs | cold-run数 |
| `n_runs * 4` | cold runs | source-aware physical transfer descriptor |

`frame_seq` はcontrol streamのずれを検出します。readerはsector MSFの連続性を確認し、
gapがあればre-seekして正確に読み直します。それでもsequenceが一致しない場合は
前frameを保持し、desync counterを増やします。

frame type 0はnormal、1はfade-in、2はfade-out、3はreservedです。Type 1と2は
update数0かつlist bit clearが必須です。Name tableは変えず、inline imageからCRAMの
64 word全てを入れ替えます。Audio decodeとcold-run suffixは続くため、static fade中に
将来patternをprefetchできます。2つのfade方向のplayer操作は同じで、tagはencoderが
検出した方向をvalidationとanalysisのために保存します。

Run descriptorは`n_runs`の直後に続きます。SubがCDC polling cadenceを保ちながら
`O_LOADS v2`へ解決し、Mainはguard付き残余VBlank budgetでその展開済みrecordを
runtime scheduleします。全pattern runがDMAを使います。Current残budget境界を
越えるrunはそこで分割し、次のfresh VBlank headから続きを行います。Streamは
encoded VBlank boundaryを持ちません。

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
