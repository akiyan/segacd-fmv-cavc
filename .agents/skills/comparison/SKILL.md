---
name: comparison
description: Adjust a profile's comparison frame (its panels, labels, specs, texts, footage paths and synchronisation) and show a preview composed from the real footage. Use when the user asks to change the comparison layout or its wording, when a panel's material or timing changes, when new footage such as a real-hardware capture arrives, or when they invoke "/comparison".
---

# /comparison: Comparison Frame and Preview

The comparison video shows one encode beside its source master and reference
recordings inside a 1920x1080 frame. This skill adjusts that frame and shows
the result, so a change is judged against real pictures rather than against a
description of them.

Three places own the work. Edit the right one:

- **`[comparison]` in the profile TOML** owns everything per-source: the
  title, subtitle, codec line, which panel supplies audio, the output path and
  duration, and one `[comparison.panels.<key>]` table per panel carrying its
  label, slot, aperture, pixel aspect, spec line, footage path, cropping,
  padding, input re-timing and synchronisation. **All frame text is here.**
- **`tools/comparison_layout.py`** owns the frame as a layout: canvas size,
  slot geometry, gaps, type sizes, colours, the drawing, the overlay PNG, and
  the panel rectangles. It also validates the `[comparison]` section.
- **`tools/render_comparison.py`** owns the ffmpeg graph that fills the panels.

Wording, footage and timing changes are TOML edits and need no code change.
Reach for the layout module only when the frame's geometry itself must move.
Never hard-code a rectangle in the render module: it reads them from the layout
so the drawn frame and the video placement cannot drift apart.

## Procedure

### 1. Read the current state before editing

```sh
tools/python.sh tools/comparison_layout.py profiles/PROFILE.toml --print-layout
```

This prints every panel's rectangle, aperture, displayed aspect, slot, footage
path, source offset and timeline start. Report the panel the request concerns.

### 2. Apply the adjustment

For text, footage or timing, edit the profile's `[comparison]`. For geometry,
keep the rules the layout already follows:

- **Panels are sized from a displayed aspect, never from a nominal 4:3.** An
  H40 panel is a 320x224 aperture with pixel aspect 32:35, displayed 1.3061. A
  16:9 capture is 1.7778. Compute a width from a height and the aspect; do not
  type both.
- **Derive positions from other positions.** The upper right row is justified
  to the right column's outer edges, the lower panel's bottom edge is flush
  with the left column's, and the lower row's label clears the upper row's spec
  line by `ROW_GAP`. Express a new constraint the same way instead of adding a
  magic number.
- **Every panel gets a label above and a spec line below.** A panel without
  footage still gets both.
- **The audio note is generated from `audio_panel`**, so it cannot disagree
  with what is muxed. Changing which panel supplies audio is one TOML edit.

### 3. Show a preview composed from the real footage

Always render a still from the actual materials whenever any footage exists:

```sh
tools/python.sh tools/render_comparison.py profiles/PROFILE.toml \
  --still /tmp/.../preview.png --at 45
```

`--at` is a timeline second. Pick a moment where the panels carry real
pictures. A panel with no footage, and a panel whose footage has not started by
that second, are left as the frame's blacked-out rectangle, which is the
correct appearance.

Then do both of these, in this order:

1. **Read the PNG yourself** and check it against what was asked.
2. **Send it with SendUserFile** (`display: "render"`). Reading a file only
   puts it in your own context - the user's screen shows nothing until it is
   sent. A report that describes the preview without delivering it does not
   count as showing it.

Use the placeholder preview only when no footage exists at all:

```sh
tools/python.sh tools/comparison_layout.py profiles/PROFILE.toml \
  --preview /tmp/.../preview.png
```

### 4. Verify numerically as well as visually

A preview hides small errors. After a geometry change, confirm from
`--print-layout` that each panel's width/height still matches its
`display_aspect`, and that the promised alignments hold. `tools/python.sh -m
unittest tools.test_comparison_layout` checks those invariants and the
section's validation. State the numbers in the report.

### 5. Re-render the video only when asked

The still is the review artifact. When the user wants the video, delete the
previous file first so a failed run cannot be mistaken for a fresh one:

```sh
rm -f videos/NAME/comparison.mp4
tools/python.sh tools/render_comparison.py profiles/PROFILE.toml
```

The output path and duration come from the profile. Report the picture start
and each panel's source offset, which the renderer prints.

## Adding footage to an empty panel

A panel with no `path` is drawn as its frame with a `placeholder` caption. When
its recording arrives:

1. Put the file under `assets/<source>/` and set `path` in its panel table.
2. **Measure `fmv_start`; do not assume it.** Find the candidate boundaries,
   then confirm which one is the picture by looking at frames either side:

   ```sh
   ffmpeg -hide_banner -i MATERIAL \
     -vf blackdetect=d=0.2:pic_th=0.99:pix_th=0.05 -f null -
   ```

   A black-end is where a panel stops being black, which is **not always where
   it starts moving**. The encode's own recording holds frame 0 up while the
   player waits for the first timed slot to prove CD service, so its picture
   starts 0.283 s after its black-end; aligning other panels to the black-end
   ran them visibly early. When a panel shows the same content as another,
   measure the offset from content instead: detect scene cuts in both with
   `select='gt(scene,0.3)',metadata=print`, and take the offset on which
   several cuts agree.
3. Set `lead` to how much run-up should stay on the timeline. Equal leads make
   two panels start their boot sequences together; a lead of 0 makes a panel
   wait for the picture.
4. Check the material's frame rate. Re-time it with `input_fps` when its stored
   rate is not the rate the console displays it at — a 30.000 master is
   displayed on the NTSC 29.97 cadence, and leaving it at 30.000 both drifts
   over the clip and lands unevenly on the 59.94 output grid.
5. Set `crop` or `pad` when the material is not already the panel's aperture.
   Pad fill is black, because the frame backdrop would show through as grey
   around a smaller picture.
6. Re-render the still, verify the new panel against its neighbours, then the
   video.

## Verifying synchronisation

Correlate two panels that show the same content, comparing each against
deliberate offsets so the chosen value is shown to be the best one rather than
merely plausible. Crop both panels from the output using the rectangles from
`--print-layout`, normalise them to one size, and compare. A correct alignment
holds to the end of the clip, not only at the start; check a late second too,
since a rate mismatch shows up only after it has accumulated.

## Reporting

Send the preview with SendUserFile before writing the report, then lead with
what changed. Include the affected panel's rectangle, its aspect check, and any
alignment the change moved. Say plainly which panels had no footage. Never end a
layout adjustment without having delivered the image.
