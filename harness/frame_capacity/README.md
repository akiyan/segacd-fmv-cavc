# Frame capacity qualification

The player supports 1..83,520 frames in the full 320x224 aperture. The low
count word stays at header offset 4 and its high byte uses offset 37. Control
sequence values and the DEBUG HUD retain their low 16 bits; Main/Sub keep full
32-bit counters. Palette-switch frame bit 16 uses segment-word bit 15, with
`(0xFFFF, 0)` as the unchanged explicit terminator. Header (62 bytes), control
prefix, and PALIDX (256 bytes) do not grow.

Routing stays one byte per frame. Above 65,535 frames, WordBuf0/1 preloads,
refills, source selection, and quality credit are disabled. At the maximum,
each bank reserves 82 KiB for routing and 10,496 bytes for the fixed tail;
a full 1,120-pattern frame-0 output uses 35,872 aligned bytes and leaves
736 bytes. PrgBuf, APPLY, and DicBuf retain their allocations.

## Memory and boot proof

`test_boot_route.py` models every entry and both physical Word-RAM banks,
including 16K/32K boundaries and the final index. It also checks current packed
HEADER files. Long routes load into the frame-0 bank; after HEADER EOF, the
boot extension mirrors one sector at a time through PRG `0x7B000..0x7B7FF`.
Two bank toggles restore ownership after every sector. PrgBuf and APPLY retain
their complete timed allocations. Specialized tables up to 16 KiB keep the
complete PRG stage.

`test_packing.py` requires byte-identical HEADER, BODY, MOVIE, PALTAB and PALIDX
for the same short decisions under the 16K and 83,520 limits. The canonical
Word-RAM layout tests check that increasing the actual table from 16 to 64 KiB
removes exactly 48 KiB from each WordBuf when output peaks are held fixed.

```sh
tools/python.sh -m unittest discover -s harness/frame_capacity -p 'test_*.py'
tools/python.sh harness/player_constants/verify.py
tools/python.sh harness/pcm_write_pacing/check_pacing.py
```

The build matrix covers 15/24/30fps, centered output, 16,385/32,768/65,535
frames, 65,536/65,537/83,520 boundaries, and generic/specialized builds.
Disassembly checks require all three long/generic route loads to use the full
32-bit counter; short specialized loads
retain the word-index instructions. The generic runtime reference is not a
substitute for standard specialized playback qualification.

## Full playback fixture

The shared palette fixture accepts arbitrary valid frame counts. It has a
full 320x224 picture, all 64 palettes spread over the movie, checkpointed
silent audio, a 512-entry DicBuf and a final read of DicBuf entry 511. The
real packer verifies every displayed state, audio chunk and physical BODY
slot. Its timed pattern load is deliberately low; this tests long indexing,
bank mirroring, palette timing, end and restart rather than heavy-motion
quality or throughput.

```sh
tools/python.sh harness/palette_capacity/build_fixture.py \
  --output tmp/frame65535/24fps-65535 --fps 24 --frames 65535

OUTDIR="$PWD/logs/frame65535-24fps-65535" tools/run_headless.sh \
  tmp/frame65535/24fps-65535/palette.cue --tag frame65535-24fps-65535 \
  --max-frames 168000 --boot-wait 0.2 --presses 100 --press-gap 0.05 --shots 0

tools/python.sh harness/palette_capacity/verify_trace.py \
  --fixture tmp/frame65535/24fps-65535 \
  --trace logs/frame65535-24fps-65535/gpgx_logvdp_frame65535-24fps-65535.log.gz \
  --tsv logs/frame65535-24fps-65535/playback.tsv
```

Repeat at 24fps/16,384 frames with 44,000 emulator frames, 15fps/16,385 with
69,000, and 30fps/32,768 with 69,000. Use distinct directories and tags. These
are VDP traces without audio/video recording; their verification TSVs are not
recording HUD gates. The checker reconstructs VRAM/CRAM and checks every cell,
pattern, palette, frame sequence and recovery counter, including the beginning
of the next loop. Failed recovery counters still produce a diagnostic TSV and
then fail verification.

The standard specialized DEBUG player passes these full traces, including
the listed beginning of the next loop. All 64 CRAM palettes, every displayed
cell/pattern, frame order and the final DicBuf entry agree. Slip, control
desync and audio resync are zero in every row.

