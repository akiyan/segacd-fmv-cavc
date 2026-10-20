---
name: compilation
description: "Prepare and upload an existing lossless playback recording when the user requests playback publication or invokes /compilation. Use after recording; this skill does not request a new encode or capture."
---

# Playback publication

Select the requested lossless recording and its identity/evidence. An emulator
capture is not a physical-hardware capture. If evidence is missing, determine
whether it can be recovered from existing logs/recording before starting work.
Read `YOUTUBE.md` for all metadata and version rules; do not duplicate them here.

For DEBUG publication, use the matching complete-loop PASS gate described in
`record/references/qualification.md`. HUD-free publication uses the `release`
evidence chain. Never transplant a gate or claim unperformed verification.
Existing user authorization to upload remains sufficient after checks; no
additional approval of gate statistics is required.

Transcode the whole startup-inclusive input:

```sh
tools/python.sh tools/tmpfs_workspace.py run-file \
  --output STEM_emu.mp4 --kind compilation-mp4 --required-gb 8 \
  --input "$LOSSLESS" -- \
  ffmpeg -i "$LOSSLESS" \
    -vf "scale=2048:1568:flags=neighbor,setsar=1" \
    -c:v libx264 -crf 10 -preset slow -pix_fmt yuv420p \
    -c:a aac -b:a 192k -movflags +faststart '{output}'
```

Use configured runtime roots and the printed result path. H40's 320x224 PAR
32:35 becomes 2048x1568 SAR 1:1, DAR 64:49. Horizontal replication varies
between six and seven pixels; nearest preserves source samples, but H.264 and
YouTube delivery are not lossless. Do not add trimming, fps conversion or
chapters unless specifically requested.

Check output raster/SAR, audio, cadence and duration against input and inspect
fresh boot/content/tail stills. Read palette-switch count with
`tools/python.sh tools/cram_switches.py SIM_OUT`. Prepare metadata from
YOUTUBE.md; use the available configured uploader, not a workstation-specific
credential path. Report missing upload capability without pretending success.
Upload the high-quality artifact before its lease expires. Return the video
link, local path, duration and any material limitation. Do not retitle or edit
other uploads unless that change is within the user's request.
