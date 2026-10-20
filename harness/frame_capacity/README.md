# Frame capacity qualification

The player supports 1..65,535 frames with the existing unsigned 16-bit count,
control sequence, palette-switch index and four-digit DEBUG HUD. Movie indices
end at `FFFE`; `FFFF` remains the pre-roll and palette-table sentinel. Header
and control-prefix sizes do not grow.

## Memory and boot proof

`test_boot_route.py` models every entry and both physical Word-RAM banks,
including 16K/32K boundaries and the final index. It also checks current packed
HEADER files. Long routes load into the frame-0 bank; after HEADER EOF, the
boot extension mirrors one sector at a time through PRG `0x7B000..0x7B7FF`.
Two bank toggles restore ownership after every sector. PrgBuf and APPLY retain
their complete timed allocations. Specialized tables up to 16 KiB keep the
complete PRG stage.

`test_packing.py` requires byte-identical HEADER, BODY, MOVIE, PALTAB and PALIDX
for the same short decisions under the 16K and 65,535 limits. The canonical
Word-RAM layout tests check that increasing the actual table from 16 to 64 KiB
removes exactly 48 KiB from each WordBuf when output peaks are held fixed.

```sh
tools/python.sh -m unittest discover -s harness/frame_capacity -p 'test_*.py'
tools/python.sh harness/player_constants/verify.py
tools/python.sh harness/pcm_write_pacing/check_pacing.py
```

The build matrix covers 15/24/30fps, centered output, 16,385/32,768/65,535
frames, and generic/specialized builds. Disassembly checks require all three
long/generic route loads to zero-extend the index; short specialized loads
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
