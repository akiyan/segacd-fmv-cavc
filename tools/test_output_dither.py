#!/usr/bin/env python3
"""Regression tests for selectable deterministic output dithering."""

from __future__ import annotations

import unittest

import numpy as np

import output_dither
from quantize_md_video import rgb888_to_rgb333


class OutputDitherTests(unittest.TestCase):

    def test_gentle_gradient_keeps_complete_bayer_pattern(self) -> None:
        values = np.arange(16, dtype=np.uint8) * 4 + 80
        image = np.repeat(values[None, :, None], 16, axis=0)
        image = np.repeat(image, 3, axis=2)
        self.assertLessEqual(int(output_dither.local_luma_range(image).max()), 8)
        np.testing.assert_array_equal(
            output_dither.edge_attenuated_bayer_rgb333(image),
            output_dither.bayer_rgb333(image),
        )

    def test_strong_edge_uses_nearest_rounding_next_to_boundary(self) -> None:
        image = np.empty((8, 8, 3), dtype=np.uint8)
        image[:, :4] = 30
        image[:, 4:] = 225
        adaptive = output_dither.edge_attenuated_bayer_rgb333(image)
        nearest = rgb888_to_rgb333(image)
        np.testing.assert_array_equal(adaptive[:, 3:5], nearest[:, 3:5])
        self.assertTrue(np.any(
            output_dither.bayer_rgb333(image)[:, 3:5] != nearest[:, 3:5]))

    def test_strong_edge_attenuation_reaches_one_pixel_into_fringe(self) -> None:
        image = np.zeros((8, 8, 3), dtype=np.uint8)
        image[:, 5:7] = 250
        image[:, 7] = 255
        expanded = output_dither.edge_attenuated_bayer_rgb333(image)
        original = output_dither.bayer_rgb333(image)
        # Row 1 / column 6 is two pixels from the black core. Its own 3x3
        # range is only five levels, but the adjacent edge core now suppresses
        # the lone dark Bayer result in the antialiased white fringe.
        np.testing.assert_array_equal(expanded[1, 6], np.array([7, 7, 7]))
        np.testing.assert_array_equal(original[1, 6], np.array([6, 6, 6]))

    def test_edge_range_expands_exactly_one_pixel(self) -> None:
        edge_range = np.zeros((5, 5), dtype=np.int16)
        edge_range[2, 2] = output_dither.EDGE_DITHER_FULL
        expanded = output_dither.expand_edge_range(edge_range)
        expected = np.zeros_like(edge_range)
        expected[1:4, 1:4] = output_dither.EDGE_DITHER_FULL
        np.testing.assert_array_equal(expanded, expected)

    def test_profile_dispatch_defaults_to_standard_bayer(self) -> None:
        image = np.random.default_rng(173).integers(
            0, 256, (16, 24, 3), dtype=np.uint8)
        np.testing.assert_array_equal(
            output_dither.quantize_rgb333(image),
            output_dither.bayer_rgb333(image),
        )
        np.testing.assert_array_equal(
            output_dither.quantize_rgb333(
                image, output_dither.EDGE_ATTENUATED_BAYER),
            output_dither.edge_attenuated_bayer_rgb333(image),
        )

    def test_none_mode_matches_nearest_colour_rounding(self) -> None:
        image = np.random.default_rng(111).integers(
            0, 256, (16, 24, 3), dtype=np.uint8)
        nearest = output_dither.quantize_rgb333(image, output_dither.NONE)
        np.testing.assert_array_equal(nearest, rgb888_to_rgb333(image))
        self.assertTrue(np.any(
            nearest != output_dither.bayer_rgb333(image)))

    def test_unknown_profile_mode_is_rejected(self) -> None:
        with self.assertRaisesRegex(ValueError, "output dither"):
            output_dither.quantize_rgb333(
                np.zeros((8, 8, 3), dtype=np.uint8), "diffusion")


if __name__ == "__main__":
    unittest.main()
