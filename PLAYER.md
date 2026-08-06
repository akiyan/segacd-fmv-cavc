EN / [JP](#jp)

# Player Memory Maps and Runtime Sequence

This document describes the player as currently built: the Sub PRG-RAM,
Word RAM 1M/1M, and Main RAM maps, the startup sequence, and the per-frame
CPU handoff. Each map row carries a short range name (shown as `CODE`) so a
range can be referenced unambiguously in issues, commits, and reviews.

**fps dependence.** Across 15, 24, and 30 fps content, the only address-map
difference is the `PRG-BUF` / `JITTER` split inside the fixed
`0x0D800..0x74FFF` region; that split is the one place below where both
15 and 30 fps values are listed side by side. Every other row of every map,
and the whole startup / per-frame sequence, apply at all three rates. Word-RAM
WordBuf and routing sizes vary by
profile (frame count, cell count, cold cap), not by fps.

**Display cadence.** The player derives one authoritative repeating VBlank
schedule from the packed header. The 15 fps path repeats `(4)`, 24 fps repeats
`(2, 3)` beginning with two VBlanks from frame 0 to frame 1, and 30 fps repeats
`(2)`. Main's display deadline and Sub's CD-sector allowance advance in the
same phase. Their effective rates are 15000/1001, 24000/1001, and 30000/1001
fps respectively.

The 24 fps display controller remains phase-locked after a missed deadline.
It counts whole-VBlank lateness as debt and repays that debt only by shortening
a later nominal three-VBlank display step to two. It never shortens a
two-VBlank step to one. The Sub CPU's physical `(2, 3)` sector schedule remains
unchanged; the late frame has already given the reader the extra physical time
that the compensating display step consumes. This prevents isolated display
misses from becoming permanent reader lead and filling the APPLY queue.

## Unallocated Space Summary

These are the only ranges with no live owner data. Guards, reserves, and
jitter ranges elsewhere in the maps are allocated to their protective role
and are listed in place.

| Domain | Unallocated ranges |
|---|---|
| Sub PRG-RAM | `SP-GAP` 224 B, `SCRATCH` 256 B, and `RING-ALIGN` 448 B; the multi-video overlay uses the first 34 B of `SP-GAP` |
| Word RAM (each bank) | none — every complete sector is assigned; `WB-GAP` is a sector-rounding remainder, not an allocatable range |
| Main RAM | `M-FREE` 10.38 KiB in the ordinary player; the multi-video overlay uses its return stub and loop flag. The 192 B cushion below `M-STACK` is a guard, not allocatable |
| VRAM | `0xDE80..0xDFFF` 384 B; unused Window/HScroll table rows remain reserved to those VDP structures. DEBUG shapes its HUD row with reg 18 only; reg 17 must stay 0 because Window row 24 cols 0-1 alias the HScroll table at `0xFC00`, which now carries nonzero scroll values |

## Sub PRG-RAM Map

PRG-RAM is 512 KiB at `0x00000..0x7FFFF`.

| Name | Address | Size | Contents |
|---|---|---:|---|
| `BIOS-LOW` | `0x00000..0x05FFF` | 24.00 KiB | BIOS / low PRG work area |
| `SP-RES` | `0x06000..0x073FF` | 5.00 KiB | BIOS-loaded resident specialized SP image; the linker rejects a larger image |
| `ADP-IDX` | `0x07400..0x07F1F` | 2,848 B | persistent ADPCM next-index table, copied once at boot; the full range is continuous-read marker-qualified |
| `SP-GAP` | `0x07F20..0x07FFF` | 224 B | unallocated marker-qualified tail; multi-video uses `0x07F20..0x07F41` for its menu-info table and loop flag |
| `PCM-BUF` | `0x08000..0x085FF` | 1.50 KiB | live decoded ADPCM buffer |
| `WORD-PENDING0` | `0x08600..0x08DFF` | 2.00 KiB | first Sub-owned sector waiting for its parity WordBuf bank |
| `WORD-PENDING1` | `0x08E00..0x095FF` | 2.00 KiB | second pending WordBuf sector |
| `ADP-OUT` | `0x09600..0x096FF` | 256 B | persistent predictor-high-byte to RF5C164 output lookup |
| `SCRATCH` | `0x09700..0x097FF` | 256 B | unallocated marker-qualified scratch; the SP-tail diagnostic installs its checker here |
| `BIOS-CD` | `0x09800..0x0BFFF` | 10.00 KiB | BIOS-touched during continuous reads |
| `ADP-DELTA` | `0x0C000..0x0D63F` | 5,696 B | persistent signed ADPCM delta table, copied once at boot |
| `RING-ALIGN` | `0x0D640..0x0D7FF` | 448 B | unallocated gap that sector-aligns PrgBuf |
| `PRG-BUF` | fps split, see next table | 374 / 394 KiB | streamed PrgBuf normal ceiling |
| `JITTER` | fps split, see next table | 40 / 20 KiB | live delivery-jitter reserve above the scheduled ceiling |
| `OBS-GUARD` | `0x75000..0x757FF` | 2.00 KiB | observation guard below pump back-pressure |
| `OVF-GUARD` | `0x75800..0x767FF` | 4.00 KiB | physical PrgBuf overflow guard |
| `WORD-PENDING3` | `0x76800..0x76FFF` | 2.00 KiB | third Sub-PRG pending destination (`WORD_PENDING3` in the player); the boot-only extension executes here before timed playback |
| `APPLY` | `0x77000..0x7F7FF` | 34.00 KiB | APPLY circular queue |
| `SUB-STACK` | `0x7F800..0x7FEFF` | 1.75 KiB | Sub stack reserve |
| `STACK-TOP` | `0x7FF00..0x7FFFF` | 256 B | area above the configured stack top |

### `PRG-BUF` / `JITTER` fps split

The physical bounds are fixed at every fps: the PrgBuf ring is 420 KiB at
`0x0D800..0x767FF`, pump back-pressure begins at 416 KiB, and the delivery
observation boundary is 414 KiB (`..0x74FFF`). Inside that fixed region the
normal/scheduled ceiling and the jitter reserve move with content cadence:

```text
normal PrgBuf KiB = 414 - cadence reserve KiB
cadence reserve KiB = ceil(20 * 30 / fps)
```

| Item | 15 fps | 30 fps |
|---|---|---|
| cadence reserve | 40 KiB | 20 KiB |
| `PRG-BUF` normal / scheduled ceiling | 374 KiB | 394 KiB |
| `PRG-BUF` address | `0x0D800..0x6AFFF` | `0x0D800..0x6FFFF` |
| `JITTER` address | `0x6B000..0x74FFF` | `0x70000..0x74FFF` |

Other rates follow the same formula (24 fps: reserve 25 KiB, ceiling 389 KiB,
`PRG-BUF` = `0x0D800..0x6EBFF`). The values come from
`cadence_jitter_reserve_kb()`, `prg_buf_cap_kb()`, and
`scheduled_delivery_cap_kb()` in `tools/av_config.py`; this document defines
no independent capacity. The `JITTER` reserve is kept for live sector-arrival
variation and is never encoder Supply.

### `SP-RES` usage

The 32 KiB disc system area places the SP source at offset `0x06000` and
reserves its final 5 KiB. The BIOS loads the exact linked image contiguously
at Sub PRG `0x06000`; it is not limited to one 4 KiB sector pair. The image
is profile-specialized (`PLAYER_SPECIALIZE`) and the linker enforces the hard
end at `0x07400`. Continuous-read marker qualification covers the reclaimed
`0x07400..0x07FFF` interval before `ADP-IDX` uses its leading 2,848 bytes.

The packer places the exact 940-byte hash-bound extension after the
8,800-byte ADPCM table in its existing five-sector padding. Sub stages that
image at `SP-STAGE` (`0x7B000`) and runs the extension from `0x7D260` in two
ways: its qualified first 88 bytes run from `EXT-RUN` (`0x76800`, the unused
timed-ring tail); when routing is at most 8 KiB, the second entry runs in
place at `0x7D2B8` after prebuffer, while longer-route builds copy the
complete extension first. The extension also initializes wave RAM from its
fixed `+0x300` entry at staged address `0x7D560`. These boot-only entries copy
all three ADPCM tables once to their Sub PRG destinations, prepare routing,
and initialize PCM plus the ring/APPLY/frame state. Frame-0 staging may then
overwrite both temporary extension locations.

### Multi-video menu overlay

The multi-video menu is a separate boot build. Its boot SP image is only a
bootstrap at `0x06000`; `MENUSP.BIN` is loaded into the Sub-owned Word-RAM
launcher slot `0x1E000..0x1F3FF` in both physical banks and executes at
`0x0DE000`. While the menu is active, `MENUIP.BIN` uses Word-RAM offset
`0x00000..0x04FFF`, and the selected player's IP image is staged at
`0x05000..0x1AFFF` before Main copies it to `0xFF0000`.

The selected player's SP image is loaded into the normal resident slot
`0x06000..0x073FF`, so the video uses the same PrgBuf and APPLY map as an
ordinary specialized build. The menu launcher records the menu and selected
stream LBAs in the marker-qualified `SP-GAP` at `0x07F20..0x07F3F` and keeps
the Sub-side loop flag at `0x07F40`, outside PrgBuf. After an A-play, the player
reloads the menu image into a free Word-RAM bank, Main restores the menu IP from
that bank, and the player reloads `MENUSP.BIN` into both banks before returning
to the menu. Each selected player clears the fixed `M-STATE` range before
using its own Main-CPU `.bss`. Main's return stub is copied to `0xFF8880`; its
loop choice is kept at `0xFFB1F0`.

### Boot-only overlays

| Name | Address | Phase |
|---|---|---|
| `ISO-SCR` | `0x67000..0x76FFF` | 64 KiB scratch image during ISO discovery only |
| `F0-STAGE` | `0x72000..0x7AFFF` | frame-0 pattern staging |
| `SP-STAGE` | `0x7B000..` | staged SP image containing the extension source |
| `EXT-RUN` | `0x76800..0x76BAB` | boot-only extension execution window; timed playback reuses its first sector as `WORD-PENDING3` |

`ISO-SCR` and `F0-STAGE` may overlap the timed ring tail, and `F0-STAGE` may
also overlap `APPLY`, because those timed owners are inactive in each boot
phase. Neither overlay changes the timed map.

The APPLY queue retains deliberate back-pressure headroom; its unused
instantaneous occupancy is not a fixed allocation.

## Word RAM 1M/1M Map

There are two independent 128 KiB physical banks. Sub owns one bank while
Main owns the other. A bank swap exchanges ownership; it does not make one
copy simultaneously visible to both CPUs. This map varies by profile, not by
fps.

`tools/pattern_supply.py` derives the map from frame count, the final
source-grouped run plan, and cold cap. Routing occupies
`ceil(frames / 2048) * 2048` bytes at the bank end. The fixed tail is packed
immediately below routing:

| Name | Relative order, high to low | Size | Contents |
|---|---|---:|---|
| `ROUTE` | bank end | variable, sector-rounded | resident routing table |
| `SECT-STG` | next | 2,048 B | CD-sector stage / pad discard |
| `CTRL-SCR` | next | 8,192 B | linear control scratch |
| `DBG-HDR` | next | 256 B | DEBUG counters and copied header |

The front of each bank starts with `W-HDR`: `O_NRUN` and `O_NLOAD`, two bytes
each. `LOADS` (`O_LOADS`) follows at `+0x0004`. Main reads name updates
directly from `CTRL-SCR`; `O_CRAM`, `O_NUPD`, and `O_UPDS` do not exist.

Sub expands each on-disc four-byte source run into one 22-byte `O_LOADS v2`
record containing VDP-ready DMA length, registers, destination command, and
resolved source. Only Prg records carry their 32-byte-per-pattern payload
inline immediately after the record. Wr and Dic records point at their
persistent stores. Main reads this one cursor in place; it does not build or
copy a run table. The encoder splits a Wr descriptor at its parity WordBuf
ring end before packing. Sub therefore emits only linear source spans, and
Main can run each Word-RAM DMA without wrapping a source address.

| Record offset | Size | Value |
|---:|---:|---|
| `+0` | 2 B | DMA length in words (`patterns * 16`) |
| `+2`, `+4` | 2 B each | prebuilt VDP registers 93 and 94 |
| `+6` | 4 B | destination VDP command without the DMA trigger bit |
| `+10` | 2 B | raw destination byte address for split-run continuation |
| `+12`, `+14`, `+16` | 2 B each | prebuilt VDP source registers 95, 96, and 97 |
| `+18` | 4 B | raw Main-view source address; for Prg it equals the following inline-payload cursor |

`WORDBUF` starts after the parity-specific exact `LOADS` peak and ends before
the fixed tail. The encoder recomputes the even and odd maxima over every
frame as `32 * inline Prg patterns + 22 * runs`, writes both byte counts to
PSUP, and freezes the resulting starts in `player_constants.inc`. Only the
residual after that first reservation becomes WordBuf capacity, rounded down
to complete 2 KiB preload sectors. The two banks can therefore have different
starts and capacities; `WB-GAP` is the remaining sub-sector rounding space.

During boot, `BOOT-STG` uses `+0x0000..+0x5FFF` for the optional boot-VRAM
sidecar records; `DIC-STG` uses `+0x6000..+0x9FFF` for DicBuf staging. The
palette table and switch table are not staged here: the Main-IP image embeds
`paltab.bin` / `palidx.bin` and copies both to `M-PALTAB` / `M-PALIDX` at
entry, before generated code reuses the transient `.startup` area. Sub
gives the staging bank to Main, Main copies the dictionary and optional VRAM
sidecar to their persistent homes, and Main returns the bank. Sub stops `HEADER.DAT` before
this handoff and restarts at the exact first unread sector after the return,
so the copy interval cannot create a sector slip. Sub then reads the finite
untimed BODY arm and expands frame 0; frame 0 and `WORDBUF` may overwrite the
temporary staging range safely. Dump diagnostics write list-form updates into
`CTRL-SCR`.

## Main RAM Map

Main RAM is `0xFF0000..0xFFFFFF`. This map is completely fixed: it is
identical in every build, profile, and fps. Generated code grows upward and is
build-time checked against the `M-STATE` base.

| Name | Address | Size | Contents |
|---|---|---:|---|
| `M-CODE` | `0xFF0000..0xFF66FF` | 25.75 KiB | permanent player, transient boot UI, generated bitmap handlers and guard |
| `M-STATE` | `0xFF6700..0xFF87FF` | 8.25 KiB | BSS, shadow, DEBUG HUD row, name-table stage (a persistent 4,096 B 64x32 plane band on a scroll build), scroll state (`scroll_next_h`/`scroll_next_v`/`scroll_h_dirty`), state; worst-case fixed reserve |
| `M-FCRAM` | `0xFF8800..0xFF887F` | 128 B | current inline fade CRAM image, copied before the consumed Word RAM bank is returned |
| `M-FREE` | `0xFF8880..0xFFB1FF` | 10.38 KiB | unallocated in the ordinary player; the multi-video overlay copies its return stub at `0xFF8880` and keeps its loop flag at `0xFFB1F0` |
| `M-PALTAB` | `0xFFB200..0xFFB9FF` | 2.00 KiB | 16-entry PALTAB (player-embedded paltab.bin) |
| `M-PALIDX` | `0xFFBA00..0xFFBA3F` | 64 B | 16-entry palette-switch table, 15 switches + sentinel (player-embedded palidx.bin) |
| `M-DIC` | `0xFFBA40..0xFFFA3F` | 16.00 KiB | 512-pattern persistent DicBuf |
| guard | `0xFFFA40..0xFFFAFF` | 192 B | cushion below the stack guard |
| `M-STACK` | `0xFFFB00..0xFFFCFF` | 512 B | stack and interrupt reserve |
| `M-TOP` | `0xFFFD00..0xFFFFFF` | 768 B | area above stack top / BIOS reserve |

The realized generated-code end inside `M-CODE` and the realized `.bss` end
inside `M-STATE` vary per build and profile; build-time assertions keep each
inside its fixed range. A scroll DEBUG build fills the `M-STATE` reservation
completely, with zero spare bytes. Main keeps no run-plan cursor or WordBuf
read cursor: Sub owns both parity cursors and hands off already-resolved
records.

## VRAM Map

The movie uses one displayed Plane A name table. No per-frame register-2
switch selects another table.

| Name | Address | Size | Contents |
|---|---|---:|---|
| blank tile | `0x0000..0x001F` | 32 B | fixed transparent tile 0 |
| resident pool | `0x0020..0xD9FF` | 1,743 tiles | contiguous movie-pattern slots 1–1,743 |
| HUD font | `0xDA00..0xDBFF` | 16 tiles | hexadecimal glyphs shared by DEBUG and release startup |
| sprite table | `0xDC00..0xDE7F` | 640 B | complete 80-record hardware SAT footprint at the highest 0x400-aligned base below the name table; DEBUG uses 24 B (3 records) |
| gap | `0xDE80..0xDFFF` | 384 B | unallocated VRAM |
| movie NT | `0xE000..0xEFFF` | 4 KiB | single 64x32 Plane A table |
| HUD Window row | `0xF000..0xF04F` | 80 B | first DEBUG row; one word per each of the 40 screen columns |
| horizontal scroll | `0xFC00..0xFC03` | 4 B | Plane A/B full-screen HScroll pair; zero outside a scroll window, rewritten every flip inside one |

VSRAM entries 0 and 1 carry the Plane A/B VScroll. The stream's scroll value
follows the `y - vscroll` convention while the VDP adds VSRAM to the line
counter, so the player writes the negated value; both pairs are zero outside
a scroll window and republished in the same VBlank as the band DMA.

Main expands the logical grid into a zero-gapped, 64-entry-pitch Main-RAM
stage. During the cadence-final VBlank it DMAs the contiguous band from the
grid's centered top-left cell through its final cell into `movie NT`. The
transfer length is `(rows - 1) * 64 + cols`: 1,192 words for 40x19 and 1,768
for the full-height 40x28 grid. Inside a scroll window the
DMA instead covers the full 64-column band — `rows * 64` words, or all 32
plane rows (2,048 words) on a vertical window. DEBUG then sends the first
screen-width HUD row to the Window table and its three spill digits as
sprites. Generic and specialized players use the same routes at every cadence.

## Startup and Per-Frame CPU Sequence

The sequences below are identical at 15, 24, and 30 fps; only the cadence
differs.

### Startup

One `CMD_STREAM` command spans the complete startup. The BOOT_STAGE ownership
exchange still uses `STAT_BOOT_STAGE` plus `COMCMD1`, because Main must copy
palette, switch table, dictionary, and sidecar data before Sub reuses that physical bank.
There is no separate frame-0/BODY-start handshake.

`STAT_READY` exposes the completed frame-0 bank while the timed CD reader is
still stopped. Clearing the original command after visible frame-0 publication
launches timed BODY service. PCM stays stopped through `ROM_READN` startup and
begins when the first frame-1 control sector arrives. Sub finishes that
physical slot before acknowledging the clear, so its remainder and the next
VBlank form the normal frame-0-to-frame-1 interval. Frame -1 therefore creates
no unplanned PrgBuf lead, and the CD startup interval does not advance audio.

```mermaid
sequenceDiagram
    participant CD as CD / CDC
    participant S as Sub CPU
    participant W as Word RAM 1M/1M
    participant M as Main CPU
    participant V as VDP

    M->>M: Copy embedded PALTAB and PALIDX to Main RAM
    M->>S: Assert CMD_STREAM
    CD-->>S: Static HEADER
    S-->>M: STAT_BOOT_STAGE
    M->>W: Copy DicBuf and sidecar
    M->>S: COMCMD1 stage acknowledgement
    CD-->>S: Finish static HEADER
    CD-->>S: Finite BODY arm (PCM + frame 0)
    S->>S: Stop arm read and expand frame 0
    S->>W: Exchange completed frame-0 bank
    S-->>M: STAT_READY
    Note over S,CD: Timed suffix remains stopped
    M->>V: Show black frame -1 (DEBUG frame=FFFF)
    M->>V: Build and publish frame 0 (frame=0000)
    M->>S: Clear the original CMD_STREAM
    S->>CD: Launch continuous timed suffix
    CD-->>S: First frame-1 control sector
    S->>S: Start PCM
    CD-->>S: Finish frame-1 physical slot
    S-->>M: Clear STAT_READY
    M->>S: CMD_SWAP for frame 1
```

Frame -1 is a player/HUD state only. It does not add a sim frame, a control
block, a routing entry, or a HUD TSV row.

### Timed playback

On every generic and specialized path, Main returns the consumed Word
RAM bank as soon as its final pattern and status reads are complete. The bank
exchange is started without blocking, before Main finishes the name-table,
HUD, CRAM, and publication work for frame `N`.

```mermaid
sequenceDiagram
    participant CD as CD / CDC
    participant S as Sub CPU
    participant W as Word RAM 1M/1M
    participant M as Main CPU
    participant V as VDP

    par Sub prepares frame N+1
        CD-->>S: BODY sectors
        S->>S: Route control and Prg payload
        S->>S: Decode ADPCM and write RF5C164
        S->>W: Expand control and O_LOADS v2 records
    and Main consumes frame N
        M->>W: Read O_LOADS v2 in place
        M->>M: Apply bitmap or update list
        M->>M: Copy inline fade CRAM to M-FCRAM when present
        M->>V: Transfer the final cold run and repair its first word
    end

    M->>S: Assert CMD_SWAP for prepared frame N+1; do not wait
    S->>W: Exchange bank ownership
    S-->>M: STAT_READY

    par Sub uses the returned bank
        S->>W: Flush pending WordBuf data
        CD-->>S: Pump sectors while CMD_SWAP remains asserted
    and Main finishes frame N without Word RAM
        M->>V: DMA movie NT and HUD, update CRAM, commit cadence origin
    end

    M->>S: At the next loop head, wait only for any unfinished READY tail
    M->>S: Clear CMD_SWAP
```

A zero residual wait means Sub completed the exchange during Main's remaining
display work. It does not mean that the exchange itself was free. Inline fade
CRAM is copied to `M-FCRAM` before the request, so Main makes no further access
to the returned bank after asserting `CMD_SWAP`. Frame 0 keeps
the startup `CMD_STREAM` ownership through its publication, so frame 1 is
acquired by the ordinary synchronous request. The final frame is also excluded: Main
requests `STAT_END` only after that frame has become visible.
Non-specialized, periodic-cadence, and feature-clear paths use the same early
handoff once a future frame exists.

On a scroll build, a type-3 control takes a dedicated apply path: item 0
supplies the absolute HScroll/VScroll pair, and the remaining completed-list
items write directly into the persistent 64x32 plane band, leaving the
logical shadow untouched and skipping the stage expansion. The flip then
publishes the full plane band and both scroll pairs. On the first following
non-scroll frame the player compacts the tile-aligned final viewport back
into the logical shadow and rearms both scrolls at zero.

CAVC controls store `n_runs` immediately followed by compact source-aware
run descriptors. Sub keeps the existing CDC polling cadence while resolving
those descriptors into `O_LOADS v2`; Main schedules the expanded records
against the runtime residual budget. Fixed N is the healthy fresh-budget
count: N2 permits two and N4 permits four; opening another budget remains
bounded but raises a HUD warning. A light N4 frame may open only one or two
budgets and leave the remaining cadence windows empty. These counters record
explicit budget openings.

For fixed-cadence playback, one transfer deadline can serve both
the final cold-run tail and display publication. The Main CPU uses a
conservative
3,200 DMA-word-equivalent budget for each VBlank. A DMA word
costs one unit. Every pattern run uses DMA. A Word-RAM DMA also pays four units
for its required CPU first-word repair. Main grants a budget only after waiting for a
new VBlank or while the V counter is still on its first blank line (`E0`).
Entering an already-running blank later never creates a full budget; Main
waits for the next head.

Budgets 1 through the current cadence target minus one are available to
patterns. Before pattern work enters the target budget, Main withholds the
complete display reserve: the exact movie band, a 128-unit timing guard, the
physical DEBUG HUD DMAs when present, and an optional CRAM replacement. CRAM
is written by the CPU, so its 64 words reserve 256 units. Full-height H40 uses
1,896 units in release or 1,948 in DEBUG; a palette switch raises those values
to 2,152 and 2,204. Thus an N2 DEBUG full-height H40 frame has 3,200 units in
VBlank 1 and 1,252 pattern units in VBlank 2, or 996 on a palette switch. A
40x19 DEBUG frame reserves only 1,372 units, or 1,628 with a palette switch.
A scroll build adds the fixed scroll term — the full-band excess over the
trimmed band plus 16 units for the CPU-written HScroll/VScroll pairs (40
units at full-height H40) — and a vertical window adds a further 256 units
at runtime for the wrapped plane rows. A scroll frame carries no inline CRAM
image, so the palette-switch variants never apply to it.

A DMA run crossing a residual boundary is split exactly there and continued
at the next fresh VBlank head, regardless of run length. After the pattern
tail, Main restores the withheld reserve and admits the shared
name-table/HUD/CRAM publication path only if the current phase is still inside
that same VBlank. VBlank status is checked before and after the V counter, and terminal
lines `FC..FF` are rejected. If any condition fails, Main waits for a fresh
VBlank.

For a multi-budget DEBUG pattern transfer, Main formats the stable HUD fields
after the first transfer budget and before waiting for the next fresh VBlank.
After the final pattern word, it patches only the transfer-final fields and
the resolved palette segment in `dbg_row`. The exact-band movie NT DMA and the
Window/SAT HUD DMAs then run as separate members of the same admitted VBlank;
there is no CPU VDP-port HUD republish. Exact logical pattern
word counters cover runtime VBlank budgets 1 through 4; they remain separate
from the weighted capacity charge. `transfer_vblanks` exposes a fifth or later
budget. The admission check charges the exact physical words for each display
DMA.

Sub wait loops service a pending `CMD_SWAP` before another opportunistic
sector pump. CD pumping continues while Main is genuinely idle, but future
payload work cannot delay an already-pending handoff.

## Reproducing the Map Measurements

Use the managed Python environment and an explicit profile:

```sh
tools/python.sh tools/check_player_ring.py \
  --constants out/PROFILE/player_constants.inc \
  --extension tmp/PROFILE/build/movieplay_sp_ext.bin \
  --extension-constants tmp/PROFILE/build/sp_extension.inc
make movieplay CONFIG=profiles/PROFILE.toml \
  DEBUG=1 MAIN_CODEGEN=1 PLAYER_SPECIALIZE=1

~/toolchains/mars/m68k-elf/bin/m68k-elf-size -A \
  tmp/PROFILE/build/movieplay_ip.o \
  tmp/PROFILE/build/movieplay_sp.o
```

The `SP-RES` loaded size is the linked size of
`tmp/PROFILE/build/movieplay_sp.bin`. Rebuild, pack with verification, and
complete the DEBUG recording and HUD gate before revising any address or
size in this document.

---

<a id="jp"></a>

# Player memory mapとruntime sequence

この文書は、現在ビルドされているplayerをそのまま記述します。Sub PRG-RAM、
Word RAM 1M/1M、Main RAMのmap、startup sequence、frameごとのCPU handoffが
対象です。各map行には短いrange名（`CODE`表記）を付けており、issue・commit・
reviewでrangeを曖昧さなく参照できます。

**fps依存について。** 15、24、30 fpsのcontent間でaddress mapが変わるのは、
固定領域`0x0D800..0x74FFF`内部の`PRG-BUF` / `JITTER`分割だけです。その分割
だけを後述の表で15 fpsと30 fpsの両値併記にします。それ以外のすべてのmap行と
startup / per-frame sequence全体は3 rateすべてに適用されます。
Word RAMのWordBufとrouting sizeはprofile（frame数、cell数、cold cap）で変わる
ものであり、fpsでは変わりません。

**Display cadence。** playerはpacked headerから正式な反復VBlank scheduleを1つ
導出します。15 fps pathは`(4)`、24 fps pathはframe 0からframe 1までの2 VBlankで
始まる`(2, 3)`、30 fps pathは`(2)`を反復します。Mainのdisplay deadlineとSubの
CD-sector allowanceは同じ位相で進みます。実効rateは順に15000/1001、24000/1001、
30000/1001 fpsです。

24 fps display controllerはdeadlineを外した後も位相を維持します。遅れをVBlank単位の
debtとして数え、後の名目3 VBlank display stepを2へ短縮する場合だけdebtを返済します。
2 VBlank stepを1へ短縮することはありません。Sub CPUの物理`(2, 3)` sector scheduleは
変えません。遅れたframeがreaderへ追加の物理時間をすでに与えており、補償display stepは
その時間を消費します。これにより、単発のdisplay missが恒久的なreader leadとなって
APPLY queueを満たすことを防ぎます。

## 未割当領域の要約

live ownerのdataを持たないrangeは次だけです。map中のguard・reserve・jitter
rangeは保護役として割り当て済みであり、各mapの該当行に記載しています。

| Domain | 未割当range |
|---|---|
| Sub PRG-RAM | `SP-GAP` 224 B、`SCRATCH` 256 B、`RING-ALIGN` 448 B。multi-video overlayは`SP-GAP`先頭34 Bを使う |
| Word RAM（各bank） | なし。完全なsectorはすべて割当済み。`WB-GAP`はsector丸めの余りで、割当可能なrangeではない |
| Main RAM | 通常playerでは`M-FREE` 10.38 KiB。multi-video overlayはreturn stubとloop flagを使う。`M-STACK`直下の192 Bクッションはguardであり割当不可 |
| VRAM | `0xDE80..0xDFFF` 384 B。未使用Window/HScroll table rowは各VDP structure用に予約したまま。DEBUGのHUD行はreg 18だけで形成し、reg 17は0のまま保つ。Window row 24 col 0-1は`0xFC00`のHScroll tableとaliasし、そこはいまや非ゼロのscroll値を運ぶため |

## Sub PRG-RAM map

PRG-RAMは`0x00000..0x7FFFF`の512 KiBです。

| Name | Address | Size | 内容 |
|---|---|---:|---|
| `BIOS-LOW` | `0x00000..0x05FFF` | 24.00 KiB | BIOS / low PRG work area |
| `SP-RES` | `0x06000..0x073FF` | 5.00 KiB | BIOS-loadされるresident specialized SP image。linkerがこれを超えるimageを拒否 |
| `ADP-IDX` | `0x07400..0x07F1F` | 2,848 B | boot時に1回copyするpersistent ADPCM next-index table。全rangeをcontinuous-read markerで検証済み |
| `SP-GAP` | `0x07F20..0x07FFF` | 224 B | 未割当のmarker検証済みtail。multi-videoはmenu-info tableとloop flagに`0x07F20..0x07F41`を使う |
| `PCM-BUF` | `0x08000..0x085FF` | 1.50 KiB | live decoded ADPCM buffer |
| `WORD-PENDING0` | `0x08600..0x08DFF` | 2.00 KiB | parity WordBuf bank待ちのSub所有1本目sector |
| `WORD-PENDING1` | `0x08E00..0x095FF` | 2.00 KiB | 2本目のpending WordBuf sector |
| `ADP-OUT` | `0x09600..0x096FF` | 256 B | persistent predictor-high-byte to RF5C164 output lookup |
| `SCRATCH` | `0x09700..0x097FF` | 256 B | 未割当のmarker検証済みscratch。SP-tail diagnosticはここへcheckerを置く |
| `BIOS-CD` | `0x09800..0x0BFFF` | 10.00 KiB | continuous read中にBIOSが使用 |
| `ADP-DELTA` | `0x0C000..0x0D63F` | 5,696 B | boot時に1回copyするpersistent signed ADPCM delta table |
| `RING-ALIGN` | `0x0D640..0x0D7FF` | 448 B | PrgBufをsector alignmentする未割当gap |
| `PRG-BUF` | fps分割、次表参照 | 374 / 394 KiB | streamed PrgBufのnormal上限 |
| `JITTER` | fps分割、次表参照 | 40 / 20 KiB | scheduled上限より上のlive delivery-jitter予約 |
| `OBS-GUARD` | `0x75000..0x757FF` | 2.00 KiB | pump back-pressure前の観測guard |
| `OVF-GUARD` | `0x75800..0x767FF` | 4.00 KiB | physical PrgBuf overflow guard |
| `WORD-PENDING3` | `0x76800..0x76FFF` | 2.00 KiB | playerで`WORD_PENDING3`と呼ぶ3本目のSub-PRG pending destination。boot-only extensionはtimed playback前にここで実行 |
| `APPLY` | `0x77000..0x7F7FF` | 34.00 KiB | APPLY circular queue |
| `SUB-STACK` | `0x7F800..0x7FEFF` | 1.75 KiB | Sub stack reserve |
| `STACK-TOP` | `0x7FF00..0x7FFFF` | 256 B | configured stack topより上 |

### `PRG-BUF` / `JITTER`のfps分割

物理境界はすべてのfpsで固定です。PrgBuf ringは`0x0D800..0x767FF`の420 KiB、
pump back-pressureは416 KiBで始まり、delivery観測境界は414 KiB
（`..0x74FFF`）です。この固定領域の内部で、normal/scheduled上限とjitter予約
がcontent cadenceに応じて動きます。

```text
normal PrgBuf KiB = 414 - cadence reserve KiB
cadence reserve KiB = ceil(20 * 30 / fps)
```

| 項目 | 15 fps | 30 fps |
|---|---|---|
| cadence reserve | 40 KiB | 20 KiB |
| `PRG-BUF` normal / scheduled上限 | 374 KiB | 394 KiB |
| `PRG-BUF` address | `0x0D800..0x6AFFF` | `0x0D800..0x6FFFF` |
| `JITTER` address | `0x6B000..0x74FFF` | `0x70000..0x74FFF` |

他のrateも同じ式に従います（24 fps: reserve 25 KiB、上限389 KiB、
`PRG-BUF` = `0x0D800..0x6EBFF`）。数値は`tools/av_config.py`の
`cadence_jitter_reserve_kb()`、`prg_buf_cap_kb()`、
`scheduled_delivery_cap_kb()`から得ます。この文書では独立した容量を定義
しません。`JITTER`予約はliveのsector到着変動のために保持され、encoder
Supplyになることはありません。

### `SP-RES`の使用量

32 KiB disc system areaはSP sourceをoffset `0x06000`へ置き、最後の5 KiBを
予約します。BIOSは正確なlinked imageをSub PRG `0x06000`へ連続loadし、
1組の4 KiB sectorには制限されません。imageはprofile-specialized
（`PLAYER_SPECIALIZE`）で、linkerがhard end `0x07400`を強制します。
`ADP-IDX`が先頭2,848 byteを使う前に、回収した`0x07400..0x07FFF`全体を
continuous-read markerで検証します。

Packerはhashで固定した940-byte extensionを8,800-byte ADPCM table直後の既存
5-sector paddingへ配置します。Subはそのimageを`SP-STAGE`（`0x7B000`）へ
stageし、`0x7D260`のextensionを2通りに使います。qualified済み先頭88 byteは
`EXT-RUN`（未使用timed-ring tailの`0x76800`）で実行します。routingが8 KiB
以下なら第2入口をprebuffer後に`0x7D2B8`でそのまま実行し、長いroutingの
buildはextension全体を先にcopyします。さらに固定`+0x300`入口をstaged address
`0x7D560`で呼びwave RAMを初期化します。これらのboot-only入口が3つのADPCM
tableを各Sub PRG destinationへ1回copyし、routing、PCM、初期ring/APPLY/frame
stateを設定します。その後はframe-0 stagingが両temporary extension locationを
上書きできます。

### Multi-video menu overlay

Multi-video menuは別boot buildです。Boot SP imageは`0x06000`のbootstrapだけで、
`MENUSP.BIN`を両physical bankのSub-owned Word-RAM launcher slot
`0x1E000..0x1F3FF`へloadし、`0x0DE000`で実行します。Menu active中は`MENUIP.BIN`を
Word-RAM offset `0x00000..0x04FFF`へ置き、selected playerのIP imageを
`0x05000..0x1AFFF`へstageしてからMainが`0xFF0000`へcopyします。

Selected playerのSP imageは通常のresident slot `0x06000..0x073FF`へloadするため、videoは
通常のspecialized buildと同じPrgBuf / APPLY mapを使います。Menu launcherはmenuとselected
streamのLBAをmarker検証済み`SP-GAP`の`0x07F20..0x07F3F`へ記録し、Sub側のloop flagを
PrgBuf外の`0x07F40`に保持します。A-play後はplayerがfreeになったWord-RAM bankへmenu imageを
再loadし、Mainがそこからmenu IPをrestoreし、playerが`MENUSP.BIN`を両bankへ再loadしてmenuへ
戻ります。各selected playerは自身のMain-CPU `.bss`を使う前に固定`M-STATE` rangeをclearします。
Mainのreturn stubは`0xFF8880`へcopyし、Main側のloop choiceは`0xFFB1F0`に保持します。

### Boot-only overlay

| Name | Address | Phase |
|---|---|---|
| `ISO-SCR` | `0x67000..0x76FFF` | ISO discovery中だけの64 KiB scratch image |
| `F0-STAGE` | `0x72000..0x7AFFF` | frame-0 pattern staging |
| `SP-STAGE` | `0x7B000..` | extension sourceを含むstaged SP image |
| `EXT-RUN` | `0x76800..0x76BAB` | boot-only extension実行window。timed playbackでは先頭sectorを`WORD-PENDING3`として再利用 |

各boot phaseではtimed ownerがinactiveなので、`ISO-SCR`と`F0-STAGE`はtimed
ring tailと重複でき、`F0-STAGE`は`APPLY`とも重複できます。どちらのoverlayも
timed mapを変えません。

APPLY queueには意図的なback-pressure headroomがあります。瞬間的な未使用
occupancyは固定allocationではありません。

## Word RAM 1M/1M map

128 KiBの独立したphysical bankが2つあります。Subが一方を所有するときMainは
他方を所有します。Bank swapはownershipを交換するだけで、同じcopyを両CPUへ
同時公開しません。このmapはprofileで変わり、fpsでは変わりません。

`tools/pattern_supply.py`がframe数、最終source-grouped run計画、cold capから
mapを導出します。Routingはbank末尾に`ceil(frames / 2048) * 2048` byteを
使います。Fixed tailはroutingの直下へ次の順で詰めます。

| Name | 上から下への相対順 | Size | 内容 |
|---|---|---:|---|
| `ROUTE` | bank末尾 | 可変、sector丸め | resident routing table |
| `SECT-STG` | 次 | 2,048 B | CD-sector stage / pad discard |
| `CTRL-SCR` | 次 | 8,192 B | linear control scratch |
| `DBG-HDR` | 次 | 256 B | DEBUG counterとcopied header |

各bank先頭の`W-HDR`は`O_NRUN`と`O_NLOAD`で、それぞれ2 byteです。
`LOADS`（`O_LOADS`）は`+0x0004`から続きます。Mainはname updateを
`CTRL-SCR`から直接読むため、`O_CRAM`、`O_NUPD`、`O_UPDS`は存在しません。

Subはdisc上の各4-byte source runを、VDP-ready DMA length、register、
destination command、解決済みsourceを持つ22-byte `O_LOADS v2` recordへ
展開します。Prg recordだけが直後にpattern当たり32 byteのpayloadをinlineで
持ちます。Wr/Dic recordはpersistent storeを直接指します。Mainは単一cursorを
in-placeで読み、run tableを構築もcopyもしません。EncoderはWr descriptorを
pack前にparity WordBuf ring末尾で分割します。Subが出力するsource spanは常に
linearとなり、Mainはsource addressをwrapせず各Word-RAM DMAを実行できます。

| Record offset | Size | 値 |
|---:|---:|---|
| `+0` | 2 B | word単位DMA length（`patterns * 16`） |
| `+2`, `+4` | 各2 B | 構築済みVDP register 93、94 |
| `+6` | 4 B | DMA trigger bitを除くdestination VDP command |
| `+10` | 2 B | split run継続用のraw destination byte address |
| `+12`, `+14`, `+16` | 各2 B | 構築済みVDP source register 95、96、97 |
| `+18` | 4 B | Main-view raw source address。Prgでは直後のinline payload cursorと同値 |

`WORDBUF`はparity別の正確な`LOADS`ピーク直後からfixed tail手前までです。
Encoderは全frameから偶数・奇数それぞれの最大値を
`32 * inline Prg patterns + 22 * runs`で再計算し、そのbyte数をPSUPへ書き、
導出したstartを`player_constants.inc`へ固定します。この予約を先に引いた
残余だけがWordBuf容量となり、完全な2 KiB preload sectorへ切り下げられます。
したがって2 bankのstartとcapacityは異なり得ます。`WB-GAP`は残った
sub-sector丸め領域です。

Boot中は`BOOT-STG`が`+0x0000..+0x5FFF`（optionalなboot-VRAM sidecar record専用）、
`DIC-STG`が`+0x6000..+0x9FFF`をDicBuf stagingに使います。palette表と切替表は
ここにstageしません: Main-IP imageが`paltab.bin` / `palidx.bin`を内蔵し、生成
codeが一時`.startup`領域を再利用する前のentry直後に`M-PALTAB` / `M-PALIDX`へ
copyします。Subがstaging bankをMainへ渡し、Mainはdictionaryと任意のVRAM
sidecarをpersistentな保存先へcopyしてbankを返します。Subはhandoff前に`HEADER.DAT`を停止し、返却後に正確な最初の
未読sectorから再開するため、copy intervalがsector slipを発生させません。
続いてSubは有限でuntimedなBODY armを読み、frame 0を展開します。その後は
frame 0と`WORDBUF`がtemporary stage rangeを安全に上書きできます。Dump
diagnosticはlist形式のupdateを`CTRL-SCR`へ書きます。

## Main RAM map

Main RAMは`0xFF0000..0xFFFFFF`です。このmapは完全固定で、すべてのbuild・
profile・fpsで同一です。Generated codeは上方向へ伸び、`M-STATE` baseに対して
build-time checkされます。

| Name | Address | Size | 内容 |
|---|---|---:|---|
| `M-CODE` | `0xFF0000..0xFF66FF` | 25.75 KiB | permanent player、transient boot UI、generated bitmap handler、guard |
| `M-STATE` | `0xFF6700..0xFF87FF` | 8.25 KiB | BSS、shadow、DEBUG HUD row、name-table stage（scroll buildでは常駐4,096 Bの64x32 plane band）、scroll state（`scroll_next_h`/`scroll_next_v`/`scroll_h_dirty`）、state。最悪ケース固定予約 |
| `M-FCRAM` | `0xFF8800..0xFF887F` | 128 B | 消費済みWord RAM bankを返す前にcopyする、現在のinline fade CRAM image |
| `M-FREE` | `0xFF8880..0xFFB1FF` | 10.38 KiB | 通常playerでは未割当。multi-video overlayは`0xFF8880`へreturn stubをcopyし、`0xFFB1F0`をloop flagに使う |
| `M-PALTAB` | `0xFFB200..0xFFB9FF` | 2.00 KiB | 16-entry PALTAB（player内蔵paltab.bin） |
| `M-PALIDX` | `0xFFBA00..0xFFBA3F` | 64 B | 16-entry palette切替表、15切替+番兵（player内蔵palidx.bin） |
| `M-DIC` | `0xFFBA40..0xFFFA3F` | 16.00 KiB | 512-pattern persistent DicBuf |
| guard | `0xFFFA40..0xFFFAFF` | 192 B | stack guard直下のクッション |
| `M-STACK` | `0xFFFB00..0xFFFCFF` | 512 B | stackとinterrupt reserve |
| `M-TOP` | `0xFFFD00..0xFFFFFF` | 768 B | stack topより上 / BIOS reserve |

`M-CODE`内の実generated-code末尾と`M-STATE`内の実`.bss`末尾はbuildとprofile
ごとに変わり、build-time assertionが各固定rangeの内側に保ちます。scroll DEBUG
buildは`M-STATE`予約を余りゼロで使い切ります。Mainは
run-plan cursorもWordBuf read cursorも持たず、Subが両parity cursorを所有して
解決済みrecordを渡します。

## VRAM map

Movieは表示用Plane A name tableを1枚だけ使います。Frameごとに別tableを選ぶ
register-2 switchはありません。

| Name | Address | Size | 内容 |
|---|---|---:|---|
| blank tile | `0x0000..0x001F` | 32 B | 固定transparent tile 0 |
| resident pool | `0x0020..0xD9FF` | 1,743 tiles | 連続movie-pattern slot 1〜1,743 |
| HUD font | `0xDA00..0xDBFF` | 16 tiles | DEBUGとrelease startupで共有するhexadecimal glyph |
| sprite table | `0xDC00..0xDE7F` | 640 B | name table直下の最上位0x400整列baseに置いた80 record分の完全なhardware SAT領域。DEBUGの実使用は24 B（3 record） |
| gap | `0xDE80..0xDFFF` | 384 B | 未割当VRAM |
| movie NT | `0xE000..0xEFFF` | 4 KiB | 単一64x32 Plane A table |
| HUD Window row | `0xF000..0xF04F` | 80 B | DEBUG先頭行。40 screen columnそれぞれに1 word |
| horizontal scroll | `0xFC00..0xFC03` | 4 B | Plane A/Bのfull-screen HScroll対。scroll window外では0、window中は毎flip書き換え |

VSRAM entry 0と1はPlane A/BのVScrollを運びます。streamのscroll値は
`y - vscroll`規約に従い、VDPはVSRAMをline counterへ加算するため、playerは
符号反転した値を書きます。両対ともscroll window外では0で、band DMAと同じ
VBlank内でrepublishします。

Mainはlogical gridをzero gap付き64-entry-pitch Main-RAM stageへ展開します。
Cadence-final VBlank中に、gridのcentered top-left cellからfinal cellまでの連続bandを
`movie NT`へDMAします。Transfer lengthは`(rows - 1) * 64 + cols`で、40x19は
1,192 word、full-height 40x28 gridは1,768です。scroll window中は
代わりに64列band全体をDMAします。horizontalは`rows * 64` word、verticalは
32 plane行すべて（2,048 word）です。DEBUGは続いて
先頭screen-width HUD rowをWindow tableへ、spillする3桁をspriteとして
送ります。Generic / specialized playerは全cadenceで同じrouteを使います。

## StartupとframeごとのCPU sequence

以下のsequenceは15、24、30 fpsで同一で、cadenceだけが異なります。

### Startup

1個の`CMD_STREAM` commandがstartup全体を通してassertされたままです。
BOOT_STAGEのownership交換には引き続き`STAT_BOOT_STAGE`と`COMCMD1`を使います。
Subが同じ物理bankを再利用する前に、Mainがpalette、切替表、dictionary、sidecar data
をcopyする必要があるためです。frame-0/BODY-start専用の2個目のhandshakeは
ありません。

`STAT_READY`は完成したframe-0 bankを公開しますが、この時点ではtimed CD
readerを停止したままにします。frame 0を実際にpublishした後で元のcommandを
clearするとtimed BODY serviceを起動します。`ROM_READN` の起動中はPCMを停止したままにし、
最初のframe-1 control sector到着時にPCMを開始します。Subはそのphysical slotを最後まで
drainしてからclearをacknowledgeするため、slotの残り時間と次のVBlankが通常の
frame-0-to-frame-1 intervalになります。したがってframe -1は計画外のPrgBuf先行量を
作らず、CD起動待ちも音声を進めません。

```mermaid
sequenceDiagram
    participant CD as CD / CDC
    participant S as Sub CPU
    participant W as Word RAM 1M/1M
    participant M as Main CPU
    participant V as VDP

    M->>M: 内蔵PALTAB/PALIDXをMain RAMへcopy
    M->>S: CMD_STREAMをassert
    CD-->>S: static HEADER
    S-->>M: STAT_BOOT_STAGE
    M->>W: DicBufとsidecarをcopy
    M->>S: COMCMD1 stage acknowledgement
    CD-->>S: static HEADERの残り
    CD-->>S: finite BODY arm（PCM + frame 0）
    S->>S: arm readを停止しframe 0を展開
    S->>W: completed frame-0 bankを交換
    S-->>M: STAT_READY
    Note over S,CD: timed suffixは停止したまま
    M->>V: black frame -1を表示（DEBUG frame=FFFF）
    M->>V: frame 0を構築・publish（frame=0000）
    M->>S: 元のCMD_STREAMをclear
    S->>CD: continuous timed suffixを起動
    CD-->>S: 最初のframe-1 control sector
    S->>S: PCMを開始
    CD-->>S: frame-1 physical slotを完了
    S-->>M: STAT_READYをclear
    M->>S: frame 1のCMD_SWAP
```

frame -1はplayer/HUDだけのstateです。sim frame、control block、routing
entry、HUD TSV rowは追加しません。

### Timed playback

すべてのgeneric / specialized pathで、Mainは最後のpattern readとstatus readを
終えた時点で、消費済みWord RAM bankを返します。Frame `N`のname-table、
HUD、CRAM、publication処理を終える前に、bank交換をblockingせず開始します。

```mermaid
sequenceDiagram
    participant CD as CD / CDC
    participant S as Sub CPU
    participant W as Word RAM 1M/1M
    participant M as Main CPU
    participant V as VDP

    par Subがframe N+1を準備
        CD-->>S: BODY sector
        S->>S: controlとPrg payloadをroute
        S->>S: ADPCM decodeとRF5C164 write
        S->>W: controlとO_LOADS v2 recordをexpand
    and Mainがframe Nを消費
        M->>W: O_LOADS v2をin-placeで読む
        M->>M: bitmapまたはupdate listをapply
        M->>M: inline fade CRAMがあればM-FCRAMへcopy
        M->>V: 最後のcold runをtransferして先頭wordを補修
    end

    M->>S: prepared frame N+1のCMD_SWAPをassertし、待たない
    S->>W: bank ownership交換
    S-->>M: STAT_READY

    par Subが返却bankを使う
        S->>W: pending WordBuf dataをflush
        CD-->>S: CMD_SWAP assert中にsectorをpump
    and MainがWord RAMなしでframe Nを完了
        M->>V: movie NTとHUDをDMA、CRAM update、cadence originをcommit
    end

    M->>S: 次のloop先頭で未完了のREADY tailだけを待つ
    M->>S: CMD_SWAPをclear
```

残り待ちがゼロなら、Mainの残るdisplay work中にSubの交換が完了したという
意味です。交換自体の所要時間がゼロという意味ではありません。Inline fade
CRAMはrequest前に`M-FCRAM`へcopyするため、Mainは`CMD_SWAP` assert後、返却した
bankへアクセスしません。Frame 0はpublicationまで
startupの`CMD_STREAM` ownershipを保つため、frame 1は通常の同期requestで
取得します。最終frameも対象外で、表示された後にだけMainが`STAT_END`を
requestします。Non-specialized、periodic-cadence、feature-clear pathも、
future frameが存在すれば同じearly handoffを使います。

scroll buildでは、type 3 controlが専用のapply pathを通ります。item 0が絶対
HScroll/VScroll対を供給し、残りのcompleted-list itemは常駐64x32 plane bandへ
直接書き込みます。logical shadowには触れず、stage展開もskipします。flipは
plane band全体と両scroll対をpublishします。直後の最初の非scroll frameで、
playerはtile整列済みの最終viewportをlogical shadowへ圧縮複写し、両scrollを
0へ戻して再armします。

CAVC controlは`n_runs`の直後にcompactなsource-aware run descriptorを
置きます。Subは既存のCDC polling cadenceを保ったままdescriptorを
`O_LOADS v2`へ解決し、Mainがruntime残budgetに対して展開済みrecordをschedule
します。Fixed Nはhealthyなfresh budget数で、N2は2本、N4は4本です。さらに
budgetを開く処理はboundedのままですがHUD warningになります。軽いN4 frameは
1〜2 budgetだけを開き、残るcadence windowを空きにできます。このcounterは
explicitなbudget openingを記録します。

Fixed-cadence再生では、1個のtransfer deadlineを最後のcold-run tailと
display publicationで共有できます。Main CPUは各VBlankに、安全側の
3,200 DMA-word相当budgetを使います。DMA wordは1 unitで、全pattern runがDMAを使います。
Word-RAM DMAは必須のCPU先頭word補修に4 unitを追加します。新しいVBlankを待った
直後、またはV counterが最初のblank line（`E0`）にある場合だけbudgetを与えます。
すでに進行中のblankへそれより遅く入った場合はfull budgetを作らず、次のheadを
待ちます。

Budget 1からcurrent cadence targetの1つ前まではpatternに使えます。Pattern workが
target budgetへ入る前に、Mainはdisplay work全体を先に取り置きします。内訳は
exact movie band、128-unit timing guard、存在する場合の物理DEBUG HUD DMA、任意の
CRAM replacementです。CRAMはCPU writeなので64 wordに256 unitを予約します。
Full-height H40のreserveはreleaseで1,896 unit、DEBUGで1,948 unit、palette switch時は
それぞれ2,152と2,204です。したがってN2 DEBUG full-height H40 frameはVBlank 1に
3,200 unit、VBlank 2にpattern用1,252 unit、palette switch時は996 unitを持ちます。
40x19 DEBUG frameのreserveは1,372 unit、palette switch時は1,628 unitだけです。
scroll buildは固定のscroll項 — trim済みbandに対するfull bandの超過分と、CPU
writeするHScroll/VScroll対の16 unit（full-height H40では計40 unit）— を加え、
vertical windowはwrapするplane行の分としてさらに256 unitをruntimeで加えます。
scroll frameはinline CRAM imageを運ばないため、palette switch変種は適用されません。

DMA runが残budget境界を越える場合はrun長に関係なくそこで正確に分割し、次の
fresh VBlank headから続きを行います。Pattern tail後に取り置いたreserveを戻し、
同じVBlank内にまだいる場合だけname-table/HUD/CRAM publication shared pathを許可します。
VBlank statusはV counterの前後で確認し、terminalの`FC..FF` lineは拒否します。
どれかを満たさなければfresh VBlankを待ちます。

multi-budget DEBUG pattern transferでは、Mainは最初のtransfer budget後、次のfresh
VBlank待ちより前にstableなHUD fieldをformatします。最後のpattern word後は、
transfer終了時に確定するfieldとpalette segmentだけを`dbg_row`へpatchします。
Exact-band movie NT DMAとWindow/SAT HUD DMAは、同じadmitted VBlankの別々のmember
として実行します。CPU VDP-portによるHUD republishは行いません。Runtime VBlank budget
1〜4のexact logical pattern word counterはweighted capacity chargeと分離して保持し、
`transfer_vblanks`が5本目以降のbudgetを可視化します。Admission checkは各display
DMAの正確な物理word数をchargeします。

Sub wait loopは、別のopportunistic sector pumpより先にpending `CMD_SWAP`を
処理します。Mainが本当にidleな間はCD pumpを続けますが、将来payloadの処理が
pending handoffを遅らせることはできません。

## Map測定値の再現

Managed Python環境と明示的なprofileを使います。

```sh
tools/python.sh tools/check_player_ring.py \
  --constants out/PROFILE/player_constants.inc \
  --extension tmp/PROFILE/build/movieplay_sp_ext.bin \
  --extension-constants tmp/PROFILE/build/sp_extension.inc
make movieplay CONFIG=profiles/PROFILE.toml \
  DEBUG=1 MAIN_CODEGEN=1 PLAYER_SPECIALIZE=1

~/toolchains/mars/m68k-elf/bin/m68k-elf-size -A \
  tmp/PROFILE/build/movieplay_ip.o \
  tmp/PROFILE/build/movieplay_sp.o
```

`SP-RES`のloaded sizeは`tmp/PROFILE/build/movieplay_sp.bin`のlinked size
です。この文書のaddressやsizeを改訂する前に、rebuild、verify付きpack、
DEBUG recording、HUD gateを完了します。
