# Archived Genesis Plus GX LOGVDP traces

Use this reader on a compact emulator log, its complete compressed LOGVDP
trace, and the HUD TSV from that same recorded execution. New recordings use
BlastEm BLSTEL VDP events. See `harness/blastem/README.md` for current commands.
Those events provide actual write values and cycle positions. The archived
text carries DMA distinction and program-counter details used by this reader.

```sh
tools/python.sh harness/gpgx_logvdp/extract_frame_tsv.py \
  <OUTDIR>/retroarch_<tag>.log \
  --full-log-gz <OUTDIR>/gpgx_logvdp_<tag>.log.gz \
  --hud-tsv logs/<run>_hud.tsv \
  --output logs/<run>_gpgx_vdp.tsv
```

The output separates:

- pattern DMA words transferred in blanking and active display;
- one-word CPU pattern repairs written after DMA in blanking, active display,
  and the two ambiguous LOGVDP V-counter boundary representations;
- name-table DMA words transferred in blanking and active display; and
- pattern DMA command and update counts.

The extractor identifies every timed pattern-DMA wait site (whole-run, split
Word-RAM, and split DicBuf) and the largest fixed per-frame DMA command as the
statically trimmed name-table band. This remains unambiguous when the movie NT,
Window row, sprite table, and ordinary Main-RAM pattern DMA share one program
counter. DMA-generated
VRAM writes carry those site PCs and are excluded from the CPU totals. In the
recorded player, the remaining per-frame VRAM writes are the one-word DMA
repairs.
If the safety recording continues into another movie loop, extraction stops
after the complete first loop named by the HUD TSV; the later trace remains in
the compressed sidecar but does not extend the frame axis.

The extractor validates every timed frame with at most four transfer budgets:
pattern DMA words plus the DMA first-word repair count must exactly equal the
logical pattern workload in the HUD TSV. It also writes a JSON receipt beside
the TSV with source hashes, inferred call sites, phase rules, maxima, and the
number of validated frames. Frame 0 remains untimed and is not part of this
equivalence check.

## Historical comparison

On 2026-07-29, the managed core was compared with the previously used Ubuntu
core by playing one 3000-frame input Replay through both. Each side recorded
the same 2880 emulator frames, including Mega-CD startup and an eight-second
H40 DEBUG movie:

- managed core SHA-256:
  `51cfd71f338865288e274b271b8ce0d9a1d3dc415688f14db963a29555d9b4ac`;
- Ubuntu core SHA-256:
  `40791618c03ea3f1fa04d925835b10671c8429c5ff9919ef58401303c57df920`;
- all 2880 decoded video frames equal, hash-sequence SHA-256
  `190c8bae28f16284fe6f7cb56de71799dd139606735e463bae06b4eb92baafe8`;
- all 2,119,529 decoded stereo PCM sample frames equal, PCM SHA-256
  `d3ee380194dc63492f44b790186e7a63e6e6353eb61b85c8506f5e551d345c2e`;
- video/audio metadata, packet counts, PTS, DTS, and durations equal; and
- managed LOGVDP recording ran at 7.90x versus 15.82x for the package core.

The managed run's 702,005,465-byte complete log became a 57,731,453-byte gzip
sidecar and a 724,875-byte compact log. DMA update, completion, and CPU-freeze
counts were unchanged by compaction. This qualification establishes equivalent
output for that recorded CUE/BIN FMV run.
