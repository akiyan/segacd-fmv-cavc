---
name: hudline
description: Render, inspect, and publicly publish one large whole-movie PNG from a DEBUG playback HUD TSV and its matching gate JSON, then require the matching codec timeline and publicly publish their combined mixline. Use after every full emulator or hardware recording, when the user invokes /hudline, or when the S/D/R/M/J gate and diagnostic C/A/Q/G/B/K/H/X/Y/O/Z/Y3/Y4/T/I fields need frame-by-frame visual comparison.
---

# Playback HUD Timeline

Create one deterministic full-recording diagnostic image after the complete HUD
OCR pass. Keep the image frame-aligned with `/timeline`, then immediately use
`/mixline` to combine both without resampling.

## Workflow

1. Require the HUD TSV and gate JSON generated from the same lossless recording.
   The HUD TSV body must be the persistent
   `logs/<datetime>_<profile>_<sha10>_eNN_pNN_hud.tsv`; a run-specific
   `videos/STEM_emu_hud.tsv` symlink to it is accepted as the input path.
   The renderer checks the first loop, contiguous frame numbers, expected frame
   count, profile SHA, gate maxima, and recording size/mtime when available.
   Render failed gates too; when playback did not complete one loop, render
   the contiguous observed prefix only if the matching gate explicitly records
   that incomplete-loop failure. Keep the expected full-movie frame axis,
   shade the unobserved suffix, and state observed/expected frame counts in the
   heading so the matching full codec timeline can still be combined without
   resampling. The image is evidence and must not hide the missing suffix.
2. Run:

```sh
tools/python.sh .agents/skills/hudline/scripts/render_hudline.py \
  videos/STEM_emu_hud.tsv \
  --gate-json videos/STEM_emu_hud_gate.json \
  --config profiles/PROFILE.toml \
  --label "short run label" \
  --output videos/STEM_hudline.png
```

3. Inspect the PNG with `view_image`. Confirm that every frame is present, the
   gate summary matches the JSON, gate-limit lines are visible, palette
   boundaries and their `Pxx` labels align, and all HUD rows are legible.
4. Generate the exact warning/over-limit frame table:

```sh
tools/python.sh .agents/skills/hudline/scripts/report_overages.py \
  videos/STEM_emu_hud.tsv \
  --gate-json videos/STEM_emu_hud_gate.json \
  --output videos/STEM_emu_hud_warnings.md
```

   Frame 0 is untimed boot staging. Exclude it from every metric, gate,
   severity decision, scale maximum, OCR aggregate, and VBLANK statistic; leave
   its complete horizontal extent blank in every HUD row. Keep it only for
   first-loop sequence completeness and x-axis alignment.

   Always report the minimum, mean, median, and maximum of both `C` and `A`
   across the timed first loop. Validate those statistics against schema-4 or
   newer gate JSON, include them in the Markdown summary and image heading, and
   preserve them in the layout receipt.
   When `G` is available, report and preserve its minimum, mean, median, and
   maximum after separating `B`; also report the B APPLY-back-pressure frame
   count. When `H/X` are available, validate and report the exact maximum
   physical PrgBuf occupancy and maximum packed reader lead against the gate
   JSON. When `Y/O/Z/Y3/Y4/T/I` are available, validate and report the exact
   maxima for the first four runtime VBlank word shares, first/final
   pattern-exit V-counters, and transfer-VBlank count. `T>N` at fixed cadence
   raises alert `WARNING` while retaining gate `PASS`; the individual shares
   and phases remain diagnostic.

   For exact integer-VBlank rates, treat every timed derived `VBLANK` value
   different from the normal cadence as a warning: 15 fps expects 4 and 30 fps expects 2.
   Report VBLANK only as `warning rate / warning count / evaluated total`; do
   not add individual VBLANK-warning frames to the event table. This warning
   does not turn an otherwise passing upload gate into a failure; keep gate
   `PASS` and report alert `WARNING`. Do not apply this generic rule to 24 fps: its
   expected 2/3 cadence needs a separate profile-specific rule when a 24 fps
   work is tuned.

   Show the resulting Markdown table in the response. It must include
   hexadecimal `F`, every gate-overage value/limit, derived `VBLANK`, and
   every HUD value available in the TSV
   (`P/S/D/R/L/C/W/M/A/U/N/J/Q/G/B/K/H/X/Y/Z/Y3/Y4/T/I/V/O/E`).
   For per-frame `M`, include every over-limit frame and label it `WARNING`.
   `C` is diagnostic and must never create an over-limit event or alter the
   gate status. For cumulative `S/D/R`
   and sticky-peak `J`, include only transitions to a new over-limit value
   rather than repeating unchanged state on every later frame. A gate value
   equal to its limit is not an overage.
