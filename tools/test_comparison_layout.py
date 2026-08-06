#!/usr/bin/env python3
"""Tests for the profile-driven comparison frame."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import comparison_layout as layout_mod
from comparison_layout import load

ROOT = Path(__file__).resolve().parents[1]
PROFILE = ROOT / "profiles/sonic-jam-op.toml"

# A profile body the comparison section can be appended to, so an invalid
# [comparison] is rejected for its own reason rather than for a missing encode.
BASE = """schema_version = 5

[source]
path = "assets/sonic-jam-op/original-sonic-jam-op.avi"
fps = "30"
duration = "90.466667"

[video]
width = 288
height = 200
fit = "pad"

[output]
directory = "tmpfs/x/sim"
emit_decisions = true

[encoder]
cold_cap = 210

[palette]
algorithm = "mosaic-gm"
"""

PANELS = """
[comparison]
title = "T"
audio_panel = "emu"
duration = 10.0

[comparison.panels.emu]
label = "Encode"
slot = "main"
aperture = [320, 224]
pixel_aspect = [32, 35]
spec = "spec"
path = "assets/sonic-jam-op/original-sonic-jam-op.avi"
fmv_start = 5.0
lead = 5.0

[comparison.panels.a]
label = "A"
slot = "top_left"
aperture = [320, 224]
pixel_aspect = [32, 35]
spec = "spec"

[comparison.panels.b]
label = "B"
slot = "top_right"
aperture = [320, 224]
pixel_aspect = [32, 35]
spec = "spec"

