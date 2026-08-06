# Pipeline speedup — where the Sub actually spends time

The measurement sections below are archived results from the p11--p14 Sub-CPU
optimization campaign, taken on the H32 discs that existed then; their specs and
numbers are kept as measured. The proof sections at the end (`verify_*.py`)
describe checkers that run against a current stream.

Goal: let a dense spec (Sonic H32, 256x208, 832 cells) play clean 29.97fps. The
first rate-matched build was structurally correct (`control_desync=0`) but ran at ~16fps with
CD sector slips. The completed p11 path now saturates the 29.97 display cadence
and finishes with `sector_slip=0`, `control_desync=0` on the same e14 disc.

## Initial diagnostic: it was NOT the cold cap / cold-pop

The issue was framed around raising the per-VBlank cold draw limit. A direct test
disproves that framing:

| build | per-frame cold cap | realized cold | effective fps |
|---|---|---|---|
| Sonic 30fps cap 175 | 175 | ~200 | ~16.0 |
| Sonic 30fps cap 88  | 88  | ~121 | ~18.5 |

Halving the cold barely moved the rate (16 → 18.5). The disc is rate-matched to CD 1x
in **both** (6777 sectors), so the pump/drain load is identical; only the cold-pop
(32-byte pattern copies) changed — and it is not the bottleneck.

## What the bottleneck actually is: per-cell decode work

Compare the sustained **cell-update rate** (cells × fps):

- ed 15fps, 1120 cells: 16,800 cell-updates/s → plays clean
  (`sector_slip=0`).
- Sonic 30fps, 832 cells: wants 24,960 cell-updates/s → the Sub can't, settles ~16fps
  (≈13,300/s) with slips.

So the Sub saturates on the **per-cell decode loop** in `expand_frame` (`ef_byte`/
`ef_bit`): the bitmap walk, per-updated-cell entry read, the two `O_UPDS` writes, the
cold/reuse test, and the run-table (slot-run) building — plus the fixed costs that do
not scale with cold: the CD drain (`drain1` + `stage_copy`, 75 sectors/s), ADPCM
decode, and RF5C164 output (`write_wave_chunk`).
None of these shrink when you lower the cold cap.

## Implication for optimization

To reach 30fps at 832 cells the Sub needs ~1.5x on the per-cell decode path (and the
fixed pump/audio costs trimmed), i.e. broad work, not one lever:

1. `expand_frame` inner loop (`ef_bit`): remove sign-extension (`CLR.L`+`MOVE.B`),
   kill redundant address math, tighten the run-table build. Per updated cell.
2. `write_wave_chunk`: the wave-RAM address is recomputed (`lea`+`add`+`adda`) every
   byte; keep a running pointer (+2/byte, handle the bank window) instead. Fixed cost.
3. `stage_copy` / `drain1`: the 2 KB Word-RAM->PRG CPU copy per sector, 75x/s.
4. Cut per-frame fixed overhead (fetch_control copy, expand setup, handshake) — these
   double at 30fps vs 15fps.

Individually each is a few percent, so they must compound; expect this to be several
increments, measured against the Sonic-30fps slip/fps, not a single change. A lighter
grid (fewer cells) reaches clean 30fps now without any of this (cell-rate is the knob).

## Results (first optimization pass, Sonic H32 832-cell 30fps)

Measured effective fps (from the DEBUG `frame` counter, 60s window),
`control_desync=0` throughout, full movie plays correct:

| build | change | fps | slips (mid-movie) |
|---|---|---|---|
| baseline (rate-matched) | — | ~16.0 | ~168 |
| opt1 | pump_poll 8→16B (expand) + wwc 0x40→0x80; wave-write running pointer | ~21.2 | ~107 |
| opt2 | pump 16→32B, wwc 0x80→0x100, drop fetch_control's redundant movem | ~22.9 | ~81 |
| opt3 | pump 32→64B | ~24.0 | ~68 |

**+50% (16→24fps)** from freeing Sub time. The gain is **nonlinear**: the disc delivers
at 30fps but the Sub consumes slower, so the surplus overflows the CDC → sector slips →
re-seeks (expensive). Freeing Sub time cuts slips, and each avoided re-seek is worth far
more than its cycle cost — hence a few percent of Sub work buys a big fps jump.

