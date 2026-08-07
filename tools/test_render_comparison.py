#!/usr/bin/env python3
"""Tests for the comparison muxing stage."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import render_comparison
from comparison_layout import load

ROOT = Path(__file__).resolve().parents[1]

# A profile whose two panels differ in exactly the thing under test: one is
# re-timed on input, the other is not.
BODY = """schema_version = 5

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

[comparison]
title = "T"
audio_panel = "emu"
duration = 10.0

[comparison.panels.emu]
label = "Playback"
slot = "main"
aperture = [320, 224]
pixel_aspect = [32, 35]
spec = "spec"
path = "assets/sonic-jam-op/original-sonic-jam-op.avi"
fmv_start = 5.0
lead = 5.0

[comparison.panels.src]
label = "Source"
slot = "right_top"
aperture = [320, 224]
pixel_aspect = [32, 35]
spec = "spec"
path = "assets/sonic-jam-op/original-sonic-jam-op.avi"
input_fps = "30000/1001"
fmv_start = 0.0
lead = 0.0

[comparison.panels.real]
label = "Real hardware"
slot = "right_bottom"
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


class StillSeekTests(unittest.TestCase):
    """A re-timed panel must be seeked in the graph, not on its input.

    `-ss` reads the material's stored timestamps and `-r` replaces them, so
    asking ffmpeg for both lands on a different frame than the video path
    shows. A preview that does that reports panels out of step which the video
    itself keeps together, which is worse than no preview.
    """

    def setUp(self) -> None:
        self.spec = load(written(BODY))
        self.cmd = render_comparison.build_still_command(
            self.spec, Path("/tmp/still.png"), at=8.0,
            overlay_png=Path("/tmp/overlay.png"))

    def test_a_retimed_panel_is_not_seeked_on_its_input(self) -> None:
        # One -ss for the panel without input_fps, none for the one with it.
        self.assertEqual(self.cmd.count("-ss"), 1)
        rate = self.cmd.index("-r")
        self.assertEqual(self.cmd[rate + 1], "30000/1001")
        # The rate override is immediately followed by its input, with no
        # seek wedged between them.
        self.assertEqual(self.cmd[rate + 2], "-i")

    def test_a_retimed_panel_is_seeked_in_the_graph(self) -> None:
        graph = self.cmd[self.cmd.index("-filter_complex") + 1]
        # picture_start is 5.0, the source panel has no lead, so at t=8 it is
        # 3 seconds into its own material.
        self.assertIn("select='gte(t\\,3.000000)'", graph)

    def test_a_panel_at_its_stored_rate_keeps_the_input_seek(self) -> None:
        # The playback panel carries the whole run-up, so it starts the
        # timeline and at t=8 it is 8 seconds into its own material.
        seek = self.cmd.index("-ss")
        self.assertEqual(self.cmd[seek + 1], "8.000000")
        self.assertEqual(self.cmd[seek + 2], "-i")
        graph = self.cmd[self.cmd.index("-filter_complex") + 1]
        self.assertEqual(graph.count("gte(t"), 1)

    def test_the_video_path_needs_no_such_split(self) -> None:
        # The video path never seeks a panel whose material starts at zero, so
        # the two settings cannot meet there in the first place.
        cmd = render_comparison.build_command(
            self.spec, Path("/tmp/out.mp4"), duration=10.0,
            overlay_png=Path("/tmp/overlay.png"))
        self.assertNotIn("-ss", cmd)
        graph = cmd[cmd.index("-filter_complex") + 1]
        self.assertNotIn("gte(t", graph)


class ResizeTests(unittest.TestCase):

    def test_each_panel_scales_with_its_own_filter(self) -> None:
        body = BODY.replace('spec = "spec"\npath =',
                            'spec = "spec"\nresize = "neighbor"\npath =', 1)
        spec = load(written(body))
        cmd = render_comparison.build_command(
            spec, Path("/tmp/out.mp4"), duration=10.0,
            overlay_png=Path("/tmp/overlay.png"))
        graph = cmd[cmd.index("-filter_complex") + 1]
        self.assertIn("flags=neighbor", graph)
        self.assertIn("flags=lanczos", graph)


if __name__ == "__main__":
    unittest.main()
