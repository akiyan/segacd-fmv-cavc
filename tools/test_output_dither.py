#!/usr/bin/env python3
"""Regression tests for deterministic edge-adaptive output dithering."""

from __future__ import annotations

import unittest

import numpy as np

import output_dither
from quantize_md_video import rgb888_to_rgb333


class OutputDitherTests(unittest.TestCase):
    def test_flat_field_matches_original_bayer(self) -> None:
        image = np.full((16, 16, 3), 120, dtype=np.uint8)
        np.testing.assert_array_equal(
            output_dither.edge_adaptive_rgb333(image),
            output_dither.bayer_rgb333(image),
        )

    def test_gentle_gradient_keeps_complete_bayer_pattern(self) -> None:
        values = np.arange(16, dtype=np.uint8) * 4 + 80
        image = np.repeat(values[None, :, None], 16, axis=0)
        image = np.repeat(image, 3, axis=2)
        self.assertLessEqual(int(output_dither.local_luma_range(image).max()), 8)
        np.testing.assert_array_equal(
            output_dither.edge_adaptive_rgb333(image),
            output_dither.bayer_rgb333(image),
        )

    def test_strong_edge_uses_nearest_rounding_next_to_boundary(self) -> None:
        image = np.empty((8, 8, 3), dtype=np.uint8)
        image[:, :4] = 30
        image[:, 4:] = 225
        adaptive = output_dither.edge_adaptive_rgb333(image)
        nearest = rgb888_to_rgb333(image)
        np.testing.assert_array_equal(adaptive[:, 3:5], nearest[:, 3:5])
        self.assertTrue(np.any(
            output_dither.bayer_rgb333(image)[:, 3:5] != nearest[:, 3:5]))

    def test_edge_attenuation_is_continuous_between_fixed_limits(self) -> None:
        edge_range = np.array([
            0,
            output_dither.EDGE_DITHER_START,
            (output_dither.EDGE_DITHER_START
             + output_dither.EDGE_DITHER_FULL) // 2,
            output_dither.EDGE_DITHER_FULL,
            255,
        ])
        np.testing.assert_array_equal(
            output_dither.edge_dither_amount(edge_range),
            np.array([1.0, 1.0, 0.5, 0.0, 0.0], dtype=np.float32),
        )

    def test_same_frame_always_produces_identical_output(self) -> None:
        image = np.random.default_rng(103).integers(
            0, 256, (24, 32, 3), dtype=np.uint8)
        first = output_dither.edge_adaptive_rgb333(image)
        second = output_dither.edge_adaptive_rgb333(image.copy())
        np.testing.assert_array_equal(first, second)

    def test_invalid_image_shape_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "shape"):
            output_dither.edge_adaptive_rgb333(
                np.zeros((16, 16), dtype=np.uint8))


if __name__ == "__main__":
    unittest.main()
