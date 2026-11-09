# Single-movie loop playback

These checks exercise two distinct replay failures: accepting an older CDC
sector as the first sector of a new finite read, and retaining hidden
name-table cells that a later fine-scroll frame exposes. They use assembled
players and the managed GPGX LOGVDP core, with no source encode or A/V recording.

## Independent synthetic pixels

Use the palette-capacity fixture at 15, 24 and 30 fps. Its independent reader
checks every cell, pattern and palette, final DicBuf entry 511, frame order and
zero recovery counters. An 8,000-VBlank run with `--min-loops 3` covers repeated
end/start transitions. Commands are in `harness/palette_capacity/README.md`.
Keep each build and emulator output in a leased workspace directory using
`tools/tmpfs_workspace.py run-directory`; retain TSVs and receipts in `logs/`.

The player-constants matrix also builds a 15 fps, 40x18, cold-cap-480 player
with WordBuf rings and scroll support. This combination catches resident-SP
size regressions that the non-scrolling generic player cannot expose. It
requires no source media.

## Existing movie pixels

`verify_trace.py` reads an existing DEBUG player's complete compressed trace:

```sh
tools/python.sh harness/loop_playback/verify_trace.py \
  --header /path/to/matching/HEADER.DAT \
  --trace /path/to/gpgx_logvdp_run.log.gz \
  --tsv logs/loop-playback.tsv --min-loops 3
```

Hold a managed artifact lease while reading a workspace trace. The header must
belong to that exact disc. The reader reconstructs the centered movie aperture
from actual VRAM/CRAM writes, including flips and the player's whole-plane
HScroll/VScroll. It requires consecutive frame numbers, compares every later
loop's RGB333 pixels with the first loop, and rejects nonzero slip, control
desync or audio resync counters. It writes a diagnostic TSV before reporting
pixel/counter failures. Movies above 65,535 frames are outside this reader's
scope. These TSVs are not recording/publication HUD gates.

The first loop is a replay reference, not an independent source-quality
oracle. A successful comparison proves restored visual state, not that the
first loop equals the encoder decisions. The synthetic reader supplies that
independent check for its own fixture. Neither reader proves physical drive
timing, PCM sample equality or sound quality.

## Reproduction and evidence

On base `3ddca8f`, the 15 fps 256-frame fixture completes one exact loop in
6,000 VBlanks and then stops. A debugger snapshot identifies Main at
`cmd_wait_ready` and Sub at the header-signature `bad_header` branch. Checking
only the first sector's absolute MSF restores repeated playback but charges a
recovery per restart. A 24 fps diagnostic records an older sector at MSF
`0x03DC` when the requested first MSF is `0x03DD` (LBA `0x0347` plus 150).
Discarding this preceding sector preserves the file count and continuous read.
Increasing a STOP delay alone does not remove that preceding sector.

The existing 2,293-frame CAVC `machi-op` BODY provides a separate real-footage
case. With the read boundary repaired, three complete loops progress with
zero recovery counters, but frame 114 differs after each restart: 24 pixels
at the left edge, x=0..2 and y=8..15 within the 320x144 raster. The first pan
uses HScroll=3. Its previously hidden name-table cell at plane row 6, column
63 changes from zero on first boot to `0x2229` on replay. Clearing the full
64x32 stage at every start removes the retained cell. Frame 0 also publishes
zero HScroll/VScroll, including when the preceding movie ended while scrolled.

This local real-footage build reuses the existing BODY byte-for-byte. Its
copied HEADER updates only boot-extension padding, and its old PALIDX gains
unused sentinel entries to meet the current capacity. This is a diagnostic
rebuild, not a supported legacy-format migration. The saved `machi-ed`
HEADER is the older TTRC format and is rejected; this qualification does not
claim a current `machi-ed` disc or a fresh matching SIM.

Local evidence uses the `logs/issue125-` prefix. `before.tsv` contains the
256-frame stopped baseline; `prefix-{15,24,30}.tsv` contains the cadence
regressions; `machi-op-final2.tsv` retains the pixel-failure reference. Final
real-footage and build results, command parameters, artifact hashes and exit
statuses are bound in `logs/issue125-qualification.json`.

The qualified cadence runs display 1,024 / 1,280 / 1,280 exact frames over
4 / 5 / 5 complete loops at 15 / 24 / 30 fps. The final `machi-op-complete`
run covers 25,000 emulator VBlanks, 5,404 displayed movie frames, two complete
loops and 818 frames of the third loop. Every replay pixel equals its first-loop
reference and all recovery counters remain zero. The preceding
`machi-op-verified` run also covers three complete loops before the final
explicit zero-scroll publication was added. The build matrix passes with the
15 fps scroll/WordBuf player at 5,104 bytes, within the 5,120-byte resident limit.