5. Publish the exact PNG to a public Gist:

```sh
tools/python.sh .agents/skills/timeline/scripts/publish_gist.py \
  videos/STEM_hudline.png \
  --description "SEGA-CD FMV playback HUD timeline: short run label"
```

6. Show the image inline in the conversation and provide the Gist page plus raw
   PNG URL. Do this after every completed recording, whether the gate passes or
   fails. Public Gist publication is authorized only when the user requested
   this workflow.
7. Require the matching `/timeline` PNG and layout receipt from the exact sim
   decision log used to build the recording. If they are absent, generate and
   publicly publish that timeline first. Immediately invoke `/mixline`, inspect
   the aligned combined PNG, show it inline, and publish it to a public Gist.
   Preserve the timeline, hudline, and mixline layout/Gist receipts. This is
   mandatory for every hudline, including `FAIL` and incomplete-loop evidence;
   do not finish the workflow with only the hudline.

## Image contract

- Use the complete first movie loop. For an explicitly failed incomplete-loop
  gate, draw the complete observed prefix on the expected full-movie frame
  axis, visibly shade and label the unobserved suffix, and state the
  expected/observed counts in the heading. Frame 0 keeps its horizontal
  position for alignment, but all metric rows are blank there and it affects
  no gate, aggregate, or scale.
- Keep `/timeline`'s horizontal contract: left edge 220 px, the same automatic
  pixels-per-frame rule, and `x = 220 + frame * pixels_per_frame`.
- Put `VBLANK` first. Derive it from the difference between consecutive
  `capture_first` values: because HUD `F` is published with the displayed
  image, this is the number of scanouts for which that content frame was
  actually visible. Draw the expected cadence
  (`vsync_n_for_fps(content_fps)`, so 15 fps is 4) as a green guide line. Use
  neutral gray for healthy samples and yellow for nonzero deviations.
  Leave frame 0 and the final frame unknown and exclude both from the
  statistics: frame 0 is untimed boot staging and the final span is the
  recorder's terminal hold, not playback cadence. For 24 fps, retain the
  measured row but defer its normal-line and warning rule until its 2/3 cadence
  is specified.
- Include the values-only HUD fields `S/D/R/L/C/W/M/A/U/N/J`, plus
  `Q/V/O/E`, `G/K`, `H/X`, and `Y/O/Z/Y3/Y4/T/I` whenever present. Decode packed `G` bit 15 into
  a separate `B` row. Split `X` into its high-byte complete-frame lead and
  low-byte current-slot sector rows. `F` is the x-axis. Do not allocate a
  separate `P` row: palette is
  represented by the `Pxx` switch labels and vertical boundaries on the shared
  horizontal axis.
- Put the five upload-gate rows first and show their exact limits:
  `S/D/R/M/J`. Show the cadence's normal jitter interval separately from the
  absolute J gate limit. Keep `S/D/R` at 23 px (half the normal row height)
  with no unit subheading, but use the same heading font size as every other
  HUD metric. Put `C` first among the diagnostic rows and do not draw a gate
  line for it.
- Follow with the remaining diagnostic, player-state, Sub, Main, and phase
  rows. Render `Q` as two derived rows when present: nonnegative minimum
  balance and positive underflow debt. Render `G` in 30.72 us ticks, `B` as a
  Boolean APPLY-block row, `K` as a cumulative MSF-gap row, `H` as exact
  32-byte-pattern occupancy with the physical back-pressure guide, and `X` as
  separate complete-frame and current-slot-sector rows. Render
  `Y/Z/Y3/Y4` as exact transfer words (16 words per 32-byte pattern), `T` as
  the count of VBlanks
  carrying pattern work, and `I` as the pattern-exit V-counter. Preserve HUD units
  instead of normalizing each recording to its
  observed peak. Every HUD vertical axis shows only its maximum label; omit
  all midpoint and zero labels.
