---
name: hudline
description: Render and inspect one whole-movie PNG from a descriptive DEBUG playback HUD TSV and matching schema-14 gate JSON, then combine it with the exact codec timeline. Use after a full recording, for frame-by-frame playback diagnostics, or when the user invokes /hudline.
---

# Playback HUD Timeline

Create one deterministic, frame-aligned diagnostic image from a complete DEBUG
HUD OCR pass. Use descriptive field names throughout.

## Workflow

1. Require the persistent HUD TSV and adjacent gate JSON generated from the
   same lossless recording:

   ```text
   logs/<datetime>_<profile>_<sha10>_eNN_pNN_hud.tsv
   logs/<datetime>_<profile>_<sha10>_eNN_pNN_hud_gate.json
   ```

   The gate must use schema 14. Render failed gates too. An incomplete loop may
   be rendered only when the gate explicitly records that failure; keep the
   complete expected frame axis and shade the missing suffix.

2. Render:

   ```sh
   tools/python.sh .agents/skills/hudline/scripts/render_hudline.py \
     logs/RUN_hud.tsv \
     --gate-json logs/RUN_hud_gate.json \
     --config profiles/PROFILE.toml \
     --label "short run label"
   ```

   The renderer prints the direct tmpfs PNG and a persistent content-keyed
   layout receipt under `logs/`.

3. When a matching managed GPGX LOGVDP run is available, first run
   `harness/gpgx_logvdp/extract_frame_tsv.py`, then pass its TSV with
   `--gpgx-vdp-tsv`. The extraction receipt proves input hashes and HUD frame
   alignment. Physical transfer totals are independent diagnostics; the
   retired per-VBlank logical share fields are no longer present in the HUD.

4. Inspect the PNG with `view_image`. Confirm:

   - expected and observed frame counts;
   - gate maxima and limits;
   - descriptive row labels;
   - palette boundaries;
   - frame 0 is blank in every metric row;
   - the terminal hold is absent from cadence statistics;
   - edge cadence observations remain visible but are absent from the ALERT
     count: first/last four content frames at 30 fps and two at 15 fps.

5. Generate the exact warning/over-limit report:

   ```sh
   tools/python.sh .agents/skills/hudline/scripts/report_overages.py \
     logs/RUN_hud.tsv \
     --gate-json logs/RUN_hud_gate.json \
     --output STEM_emu_hud_warnings.md
   ```

   Cumulative `sector_slip`, `control_desync`, and `audio_resync` fields and
   sticky `prgbuf_jitter_peak_kib` produce events only when their value
   changes. `vblank_spill` produces a warning for every over-limit frame.
   `cd_wait_count` is diagnostic and never creates an over-limit event.

6. Require the matching `/timeline` PNG and receipt from the exact sim
   decisions. Generate it when absent, then invoke `/mixline`. Do not resize
   either graph.

7. Publish images only when the user requested this publication workflow or
   an enclosing upload workflow authorizes it. Use
   `.agents/skills/timeline/scripts/publish_gist.py`, preserve its receipts,
   and show the local image in the conversation.

## Image contract

- Frame axis: `x = 220 + frame * pixels_per_frame`.
- First row: derived displayed VBlanks per content frame. Frame 0 and the
  terminal frame are unknown. Fixed 15 fps expects four VBlanks and fixed
  30 fps expects two. Delivery-paced cadence has no fixed guide. At fixed
  cadence, observations in the first/last four content frames at 30 fps and
  two at 15 fps stay plotted as diagnostics but do not raise ALERT.
- The next two rows are derived `pattern_dma_ready_pressure` and raw
  `name_table_dma_start_vcounter`. They are diagnostic-only and sit directly
  below VBLANK. Pattern ready is sampled immediately before Main waits for the
  first fresh blank head; it is not the post-wait DMA trigger. Ready pressure
  measures lateness: visible scanlines `00..DF` map directly to pressure
  `00..DF`, `E0` is the zero-margin first VBlank head, and any later raw
  V-counter maps to the `0x100` missed-head sentinel. A frame with no cold run
  has no pressure point; a real ready event on scanline 0 is pressure zero.
  This saturation avoids inventing an order for the NTSC V-counter's repeated
  `E5..EA` values. Draw an orange `E0` deadline guide and colour `0x100`
  points red. Each row uses three times the standard row height so small phase
  differences remain visible in the whole-movie image. Plot each frame as an
  unconnected point; do not fill bars or connect the points.
- Gate rows, in descriptive order:
  `sector_slip`, `control_desync`, `audio_resync`, `vblank_spill`,
  `prgbuf_jitter_peak_kib`.
- Diagnostic rows when present:
  `pump_gap_ticks`, `msf_gap_recoveries`, `apply_backpressure`,
  `reader_ahead_frames`, `reader_slot_sector`, `transfer_vblanks`,
  `transfer_end_vcounter`, `cd_wait_count`, `audio_lead_256b`,
  `sub_wait_scanlines`, `adpcm_decode_units`, `transfer_ticks`, `cold_runs`,
  `flip_vcounter`, `first_share_exit_vcounter`,
  `pattern_dma_ready_pressure` (derived from
  `pattern_dma_ready_vcounter` + `cold_runs`),
  `name_table_dma_start_vcounter`, and `pass2_delay_q4`.
- The palette segment is a switch label and vertical boundary, not a separate
  value row.
- Frame 0 keeps its horizontal cell for alignment but contributes to no bar,
  maximum, statistic, event, or scale.
- Preserve native units and hexadecimal axis labels.
- Gate limits and the ready-pressure `E0` deadline are orange, the normal
  jitter interval is yellow, and the normal cadence guide is green.
- The receipt records row geometry and plot style, hashes, expected/observed
  frames, gate limits, descriptive diagnostic maxima, statistics, and
  recording identity.

## Gate interpretation

Schema 14 gate fields are:

```text
sector_slip control_desync audio_resync vblank_spill
prgbuf_jitter_peak_kib
```

`vblank_spill` is warning-only. The other four fields fail when they exceed
their limits. Fixed-cadence `transfer_vblanks` above the cadence interval and
derived visible-duration misses outside the cadence edge exception are also
warnings. The edge exception affects only the derived display-duration alert;
it does not waive gate fields or `transfer_vblanks`. `cd_wait_count`,
`adpcm_decode_units`, `pump_gap_ticks`, APPLY back-pressure, reader lead, and
transfer phases are diagnostic.

Always preserve minimum, mean, median, maximum, and sample count for
`cd_wait_count` and `adpcm_decode_units`; do the same for `pump_gap_ticks` when
present. Report APPLY back-pressure frame count and reader/transfer maxima.

## Resource

`scripts/render_hudline.py` is the canonical renderer.
`scripts/report_overages.py` is the canonical event reporter. Update and test
them rather than creating one-off plots.
