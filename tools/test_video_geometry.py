#!/usr/bin/env python3
"""Regression tests for HAR-aware source geometry conversion."""
from __future__ import annotations

import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from video_geometry import geometry_plan, raw_filter, source_filter


class VideoGeometryTests(unittest.TestCase):
    def test_crop_is_object_fit_cover(self) -> None:
        plan = geometry_plan(320, 224, 512, 384, fit="crop")
        self.assertEqual(plan["crop"], [500, 384, 6, 0])
        self.assertEqual(
            raw_filter(320, 224, 512, 384,
                       fit="crop", resize_filter="area"),
            "setsar=1,crop=500:384:6:0,scale=320:224:flags=area")

    def test_plan_reports_the_h40_dot_ratio(self) -> None:
        plan = geometry_plan(320, 224, 512, 384, fit="crop")
        self.assertEqual(plan["mode"], "H40")
        self.assertEqual(plan["har"], "32:35")
        # 320x224 with PAR 32:35 is the 64:49 visible NTSC aperture.
        self.assertAlmostEqual(plan["display_aspect"], 64 / 49, places=12)

    def test_crop_denoise_finishes_at_output_raster(self) -> None:
        self.assertEqual(
            source_filter(320, 224, 512, 384, fit="crop"),
            "setsar=1,crop=500:384:6:0,scale=640:448:flags=lanczos,"
            "hqdn3d=6:6:8:8,gblur=sigma=1.6,scale=320:224:flags=lanczos")

    def test_native_source_needs_only_identity_crop(self) -> None:
        plan = geometry_plan(
            320, 224, 320, 224,
            src_sar_num=32, src_sar_den=35, fit="crop")
        self.assertEqual(plan["crop"], [320, 224, 0, 0])
        self.assertEqual(
            raw_filter(
                320, 224, 320, 224,
                src_sar_num=32, src_sar_den=35, fit="crop"),
            "setsar=1,crop=320:224:0:0")
        self.assertEqual(
            source_filter(
                320, 224, 320, 224,
                src_sar_num=32, src_sar_den=35, fit="crop",
                denoise=False),
            "setsar=1,crop=320:224:0:0")

    def test_pad_preserves_complete_source_and_adds_bars(self) -> None:
        self.assertEqual(
            raw_filter(320, 224, 512, 384, fit="pad"),
            "setsar=1,scale=320:218:flags=lanczos,"
            "pad=320:224:(ow-iw)/2:(oh-ih)/2:color=black")


if __name__ == "__main__":
    unittest.main()
