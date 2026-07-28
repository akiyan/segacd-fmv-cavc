EN / [JP](#jp)

# On-hardware DEBUG HUD

This document is the complete reference for the values-only playback HUD drawn
by `boot/movieplay_ip.s` in `DEBUG=1` builds. It covers the runtime movie HUD,
not the minimal four-digit boot preload counter and not the offline analysis
overlay documented in [`ANALYSIS.md`](ANALYSIS.md). The boot counter reuses the
same 16 hexadecimal glyphs; their VRAM is fixed at `0xD000` (tiles 1664..1679)
in the unused `0xD000`-`0xDFFF` gap between the two name tables, identical in
DEBUG and release builds. The resident pool therefore has 1535 slots and both
build types share the same pool shape.

The HUD answers three different questions at once:

1. Which movie frame and palette segment are actually visible?
2. Is the Sub CPU keeping the CD stream and audio ready?
3. Is the Main CPU finishing pattern transfer before the display deadline?

It is deliberately diagnostic. A nonzero value is not automatically a codec
failure, and several fields show only the low byte of a larger counter.

## Enabling the HUD

Build the profile with DEBUG enabled:

```sh
make disc CONFIG=profiles/PROFILE.toml DEBUG=1
```

Specialized H32 and H40 DEBUG builds use the same 63-cell combined layout.
H32 wraps it after 32 cells and H40 after 40 cells. Release builds omit it.

`tools/record_movie.sh` uses a DEBUG disc by default. Release builds omit the
HUD and use a slip-triggered CRAM0 red indicator. DEBUG builds keep the HUD
colours stable and expose slips through `S`.

## Physical layout

The hardware draws hexadecimal values only. There are no labels, spaces, or
separators in the actual image. Spaces below show the field boundaries:

```text
row 0 common: FFFF PP SS DD RR LL CC WW MM AA UUUU NN JJ
H32 row 0:   FFFF PP SS DD RR LL CC WW MM AA UUUU NN JJ QQ
H32 row 1:   QQ VV OO EE GGGG KK HHHH XXXX YYY ZZZ T II
H40 row 0:   FFFF PP SS DD RR LL CC WW MM AA UUUU NN JJ QQQQ VV OO EE
H40 row 1:   GGGG KK HHHH XXXX YYY ZZZ T II
```

The fixed interpretation order is:

```text
F / P / S / D / R / L / C / W / M / A / U / N / J / Q / V / O / E / G / K / H / X / Y / Z / T / I
```

H32 and H40 use the same logical field stream. Every digit occupies one 8x8
cell. The four-digit signed PrgBuf minimum `Q`, the three flip-phase fields,
and `G/K/H/X/Y/Z/T/I` follow the 30-cell common prefix. H32 fills its remaining
two row-0 cells with the first half of `Q`, then continues the other 31 cells
on row 1. H40 fits `Q/V/O/E` on row 0 and continues the other 23 cells on
row 1.

| Field | HUD row | Cell columns | Native pixel range | Digits |
|---|---:|---:|---:|---:|
| `F` | 0 | 0-3 | x=0-31 | 4 |
| `P` | 0 | 4-5 | x=32-47 | 2 |
| `S` | 0 | 6-7 | x=48-63 | 2 |
| `D` | 0 | 8-9 | x=64-79 | 2 |
| `R` | 0 | 10-11 | x=80-95 | 2 |
| `L` | 0 | 12-13 | x=96-111 | 2 |
| `C` | 0 | 14-15 | x=112-127 | 2 |
| `W` | 0 | 16-17 | x=128-143 | 2 |
| `M` | 0 | 18-19 | x=144-159 | 2 |
| `A` | 0 | 20-21 | x=160-175 | 2 |
| `U` | 0 | 22-25 | x=176-207 | 4 |
| `N` | 0 | 26-27 | x=208-223 | 2 |
| `J` | 0 | 28-29 | x=224-239 | 2 |
| `Q` (H32, high/low halves) | 0 / 1 | 30-31 / 0-1 | x=240-255 / x=0-15 | 2+2 |
| `V` (H32) | 1 | 2-3 | x=16-31 | 2 |
| `O` (H32) | 1 | 4-5 | x=32-47 | 2 |
| `E` (H32) | 1 | 6-7 | x=48-63 | 2 |
| `G` (H32) | 1 | 8-11 | x=64-95 | 4 |
| `K` (H32) | 1 | 12-13 | x=96-111 | 2 |
| `H` (H32) | 1 | 14-17 | x=112-143 | 4 |
| `X` (H32) | 1 | 18-21 | x=144-175 | 4 |
| `Y` (H32) | 1 | 22-24 | x=176-199 | 3 |
| `Z` (H32) | 1 | 25-27 | x=200-223 | 3 |
| `T` (H32) | 1 | 28 | x=224-231 | 1 |
| `I` (H32) | 1 | 29-30 | x=232-247 | 2 |
| `Q` (H40) | 0 | 30-33 | x=240-271 | 4 |
| `V` (H40) | 0 | 34-35 | x=272-287 | 2 |
| `O` (H40) | 0 | 36-37 | x=288-303 | 2 |
| `E` (H40) | 0 | 38-39 | x=304-319 | 2 |
| `G` (H40) | 1 | 0-3 | x=0-31 | 4 |
| `K` (H40) | 1 | 4-5 | x=32-47 | 2 |
| `H` (H40) | 1 | 6-9 | x=48-79 | 4 |
| `X` (H40) | 1 | 10-13 | x=80-111 | 4 |
| `Y` (H40) | 1 | 14-16 | x=112-135 | 3 |
| `Z` (H40) | 1 | 17-19 | x=136-159 | 3 |
| `T` (H40) | 1 | 20 | x=160-167 | 1 |
| `I` (H40) | 1 | 21-22 | x=168-183 | 2 |

The common part covers 30 cells or 240 pixels. The complete HUD covers 32
cells on H32 row 0 plus 31 on row 1, or 40 cells on H40 row 0 plus 23 on row 1.
It can cover active picture content; it is not repositioned around
letterboxing.

For any recording that can proceed to compilation or upload, the complete first
movie loop produces a binary `gate` (`PASS` or `FAIL`) and a separate
three-state `alert` (`NONE`, `WARNING`, or `FAIL`). Alerts `NONE` and `WARNING`
are upload-capable and map to gate `PASS`; alert `FAIL` maps to gate `FAIL`.
The deprecated `status` and `pass` fields remain in gate JSON for compatibility.
`S/D/R` must remain zero. `M` and `J` thresholds follow the profile's player
cadence. Fixed-N allows the `N-1`
intervening pattern-work fields: fixed N2 fails when `M>01`, while fixed N4
fails when `M>03`. Delivery-paced content may use all display fields in one
content frame; 24 fps fails when `M>03`. The largest passing `J` is
normal-ceiling-to-physical-end minus one
KiB: `2D` at 15fps, `1E` at 24fps, and `19` at 30fps. Values above the normal
jitter interval (`28`, `19`, or `14` respectively) show that
sector-granular occupancy crossed the shared 416 KiB delivery observation
boundary and entered the final physical guard left outside the schedule.
Report the value, but a `J` within the cadence-specific passing limit does not
by itself require another confirmation or fail the recording. `C` has no gate
threshold and never changes the gate result; it remains a diagnostic measure
of Sub-side CD work. Report all `S/D/R/M/J` gate maxima when gate is `PASS` and
report the diagnostic C maximum. When the enclosing task already authorizes
publication, continue without requesting another approval merely because the
gate ran.

For fixed-N playback, the analyzer also measures the visible duration of each
timed, nonterminal movie frame from consecutive `F` transition capture
positions. A duration other than N VBlanks raises alert `WARNING` while
retaining gate `PASS`; it records the complete histogram and every affected
frame in the gate JSON. Frame 0 and the terminal frame are excluded because
their timed display extents are not both observable. Delivery-paced playback
records the histogram without applying an exact-duration warning.

For every gate result, the analyzer and `/hudline` report the minimum, mean,
median, and maximum of both `C` and `A` across the timed first loop and preserve
them in the gate JSON and hudline receipt. When `G` is present, they also
report its minimum, mean, median, and maximum after separating the packed `B`
marker. `H` reports the exact physical peak and `X` reports the reader lead.
`Y/Z/T/I` report the Main pattern-transfer split and its exit phase.
`G`, `B`, `K`, `H`, `X`, `Y`, `Z`, `T`, and `I` are diagnostic only and
never alter the gate.

The black player-only frame -1 uses `F=FFFF` before frame 0. It is an OCR
sentinel, not a stream frame, and is never written as a HUD TSV row. Frame 0
is an untimed boot construction, not a playback measurement. Keep it
only for first-loop sequence completeness and frame-axis alignment. Exclude
all of its HUD values from gate maxima, warning/failure events, timeline bars,
dynamic scale maxima, OCR aggregates, and derived VBlank cadence statistics.
The frame-0 extent of every `/hudline` metric row is blank. The final frame's
derived VBlank is also unknown because the next movie-frame transition is not
available.

## At-a-glance field reference

| Field | Owner | Scope | Meaning | Healthy interpretation |
|---|---|---|---|---|
| `F` | Main | current state | Visible movie frame number; `FFFF` is player-only frame -1 | `FFFF`, then `0000`, then movie cadence |
| `P` | Main | current state | Zero-based CRAM palette-segment number | Changes only at expected palette boundaries |
| `S` | Sub | cumulative | CD sector-slip/re-seek recovery count | `00` throughout a clean run |
| `D` | Sub | cumulative | Control-stream frame-sequence mismatch count | `00` throughout a clean run |
| `R` | Sub | cumulative | RF5C164 write-pointer re-sync count | `00` is ideal |
| `L` | Sub | current state | Audio write lead, in units of 256 decoded bytes | Stable and comfortably inside the configured lead range |
| `C` | Sub | per frame | Blocking CD sector pumps before control execution | `00` means control was already ready |
| `W` | Main | per frame | Main wait for Sub handoff, in approximate scanlines | Small and stable |
| `M` | Main | per timed frame | VBlank starts waited by the Main pattern path; frame 0 is excluded because it is an untimed boot construction | `00` or `01`; `02+` proves an extra spill |
| `A` | Sub | per frame | ADPCM decode phase time | Stable band for the same profile |
| `U` | Main | per frame | Main pattern-transfer elapsed time | Below the frame's available transfer window |
| `N` | Main | per frame | Source-aware cold-run descriptor count | Content-dependent; correlate with `U` |
| `J` | Sub | cumulative peak | Maximum streamed PrgBuf occupancy above the fps-derived normal ceiling | `00` means the jitter headroom was never used |
| `Q` | Sub | per frame | Minimum signed logical PrgBuf balance, in exact 32-byte patterns | Positive is supplied data; `0000` is truly empty; `FFFF` is one-pattern underflow |
| `G` | Sub | per frame | Longest interval outside a CDC pump opportunity, in 30.72 us ticks | A stable band means no exceptional Sub-side pump neglect |
| `B` | Sub | per frame | APPLY control-queue back-pressure rejected a pump (derived from `G` bit 15) | `00`; `01` proves the control queue blocked continuous delivery |
| `K` | Sub | cumulative | MSF sequence-gap recovery count | Compare with `S`; `S-K` is the CDC_TRN retry-exhaustion count |
| `H` | Sub | per frame | Maximum physical PrgBuf occupancy, in exact 32-byte patterns | Below `3440` stays below the 418 KiB payload back-pressure boundary |
| `X` | Sub | per frame | CD reader position ahead of the next frame expansion; high byte is complete frame slots, low byte is sector position in the current slot | Read with `H`; large lead is safe only while every destination retains space |
| `Y` | Main | per frame | Exact pattern-transfer words issued in the first transfer VBlank | Divide by 16 for whole 32-byte patterns; read with `Z/T` |
| `Z` | Main | per frame | Exact pattern-transfer words issued in the second transfer VBlank | The second share should leave enough time for name table, HUD, palette work, and flip |
| `T` | Main | per frame | Number of VBlanks that carried pattern transfer | `01` or `02` is the intended one-/two-VBlank path; `03+` proves a further transfer spill |
| `I` | Main | per frame | V-counter when pattern transfer ended, before the remaining deadline work | Read with `Z` and the following row's `V/O`; it measures phase, not gate status |
| `V` | Main | previous frame | V-counter at the last accepted display flip | `E0` = flip at the VBlank start; higher blank lines mean the flip ran late inside its blank |
| `O` | Main | previous frame | That flip's interval excess over 1024 stopwatch ticks | About `3E` (62 = nominal 1086-tick N2 interval); `FF` marks a slipped 3-field frame |
| `E` | Main | per frame | Pass2 entry delay since the previous flip, in 4-tick units | Below one field (`88` = 544 ticks) with margin; approaching the field-1 blank end means the transfer is about to miss its VBlank |

`S`, `D`, and `R` are cumulative counters. They should be read as transitions:
once incremented, they remain nonzero until playback restarts, and the displayed
low byte wraps from `FF` to `00`. `J` is also cumulative but retains the
largest observed excess rather than counting events. `C`, `W`, `M`, `A`, `U`,
`N`, `Q`, `G`, `B`, `H`, `X`, `Y`, `Z`, `T`, and `I` describe one frame.
`K` is cumulative. `F`, `P`, and `L` describe current player state.
`V` and `O` are sampled at `do_flip` *after* the flip register write, so the
row that carries them was built one frame later: frame `F`'s row shows the
flip that published frame `F - 1`. Shift by one frame when correlating them
with per-frame workload. `E` is sampled during frame `F`'s own build, before
its transfer VBlank wait, and needs no shift.

## Field details

### `F`: displayed frame

`F` is the full 16-bit movie frame number. Before frame 0, the player clears
the visible movie table to black and publishes the reserved `FFFF` value for
frame -1. Frame -1 exists only in the player/HUD: sim, routing, controls, and
the HUD TSV still begin at frame 0 (`0000`).

For streamed frames, the Main CPU formats the number into the inactive table
and selects that table with the same Plane A flip that publishes the picture,
so the value and image identify the same frame.

The current stream format holds fewer than 65536 frames, so `F` does not wrap
inside one valid playback loop and `FFFF` remains unambiguous. Loop playback
shows frame -1 again after the end hold, then returns to `0000`.

### `P`: active palette segment

`P` is the low byte of the zero-based palette-segment number currently used by
CRAM. Segment 0 displays as `00`. The stream's palette reference is stored as
segment plus one, but the Main CPU subtracts one before updating this HUD state.

`P` reports the active state, not merely a switch command. It therefore remains
constant between CRAM changes. The current table capacity is 64 segments, so a
valid stream never needs the field's byte wrap.

### `S`: CD sector slips and re-seek recovery

`S` is the low byte of the cumulative `slip_count`. The Sub CPU increments it
when continuous CD delivery loses or skips a sector and the recovery path must
re-establish the read position. A new increment marks a real streaming
incident and is a likely visual or timing glitch boundary.

`S=00` is required for a clean qualified run. Because only the low byte is
shown, compare adjacent frames rather than treating a later `00` as proof that
no earlier slips occurred.

### `D`: control-stream desynchronization

Every control block carries a frame sequence. `D` increments when that sequence
does not match the frame the Sub CPU expected. The player rejects the mismatched
control and holds the previous image instead of walking corrupt data.

`D` is therefore more severe than ordinary encoder Miss: it means the runtime
stream position is wrong. A clean run keeps `D=00`.

### `R`: audio pointer re-syncs

The RF5C164 writer normally remains ahead of playback. `R` increments when the
measured lead leaves the configured `[SYNC_MIN, SYNC_MAX]` range and the writer
jumps to `play + SYNC_LEAD`. The jump restores safety but can be audible.

`R=00` is ideal. Diagnose an increment together with the preceding `L` trend;
the transition matters more than the persistent nonzero value afterwards.

### `L`: audio lead

`L` is the high byte of the current ring distance from the RF5C164 play pointer
to the write pointer. One displayed unit is 256 decoded sample bytes:

```text
lead_bytes is approximately L * 256 through L * 256 + 255
```

With the current constants, normal re-sync placement uses `SYNC_LEAD=0x3000`,
which appears near `L=30`. `SYNC_MAX=0x6800`, which appears near `L=68`.
Approaching `00` means the reserve is draining; approaching or exceeding the
upper boundary means the writer has run too far ahead. Convert bytes to time
using the profile's effective playback sample rate.

### `C`: blocking CD work on the Sub critical path

`C` is the low byte of two per-frame counts added together:

- pumps needed to finish this frame's control sectors;
- pumps needed while a preceding BODY payload or padding slot was still draining.

Each pump drains one physical sector. `C=00` means the needed control was
already armed when `process_frame` reached it. A small nonzero value is not a
sector slip; it means delivery work landed directly on the current frame's
critical path. `C` is excluded from the gate and has no threshold. Persistent
C, especially with rising `W`, is stronger diagnostic evidence than an
isolated peak, but the actual playback result determines whether it matters.

### `W`: Main wait for the Sub CPU

At `CMD_SWAP`, the Main CPU samples the V counter, waits for the Sub CPU's
`STAT_READY` or `STAT_END`, then samples it again. `W` is the masked eight-bit
difference, expressed as approximate scanlines.

This includes whatever prevents the Sub from completing the handoff, such as
control delivery, expansion, ADPCM work, or a late command response. It is not
a cycle-accurate timer and wraps at 256. Use it for relative comparisons and
spikes within the same mode, not as an absolute duration measurement.

### `M`: Main pattern-path VBlank waits

`M` counts VBlank starts consumed by the Main-side pattern transfer path for
the current frame. Display cadence waiting is deliberately excluded. This
makes `M` a deadline diagnostic rather than a restatement of 15/24/30 fps
pacing.

On fixed-N H40, the final cold tail may use the same deadline VBlank as the
name-table DMA and flip when the guarded residual budget is sufficient. That
shared target wait is display cadence, so it is excluded from `M`; only the
earlier intervening pattern-work VBlank starts remain. A fallback that needs
a fresh flip VBlank likewise remains display work rather than pattern work.

For fixed-N playback, the normal region is `M=00..N-1`; reaching `N` proves
that pattern work spilled into the fixed display deadline. Thus fixed N2 allows
`M<=01`, and fixed N4 allows `M<=03`. Delivery-paced content uses the automatic
limit `ceil(60000/1001/fps)`. Correlate `M` with `U` and `N` to distinguish
total transfer volume from run fragmentation.

### `A`: Sub ADPCM decode time

The Sub CPU measures the checkpointed IMA decode phase with the Mega-CD
stopwatch. The player shifts the raw value right by two before displaying its
low byte:

```text
one A unit = 4 * 30.72 us = approximately 0.12288 ms
```

For example, `A=40` means about 7.86 ms. At low frame rates, the longer ADPCM
decoder periodically services the CDC, so `A` can also
include that intentionally interleaved pump work. It does not measure the
subsequent RF5C164 wave-RAM write phase.

### `U`: Main pattern-transfer time

`U` displays four hexadecimal digits from the Main CPU's Mega-CD stopwatch.
One tick is 30.72 us. Measurement begins at the first cold run and ends after
the final DMA repair or short-run CPU write. It includes waits between pieces
when a long run must cross a VBlank word-budget boundary.

The hardware counter is 12-bit, and the player masks the difference to
`0x0FFF`. It therefore wraps after 4096 ticks, about 125.83 ms. A frame with no
cold runs reports `0000`.

### `N`: packed cold-run count

`N` is the low byte of the source-aware cold-run descriptor count constructed
for the frame. A run groups consecutive VRAM slots from the same physical
pattern source. Prg, the parity-selected WordBuf, and DicBuf boundaries split
runs even when the destination slots are consecutive.

`N` is not the cold-tile count and is not the number of physical VDP DMA
commands. One- and two-tile runs use CPU writes. Longer runs use DMA and can be
split again at VBlank boundaries. `N` measures fragmentation before those
hardware transfer choices.

The whole-movie `/hudline` `N COLD RUNS` row uses the maximum timed `N` value
present in that HUD TSV as its vertical scale. Untimed frame 0 is excluded from
the maximum.

### `J`: streamed PrgBuf jitter-reserve high-water mark

`J` is the maximum simultaneous streamed PrgBuf occupancy above the
fps-derived normal ceiling observed since BODY streaming began. That ceiling
is 376 KiB at 15fps, 391 KiB at 24fps, and 396 KiB at 30fps. It is rounded
upward to KiB and displayed in hexadecimal. `J=00` proves that occupancy never
crossed the ceiling; `J=01` means a nonzero excess of at most 1 KiB, and
`J=0A` means a maximum excess of at most 10 KiB.

The Sub CPU samples occupancy immediately after each BODY payload sector is
appended. Only an append can raise the high-water mark, so polling and pattern
consumption need no extra sampling. The separate frame-0 block temporarily
stored at `F0PAT_TMP` does not pass through this path and is deliberately
excluded. The field measures simultaneous occupancy, not whether a circular
read or write pointer happened to enter the physical address range above that
stream's normal boundary.

### `Q`: signed per-frame PrgBuf minimum

`Q` tracks a separate signed logical balance: each BODY payload sector adds 64
patterns, and each Prg source run subtracts its exact pattern count. The player
publishes the minimum balance reached during the frame as a four-digit signed
16-bit hexadecimal value. `0001` means one 32-byte pattern remained, `0000`
means the logical supply became exactly empty, and `FFFF` means it consumed one
pattern before that pattern had arrived.

This counter exists because circular pointer arithmetic cannot identify an
underflow after it happens. If the pop head passes the append tail, the modulo
distance looks almost full and can trigger payload back-pressure. `Q` retains
the signed fact for the whole frame even if a later sector repays the debt.
It is diagnostic only and does not change the upload gate.

### `H` / `X`: physical PrgBuf pressure and CD reader lead

`H` is the largest physical PrgBuf occupancy reached during one frame. The Sub
CPU initializes it from the exact circular-ring distance and updates it after
every 2 KiB payload append. One displayed unit is one 32-byte pattern, so
`H=3440` is 418 KiB: the point at which the next payload poll is refused.
Unlike sticky whole-run `J`, `H` returns to the current occupancy at each frame
boundary and shows when pressure was present. The `/hudline` H row draws the
418 KiB back-pressure guide.

`X` records how far the physical CD reader has advanced relative to the next
frame expansion. Its high byte is the number of complete frame slots between
the reader and that consumer position; its low byte is the sector index inside
the current slot. The value retains the furthest lexicographic position reached
during the frame. `/hudline` splits it into `XH READER AHEAD` and
`XL READER SLOT` rows. Read `X` with `H`: reader lead is useful prefetch while
the destination buffers have space, but lead concurrent with `H=3440` proves
that physical PrgBuf back-pressure can stop a continuously arriving payload
sector. Both fields are observational and have no upload-gate threshold.

### `Y` / `Z` / `T` / `I`: Main pattern-transfer split

`Y` and `Z` are the exact word counts issued by the pattern path in its first
and second transfer VBlanks. Sixteen words make one 32-byte pattern. A DMA run
may be cut at a word-budget boundary, so either value can contain a partial
pattern even though their sum still accounts for the exact transfer.

`T` counts every VBlank that carried pattern work. `T=01` means all pattern
work fit in one VBlank, `T=02` means the intended two-VBlank split was used,
and `T=03` or more proves that the transfer itself needed an additional blank.
When `T<=02`, `Y+Z` equals the frame's complete pattern word count. When
`T>=03`, `Y+Z` intentionally covers only the first two VBlanks.

`I` is the raw V-counter high byte sampled when the pattern path finishes,
before HUD publication, name-table DMA, CRAM replacement, and display flip.
Read it with the second share `Z` and with `V/O` from the following HUD row.
It distinguishes a late pattern tail from work that spills after the tail.
All four fields are observational and have no upload-gate threshold.

### `G` / `B` / `K`: Sub pump and control back-pressure

`G` is the longest interval in one frame between Sub-CPU CDC service
opportunities. Its low 12 bits use the Mega-CD stopwatch unit of 30.72 us.
The timer restarts after a sector transfer or re-seek recovery, so `G` measures
time spent outside the pump path rather than the recovery work itself.

`B` is decoded from `G` bit 15 as a separate Boolean row. It is set when
APPLY-ring occupancy reaches the `APPLY_SIZE - 4 KiB` guard (30 KiB with the
current 34 KiB ring) and the Sub CPU therefore refuses the next control-sector
pump. The player temporarily stores this marker in the unused high bit of the
per-frame control-wait counter, then combines it with `G` only while formatting
the HUD; it does not disturb the `G` maximum or the displayed low-byte `C`.

`K` is the cumulative count of `S` incidents caused specifically by an MSF
sector-sequence gap. `S` remains the total recovery count, so `S-K` identifies
CDC_TRN retry-exhaustion recoveries modulo 256. All three fields are diagnostic
and have no upload-gate threshold.

### `V` / `O` / `E`: flip phase and Pass2 entry phase

`V` is the raw V-counter high byte read immediately after the accepted
display flip's register write. `E0` (line 224) is a flip taken exactly at
the VBlank start — the dominant healthy value; higher blank lines mean the
flip ran late inside its blank, and the guarded terminal lines (`FC..FF`)
are never accepted. `O` is the flip-to-flip stopwatch interval minus `N*512`
ticks, clamped to `0..FF`: the nominal fixed-N2 interval of ~1086 ticks reads
as about `3E` (62), while fixed N4's ~2172 ticks reads as about `7C` (124).
Late-in-blank flips read higher, and a sufficiently slipped frame saturates at
`FF`. Both describe the flip that published the
*previous* frame (see above).

`E` is sampled at the Pass2 entry (`bf_dma`), before its VBlank wait: the
stopwatch distance from the previous flip in 4-tick units. It measures the
complete pre-transfer Main phase — CMD_SWAP wait (`W`), control parse, the
bitmap/list shadow walk, and the name-table blit — against the hard
deadline: Pass2 must enter before field 1's
VBlank (one field = 543 ticks = `E` about `88`) or the transfer consumes
the flip's own VBlank and the frame slips to three fields. `U` alone
cannot show this because its stopwatch starts only inside the transfer
VBlank.

## Reading combinations

| Observation | Likely interpretation |
|---|---|
| `S`, `D`, and `R` remain `00` | No detected CD loss, control desync, or audio pointer jump |
| `S` increments, then `D` remains `00` | Sector recovery occurred without losing control alignment |
| `D` increments | A control block was rejected and the previous image was held |
| `L` trends toward a boundary, then `R` increments | Audio reserve left its safe range and the write pointer jumped |
| `C` and `W` rise together | CD/control work is delaying the Sub-to-Main handoff |
| `A` rises with `W`, while `C` stays low | ADPCM decode or its internal low-rate CDC service is the stronger Sub-side cost |
| `N` rises with `U` | Run fragmentation is increasing Main fixed transfer overhead |
| `U` rises while `N` stays modest | Larger pattern volume or VBlank splitting dominates rather than descriptor count |
| `T=02` and `Y+Z` matches the frame's pattern words | The intended two-VBlank pattern split completed |
| `T>=03` | Pattern transfer itself consumed a third or later VBlank |
| `T=02`, `I` is early, but the following row's `O=FF` | Pattern work finished in the second blank; later HUD/name-table/palette/flip work caused the visible hold |
| `T=02` and `I` is near the terminal blank | The second pattern share left little margin for the remaining deadline work |
| `M` reaches `02` or more | Main pattern work crossed an extra VBlank deadline |
| `P` changes with stable `S/D` | Normal scheduled CRAM segment switch |
| `J` changes from `00` | Streaming occupancy used part of the physical jitter reserve |
| `J` rises again later | Timed playback exceeded the previous startup/runtime high-water mark |
| `Q=0000` | Logical PrgBuf supply became exactly empty during that frame |
| `Q=8000..FFFF` | Signed PrgBuf balance went negative; decode as `Q-0x10000` patterns |
| `H=3440` while `X` is ahead | The physical PrgBuf reached payload back-pressure while the CD reader was prefetched ahead |
| `H` falls but `J` stays high | Current pressure recovered; `J` is retaining the earlier whole-run peak |
| `G` remains in its normal band at an `S` transition | The incident was not caused by an exceptional interval outside the CDC pump |
| `B=01`, followed by a rise in `K`/`S` | APPLY control back-pressure blocked delivery before an MSF-gap recovery |
| `K` rises by the same amount as `S` | The observed recoveries are MSF sequence gaps, not CDC_TRN retry exhaustion |

These are correlations, not standalone proofs. Use native lossless capture and
the packed stream when investigating a regression.

## How the HUD is rendered

The HUD does not use the Window plane. For each frame the Main CPU:

1. builds the complete next movie name table in the inactive Plane A table;
2. formats the HUD into one 126-byte Main-RAM staging block in both modes;
3. overwrites 32 cells of H32 row 0 plus 31 of row 1, or 40 cells of H40 row 0
   plus 23 of row 1;
4. selects that completed table with the same register-2 flip as the movie.

The inactive tables are at VRAM `0xC000` and `0xE000`. Publishing the HUD uses
31 longword writes plus one word write in either mode and no DMA. Unoccupied cells retain
their movie entries, which avoids exposing an unrelated Plane B frame.

The final flip has a terminal-VBlank guard: V-counter lines `FC` through `FF`
are rejected so the table is not selected at the end-of-blank race.

## Hex font and CRAM stability

The HUD font contains exactly 16 patterns, one for each hexadecimal digit.
Each 8x8 glyph has:

- a top-row four-bit barcode, with two pixels per bit, most-significant bit
  first;
- a compact 6x7 human-readable hexadecimal glyph below it.

The 16 font patterns are uploaded once at startup to VRAM `0xD000` (tiles
1664..1679); the name-table cells reference those fixed tile indices directly
(11-bit indices reach the whole 2048-tile space). The player expands source
colour 0 to P0/index1 and source colour 1 to P0/index15 when uploading the
font. The encoder and packer canonicalize these
as the globally darkest and brightest usable colours across every palette
segment. Consequently CRAM switches do not recolour or blink the HUD, and no
font scan, recolour, DMA, or extra VBlank wait is needed per frame.

## OCR and recording analysis

Read a native screenshot with:

```sh
tools/python.sh tools/read_frameno.py frame.png
```

The result includes every field and a confidence value, for example:

```text
frame.png -> F=012A(0.99) P=03(0.99) S=00(0.99) ...
```

`read_frameno.py` decodes the barcode and checks the lower glyph with normalized
correlation. Legacy common and one-row H40 layouts remain explicit. Current
recordings use `HUD_H32_COMBINED_LAYOUT` or `HUD_H40_COMBINED_LAYOUT`; the
reader maps every logical digit through the mode-specific 32- or 40-cell wrap,
including the H32 `Q` split. Supplying either profile makes the recording
analyzer select the matching layout automatically; `--combined-fields` is only
needed when no profile is supplied.

For a complete recording, `harness/startup_resync/analyze.py` groups repeated
60 Hz capture frames by `F`, retains per-field confidence, and reports counter
transitions. It prefers a valid `F0000` run immediately after `F=FFFF`, which
makes first-loop head selection exact; recordings made before the sentinel
retain the plausible-sequence fallback. The `FFFF` group itself is discarded.
The analyzer reports the selected method and stores its capture indices in the
gate JSON `ocr_start_anchor` object together with the corresponding capture
times. Publication recordings remain untrimmed. Their CRAM chapter offset uses
the exact `F=FFFF` to `F=0000` transition stored in this object, avoiding a
second visual head search.

Write the complete per-frame series as the canonical project TSV:

```sh
tools/python.sh harness/startup_resync/analyze.py \
  videos/STEM_emu_lossless.mkv profiles/PROFILE.toml \
  --tsv videos/STEM_emu_hud.tsv \
  --gate-json videos/STEM_emu_hud_gate.json \
  --expected-frames FRAME_COUNT
```

The log is UTF-8 with a header row, tab separators, LF line endings, and a
`.tsv` extension. With the required profile argument, its permanent file is
written as
`logs/<datetime>_<profile>_<sha10>_eNN_pNN_hud.tsv`; the `--tsv` path becomes
a run-specific compatibility symlink to that log. Project-owned HUD logs are
never comma-delimited.

For current H32/H40 combined HUDs, the TSV preserves `Q` as
`prgbuf_min_patterns_raw16`, decodes its signed value into
`prgbuf_min_patterns_signed`, and writes the positive debt magnitude as
`prgbuf_underflow_patterns`. The combined pump diagnostic also writes
`sub_poll_gap_ticks`, `sub_poll_gap_ms`, `apply_guard_blocked`,
`slip_msf_gap_count`, and `slip_trn_retry_count`. The physical-buffer
diagnostic writes `prgbuf_physical_peak_patterns`, `reader_ahead_raw16`,
`reader_ahead_frames`, and `reader_slot_sector`. `/hudline` and `/mixline`
always include those rows plus G/B and H/X summaries when the columns are
present. The pattern-split diagnostic writes `pattern_vblank1_words`,
`pattern_vblank2_words`, `pattern_transfer_vblanks`, and
`pattern_exit_vcounter`; the same renderers preserve those rows and maxima.

The reproducible glyph/layout proof is:

```sh
tools/python.sh harness/hud_ocr/verify.py
```

## Maintenance contract

Any field, width, or ordering change must update these together:

- `boot/movieplay_ip.s` `prepare_dbg` and `publish_dbg`;
- `tools/read_frameno.py` layout and field decoding;
- `harness/hud_ocr/verify.py` layout/OCR proof;
- this document and the short README summary;
- field-specific verification such as `harness/pipeline_speedup/verify_run_hud.py`.

Keep the HUD values-only unless a new layout is deliberately qualified. Adding
labels consumes movie cells and Main-side publication work; it is not a free
presentation change.

---

<a id="jp"></a>

# 実機DEBUG HUD

この文書は、`DEBUG=1` buildで`boot/movieplay_ip.s`が描くvalues-only playback HUDの
完全なreferenceです。Runtime movie HUDを対象とし、最小4-digit boot preload counterや、
[`ANALYSIS.md`](ANALYSIS.md)のoffline analysis overlayは対象外です。Boot counterも
同じ16個のhex glyphを使います。Glyph VRAMは2つのname table間の未使用gap
`0xD000..0xDFFF`にある`0xD000`（tile 1664..1679）で、DEBUG/release共通です。
Resident poolは1535 slotで、両buildが同じpool shapeを使います。

HUDは同時に3つの問いへ答えます。

1. どのmovie frameとpalette segmentが実際に見えているか
2. Sub CPUがCD streamとaudioをreadyに保てているか
3. Main CPUがdisplay deadline前にpattern transferを完了しているか

これはdiagnostic表示です。Nonzero valueが必ずcodec failureを意味するわけではなく、
一部fieldは大きなcounterのlow byteだけを表示します。

## HUDの有効化

ProfileをDEBUG付きでbuildします。

```sh
make disc CONFIG=profiles/PROFILE.toml DEBUG=1
```

Specialized H32/H40 DEBUGは同じ63-cell combined layoutを使います。
H32は32 cell、H40は40 cellで折り返します。Release buildはHUDを省きます。

`tools/record_movie.sh`は既定でDEBUG discを使います。Release buildはHUDを省き、
slip-triggered CRAM0 red indicatorを使います。DEBUG buildはHUD colourを固定し、
slipを`S`で表示します。

## 物理layout

Hardware上はhex valueだけを描き、label、space、separatorはありません。下記spaceは
field boundaryを示します。

```text
row 0 common: FFFF PP SS DD RR LL CC WW MM AA UUUU NN JJ
H32 row 0:   FFFF PP SS DD RR LL CC WW MM AA UUUU NN JJ QQ
H32 row 1:   QQ VV OO EE GGGG KK HHHH XXXX YYY ZZZ T II
H40 row 0:   FFFF PP SS DD RR LL CC WW MM AA UUUU NN JJ QQQQ VV OO EE
H40 row 1:   GGGG KK HHHH XXXX YYY ZZZ T II
```

固定解釈順は次のとおりです。

```text
F / P / S / D / R / L / C / W / M / A / U / N / J / Q / V / O / E / G / K / H / X / Y / Z / T / I
```

H32とH40は同じlogical field streamを使います。1 digitは1つの8x8 cellです。
30-cell common prefixの後に、4桁のsigned PrgBuf minimum `Q`、3つのflip-phase
field、`G/K/H/X/Y/Z/T/I`が続きます。H32はrow 0の残り2 cellへ`Q`の前半を書き、
残る31 cellをrow 1へ続けます。H40はrow 0へ`Q/V/O/E`、残る23 cellをrow 1へ
続けます。

| Field | HUD row | Cell columns | Native pixel range | Digits |
|---|---:|---:|---:|---:|
| `F` | 0 | 0-3 | x=0-31 | 4 |
| `P` | 0 | 4-5 | x=32-47 | 2 |
| `S` | 0 | 6-7 | x=48-63 | 2 |
| `D` | 0 | 8-9 | x=64-79 | 2 |
| `R` | 0 | 10-11 | x=80-95 | 2 |
| `L` | 0 | 12-13 | x=96-111 | 2 |
| `C` | 0 | 14-15 | x=112-127 | 2 |
| `W` | 0 | 16-17 | x=128-143 | 2 |
| `M` | 0 | 18-19 | x=144-159 | 2 |
| `A` | 0 | 20-21 | x=160-175 | 2 |
| `U` | 0 | 22-25 | x=176-207 | 4 |
| `N` | 0 | 26-27 | x=208-223 | 2 |
| `J` | 0 | 28-29 | x=224-239 | 2 |
| `Q`（H32、前半/後半） | 0 / 1 | 30-31 / 0-1 | x=240-255 / x=0-15 | 2+2 |
| `V`（H32） | 1 | 2-3 | x=16-31 | 2 |
| `O`（H32） | 1 | 4-5 | x=32-47 | 2 |
| `E`（H32） | 1 | 6-7 | x=48-63 | 2 |
| `G`（H32） | 1 | 8-11 | x=64-95 | 4 |
| `K`（H32） | 1 | 12-13 | x=96-111 | 2 |
| `H`（H32） | 1 | 14-17 | x=112-143 | 4 |
| `X`（H32） | 1 | 18-21 | x=144-175 | 4 |
| `Y`（H32） | 1 | 22-24 | x=176-199 | 3 |
| `Z`（H32） | 1 | 25-27 | x=200-223 | 3 |
| `T`（H32） | 1 | 28 | x=224-231 | 1 |
| `I`（H32） | 1 | 29-30 | x=232-247 | 2 |
| `Q`（H40） | 0 | 30-33 | x=240-271 | 4 |
| `V`（H40） | 0 | 34-35 | x=272-287 | 2 |
| `O`（H40） | 0 | 36-37 | x=288-303 | 2 |
| `E`（H40） | 0 | 38-39 | x=304-319 | 2 |
| `G`（H40） | 1 | 0-3 | x=0-31 | 4 |
| `K`（H40） | 1 | 4-5 | x=32-47 | 2 |
| `H`（H40） | 1 | 6-9 | x=48-79 | 4 |
| `X`（H40） | 1 | 10-13 | x=80-111 | 4 |
| `Y`（H40） | 1 | 14-16 | x=112-135 | 3 |
| `Z`（H40） | 1 | 17-19 | x=136-159 | 3 |
| `T`（H40） | 1 | 20 | x=160-167 | 1 |
| `I`（H40） | 1 | 21-22 | x=168-183 | 2 |

共通部は30 cell、240 pixelです。Complete HUDはH32ではrow 0の32 cellとrow 1の
31 cell、H40ではrow 0の40 cellとrow 1の23 cellを使います。Active pictureを
覆う場合があり、letterboxに合わせて移動しません。

Compilationまたはuploadへ進めるrecordingでは、最初のmovie loop全体から2値の
`gate`（`PASS`または`FAIL`）と、別の3段階`alert`（`NONE`、`WARNING`、`FAIL`）を
生成します。Alert `NONE`と`WARNING`はupload可能でgate `PASS`へ、alert `FAIL`は
gate `FAIL`へ対応します。Deprecatedな`status`と`pass` fieldは互換性のためgate
JSONに残します。`S/D/R`は0を維持する必要があります。`M`と`J` thresholdは
profileのplayer cadenceに従います。

Fixed-Nは介在する`N-1`個のpattern-work fieldを使えます。Fixed N2は`M>01`でfail、
fixed N4は`M>03`でfailです。Delivery-paced 24 fpsは`M>03`でfailです。
Passing `J`の最大値はnormal ceilingから
physical endまでの差より1 KiB小さい値で、15 fpsは`2D`、24 fpsは`1E`、30 fpsは
`19`です。Normal jitter interval（それぞれ`28`、`19`、`14`）を超える値は、
共通の416 KiB delivery observation boundaryを越え、schedule外に残した最後の
physical guardへ入ったことを示します。値は報告しますが、cadence固有
passing limit内の`J`だけで再確認やfailにはしません。`C`にはgate thresholdがなく、
gate結果を変えません。Sub側CD workのdiagnosticとして保持します。

Gate `PASS`では全`S/D/R/M/J` gate maximumとdiagnostic C maximumを報告します。
Taskがpublicationを許可済みなら、gate実行だけを理由に追加approvalは求めません。

Fixed-N playbackでは、analyzerは連続する`F` transitionのcapture位置から、timedかつ
nonterminalな各movie frameの実表示時間も測ります。N VBlank以外ならgate `PASS`を
維持したままalert `WARNING`とし、完全なhistogramと該当frameをgate JSONへ記録します。
Frame 0とterminal frameはtimed表示区間の両端を観測できないため除外します。
Delivery-paced playbackはhistogramを記録しますが、exact duration warningは適用しません。

すべてのgate結果で、analyzerと`/hudline`はtimed first loopにおける`C`と`A`それぞれの
minimum、mean、median、maximumを報告し、gate JSONとhudline receiptにも保存します。
`G`がある場合はpacked `B` markerを分離したGのminimum、mean、median、maximumも
報告します。`H`はexact physical peak、`X`はreader leadを報告します。
`Y/Z/T/I`はMain pattern-transfer splitとexit phaseを報告します。
`G/B/K/H/X/Y/Z/T/I`はdiagnostic専用でgateを変えません。

Player-onlyの黒いframe -1はframe 0の前に `F=FFFF` を使います。これはOCR
sentinelでstream frameではなく、HUD TSV rowにも書きません。Frame 0はuntimed boot
constructionで、playback measurementではありません。
First-loop sequenceとframe-axis alignmentのためだけに保持し、全HUD値をgate maximum、
warning/failure event、timeline bar、dynamic scale maximum、OCR aggregate、derived
VBlank cadenceから除外します。`/hudline`の全metric rowでframe-0範囲をblankにします。
Final frameは次のmovie-frame transitionがないため、derived VBlankはunknownです。

## Field早見表

| Field | Owner | Scope | 意味 | Healthyな解釈 |
|---|---|---|---|---|
| `F` | Main | current state | Visible movie frame number。`FFFF`はplayer-only frame -1 | `FFFF`、`0000`、movie cadenceの順 |
| `P` | Main | current state | zero-based CRAM palette-segment number | 予定palette boundaryだけで変化 |
| `S` | Sub | cumulative | CD sector-slip / re-seek recovery count | clean run全体で`00` |
| `D` | Sub | cumulative | control-stream frame-sequence mismatch count | clean run全体で`00` |
| `R` | Sub | cumulative | RF5C164 write-pointer re-sync count | `00`が理想 |
| `L` | Sub | current state | audio write lead。256 decoded byte単位 | configured lead range内で安定 |
| `C` | Sub | per frame | control実行前のblocking CD sector pump | `00`ならcontrol ready済み |
| `W` | Main | per frame | Sub handoff待ち。概算scanline単位 | 小さく安定 |
| `M` | Main | per timed frame | Main pattern pathが待ったVBlank start数。Frame 0は除外 | `00`または`01`。`02+`はextra spill |
| `A` | Sub | per frame | ADPCM decode phase time | 同profileで安定したband |
| `U` | Main | per frame | Main pattern-transfer elapsed time | frameのtransfer window未満 |
| `N` | Main | per frame | source-aware cold-run descriptor count | content依存。`U`と相関を見る |
| `J` | Sub | cumulative peak | fps-derived normal ceilingを超えたstreamed PrgBuf occupancy最大値 | `00`ならjitter headroom未使用 |
| `Q` | Sub | per frame | exact 32-byte pattern単位のsigned logical PrgBuf minimum | positiveは供給済み、`0000`は真のempty、`FFFF`は1 pattern underflow |
| `G` | Sub | per frame | CDC pump opportunity外にいた最長interval。30.72 us tick単位 | 安定bandなら例外的なSub-side pump放置はない |
| `B` | Sub | per frame | APPLY control queueのback-pressureがpumpを拒否（`G` bit 15から分離） | `00`。`01`はcontrol queueがcontinuous deliveryをblockした証明 |
| `K` | Sub | cumulative | MSF sequence-gap recovery count | `S`と比較し、`S-K`をCDC_TRN retry-exhaustion countとして読む |
| `H` | Sub | per frame | exact 32-byte pattern単位のphysical PrgBuf maximum | `3440`未満なら418 KiB payload back-pressure boundary未満 |
| `X` | Sub | per frame | 次frame展開に対するCD reader位置。high byteは完了frame slot数、low byteはcurrent slot内sector位置 | `H`と一緒に読み、全destinationに空きがある場合だけ大きなleadが安全 |
| `Y` | Main | per frame | 1つ目のtransfer VBlankで発行したexact pattern-transfer word数 | 16で割るとcompleteな32-byte pattern数。`Z/T`と一緒に読む |
| `Z` | Main | per frame | 2つ目のtransfer VBlankで発行したexact pattern-transfer word数 | name table、HUD、palette work、flipの時間を残す必要がある |
| `T` | Main | per frame | pattern transferを行ったVBlank数 | `01`または`02`が意図した1/2-VBlank path。`03+`は追加transfer spill |
| `I` | Main | per frame | pattern transfer終了時、残りdeadline work前のV-counter | `Z`と次rowの`V/O`を一緒に読むphase値。Gate statusではない |
| `V` | Main | previous frame | accepted display flip時のV-counter | `E0`ならVBlank start。大きいblank lineはlate flip |
| `O` | Main | previous frame | flip intervalの1024 tick超過分 | nominal N2は約`3E`、`FF`は3-field slip |
| `E` | Main | per frame | previous flipからPass2 entryまで。4-tick単位 | 1 field未満で余裕を持つ。`88`は544 tick |

`S`、`D`、`R`はcumulative counterで、一度増えるとrestartまでnonzeroです。表示low byteは
`FF`から`00`へwrapします。`J`もcumulativeですがevent数ではなく最大excessを保持します。
`C/W/M/A/U/N/Q/G/B/H/X/Y/Z/T/I`は1 frame、`K`はcumulative、`F/P/L`は
current stateです。

`V/O`は`do_flip`でregister write後にsampleするため、その値を持つrowは1 frame後に
作られます。Frame `F`のrowはframe `F - 1`をpublishしたflipを示すため、per-frame
workloadと比較するとき1 frame shiftします。`E`はframe `F`自身のbuild中、transfer
VBlank wait前にsampleし、shift不要です。

## Field詳細

### `F`: displayed frame

`F`はfull 16-bit movie frame numberです。Frame 0より前にplayerがvisible movie
tableを黒でclearし、予約値`FFFF`をframe -1としてpublishします。frame -1は
player/HUDだけに存在し、sim、routing、control、HUD TSVはframe 0（`0000`）から
始まります。

stream frameではMain CPUがinactive tableへ値をformatし、pictureをpublishする
Plane A flipと同じflipでtableを選ぶため、値とimageは同じframeを示します。

Valid streamは65536 frame未満なので1 loop内でwrapせず、end hold後のloop開始時に
`FFFF`は曖昧になりません。Loop playbackはframe -1を再び表示してから`0000`へ
戻ります。

### `P`: active palette segment

`P`はCRAMが現在使うzero-based palette-segment numberのlow byteです。Segment 0は
`00`です。Streamはsegment+1を保存し、Main CPUがHUD state更新前に1を引きます。

Switch commandではなくactive stateを示すため、CRAM change間は一定です。Table capacityは
64 segmentなのでvalid streamでbyte wrapは不要です。

### `S`: CD sector slipとre-seek recovery

`S`はcumulative `slip_count`のlow byteです。Continuous CD deliveryがsectorをlostまたは
skipし、recovery pathがread positionを再確立するとSub CPUがincrementします。
新incrementは実streaming incidentで、visual/timing glitch boundaryになり得ます。

Clean qualified runでは`S=00`が必須です。Low byteだけなので、後の`00`だけでincidentが
なかったとは判断せず、隣接frameのtransitionを比較します。

### `D`: control-stream desynchronization

各control blockはframe sequenceを持ちます。Sub CPUのexpected frameと一致しないと
`D`が増え、playerはcorrupt dataを歩かずmismatched controlを拒否して直前imageを
保持します。通常encoder Missより重大で、clean runは`D=00`です。

### `R`: audio pointer re-sync

RF5C164 writerは通常playbackより先行します。Measured leadが`[SYNC_MIN, SYNC_MAX]`を
外れると`R`が増え、writerは`play + SYNC_LEAD`へjumpします。安全は回復しますが、
audibleな場合があります。

`R=00`が理想です。Increment直前の`L` trendと合わせて診断し、持続nonzero valueより
transitionを重視します。

### `L`: audio lead

`L`はRF5C164 play pointerからwrite pointerまでのring distanceのhigh byteです。
1 unitは256 decoded sample byteです。

```text
lead_bytesは約 L * 256 から L * 256 + 255
```

`SYNC_LEAD=0x3000`は`L=30`付近、`SYNC_MAX=0x6800`は`L=68`付近です。`00`へ近づくと
reserve減少、upper boundaryへ近づくか超えるとwriter先行過多です。Byteからtimeへの
変換にはprofileのeffective playback sample rateを使います。

### `C`: Sub critical path上のblocking CD work

`C`は次のper-frame countを合算したlow byteです。

- このframeのcontrol sectorを完了するためのpump
- 直前BODY payloadまたはpadding slotをdrain中に必要なpump

1 pumpは1 physical sectorをdrainします。`C=00`なら`process_frame`到達時にcontrolが
armed済みです。Small nonzeroはsector slipではなく、delivery workがcurrent frameの
critical pathへ入ったことを示します。`C`はgateから除外され、thresholdを持ちません。
Rising `W`を伴うpersistent Cはisolated peakより強いdiagnosticですが、問題かどうかは
実際の再生結果で判断します。

### `W`: MainのSub CPU待ち

Main CPUは`CMD_SWAP`時のV counterをsampleし、Sub CPUの`STAT_READY`または`STAT_END`を
待って再sampleします。`W`はmasked 8-bit differenceを概算scanlineで表します。

Control delivery、expansion、ADPCM work、late command responseなどhandoffを妨げるものを
含みます。Cycle-accurate timerではなく256でwrapするため、同mode内のrelative comparisonと
spikeに使います。

### `M`: Main pattern-path VBlank wait

`M`はcurrent frameのMain-side pattern transfer pathが消費したVBlank start数です。
Display cadence待ちは除外するため、deadline diagnosticになります。

Fixed-N H40では、guard付きの残りbudgetが十分なら、最後のcold tailがname-table
DMAとflipと同じdeadline VBlankを使えます。このshared target waitはdisplay
cadenceなので`M`から除外し、それより前のintervening pattern-work VBlank start
だけを残します。Fresh flip VBlankが必要なfallbackもpattern workではなくdisplay
workのままです。

Fixed-Nの正常範囲は`M=00..N-1`で、`N`到達はpattern workがfixed display deadlineへ
spillした証明です。Fixed N2は`M<=01`、fixed N4は`M<=03`です。Delivery-paced contentは
`ceil(60000/1001/fps)`をlimitにします。`U/N`と相関させ、transfer volumeとrun
fragmentationを分けます。

### `A`: Sub ADPCM decode time

Sub CPUはMega-CD stopwatchでcheckpoint付きIMA decode phaseを測ります。Playerはraw
valueを2 bit右shiftし、そのlow byteを表示します。

```text
1 A unit = 4 * 30.72 us = 約0.12288 ms
```

例えば`A=40`は約7.86 msです。Low frame rateのdecoderはCDCをperiodic serviceするため、
`A`へinterleaved pump workも入る場合があります。その後のRF5C164 wave-RAM write phaseは
含みません。

### `U`: Main pattern-transfer time

`U`はMain CPUのMega-CD stopwatchを4 hex digitで表示します。1 tickは30.72 usです。
最初のcold runから最後のDMA repairまたはshort-run CPU writeまでを測り、long runが
VBlank word-budget boundaryをまたぐときのpiece間waitも含みます。

Hardware counterは12-bitでdifferenceを`0x0FFF`へmaskするため、4096 tick、約125.83 msで
wrapします。Cold runがないframeは`0000`です。

### `N`: packed cold-run count

`N`はframe用source-aware cold-run descriptor countのlow byteです。同じphysical pattern
sourceのconsecutive VRAM slotを1 runにします。Prg、parity-selected WordBuf、DicBufの
境界はdestination slotが連続していてもrunを分けます。

Cold-tile countでもphysical VDP DMA command数でもありません。1・2 tile runはCPU write、
long runはDMAを使い、VBlank boundaryでさらに分割される場合があります。`N`はhardware
transfer choice前のfragmentationを測ります。

Whole-movie `/hudline` の `N COLD RUNS` rowは、そのHUD TSVにあるtimed `N`の最大値を
vertical scaleに使います。Untimed frame 0は最大値から除外します。

### `J`: streamed PrgBuf jitter-reserve high-water mark

`J`はBODY streaming開始後に観測した、fps-derived normal ceilingを超えるstreamed
PrgBuf simultaneous occupancyの最大値です。Normal ceilingは15 fpsで376 KiB、
24 fpsで391 KiB、30 fpsで396 KiBです。KiBへ切り上げhex表示します。
`J=00`はceiling未超過、`J=01`は0より大きく1 KiB以下、`J=0A`は10 KiB以下の
最大excessです。

Sub CPUは各BODY payload sector append直後にoccupancyをsampleします。Appendだけが
high-water markを上げるため、pollやpattern consumptionでの追加sampleは不要です。
Frame-0 blockはこのpathを通らないため除外します。Fieldはsimultaneous occupancyを
測り、circular pointerがnormal boundaryより上のphysical addressへ入ったかどうかとは
別です。

### `Q`: signed per-frame PrgBuf minimum

`Q`は別のsigned logical balanceを追跡します。BODY payload sectorごとに64 patternを
加え、Prg source runごとにexact pattern countを引きます。そのframeで到達した最小値を
signed 16-bitの4桁hexでpublishします。`0001`は32 byte patternが1つ残った状態、
`0000`はlogical supplyが正確にempty、`FFFF`は到着前のpatternを1つ消費した状態です。

Circular pointer arithmeticはunderflow発生後にそれを識別できません。Pop headがappend
tailを追い越すとmodulo distanceはほぼfullに見え、payload back-pressureを起こせます。
`Q`は後続sectorがdebtを返済しても、そのframe全体でsigned factを保持します。
Diagnostic専用でupload gateは変えません。

### `H` / `X`: physical PrgBuf pressureとCD reader lead

`H`は1 frame中に到達したphysical PrgBuf occupancyの最大値です。Sub CPUはexactな
circular-ring distanceで初期化し、2 KiB payload appendごとに更新します。表示単位は
32-byte patternなので、`H=3440`は418 KiBで、次のpayload pollを拒否する境界です。
Whole-run sticky peakの`J`と異なり、`H`は各frame境界でcurrent occupancyへ戻るため、
pressureが存在したframeを示します。`/hudline`のH rowには418 KiB back-pressure
guideを描きます。

`X`は次のframe展開に対しphysical CD readerがどこまで進んだかを記録します。High byteは
readerとconsumer位置の間で完了したframe slot数、low byteはcurrent slot内sector index
です。1 frame中に到達した最も先の辞書順位置を保持します。`/hudline`では
`XH READER AHEAD`と`XL READER SLOT`へ分離します。`X`は`H`と一緒に読みます。
Destination bufferに空きがあるreader leadは有用なprefetchですが、`H=3440`と同時なら、
continuously arriving payload sectorをphysical PrgBuf back-pressureが止め得る状態です。
両fieldとも観測専用でupload-gate thresholdはありません。

### `Y` / `Z` / `T` / `I`: Main pattern-transfer split

`Y`と`Z`はpattern pathが1つ目と2つ目のtransfer VBlankで発行したexact word countです。
16 wordで1つの32-byte patternです。DMA runはword-budget boundaryで分割され得るため、
どちらかがpartial patternを含むことがありますが、合計はexact transferを表します。

`T`はpattern workを行った全VBlankを数えます。`T=01`は1 VBlank内、`T=02`は意図した
2-VBlank split、`T=03`以上はtransfer自体が追加blankを必要とした証拠です。`T<=02`
なら`Y+Z`はframe全体のpattern word数です。`T>=03`なら`Y+Z`は意図的に最初の2
VBlankだけを表します。

`I`はpattern path終了時、HUD publication、name-table DMA、CRAM replacement、
display flipより前にsampleしたraw V-counter high byteです。2つ目のshare `Z`と、
次のHUD rowの`V/O`を一緒に読みます。Pattern tailがlateなのか、tail後のworkが
spillしたのかを分けます。4 fieldとも観測専用でupload-gate thresholdはありません。

### `G` / `B` / `K`: Sub pumpとcontrol back-pressure

`G`は1 frame内のSub CPU CDC service opportunity間で最長のintervalです。Low 12 bitを
Mega-CD stopwatchの30.72 us unitとして使います。Sector transferまたはre-seek recovery
後にtimer originを更新するため、recovery workそのものではなくpump path外の時間を
測ります。

`B`は`G` bit 15から独立したBoolean rowとしてdecodeします。APPLY-ring occupancyが
`APPLY_SIZE - 4 KiB` guard（現在の34 KiB ringでは30 KiB）へ達し、Sub CPUが次の
control-sector pumpを拒否したframeで立ちます。Playerはper-frame control-wait counterの
未使用high bitへ一時保存し、HUD format時だけ`G`へ合成します。このためG maximumや
表示low-byte `C`を妨げません。

`K`は`S` incidentのうちMSF sector-sequence gapが原因のcumulative countです。`S`は
全recovery countのままなので、`S-K`がCDC_TRN retry-exhaustion recoveryを示します。
差はmodulo 256で読みます。3 fieldともdiagnostic専用でupload-gate thresholdはありません。

### `V` / `O` / `E`: flip phaseとPass2 entry phase

`V`はaccepted display flipのregister write直後に読むraw V-counter high byteです。
`E0`（line 224）はVBlank startちょうどのflipで、dominant healthy valueです。大きい
blank lineはlate flipで、terminal line `FC..FF`はacceptしません。

`O`はflip-to-flip stopwatch intervalから`N*512` tickを引き、`0..FF`へclampします。
Nominal fixed-N2の約1086 tickは約`3E`、fixed N4の約2172 tickは約`7C`です。
Late-in-blank flipは大きくなり、slipが十分大きいと`FF`になります。`V/O`はprevious
frameをpublishしたflipを示します。

`E`はPass2 entry（`bf_dma`）でVBlank wait前にsampleする、previous flipからの
stopwatch distanceです。4-tick unitで、CMD_SWAP wait（`W`）、control parse、
bitmap/list shadow walk、name-table blitを含むcomplete pre-transfer Main phaseを
測ります。Pass2はfield 1のVBlank前に入る必要があります。1 fieldは543 tick、
`E`約`88`です。`U`はtransfer VBlank内で始まるため、このdeadlineを単独では示せません。

## 組合せの読み方

| Observation | 解釈候補 |
|---|---|
| `S/D/R`が`00` | CD loss、control desync、audio pointer jumpを検出していない |
| `S`増加後も`D=00` | control alignmentを失わずsector recovery |
| `D`増加 | control blockを拒否し直前imageをhold |
| `L`がboundaryへ向かい`R`増加 | audio reserveがsafe range外へ出てwrite pointer jump |
| `C`と`W`が同時上昇 | CD/control workがSub-to-Main handoffを遅延 |
| `A`と`W`が上昇し`C`は低い | ADPCM decodeまたはinternal CDC serviceがSub側主要cost |
| `N`と`U`が同時上昇 | Run fragmentationがMain fixed overheadを増加 |
| `U`上昇、`N`は小さい | Descriptor数よりpattern volumeまたはVBlank splitが支配 |
| `T=02`かつ`Y+Z`がframeのpattern word数と一致 | 意図した2-VBlank pattern splitが完了 |
| `T>=03` | Pattern transfer自体が3つ目以降のVBlankを消費 |
| `T=02`で`I`はearly、次rowの`O=FF` | Pattern workは2つ目のblankで完了し、後続HUD/name-table/palette/flip workがvisible holdを発生 |
| `T=02`で`I`がterminal blank近く | 2つ目のpattern share後に残るdeadline marginが小さい |
| `M>=02` | Main pattern workがextra VBlank deadlineをcross |
| `P`変化、`S/D`安定 | 正常なscheduled CRAM segment switch |
| `J`が`00`から変化 | Physical jitter reserveを使用 |
| `J`がさらに上昇 | Timed playbackがそれまでのhigh-water markを更新 |
| `Q=0000` | そのframeでlogical PrgBuf supplyが正確にempty |
| `Q=8000..FFFF` | Signed PrgBuf balanceがnegative。`Q-0x10000` patternとして読む |
| `H=3440`で`X`が先行 | CD readerがprefetch先行中にphysical PrgBufがpayload back-pressureへ到達 |
| `H`が低下しても`J`が高い | Current pressureは回復し、`J`がearlier whole-run peakを保持 |
| `S` transitionでも`G`がnormal band内 | CDC pump外の例外的な長時間停止はincident原因ではない |
| `B=01`の後に`K/S`が増加 | APPLY control back-pressureがdeliveryをblockした後にMSF-gap recovery |
| `K`と`S`が同量増加 | Recovery原因はMSF sequence gapで、CDC_TRN retry exhaustionではない |

単独のproofではなくcorrelationです。Regression調査ではnative lossless captureとpacked
streamを使います。

## HUD rendering

HUDはWindow planeを使いません。各frameでMain CPUは次を行います。

1. inactive Plane A tableへcomplete next movie name tableを構築
2. 両modeとも126-byte Main-RAM staging blockへHUDをformat
3. H32ではrow 0の32 cellとrow 1の31 cell、H40ではrow 0の40 cellとrow 1の
   23 cellを上書き
4. Movieと同じregister-2 flipでcompleted tableを選択

Inactive tableはVRAM `0xC000`と`0xE000`です。HUD publicationは両modeとも
31 longword writeと1 word writeを使い、DMAは使いません。
未使用cellはmovie entryを保持し、無関係なPlane B frameを露出しません。

Final flipはterminal-VBlank guardを持ち、V-counter `FC..FF`を拒否してend-of-blank raceで
tableを選びません。

## Hex fontとCRAM安定性

HUD fontはhex digitごとに16 patternだけを持ちます。各8x8 glyphは次を含みます。

- top rowに4-bit barcode。1 bitを2 pixel、MSB first
- その下にcompactな6x7 human-readable hex glyph

16 patternはstartup時にVRAM `0xD000`（tile 1664..1679）へ1回uploadします。
Name-table cellはfixed tile indexを直接参照します。Font upload時にsource colour 0を
P0/index1、source colour 1をP0/index15へ展開します。Encoderとpackerは全palette segmentで
これらをglobal darkest/brightest usable colourへcanonicalizeします。このためCRAM
switchでHUDがrecolour/blinkせず、frameごとのfont scan、recolour、DMA、extra VBlank waitは
不要です。

## OCRとrecording解析

Native screenshotを読みます。

```sh
tools/python.sh tools/read_frameno.py frame.png
```

結果は全fieldとconfidenceを含みます。

```text
frame.png -> F=012A(0.99) P=03(0.99) S=00(0.99) ...
```

`read_frameno.py`はbarcodeをdecodeし、lower glyphをnormalized correlationでcheckします。
旧common layoutと1行H40 layoutは明示指定で残します。Current recordingは
`HUD_H32_COMBINED_LAYOUT`または`HUD_H40_COMBINED_LAYOUT`を使い、readerが各logical
digitを32/40-cellの折り返しへ割り当てます。H32で分割される`Q`も同じfieldとして
読みます。どちらのprofileでもrecording analyzerがmatching layoutを自動選択し、
profileなしの場合だけ`--combined-fields`が必要です。

Complete recordingでは`harness/startup_resync/analyze.py`が`F`ごとにrepeated 60 Hz
capture frameをgroup化し、field別confidenceとcounter transitionを報告します。
`F=FFFF`直後のvalidな`F0000` runを優先するため、first-loopの頭出しを正確にできます。
sentinel導入前のrecordingにはplausible sequence fallbackを残し、`FFFF` group自体は
捨てます。Analyzerは選んだmethodを報告し、capture indexをgate JSONの
`ocr_start_anchor` objectへ対応するcapture timeと共に保存します。Publication
recordingはtrimしません。CRAM chapter offsetにはこのobjectの正確な
`F=FFFF`から`F=0000`へのtransitionを使うため、別の目視頭出しは不要です。

Canonical project TSVを書きます。

```sh
tools/python.sh harness/startup_resync/analyze.py \
  videos/STEM_emu_lossless.mkv profiles/PROFILE.toml \
  --tsv videos/STEM_emu_hud.tsv \
  --gate-json videos/STEM_emu_hud_gate.json \
  --expected-frames FRAME_COUNT
```

LogはUTF-8、header row、tab separator、LF line ending、`.tsv` extensionです。
Required profile引数がある場合、実体は
`logs/<datetime>_<profile>_<sha10>_eNN_pNN_hud.tsv`へ永続保存し、`--tsv` pathは
そのlogへのrun-specific compatibility symlinkになります。Project-owned HUD logは
comma-delimitedにしません。

Current H32/H40 combined HUDでは、TSVは`Q`を`prgbuf_min_patterns_raw16`として保持し、
signed valueを`prgbuf_min_patterns_signed`へdecodeし、positiveなdebt magnitudeを
`prgbuf_underflow_patterns`へ書きます。Pump diagnosticでは代わりに
`sub_poll_gap_ticks`、`sub_poll_gap_ms`、`apply_guard_blocked`、
`slip_msf_gap_count`、`slip_trn_retry_count`を書きます。Physical-buffer diagnosticは
`prgbuf_physical_peak_patterns`、`reader_ahead_raw16`、
`reader_ahead_frames`、`reader_slot_sector`を書きます。Columnがあれば
`/hudline`と`/mixline`は常にそれらのrowとG/BおよびH/X summaryを含めます。
Pattern-split diagnosticは`pattern_vblank1_words`、
`pattern_vblank2_words`、`pattern_transfer_vblanks`、
`pattern_exit_vcounter`を書き、同じrendererがそのrowとmaximumを保持します。

Glyph/layoutのreproducible proofは次です。

```sh
tools/python.sh harness/hud_ocr/verify.py
```

## Maintenance contract

Field、width、order変更時は次を同時更新します。

- `boot/movieplay_ip.s`の`prepare_dbg`と`publish_dbg`
- `tools/read_frameno.py`のlayoutとfield decode
- `harness/hud_ocr/verify.py`のlayout/OCR proof
- この文書とREADMEのshort summary
- `harness/pipeline_speedup/verify_run_hud.py`などのfield固有verification

意図的にnew layoutをqualificationしない限り、HUDはvalues-onlyを維持します。Label追加は
movie cellとMain-side publication workを消費し、freeなpresentation changeではありません。
