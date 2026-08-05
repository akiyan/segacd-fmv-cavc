"""Tests for screen-to-rolling-plane source projection."""

from __future__ import annotations

import unittest

import numpy as np

import scroll_frames
import scroll_plan
import scroll_runtime


class ScrollRuntimeTests(unittest.TestCase):
    def test_negative_horizontal_move_fills_only_revealed_guard_pixels(self):
        image = np.arange(16 * 8 * 3, dtype=np.uint8).reshape(8, 16, 3)
        state = scroll_plan.position_state(
            1, scroll_frames.AXIS_HORIZONTAL, -5, delta=-5,
            columns=2, rows=1)
        base = np.full((3, 8, 8, 3), 247, np.uint8)

        tiles = scroll_runtime.aligned_rgb_tiles(image, state, base)

        # Guard world column 2 appears at screen x=11. Its first five pixels
        # come from x=11..15; the last three remain hidden and untouched.
        np.testing.assert_array_equal(tiles[2, :, :5], image[:, 11:16])
        self.assertTrue(np.all(tiles[2, :, 5:] == 247))

    def test_positive_horizontal_move_uses_the_low_guard(self):
        image = np.arange(16 * 8 * 3, dtype=np.uint8).reshape(8, 16, 3)
        state = scroll_plan.position_state(
            1, scroll_frames.AXIS_HORIZONTAL, 5, delta=5,
            columns=2, rows=1)
        base = np.full((3, 8, 8, 3), 199, np.uint8)

        tiles = scroll_runtime.aligned_rgb_tiles(image, state, base)

        # The new low-edge primary world column -1 appears at screen x=-3.
        # Its last five pixels are visible at source x=0..4. The extra low
        # guard remains hidden until the motion crosses another tile.
        self.assertTrue(np.all(tiles[0, :, :3] == 199))
        np.testing.assert_array_equal(tiles[0, :, 3:], image[:, :5])
        self.assertTrue(np.all(tiles[2] == 199))


if __name__ == "__main__":
    unittest.main()