Consequence: **slips cannot reach 0 until the Sub actually sustains 30fps** (matches the
disc). The pump/fixed-cost lever has largely plateaued (opt1 +5, opt2 +2, opt3 +1). The
remaining ~6fps to 30 requires speeding the **raw per-cell decode** (`ef_bit` + cold
handling), which is the harder, higher-risk work (must preserve
`control_desync=0`). At 24fps the value
already holds: if the cell count is later reduced, fewer cells need cutting.

## opt4: per-cell decode restructure (26fps)

| build | change | fps | slips (mid) |
|---|---|---|---|
| opt3 | (pump lever) | ~24.0 | ~68 |
| opt4 | ef_bit: strip cold-bit only for cold cells (reuse writes entry directly); compute slot into d2 first so d3 is free for the occ check → drop the per-cold-cell d0 push/pop | ~26.0 | ~48 |

**16 → 26fps (+63%)**, full movie `control_desync=0`. The decode restructure preserved correctness and
still gained via the nonlinear slip effect.

## opt5: interleaved PCM writes reach 29.97fps

An audio-disable diagnostic reached ~29.9fps, proving that the supposedly small
RF5C164 fixed cost was the missing margin. The writer measured here reads four
contiguous samples with `MOVE.L` and writes them to the every-other-byte
wave-RAM window with `MOVEP.L`. A 16-byte unrolled core handles the common
path; scalar code handles an odd source address and the final zero to three
bytes.