| fps | Movie frames | Verified displayed frames | Next-loop frames |
|---|---:|---:|---:|
| 24 | 16,384 | 16,902 | 518 |
| 15 | 16,385 | 16,807 | 422 |
| 30 | 32,768 | 33,583 | 815 |
| 24 | 65,535 | 66,383 | 848 |

## Long-movie audio clock

A fixed rounded RF5C164 delta of 1388 loses PCM reserve during the 24fps
65,535-frame fixture: `audio_resync` first changes at frame 38,026. All image
states and frame numbers still agree, and the HUD lead declines continuously
across 32,768. This is a long-duration clock mismatch, not an index boundary.

The long specialized player alternates neighboring frequency deltas against
the physical NTSC crystal/scan clock. `test_audio_clock.py` bounds accumulated
frequency error separately from the normal short/long interval phase swing.
Short movies keep fixed frequency. Register writes retain the official
384-cycle spacing. The pinned core also performs an end-of-frame audio update;
its PCM timing must not be modeled solely by its truncated Sub cycles/line.

For a player-only comparison, `build_fixture.py --stream-from DIRECTORY`
copies identical stream/palette bytes and recompiles only the player. Keep
the two builds and traces separately. `logs/frame65535-builds/stream-ab.tsv`
records the matching hashes of all five files for each tested cadence.

To extract the leading HUD fields observationally from an existing full trace:

```sh
gzip -dc TRACE.log.gz | rg 'VRAM 0xf0[01][0-9a-f] write ->' | \
  tools/python.sh harness/frame_capacity/read_hud_trace.py > logs/e192_p156_trace-hud.tsv
```

The source clock relationship and the core's final audio update can be inspected
in the pinned Genesis Plus GX source, `core/system.c` (`audio_set_rate`),
`core/cd_hw/scd.c` and `core/cd_hw/pcm.c` at commit
`46652c7fd74bd64a99f624b0bd53a768de0ff672`.

## Full-length source encode

`make_source.py` creates an actual 83,520-frame, 24fps, 58-minute H.264 source
in the managed tmpfs workspace. Its full 320x224 raster uses losslessly encoded
flat grey background, silent audio, and a small white marker at the index boundaries
and final two frames. It probes the decoded frame count before writing the
normal encoder profile. The test uses the original encoder at full geometry
and cadence, with cold cap 210; it does not shorten or retime the movie.

```sh
tools/python.sh harness/frame_capacity/make_source.py \
  --profile tmp/frame83520/long83520.toml
tools/python.sh --gpu tools/sim.py tmp/frame83520/long83520.toml
make disc CONFIG=tmp/frame83520/long83520.toml DEBUG=1
```

`test_extended.py` checks complete-header parsing at every boundary, unchanged
field offsets, full-aperture memory bounds, one-byte routes, palette switches
at 65,535 and 65,536, and rejection of WordBuf use/credit in long movies.
The HUD tools reconstruct wrapped frame numbers using the expected movie
length; pass `--frames 83520` to `read_hud_trace.py` for a maximum-length trace.

The synthetic packed fixture additionally supports `--unique-frame0`: all
1,120 visible cells have distinct cold patterns. Long fixtures place palette
switches at frames 65,535 and 65,536 when both exist. These tests exercise the
largest boot output, every displayed cell, all 64 palettes, DicBuf entry 511,
final-frame display, and the following loop without expensive image analysis.
They are playback/data tests and do not substitute for the full source encode.

## Extended playback qualification

The full-raster distinct-pattern fixtures pass all-cell/pattern, palette,
sequence, recovery-counter, and loop-restart checks on the pinned GPGX core:

| fps | Movie frames | Verified displayed frames | Next-loop frames |
|---|---:|---:|---:|
| 24 | 83,520 | 84,319 | 799 |
| 30 | 65,537 | 66,717 | 1,180 |
| 15 | 65,536 | 66,197 | 661 |

Sector slip, control desync, and audio resync remain zero in every row. The
30fps fixture switches palettes at both 65,535 and 65,536; the 15fps fixture
switches at its final frame 65,535. Native and Wasm release player builds are
byte-identical for the 83,520- and 65,537-frame contracts.

A player-only regression on the existing 210-frame, 15fps synthetic WordBuf
ring stream completes two full loops with unchanged BODY bytes and zero
slip/desync/resync. Only the boot extension image and unused PALIDX terminator
padding are refreshed to match the player contract; no source encode occurs.
