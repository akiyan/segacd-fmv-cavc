"""Shared-core preference preserves automatic selection before refitting."""
import os
import unittest
from unittest.mock import patch

import numpy as np

from palette_algorithms import build_mosaic_palettes


class CoreBoostTests(unittest.TestCase):
    def test_boost_preserves_selection_and_clamps(self):
        tiles = np.random.default_rng(42).integers(
            0, 8, (48, 64, 3), dtype=np.uint8)
        env = {
            "CBRSIM_EDGE_WEIGHT": "0", "CBRSIM_PAL_GROW_REL": "0",
            "CBRSIM_PAL_GROW_ABS": "0", "CBRSIM_PAL_MIN_USAGE": "0",
            "CBRSIM_PAL_CORE_SIZES": "4,6,8,10,12,14",
        }
        with patch.dict(os.environ, env, clear=True):
            baseline, auto = build_mosaic_palettes(tiles, return_stats=True)
            self.assertGreater(auto["active_lines"], 1)
            self.assertLess(auto["core_colors"], 14)
            for steps in (0, 1, 100):
                os.environ["CBRSIM_PAL_CORE_BOOST_STEPS"] = str(steps)
                palettes, stats = build_mosaic_palettes(tiles, return_stats=True)
                self.assertEqual(stats["grows"], auto["grows"])
                self.assertEqual(stats["merged_lines"], auto["merged_lines"])
                self.assertEqual(stats["active_lines"], auto["active_lines"])
                self.assertEqual(stats["auto_core_colors"], auto["core_colors"])
                self.assertEqual(stats["core_colors"],
                                 min(14, auto["core_colors"] + 2 * steps))
                self.assertEqual(np.asarray(palettes).shape, (4, 15, 3))
                if steps == 0:
                    np.testing.assert_array_equal(palettes, baseline)
            os.environ["CBRSIM_PAL_CORE_BOOST_STEPS"] = "100"
            single, stats = build_mosaic_palettes(
                tiles, n_pal=1, return_stats=True)
            self.assertEqual(stats["core_colors"], 15)
            self.assertEqual(stats["active_lines"], 1)
            for palette in single[1:]:
                np.testing.assert_array_equal(palette, single[0])


if __name__ == "__main__":
    unittest.main()
