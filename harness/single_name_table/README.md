# Single name-table verification

This harness replays every control block from real packed `HEADER.DAT` and
`BODY.DAT` pairs. It compares two independent VRAM models:

- the removed two-table path, which copied the complete logical grid into the
  inactive table and switched Plane A;
- the current one-table path, which expands the grid into a zero-gapped
  64-entry-pitch Main-RAM band and DMAs only the words from the first encoded
  cell through the last encoded cell.

Both models start from BIOS-cleared VRAM. The proof compares all 1,792 words of
the displayed table after every movie frame, including the centered borders and
the unused cells between encoded rows.

Run the three representative same-stream cases preserved for issue 102:

```sh
tools/python.sh harness/single_name_table/verify.py \
  --case h40-15 tmp/issue102-baseline/machi-op/HEADER.DAT tmp/issue102-baseline/machi-op/BODY.DAT \
  --case h32-24 tmp/issue102-baseline/lunar-sss-op-h32/HEADER.DAT tmp/issue102-baseline/lunar-sss-op-h32/BODY.DAT \
  --case h40-30 tmp/issue102-baseline/sonic-jam-op/HEADER.DAT tmp/issue102-baseline/sonic-jam-op/BODY.DAT
```

The output reports the exact physical band length for each case. For example,
a 40x19 grid uses `18 * 64 + 40 = 1,192` words; full-height H40 and H32 grids
use 1,768 and 1,760 words respectively.

## Lossless-recording tearing detector

`detect_tearing.py` uses the exact `capture_first..capture_last` spans in a
matching DEBUG HUD TSV. It excludes the two HUD rows, then requires every
60-fps raster assigned to one movie frame to be byte-identical. A name-table
DMA that reaches active display creates a spatially mixed raster in that group
and fails the check. The input must be the native FFV1 lossless recording, not
a compressed preview.

```sh
tools/python.sh harness/single_name_table/detect_tearing.py \
  /dev/shm/segacd-fmv-ttrc/PROFILE_emu_lossless.mkv \
  logs/<run>_hud.tsv \
  --output logs/<run>_single_nt_tearing.tsv
```

The output is a per-movie-frame TSV. `PASS` means the group has one unique
movie raster; `TEAR` records the outlier count and maximum changed-pixel count.