**Hardware correction.** This batch writer strobes wave RAM every ~6-10 CPU
cycles, which violates the RF5C164's sounding-time minimum access period of
16 source clock cycles (official PCM manual 4-5). The real chip drops or
corrupts the over-paced bytes — a continuous periodic hiss on hardware
(issue #81) that no emulator and no EverDrive FPGA reproduces, so every
measurement in this file stayed clean. The MOVEP batch path is gone: the
writer sets control-register bit 7 on every bank select, so the IC is sounding
on every call including the boot prefill, and there is no state in which a
batched wave write is legal. Playback and prefill both use the 20-cycle paced
writer. The build-time proof lives in `harness/pcm_write_pacing/`. The fps
measurements below remain valid as records of the batch writer's speed; the
paced writer costs about 8k more cycles per frame and holds the same HUD
gate.

Exact A/B used the same e14 Sonic `MOVIE.DAT`, lossless GPGX A/V capture and HUD
frame counter:

| build | 80/60-second HUD window | effective fps | full-loop result |
|---|---:|---:|---|
| e14 baseline (opt4) | `frame=0221` -> `frame=0866` / 60s | 26.750 | `sector_slip=65 control_desync=0 audio_resync=32` |
| opt5 MOVEP | `frame=0282` -> `frame=098B` / 60s | ~30.02 | `sector_slip=1 control_desync=0 audio_resync=3` |
| opt5 + armed startup | `frame=0024` -> `frame=0981` / 80s | **29.9625** | **`sector_slip=0 control_desync=0 audio_resync=2`** |

The slight 30.02 reading is capture timestamp granularity; the wider final
window matches the 29.97 display limit. Historical waveform diagnostics found
no clip or jump candidates in either capture, but those content-dependent
thresholds are no longer recorder gates and do not constitute a listening
test.

### Startup arming removes the last `sector_slip=1`

The remaining slip already existed on displayed frame 0 and never increased,
then repeated once on the next loop. Frame 0 was being expanded while the
continuous FRAMES read had already started. The first armed-startup version
fixed the Sub-side expansion overlap. The current handshake additionally keeps
timed BODY stopped until the Main CPU has completed the frame-0 VRAM/name-table
build:

1. drains HEADER through PREBUFFER;
2. reads and stops at the finite untimed BODY arm;
3. expands frame 0 and hands its bank to Main with the timed suffix stopped;
4. lets Main show frame -1, build and display frame 0;
5. uses the original command-clear edge to launch a new continuous read at the
   exact timed BODY-suffix sector while PCM remains stopped;
6. starts PCM when the first frame-1 control sector proves that `ROM_READN` is
   flowing, then finishes that physical slot before acknowledging Main.

For the measured Sonic file the split is sector 211, leaving 6777 timed sectors.
`sector_slip` is not cleared at that split: prefix slips remain visible, and
the first FRAMES sector is checked against the prefix's final MSF. The observed
zero is therefore a real zero, not a counter reset.

### Boundary proof

Run:

```sh
tools/python.sh harness/pipeline_speedup/verify_wave_chunk.py
```

The model compares the old byte loop with the chunked writer across pump positions,
physical wave addresses, MOVEP stride, PCM bank changes, 0x8000 wrap and final write
pointer. It covers a boundary matrix plus 5000 deterministic random cases, including
odd source addresses.

### Fixed costs that remain

The two biggest fixed costs are hard to cut without an architecture change:
- **32-byte pattern copy** (ring PRG → O_LOADS Word-RAM), 8x move.l per cold cell,
  ~175/frame → roughly a tenth of the Sub. Register-constrained (only 2 free regs in the
  inner loop, can't MOVEM). A pattern travels CDC→Word-RAM→PRG-ring→Word-RAM (three
  copies) because the 420 KB ring must live in PRG-RAM (too big for Word-RAM) and the
  Main can only DMA from Word-RAM.
- **CD drain** (drain1 BIOS CDC_TRN + stage_copy 2 KB/sector, 75 sectors/s) is fixed by
  CD 1x and unavoidable.

These still limit denser modes and higher cold caps, but they were not the final
barrier for the 832-cell target. The old ~27-28fps ceiling estimate omitted how much
time the scalar RF5C164 loop consumed.

## p13/p14: full-height H32 (896 cells)

Treating the 4:3 source as full-screen H32 increases the grid from 32x26 to
32x28. The first p12 full-height run ended at
`sector_slip=6 control_desync=0 audio_resync=4`. p13 batches the
75 Hz CDC stage copy with 48-byte MOVEM transfers and copies variable control
blocks as longwords; the same 896-cell encode improved to
`sector_slip=4 control_desync=0 audio_resync=3`.

p14 removes another per-cell loop cost without changing stream content. It
shifts the bitmap one bit at a time and advances the cell cursor directly,
instead of indexed `BTST`, `cell=base+bit`, and an add/cmp/branch loop tail.
This targets the remaining sub-percent throughput gap measured over the full
2714-frame loop.

p14 produced the same `sector_slip=4 control_desync=0 audio_resync=3` as p13.
A 60fps HUD scan showed the first
resync at lead `0x03C2`, just below the `0x0400` guard, but later decline proves
that lowering the guard would only hide a real underrun. p15 instead halves two
redundant poll cadences at 30fps (bitmap 64->128 bytes, PCM 256->512 bytes),
while retaining the proven 15fps cadence.

p15 improved the full loop to `sector_slip=3 control_desync=0 audio_resync=3`.
p16 removes a fixed per-sector
cost: steady-state callers already preserve all registers, so they call a
non-preserving `pump1_core` rather than duplicating a 15-register save/restore
at up to 75 sectors/s. Boot arming keeps the preserving wrapper.

p16 measured `sector_slip=4 control_desync=0 audio_resync=3`, within the
run-to-run slip variation and therefore
not a useful speedup. p17 removes the larger per-cold occupancy calculation.
`process_frame` has already drained all sectors assigned to the frame, sector
loss recovery completes inside `drain1`, and the pack verifies `under=0`; the
check therefore always succeeded on valid streams while costing several
instructions for about 96 cold tiles per frame.

p17 improved the result to `sector_slip=2 control_desync=0 audio_resync=3`.
With its occupancy temporary gone,
p18 keeps the open run count in d3 instead of PRG RAM and derives the cold slot
in d2 directly. This removes the memory increment and redundant register moves
for every cold tile.

p18 reached `sector_slip=1 control_desync=0 audio_resync=3`. p19 removes the
remaining mid-wave poll at 30fps:
the 443-byte write is shorter than one CD-sector interval and is already
bracketed by frame/expand polls. The <=20fps path retains its 256-byte cadence.

p19 reproducibly regressed to `sector_slip=2 control_desync=0 audio_resync=3`
with both FFV1 and x264 CRF0
recording, so p20 restores the p18 wave cadence. It instead unrolls the variable
control-block copy from 16 to 32 bytes per loop, halving its loop branches.

p20 remained `sector_slip=1 control_desync=0 audio_resync=3`. p21 changes the
copy operation itself: eleven
registers carry 44 bytes per MOVEM batch, and the absent 22-byte debug block is
cleared with five longs plus one word rather than an 11-iteration loop.

p21 regressed to `sector_slip=2 control_desync=0 audio_resync=3`; MOVEM is
slower than the unrolled MOVE.L path
on this bus, so p22 restores p20's copy. The R2/R3 window (frames 120--180)
averages 854/896 updated cells, so p22 adds a 0xFF bitmap-byte path that handles
eight consecutive updates without per-cell LSR/BCC.

p22 reached `sector_slip=0 control_desync=0 audio_resync=3` for the complete
loop and into the next loop. e17
extends boot-time PCM arming from 32 to 45 frames at 30fps, moving thirteen more
PCM writes out of the live startup bottleneck. The pack derives a safe maximum
from AUDIO and keeps a 0x200 lead margin, clamping 15fps content to 22 frames.

## p35: remove the duplicate Sub walk and isolate delivery pacing

The Main CPU must read the bitmap to map each update entry to a screen cell. The
Sub CPU does not need that mapping: it only consumes cold entries, in their
existing stream order, to pop patterns and build consecutive DMA runs. p35 makes
the Sub iterate the header's validated `n_upd` entries directly instead of
scanning all 896 bitmap cells a second time. The old bitmap walk remains on the
Main CPU unchanged.

CAVC typed fade controls have `n_upd=0` and replace the bitmap/list field
with 128 bytes of inline CRAM. Both independent walkers skip that image and
continue at the fixed-size audio chunk; their descriptor proof still includes
any future-pattern prefetch runs in the ordinary suffix.

The same pass removes fixed work from the 75 Hz CDC path:

- cache the current routing counts across the BIOS transfer;
- copy each 2 KB stage sector with seven six-way MOVEM groups instead of 42
  loop iterations;
- remove dead full-register saves from non-preserving frame paths;
- compute the `75/fps` quotient and remainder once, replacing the per-frame
  DIVU with an exact accumulator;
- remove the successful-sector register save after all callers reload their
  live state from memory.

Run the format proof against the real packed stream:

```sh
tools/python.sh harness/pipeline_speedup/verify_entry_walk.py \
  out/PROFILE/HEADER.DAT out/PROFILE/BODY.DAT
```

That p35 Sonic disc passed all 2714 frames: 1,870,030 entries and 262,363 cold
entries produced identical entry order and cold-run grouping. Later encoder
changes alter those counts, so the verifier output is the current source of
truth.

The important A/B result is that the first dense section did **not** move after
the CPU work was removed. Relative to the first visible frame, both p34 and p35
reach frame `0x0101` at 9.376 seconds and frame `0x0181` at 13.447 seconds
(within one 60000/1001 capture frame at earlier landmarks).
`sector_slip=0` and `control_desync=0` remain unchanged. This proves that the
remaining early ~27 fps reading is not
the Sub loop: it is the on-disc delivery order. Each slot currently delivers
two or three sectors of future ring refill before the current control stream,
even though the current patterns are already in the 380 KB boot prebuffer.

The next structural step is therefore to separate the boot prefix from the
timed stream and place current control before future payload. CPU optimization
adds safety margin, but cannot make a control block arrive before preceding CD
sectors.

## Main bitmap and name-table fast-path proof

p39 implements dedicated zero/full/mixed bitmap-byte paths and advances the
shadow pointer directly. Name-table rows use four longword writes for each
eight-word group, followed by a scalar 0--7-word tail for arbitrary per-source
widths. Run the equivalence proof against the real DEBUG control stream:

```sh
SIM_OUT="$(tools/python.sh tools/encode_config.py \
  profiles/PROFILE.toml --print-sim-output)"
tools/python.sh harness/pipeline_speedup/verify_main_fastpaths.py \
  --header out/PROFILE/HEADER.DAT --body out/PROFILE/BODY.DAT \
  --decisions "$SIM_OUT/decisions.pkl"
```

The checker replays all packed Sonic frames and requires the optimized shadow to
match the former bit loop after every frame. It also checks each packed bitmap and
entry palette against `decisions.pkl`, and requires the real stream to exercise all
three bitmap paths (`0x00`, `0xFF`, and mixed). For the blit, it models the 68000
longword groups plus the tail and compares every real shadow row and
deterministic widths 1--40 with the scalar word copy.

## Packed cold-run descriptor proof

Feature bit 0 appends the already-known cold slot runs to each control block
after its audio and absolute-address alignment pad. The suffix is one
big-endian `n_runs` word followed by four-byte run descriptors. Main schedules
those runs at runtime with the guarded residual VBlank budget. The descriptors
store Prg/Wr/Dic
in the high source bits and a 9-bit DicBuf index across the source and remaining
high bits. Source `2` addresses Dic entries 0--255 and source `3` addresses
entries 256--511. A run splits when its physical source changes, when DicBuf
indices stop being consecutive, or at a 256-entry Dic block boundary. The
optimized player consumes these runs instead
of scanning every update entry and rebuilding them. Run the independent proof
against the real split stream and its decision log:

```sh
tools/python.sh harness/pipeline_speedup/verify_run_descriptors.py \
  --header out/PROFILE/HEADER.DAT --body out/PROFILE/BODY.DAT \
  --decisions "$SIM_OUT/decisions.pkl"
```

The checker reconstructs controls and payload sectors without importing the packer.
When header feature bit 0 is set, it parses the actual aligned descriptor suffix from
every control; feature-zero legacy streams remain supported by constructing the same
suffix hypothetically. Display entries stay in cell order, while the packed suffix
and payload follow ascending physical VRAM-slot order. Across the complete supplied
profile the checker rebuilds those two orders independently, including run grouping
and 32-byte payload consumption. For v25 it independently walks frame 0, Prg, Wr0,
Wr1, and indexed Dic payloads and proves every physical source is reproduced exactly.
Typed fade controls contribute no display entries; the checker skips their inline
CRAM, then validates audio alignment and the same source-aware run suffix.
It also matches bitmap cells, entry palettes and every physical cold pattern to
`decisions.pkl`. Timed raw-prefetch runs are verified as the separately
slot-sorted Prg suffix after visible cold records. Because they have no
name-table entry, their slots and packed patterns are taken from the frozen
raw-prefetch requests and checked against both descriptor bytes and source
payload consumption. Frame-0 inline requests are kept separate from the
boot-sidecar records.
The report gives the exact added control bytes/sectors,
startup frames 1--42 statistics, and decimal frame 2019 statistics.

The Main CPU counts these descriptors into `n_runs`; H40 DEBUG HUD
`cold_runs` displays its low byte. This logical run count is independent of
the physical chunks: every run body is DMA'd and a run can be split at a
VBlank boundary. To compare the HUD OCR from a real emulator recording with
the exact descriptors in the recorded disc, run:

```sh
tools/python.sh harness/pipeline_speedup/verify_run_hud.py \
  --header out/PROFILE/HEADER.DAT --body out/PROFILE/BODY.DAT \
  --tsv logs/RECORDING.tsv
```

The checker uses high-confidence observations by default and compares every one
with `packed_n_runs & 0xff`. Early p45 CSVs called the same HUD field `dma_calls`;
that legacy column name never represented the physical VDP DMA command count.

## 30 fps entry-poll fast-path proof

The legacy/fallback Sub entry loop decrements both an update counter and a CDC
cadence counter for every entry. At 30 fps the cadence is 1024 entries, while a
full-screen 40x28 grid holds up to 1120 cells, so a frame can cross that cadence
once: the fallback keeps its possible short-prefix poll followed by the final
poll. The descriptor path must reach the same poll points. Run:

```sh
tools/python.sh harness/pipeline_speedup/verify_entry_poll_fastpath.py \
  --header out/PROFILE/HEADER.DAT --body out/PROFILE/BODY.DAT
```

The checker compares the fallback masked initial `DBRA` counter with an
equivalent grouped model. It requires identical poll positions, entry order and
cold-run grouping, including v10 physical-source boundaries, for every packed frame, then
repeats the cadence comparison for every synthetic update count from 0 through
the 1120-cell H40 limit. H40 retains the fallback entry walk and its possible
prefix poll when a frame exceeds 1024 updates.
