# Palette capacity qualification

The fixture uses all 64 boot-resident palette sets, switches every four movie
frames, and fills the unchanged 512-entry DicBuf. Its last frame reads DicBuf
entry 511. It has 256 frames at either 15 or 30 fps and needs no source media.
The production packer constructs the split stream, checks every physical-slot
display update, and verifies every BODY delivery slot. The fixture also walks
the actual `paltab.bin` / `palidx.bin` bytes through the final switch and sentinel.

Build a standard specialized DEBUG disc:

```sh
tools/python.sh harness/palette_capacity/build_fixture.py \
  --output tmp/palette64/15fps --fps 15
tools/python.sh harness/palette_capacity/build_fixture.py \
  --output tmp/palette64/30fps --fps 30
```

The builder retains linked binaries and raw 68000 disassembly alongside the
disc. `--segments 17` exercises the first count beyond sixteen. `--generic`
builds the runtime-header reference player. The standard player-constants
matrix independently builds the maximum table at 15, 24 and 30 fps, including
generic and specialized players and a centered geometry:

```sh
tools/python.sh harness/player_constants/verify.py
tools/python.sh -m unittest discover -s harness/palette_capacity -p 'test_*.py'
```

The packing tests require byte-identical HEADER, BODY, combined stream and
PALTAB for the same sixteen-segment decisions under both capacities. Only
PALIDX gains unused sentinels. They also cover seventeen and sixty-four
segments at both cadences and reject a sixty-five-segment decision log.

Run the complete fixture through Genesis Plus GX with VDP tracing. This path
does not create a video or audio recording. Use a fresh tag/output directory
for each run. The trace verifier requires a complete first loop by default:

```sh
OUTDIR="$PWD/logs/palette64-15fps" tools/run_headless.sh \
  tmp/palette64/15fps/palette.cue --tag palette64-15fps \
  --max-frames 6000 --boot-wait 0.2 --presses 100 --press-gap 0.05 --shots 0

tools/python.sh harness/palette_capacity/verify_trace.py \
  --fixture tmp/palette64/15fps \
  --trace logs/palette64-15fps/gpgx_logvdp_palette64-15fps.log.gz \
  --tsv logs/palette64-15fps/playback.tsv
```

Repeat with the 30 fps fixture and its own output directory, adding
`--min-loops 2` to verify its return to frame 0. The trace verifier
reconstructs VRAM and CRAM from actual VDP writes. For every displayed movie
frame it requires the exact palette, every visible cell's palette line and
32-byte pattern, consecutive frame numbers, and zero slip/desync/audio-resync
counters. It checks the final DicBuf entry and palette 63, plus the return to
palette 0 when another loop is required. The HUD's one-digit segment field
contains only the low four bits; full segment identity is verified against
all 64 CRAM words instead of inferred from that digit. The resulting UTF-8
TSV is a fixture verification log, not a recording HUD gate.

## Qualification limits

The specialized player passes this fixture at both cadences. The generic
reference player's 15 fps fixture stops after loading the initial palette,
before publishing the first HUD row. The same sixteen-segment HEADER/BODY
and byte-identical Sub binary reproduce that stop with the sixteen-capacity
Main player built from a clean baseline worktree. Generic assembly/link checks
pass, but this fixture does not establish generic runtime qualification.

The 15 fps specialized fixture completes one exact loop but does not restart
within the 6,000-frame observation window. A sixteen-palette baseline with a
byte-identical BODY reproduces this result. The 30 fps specialized fixture
completes two exact loops, including palette 63 to palette 0. Treat the 15 fps
restart observation separately from palette-capacity qualification.

These cases prove palette capacity, address separation and playback of the
synthetic decisions. Source-dependent quality gains and heavy-pattern delivery
performance require separate full-source encodes.
