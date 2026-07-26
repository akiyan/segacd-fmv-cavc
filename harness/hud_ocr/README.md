# DEBUG HUD OCR proof

The movie player writes hexadecimal values only in a contiguous top row. The
keys below describe the fixed interpretation; their letters are not drawn:

```text
common H32/H40: xxxx xx xx xx xx xx xx xx xx xx xxxx xx xx
extended H40:   xxxx xx xx xx xx xx xx xx xx xx xxxx xx xx xxxx xx xx xx
```

The common order is `F/P/S/D/R/L/C/W/M/A/U/N/J`. Ordinary extended H40
appends `Q/V/O/E`; an opt-in `SUB_POLL_GAP_DIAG=1` build appends `G/K/O/E`
instead. `F/U/Q/G` contain four hexadecimal digits. `L` is the high byte of the audio lead;
`P`, `S`, `D`, `R`, `C`, `W`, `M`, `A`, and `N` show two hexadecimal digits. There
`U` is the Main pattern-transfer time in 30.72 us Mega-CD stopwatch ticks, and
`N` is the low byte of the packed cold-run descriptor count (wrapping at 256).
`Q` is the signed per-frame minimum logical PrgBuf balance in exact 32-byte
patterns (`0000` empty, `FFFF` one-pattern underflow). `G` low 12 bits are the
longest interval outside a Sub CDC pump opportunity in 30.72 us ticks; bit 15
is decoded separately as `B`, the per-frame APPLY back-pressure marker. `K`
counts cumulative MSF-gap recoveries. The player formats these
values into a 30-word common or 40-word extended Main-RAM row before display
pacing, then publishes it with fixed longword writes over the first cells of
the inactive movie Plane A table. The
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
four-digit `Q`, covers the `G/K/O/E` layout, and confirms that
the older `read_frameno()` API still reads an isolated `Fxxxx` field without
requiring the rest of the HUD. The synthetic source is deliberately bright and
noisy; the proof models opaque font cells and also verifies that the unused
width of the common 30-cell H40 layout remains movie content. This matches the
player: no Window transparency or alternate Plane B is involved.
