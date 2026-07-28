# DEBUG HUD OCR proof

The movie player writes hexadecimal values as one contiguous logical stream
wrapped across at most two rows. The
keys below describe the fixed interpretation; their letters are not drawn:

```text
common H32/H40: xxxx xx xx xx xx xx xx xx xx xx xxxx xx xx
combined:       xxxx xx xx xx xx xx xx xx xx xx xxxx xx xx xxxx xx xx xx xxxx xx xxxx xxxx xxx xxx x xx
```

The common order is `F/P/S/D/R/L/C/W/M/A/U/N/J`. Standard H32/H40 DEBUG appends
`Q/V/O/E/G/K/H/X/Y/Z/T/I`. H32 wraps the 63 cells after cell 31, splitting `Q`
across the two rows; H40 wraps after cell 39, before `G`. `F/U/Q/G/H/X`
contain four hexadecimal digits, `Y/Z` contain three, and `T` contains one.
`L` is the high byte of the audio lead;
`P`, `S`, `D`, `R`, `C`, `W`, `M`, `A`, and `N` show two hexadecimal digits. There
`U` is the Main pattern-transfer time in 30.72 us Mega-CD stopwatch ticks, and
`N` is the low byte of the packed cold-run descriptor count (wrapping at 256).
`Q` is the signed per-frame minimum logical PrgBuf balance in exact 32-byte
patterns (`0000` empty, `FFFF` one-pattern underflow). `O/I` are the
first/final pattern-transfer exit V-counters; unlike `V`, they belong to the
current frame. `G` low 12 bits are the
longest interval outside a Sub CDC pump opportunity in 30.72 us ticks; bit 15
is decoded separately as `B`, the per-frame APPLY back-pressure marker. `K`
counts cumulative MSF-gap recoveries. `H` is the per-frame physical PrgBuf peak
in 32-byte patterns. `X` packs complete reader frame slots ahead in its high
byte and the current slot's sector index in its low byte. The player formats
these values into a 30-word legacy common, 40-word legacy extended, or 63-word
combined Main-RAM area before display pacing, then publishes it with fixed
longword writes over the first 32 H32 or 40 H40 cells of row 0 and the
remaining cells on row 1 of the inactive
movie Plane A table. The
final control-port word switches to that complete picture-and-HUD table. Its
VBlank guard rejects terminal V-counter lines `0xFC..0xFF`, keeping the HUD and
picture aligned without extending a 30 fps frame to a third scanout.

Each of the 16 8x8 patterns contains a two-pixel-wide four-bit barcode in its
top row and a compact 6x7 hexadecimal glyph below it. The reader decodes the
barcode directly and uses the lower glyph only as a confidence check. Run the
in-memory synthetic-image proof with:

```sh
tools/python.sh harness/hud_ocr/verify.py
```

It renders the actual generated font onto H32- and H40-sized frames, verifies
all visible fields and their widths, covers `00`/`FF` byte values and negative
four-digit `Q`, covers both 32-cell and 40-cell wrapping of simultaneous
`Q/V/O/E/G/K/H/X/Y/Z/T/I`, and confirms that
the older `read_frameno()` API still reads an isolated `Fxxxx` field without
requiring the rest of the HUD. The synthetic source is deliberately bright and
noisy; the proof models opaque font cells and also retains a legacy common-row
case. `Y/Z` are the exact pattern words charged to the first two fresh VBlank
budgets, `T` is the number of budgets opened, and `I` is the V-counter at
pattern exit. A whole run may physically overrun a blank without incrementing
`T`. This matches the player: no Window transparency or alternate Plane B is
involved.
