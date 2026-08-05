# fontbench — gate-array Font bit vs CPU LUT 1bpp expansion

Standalone Sega CD bench disc measuring three Sub-CPU ways to produce 32-byte
4bpp patterns, as groundwork for a possible 1bpp ("duotone") cold-pattern
class. It does not touch the encoder or player sources.

- **FONT** — expand 1bpp through the gate-array font registers
  ($FF804C color, $FF804E bit, $FF8050-56 data readback), the expansion
  running as combinational logic with no busy state.
- **LUT** — expand 1bpp through a 256-entry x 4-byte lookup table in Sub
  PRG-RAM (the pure-software equivalent for a fixed color pair).
- **COPY** — plain 32-byte pattern copy in the player's `ef_run_pattern`
  movem shape (the current per-pattern delivery cost, as the baseline).

All variants read the same deterministic 16-bit LFSR input (seed `0xACE1`,
taps `0xB400`), write PRG-RAM destinations, and run 8 passes over 2,048
patterns timed with the Sub-side stopwatch ($FF800C, 30.72 us/tick) in
512-pattern chunks far below the 12-bit wrap.

The bench doubles as an emulator-correctness probe: the LUT encodes the
assumed convention (fontbit bit 15 = leftmost pixel of the two rows, font
color high nibble = color of 1-bits, $FF8050 word = pixels of bits 15..12),
and the FONT output is compared byte-exactly against it. A mismatch count
with the first differing word pair on screen falsifies the convention; the
16-bit output checksums allow an offline Python cross-check.

## Build and run

```sh
make fontbench
tools/run_headless.sh out/FONTBENCH.cue --tag fontbench --shots 10 --interval 2 \
  --record --record-preset ffv1-flac --record-size 320x224
tools/python.sh harness/fontbench/read_result.py tmp/FONTBENCH/record/fontbench.mkv
```

The IP forces H40 so the 320x224 recording is pixel-exact for OCR.
`read_result.py` template-matches the on-screen hex rows against the exact
`boot/hexfont.bin` glyphs and prints a TSV plus derived per-pattern costs; it
exits nonzero unless the FONT-vs-LUT verification passes.

## Screen layout (values 4 hex digits at column 4, label at column 2)

| Row | Label | Field |
|---:|---|---|
| 2 | 0 | magic `FB01` (OCR anchor) |
| 4 | 1 | FONT ticks |
| 6 | 2 | LUT ticks |
| 8 | 3 | COPY ticks |
| 10 | 4 | verify mismatch words (`0000` = byte-exact match) |
| 12 | 5 | first mismatch word index (`FFFF` = none) |
| 14 | 6 | FONT word at first mismatch |
| 16 | 7 | LUT word at first mismatch |
| 18 | 8 | FONT output 16-bit word sum |
| 20 | 9 | LUT output 16-bit word sum |

Backdrop: blue = FONT running, yellow = LUT, magenta = COPY, cyan = verify,
green = done. Interrupts stay off; the Main side polls the VDP vblank flag.

## Measured results (Genesis Plus GX libretro, headless RetroArch)

Totals cover 8 x 2,048 = 16,384 patterns per variant; per-pattern figures
assume the 12.5 MHz Sub clock.

| Variant | Ticks | us/pattern | cycles/pattern | vs COPY |
|---|---:|---:|---:|---:|
| FONT | 15294 | 28.68 | 358 | 2.01x |
| LUT | 16504 | 30.95 | 387 | 2.17x |
| COPY | 7594 | 14.24 | 178 | 1.00x |

Verification: mismatch words `0000`, checksums `1BF3` = `1BF3`, and the same
`1BF3` reproduced by an independent Python reference expansion of the LFSR
stream. Conclusions:

- Genesis Plus GX implements the font registers, and the assumed bit/nibble
  convention above is the real one.
- FONT and LUT are near-equal (FONT ~7% faster); both cost about twice the
  plain 32-byte copy per pattern. A 1bpp pattern class would therefore
  roughly double the Sub-side per-pattern delivery cost while removing
  24 bytes per pattern from CD bandwidth and PrgBuf residency.
- Emulator timing measures the 68000 instruction sequence only; unknown
  real-hardware gate-array wait states are not modeled. Re-run on hardware
  before relying on the absolute FONT figure.

## Duotone eligibility of a packed stream

`duotone_eligibility.py` walks a real v20 `HEADER.DAT` + `BODY.DAT` pair with
the `harness/pattern_supply/verify.py` reader logic, rebuilds the displayed
cell state for every frame, and reports how much a 2-color pattern class
would cover: unique-pattern color histogram, displayed time-area share, and
the timed-delivery share with its CD-byte saving.

```sh
tools/python.sh harness/fontbench/duotone_eligibility.py out/bad-apple
```

Measured on the full Bad Apple stream (6,576 frames, H40 40x28, cold 210):
88.3% of displayed cell-frames show an exactly-2-color pattern, but only
2.6% of unique patterns and 4.0% of timed pattern deliveries are 2-color
(a 2.9% timed-byte saving). The flat/duotone screen area is already served
by resident reuse, DicBuf, and WordBuf preloads; the timed cold stream is
dominated by dithered/anti-aliased edge tiles (7-8 distinct indices in
57.3% of deliveries; mean top-2-color pixel coverage 80.7%). An exact
duotone class therefore barely pays on this stream — it only becomes
significant as a lossy encoder knob (force near-duotone tiles to 2 colors)
or as a wider 2bpp class, both of which trade target quality and belong to
encoder tuning, not the player.
