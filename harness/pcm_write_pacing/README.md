# RF5C164 wave-RAM write pacing proof

`check_pacing.py` proves at build time that the playback wave-RAM writer in
`boot/movieplay_sp.s` obeys the RF5C164's minimum access period. `make disc`
runs it next to `check_player_ring.py`; a violating writer fails the build
before an image exists.

## The hardware rule

The official MEGA-CD HARDWARE MANUAL "PCM SOUND SOURCE" (VER 1.0 1991/10/14),
section 4-5 "MICROCOMPUTER INTERFACE IC", specifies access limits by sounding
state:

| state | external wave memory write |
|---|---|
| while sounding | access in a period of **16 source clock cycles or more** |
| while sounding suspended | unrestricted |

Internal-register writes while sounding need 384 or more cycles between
accesses. The Sub CPU and the RF5C164 share the 12.5 MHz clock
(32,552 Hz x 384 = 12.5 MHz), so 16 source clocks are exactly 16 CPU cycles.

Nothing on the bus enforces this. Writes issued faster are silently dropped or
corrupted by the real chip, so the failure mode is not a crash but corrupted
samples inside the ring: on hardware it played as a continuous periodic hiss
for the whole movie (issue #81), while the ADPCM content itself stayed
audible underneath.

## Why only real hardware showed it

Genesis Plus GX and the Mega EverDrive Pro FPGA core both accept wave-RAM
writes at any rate; neither models the minimum access period. Every emulator
recording and every EverDrive boot of the identical ISO was clean, which is
precisely the signature that separated this from a data or init problem. A
recording gate can therefore never catch a pacing regression — hence a static
build-time proof.

## History

- The pre-optimization scalar writer spent ~30 CPU cycles per write:
  compliant by accident.
- `issue #15 opt5` (2026-07-15) introduced the `MOVE.L` + `MOVEP.L` batch
  writer at ~10.1 cycles per write (~6-8 inside one MOVEP.L) to reach
  29.97 fps. Every real-hardware test after that date carried the violation;
  the hardware noise report (issue #81, 2026-07-28) followed it.
- `p153` split `write_wave_chunk`: the paced path writes every 20 cycles
  (`move.b (a0)+,(a1)` 12 + `addq.w #2,a1` 8, unrolled 8x) whenever
  `pcm_running` was set, and the boot prefill kept the MOVEP batch path on the
  assumption that sounding was suspended there.
- `p154` removed that exemption and the burst path with it. The writer sets
  control-register bit 7 on every bank select, so by the manual's definition
  the IC is sounding on every call, including the untimed BODY-arm prefill —
  which is the first audio the listener hears. There is one always-paced
  writer now. `p154` also spaced the internal-register writes: the wave-RAM
  bank select lives in the control register and needs 384 cycles before the
  next access, so the first byte of a bank could otherwise still land in the
  previously selected bank.

## What the checker proves

1. `write_wave_chunk` contains no MOVEP at all. A guard would be the wrong
   contract here: there is no reachable state in which a batched wave write is
   legal, so the checker requires the instruction's absence.
2. Every strobe-to-strobe distance in the paced loop bodies, including the
   `dbra` seam between iterations, is at least 20 CPU cycles — the 16-cycle
   spec floor plus project margin for cycle-table uncertainty.
3. Every internal-register write in `write_wave_chunk`, `pcm_on` and
   `pcm_boot_init` is followed immediately by `PCM_REG_WAIT`, the 390-cycle
   delay that satisfies the 384-cycle internal-register access period.

The cycle table covers only the instructions the paced block is allowed to
contain. An unknown instruction fails the check rather than being estimated:
whoever edits the loop re-derives its timing here.

## Run

```sh
tools/python.sh harness/pcm_write_pacing/check_pacing.py
```

`make disc` runs the same check automatically while assembling
`movieplay_sp.o`.

## What this cannot prove

That the noise is gone on a specific console. The proof covers the documented
access-period rule; final confirmation is listening to a real-hardware
playback of a disc built from a passing tree. Do not claim the hardware
result without that test.
