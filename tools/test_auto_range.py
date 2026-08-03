#!/usr/bin/env python3
"""Tests for the whole-movie automatic dynamic-range expansion."""
from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import auto_range


def _hist(pairs: dict[int, int], base: int = 0) -> np.ndarray:
    hist = np.full(256, base, dtype=np.int64)
    for level, count in pairs.items():
        hist[level] = count
    return hist


class DetectRangeTest(unittest.TestCase):
    def test_flat_histogram_is_untouched(self) -> None:
        self.assertEqual(auto_range.detect_range(_hist({}, base=1000)), (0, 255))

    def test_empty_histogram_is_untouched(self) -> None:
        self.assertEqual(auto_range.detect_range(_hist({})), (0, 255))

    def test_black_and_white_spikes_are_detected(self) -> None:
        # machi OP shape: dominant near-black at 8 and near-white at 239,
        # plus genuine endpoint outliers that must not mask the spikes.
        hist = _hist({0: 40_000, 8: 1_200_000, 239: 300_000, 255: 200}, base=5_000)
        self.assertEqual(auto_range.detect_range(hist), (8, 239))

    def test_small_spike_stays_untouched(self) -> None:
        # Below SPIKE_MIN_FRACTION of the total samples.
        hist = _hist({8: 2_000}, base=1_000)
        self.assertEqual(auto_range.detect_range(hist), (0, 255))

    def test_ramp_past_window_edge_is_not_a_spike(self) -> None:
        # Rising toward and beyond the window edge: a gradient, not a
        # displaced endpoint. The first bin outside the window tops it.
        hist = _hist({level: 10_000 * level for level in range(1, 32)})
        self.assertEqual(auto_range.detect_range(hist), (0, 255))

    def test_spike_must_dominate_its_window(self) -> None:
        # Every window bin is nearly as tall as the maximum.
        hist = _hist({level: 90_000 for level in range(1, 17)})
        hist[8] = 100_000
        self.assertEqual(auto_range.detect_range(hist), (0, 255))

    def test_deep_black_level_is_out_of_scope(self) -> None:
        # A dominant level far from the endpoint is a creative choice.
        hist = _hist({40: 1_000_000}, base=1_000)
        self.assertEqual(auto_range.detect_range(hist), (0, 255))


class LutTest(unittest.TestCase):
    def test_identity_points_build_identity_lut(self) -> None:
        lut = auto_range.build_lut(0, 255)
        self.assertTrue(np.array_equal(lut, np.arange(256, dtype=np.uint8)))

    def test_stretch_endpoints_and_monotonicity(self) -> None:
        lut = auto_range.build_lut(8, 239)
        self.assertTrue(np.all(lut[:9] == 0))
        self.assertTrue(np.all(lut[239:] == 255))
        self.assertTrue(np.all(np.diff(lut.astype(np.int16)) >= 0))
        self.assertEqual(int(lut[9]), round((9 - 8) * 255 / (239 - 8)))

    def test_invalid_points_are_rejected(self) -> None:
        with self.assertRaises(ValueError):
            auto_range.build_lut(200, 100)
        with self.assertRaises(ValueError):
            auto_range.build_lut(-1, 255)

    def test_apply_lut_maps_every_channel(self) -> None:
        lut = auto_range.build_lut(8, 239)
        image = np.full((4, 4, 3), 8, dtype=np.uint8)
        image[0, 0] = (0, 239, 255)
        out = auto_range.apply_lut(image, lut)
        self.assertEqual(out.dtype, np.uint8)
        self.assertTrue(np.all(out[1:] == 0))
        self.assertEqual(tuple(out[0, 0]), (0, 255, 255))


class FrameHistogramTest(unittest.TestCase):
    def test_counts_all_channels(self) -> None:
        image = np.zeros((2, 2, 3), dtype=np.uint8)
        image[0, 0] = (8, 8, 239)
        hist = auto_range.frame_histogram(image)
        self.assertEqual(int(hist.sum()), 12)
        self.assertEqual(int(hist[8]), 2)
        self.assertEqual(int(hist[239]), 1)
        self.assertEqual(int(hist[0]), 9)

    def test_rejects_non_rgb_shapes(self) -> None:
        with self.assertRaises(ValueError):
            auto_range.frame_histogram(np.zeros((4, 4), dtype=np.uint8))


class FileRoundTripTest(unittest.TestCase):
    def test_scan_and_rewrite_files(self) -> None:
        lut = auto_range.build_lut(8, 239)
        with tempfile.TemporaryDirectory() as tmp:
            paths = []
            for index in range(3):
                image = np.full((8, 8, 3), 8, dtype=np.uint8)
                image[0, index] = (239, 239, 239)
                path = Path(tmp) / f"{index:05d}.png"
                Image.fromarray(image).save(path)
                paths.append(path)
            hist = auto_range.scan_histogram(paths)
            self.assertEqual(int(hist.sum()), 3 * 8 * 8 * 3)
            self.assertEqual(auto_range.detect_range(hist), (8, 239))
            auto_range.rewrite_files(paths, lut, workers=2)
            for index, path in enumerate(paths):
                out = np.asarray(Image.open(path).convert("RGB"))
                self.assertEqual(tuple(out[0, index]), (255, 255, 255))
                self.assertEqual(tuple(out[1, 0]), (0, 0, 0))


if __name__ == "__main__":
    unittest.main()
