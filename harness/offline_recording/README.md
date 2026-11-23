# Offline lossless recording

`tools/record_movie.sh` captures standalone BlastEm output at an exact emulator
frame limit. Use CUE and ISO together, a matching BIOS and an explicit input
script when overriding the default BIOS START sequence. The same disc, BIOS,
input and executable hashes must appear in both receipts for a repeatability
check. See `harness/blastem/README.md` for the basic capture workflow.

Requalify after a capture-path change with two lossless runs under the same
inputs. Keep the complete startup and tail. Use the emitted `LOSSLESS=` paths:

```sh
tools/python.sh tools/compare_recordings.py CAPTURE_A.mkv CAPTURE_B.mkv \
  --json logs/blastem-repeatability.json
```

The comparator checks decoded video pixels, every stereo PCM sample and the
original packet timestamps and durations. With `--vdp-event-log`, compare
both same-run `VDP_EVENT_LOG=` files as well. Exact capture equality concerns
this emulator, these inputs and these settings. Playback faults and appearance
are checked separately on the matching lossless recording. Routine captures
use the runner's own media, exit and count checks.

## Historical RetroArch recording results

This section and the Results below it are the archived record of one
qualification run. Their numbers, disc geometry, and hashes belong to that
run's exact environment, recorded before the switch to BlastEm.

- Date: 2026-07-17
- RetroArch: 1.22.2, Git `b2ceb50`
- Core: system Genesis Plus GX libretro binary, SHA-256
  `40791618c03ea3f1fa04d925835b10671c8429c5ff9919ef58401303c57df920`
- Branch implementation: `251801413082431a7fd766c170d5773322afd242`
- Profile: H32 256x224, 30 fps movie, DEBUG HUD, PCM audio
- Requested bounded result: 140 seconds, with startup and tail
- Raw fixed run: 9000 emulator frames, 150.150 seconds of video time

The same 9120-frame Replay drove realtime, offline, and repeat-offline runs.

## Results

| Run | Main RetroArch wall | Main speed | High-level wall | Bounded size |
|---|---:|---:|---:|---:|
| Realtime FFV1/FLAC | 149.347 s | 1.01x | 178.759 s | 571,303,591 B |
| Offline FFV1/FLAC | 11.157 s | 13.46x | 40.592 s | 571,303,591 B |
| Offline repeat | 11.167 s | 13.45x | 40.567 s | 571,303,591 B |

The equal-setup high-level path was about **4.40x faster**. A separate
one-command offline run that also rebuilt the disc and generated its Replay
took 48.79 seconds (`PIPELINE_WALL_SECONDS=48.504`), still about **3.67x
shorter** than the 178.84-second realtime command. The final equal-setup
`/usr/bin/time -v` measurements were:

| Run | User CPU | System CPU | Reported CPU | Max RSS |
|---|---:|---:|---:|---:|
| Realtime | 186.27 s | 9.73 s | 109% | 900,988 KiB |
| Offline | 90.55 s | 2.89 s | 229% | 900,704 KiB |

Realtime versus offline and offline versus repeat both passed all exact gates:

- bounded duration: 140.016 seconds;
- decoded video: 8390 frames;
- video hash-sequence SHA-256:
  `22fb4307df8ed7f501b5d84475307baca1b8a34aec9cb7a3d557488576fd8207`;
- decoded audio: 6,174,720 stereo sample frames, 24,698,880 PCM bytes;
- PCM SHA-256:
  `2c0f18a7fe2b099ebc9617a3f7888e00c6f33056bb1378958ff3d464979b6887`;
- all video/audio packet timelines and compared stream metadata equal;
- archived diagnostic values from this qualification were RMS 869.948, peak
  12,724, and maximum adjacent-sample jump 4109. These are measurements, not
  current pass/fail gates.

A visual contact sheet confirmed the Mega-CD logo, CD player, licence screen,
DEBUG HUD movie playback through the full source, and post-movie tail.

The explicit realtime-lossless fallback also passed a wall-clock smoke run:
8.05 seconds of bounded 256x224 FFV1/FLAC, normal runtime/core unload, readable
trailer, a non-empty audio stream, and a successful preview transcode.
