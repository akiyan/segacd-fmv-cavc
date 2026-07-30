# DEBUG HUD OCR proof

The movie player writes 43 hexadecimal digits as one contiguous logical
values-only stream. H32 wraps after digit 31 and uses 32+11 cells; H40 wraps
after digit 39 and uses 40+3 cells. Field letters are not drawn. The physical
field order is:

```text
frame:4 palette_segment:1 sector_slip:1 control_desync:1 audio_resync:1
audio_lead_256b:2 cd_wait_count:1 sub_wait_scanlines:2 adpcm_decode_units:2
vblank_spill+transfer_ticks:4 cold_runs:2 prgbuf_jitter_peak_kib:2
flip_vcounter:2 first_share_exit_vcounter:2 pass2_delay_q4:2
apply_backpressure+pump_gap_ticks:4 msf_gap_recoveries:1
reader_ahead_frames+reader_slot_sector:2 transfer_vblanks:1
transfer_end_vcounter:2 pattern_dma_start_vcounter:2
name_table_dma_start_vcounter:2
```

Small cumulative counters use one digit. The transfer word packs
`vblank_spill` in its high nibble and `transfer_ticks` in its low 12 bits. The
pump word packs `apply_backpressure` in bit 15 and `pump_gap_ticks` in its low
12 bits. The reader byte packs `reader_ahead_frames` and
`reader_slot_sector` as one nibble each. `tools/read_frameno.py` exposes the
unpacked descriptive names to every TSV and gate consumer.

Each of the 16 8x8 patterns contains a two-pixel-wide four-bit barcode in its
top row and a compact 6x7 hexadecimal glyph below it. The reader decodes the
barcode directly and uses the lower glyph only as a confidence check. Run the
in-memory synthetic-image proof with:

```sh
tools/python.sh harness/hud_ocr/verify.py
```

The proof renders the actual generated font onto native H32 and H40 frames,
checks every value and packed-field split, verifies 32-cell H32 and 40-cell H40
wrapping, and confirms that the standalone
`read_frameno()` API still reads an isolated four-digit `frame` field.