[comparison.panels.c]
label = "C"
slot = "lower"
aperture = [16, 9]
pixel_aspect = [1, 1]
spec = "spec"
"""


def written(body: str) -> Path:
    tmp = tempfile.NamedTemporaryFile("w", suffix=".toml", delete=False,
                                      encoding="utf-8")
    tmp.write(body)
    tmp.close()
    return Path(tmp.name)


class ComparisonProfileTests(unittest.TestCase):

    def test_sonic_jam_panels_are_read_from_the_profile(self) -> None:
        spec = load(PROFILE)
        self.assertEqual([p.key for p in spec.panels],
                         ["emu", "saturn", "segacd", "real"])
        self.assertEqual(spec.audio_panel, "emu")
        # The label says both what the panel is and that an emulator is
        # running it, so it is not read as the real-hardware capture below.
        self.assertEqual(
            spec.panel("emu").label,
            "Custom FMV Codec Playback — SEGA-CD Emulator (Genesis Plus GX)")
        # The note is switched off, so its height goes to the panels; the
        # wording still resolves for a profile that wants it drawn.
        self.assertFalse(spec.show_audio_note)
        self.assertEqual(spec.audio_note,
                         "Audio: the codec playback panel only")
        # Every panel now has footage, the real-hardware capture included.
        self.assertEqual([p.key for p in spec.with_footage],
                         ["emu", "saturn", "segacd", "real"])

    def test_picture_start_is_the_largest_lead(self) -> None:
        spec = load(PROFILE)
        # The real-hardware capture has the longest run-up, so it opens the
        # video and its lead sets the moment every panel starts moving.
        self.assertAlmostEqual(spec.picture_start, 34.358, places=3)
        self.assertAlmostEqual(spec.panel("real").lead, 34.358, places=3)
        for key in ("emu", "saturn", "segacd", "real"):
            panel = spec.panel(key)
            timeline_start = spec.picture_start - panel.lead
            self.assertGreaterEqual(timeline_start, 0.0)
        # Each panel is fed from its own picture start minus its own run-up.
        self.assertAlmostEqual(spec.panel("emu").source_start, 0.0, places=3)
        self.assertAlmostEqual(spec.panel("segacd").source_start, 52.072,
                               places=3)
        self.assertAlmostEqual(spec.panel("saturn").source_start, 0.0,
                               places=3)
        self.assertAlmostEqual(spec.panel("real").source_start, 0.0, places=3)

    def test_audio_hands_over_when_the_audio_panel_starts(self) -> None:
        spec = load(PROFILE)
        self.assertEqual(spec.audio_intro_panel, "real")
        self.assertEqual(spec.audio_panel, "emu")
        # The hand-over is the emu panel's own timeline start, so the run-up is
        # heard from the panel that is actually on screen for it.
        self.assertAlmostEqual(spec.audio_switch, 18.943, places=3)
        self.assertAlmostEqual(
            spec.audio_switch,
            spec.picture_start - spec.panel("emu").lead, places=6)
        # Without an intro panel there is nothing to hand over.
        self.assertIsNone(load(written(BASE + PANELS)).audio_switch)

    def test_an_intro_panel_must_start_before_the_audio_panel(self) -> None:
        body = BASE + PANELS.replace('audio_panel = "emu"',
                                     'audio_panel = "emu"\n'
                                     'audio_intro_panel = "emu"')
        with self.assertRaisesRegex(ValueError, "must start before"):
            load(written(body))

    def test_source_master_is_retimed_to_the_ntsc_cadence(self) -> None:
        # 30.000 would drift against the recordings and land unevenly on the
        # 59.94 output grid.
        self.assertEqual(load(PROFILE).panel("saturn").input_fps,
                         "30000/1001")

    def test_panels_follow_their_displayed_aspect_not_four_thirds(self) -> None:
        spec = load(PROFILE)
        rects = spec.rects()
        for panel in spec.panels:
            _, _, w, h = rects[panel.key]
            self.assertAlmostEqual(w / h, panel.display_aspect, places=2,
                                   msg=f"{panel.key} is not its own aspect")
            self.assertNotAlmostEqual(panel.display_aspect, 4 / 3, places=3)

    def test_alignments_the_layout_promises(self) -> None:
        spec = load(PROFILE)
        rects = spec.rects()
        g = spec.geometry()
        main = rects["emu"]
        lower = rects["real"]
        left = rects["saturn"]
        right = rects["segacd"]
        # The lower panel's bottom edge is flush with the left column's, so
        # both spec lines share one baseline.
        self.assertEqual(main[1] + main[3], lower[1] + lower[3])
        # The upper right row is justified to the right column's outer edges.
        self.assertEqual(left[0], g["right_left"])
        self.assertEqual(right[0] + right[2], layout_mod.RIGHT_RIGHT)
        # Both upper panels share one height, so their tops and bottoms are
        # level, and the derived gap between them clears the minimum.
        self.assertEqual(left[3], right[3])
        self.assertEqual(right[0] - (left[0] + left[2]), g["inner_gap"])
        self.assertGreaterEqual(g["inner_gap"], layout_mod.INNER_GAP)
        # The lower panel spans the column exactly, so its frame lines up with
        # the row above it on both edges.
        self.assertEqual(lower[0], left[0])
        self.assertEqual(lower[0] + lower[2], right[0] + right[2])
        self.assertEqual(lower[2], g["right_width"])
        # The lower row's label clears the upper row's spec line.
        self.assertGreater(lower[1] - layout_mod.LABEL_GAP,
                           g["top_spec_baseline"])
        # Nothing overflows the canvas or the right column.
        self.assertLessEqual(lower[0] + lower[2], layout_mod.RIGHT_RIGHT)
        self.assertGreater(g["right_left"], main[0] + main[2])

    def test_left_column_takes_the_height_between_headline_and_note(self) -> None:
        # One headline instead of three lines, so the playback panel starts
        # higher and is the largest panel by a wide margin.
        spec = load(PROFILE)
        rects = spec.rects()
        main = rects["emu"]
        self.assertEqual(main[1], layout_mod.PANEL_TOP)
        self.assertEqual(main[1] + main[3], spec.geometry()["main_bottom"])
        biggest = max(rects.values(), key=lambda r: r[2] * r[3])
        self.assertEqual(biggest, main)

    def test_dropping_the_audio_note_gives_its_height_to_the_panels(self) -> None:
        spec = load(PROFILE)
        drawn = load(written(BASE + PANELS))
        self.assertFalse(spec.show_audio_note)
        self.assertTrue(drawn.show_audio_note)
        # With the note gone the main panel's spec is the lowest text, sitting
        # exactly at the last baseline the bottom margin allows.
        self.assertEqual(
            spec.geometry()["main_bottom"] + spec.panel("emu").spec_depth,
            spec.bottom_baseline)

    def test_a_two_line_spec_pushes_the_row_below_it_down(self) -> None:
        # The upper row's specs run to two lines, and the lower panel's label
        # must still clear the last of them by the full row gap.
        spec = load(PROFILE)
        g = spec.geometry()
        self.assertEqual(len(spec.panel("saturn").spec), 2)
        self.assertEqual(len(spec.panel("segacd").spec), 2)
        self.assertEqual(
            g["top_spec_baseline"],
            layout_mod.PANEL_TOP + g["top_height"]
            + layout_mod.SPEC_GAP + layout_mod.SPEC_LINE_HEIGHT)
        lower_label = g["lower_top"] - layout_mod.LABEL_GAP
        self.assertEqual(lower_label - g["top_spec_baseline"],
                         layout_mod.ROW_GAP)

    def test_a_spec_may_be_one_string_or_a_list(self) -> None:
        one = load(written(BASE + PANELS))
        self.assertEqual(one.panel("emu").spec, ("spec",))
        body = BASE + PANELS.replace(
            'spec = "spec"\npath =', 'spec = ["a", "b"]\npath =')
        self.assertEqual(load(written(body)).panel("emu").spec, ("a", "b"))

    def test_every_slot_must_be_filled_exactly_once(self) -> None:
        body = BASE + PANELS.replace('slot = "lower"', 'slot = "main"')
        with self.assertRaisesRegex(ValueError, "share one slot"):
            load(written(body))
        body = BASE + PANELS.replace("""
[comparison.panels.c]
label = "C"
slot = "lower"
aperture = [16, 9]
pixel_aspect = [1, 1]
spec = "spec"
""", "")
        with self.assertRaisesRegex(ValueError, "no panel in slot"):
            load(written(body))

    def test_audio_panel_must_name_a_panel_that_has_footage(self) -> None:
        with self.assertRaisesRegex(ValueError, "audio_panel must name"):
            load(written(BASE + PANELS.replace('audio_panel = "emu"',
                                               'audio_panel = "nope"')))
        # Panel "a" exists but has no path, so it cannot supply audio.
        with self.assertRaisesRegex(ValueError, "no footage to take audio"):
            load(written(BASE + PANELS.replace('audio_panel = "emu"',
                                               'audio_panel = "a"')))

    def test_unknown_panel_key_is_rejected(self) -> None:
        body = BASE + PANELS.replace('spec = "spec"\npath =',
                                     'spec = "spec"\nwidth = 3\npath =')
        with self.assertRaisesRegex(ValueError, "unknown keys"):
            load(written(body))

    def test_missing_comparison_section_is_reported(self) -> None:
        with self.assertRaisesRegex(ValueError, "no \\[comparison\\] section"):
            load(written(BASE))


if __name__ == "__main__":
    unittest.main()
