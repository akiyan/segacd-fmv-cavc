#!/usr/bin/env python3
"""Regression tests for the single-name-table tearing detector."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]


def load_detector():
    path = ROOT / "harness/single_name_table/detect_tearing.py"
    spec = importlib.util.spec_from_file_location("single_nt_tearing", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


detector = load_detector()


class SingleNameTableTearingTests(unittest.TestCase):
    def test_detects_one_mixed_movie_frame_group(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            video = Path(tmp) / "capture.mkv"
            red = np.zeros((32, 32, 3), np.uint8)
            red[..., 0] = 255
            blue = np.zeros((32, 32, 3), np.uint8)
            blue[..., 2] = 255
            raw = b"".join(frame.tobytes() for frame in (red, red, red, blue))
            subprocess.run(
                [
                    "ffmpeg", "-v", "error", "-f", "rawvideo",
                    "-pixel_format", "rgb24", "-video_size", "32x32",
                    "-framerate", "60", "-i", "pipe:0", "-c:v", "ffv1",
                    str(video),
                ],
                input=raw,
                check=True,
            )
            rows = detector.inspect(
                video,
                [detector.HudSpan(0, 0, 1), detector.HudSpan(1, 2, 3)],
                skip_top_rows=16,
            )
            self.assertEqual([row["status"] for row in rows], ["PASS", "TEAR"])
            self.assertEqual(rows[1]["unique_rasters"], 2)
            self.assertEqual(rows[1]["max_changed_pixels"], 32 * 16)


if __name__ == "__main__":
    unittest.main()