- Preserve the established per-metric colors for normal playback values:
  C yellow, M orange, J, Q, G, H, and W purple, L and X blue, A pink, U cyan, N orange, and
  the corresponding established colors for V/O/E. Only override that metric
  color when the individual sample is `WARNING` or `FAIL`; use yellow for a
  warning and red for a failure. `C` always keeps its diagnostic color because
  it has no gate severity. Do not recolor an entire row because another frame
  or another metric changed the overall gate status.
  Keep the guide scale colorful: gate limits are orange, J's normal jitter
  interval is yellow, and the VBLANK normal cadence is green.
- Show horizontal frame labels as hexadecimal `f0xHEX`. Show every HUD
  vertical-axis maximum and gate/normal limit as `0xHEX`. Full 8-bit rows use
  the compact row height. Keep the unit subheading at 13 px.
- `/mixline` consumes this image and its layout receipt directly. Any hudline
  row-height, scale, or colour change must therefore appear automatically in
  the immediately generated mixline without a second hard-coded layout.
- Write a `<output>.json` layout receipt containing the input hashes, frame
  mapping, expected and observed frame counts, row geometry, fixed scales,
  gate limits, `C/A` minimum, mean, median, and maximum, optional G statistics
  and B frame count, optional H/X and Y/O/Z/Y3/Y4/T/I maxima, and recording identity. `/mixline`
  should consume this receipt rather than rediscovering geometry from pixels.

## Interpretation safeguards

- `S`, `D`, and `R` are cumulative counters; their transition is the event.
- Frame 0 is not a playback measurement. Its HUD values must never be plotted,
  reported as events, or included in maxima, minima, rates, or scales.
- `VBLANK` is derived after recording from consecutive displayed `F`
  transitions; it is not another player HUD field. A 15 fps frame at 4 is
  normal, while every other value is a warning. This rule is deliberately not
  generalized to 24 fps yet.
- `J` is a cumulative PrgBuf excess high-water mark, not current occupancy.
- `Q` is the signed minimum logical PrgBuf balance reached during one frame in
  exact 32-byte patterns. Raw values `8000` through `FFFF` are negative; render
  their magnitude as underflow debt instead of treating them as a high positive
  occupancy. `Q` is diagnostic and never changes the upload gate.
- `G` is the longest interval outside a Sub CDC service opportunity; its
  stopwatch origin is restarted after sector transfer and recovery work. `B`
  proves APPLY back-pressure rejected a control-sector pump. `K` is the
  MSF-gap subset of cumulative `S`, so `(S-K) & 0xFF` is CDC_TRN retry
  exhaustion.
- `H` is the exact per-frame physical PrgBuf peak in 32-byte patterns, unlike
  sticky whole-run `J`. `X` packs the CD reader's complete-frame lead in its
  high byte and current-slot sector position in its low byte. Read them
  together to distinguish useful prefetch from a payload back-pressure event.
  These fields are diagnostic and never change the upload gate.
- `Y/Z/Y3/Y4` are exact word shares for the first four runtime
  pattern-transfer VBlanks, `O/I` are the current frame's first/final
  pattern-exit V-counters, and `T` is the total transfer-VBlank count. Use
  `O=00..DF` to identify a first share that ran into active display, and use
  `I` for the final tail. `T>N` at fixed cadence is a warning; the word shares
  and phases are diagnostic.
- When a gate fails, never report only the maximum. Include the over-limit
  table from `report_overages.py` so the exact workload and phase values at
  each gate event are preserved. Keep VBLANK warnings aggregate-only.
- `C` is diagnostic only: it has no gate line and never changes gate or alert.
  Nonzero `M` is not automatically a failure; compare it with the
  cadence-specific gate line.
- `V` displayed on frame F describes the flip that published frame F-1.
  `O` and `E` belong to frame F.
- OCR confidence and sample repetition are extraction evidence, not player HUD
  fields. Keep their minima/totals in the heading rather than inventing rows.
- Call an emulator capture an emulator recording, not a physical-hardware
  recording.

## Resource

`scripts/render_hudline.py` is the canonical renderer and
`scripts/report_overages.py` is the canonical over-limit event reporter.
Update and test these scripts instead of writing one-off plots or tables.
