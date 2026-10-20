from __future__ import annotations

import unittest

import av_config
import palette_segments


class PaletteSegmentTests(unittest.TestCase):
    def test_hardware_capacity_preserves_64_ranges_and_merges_65(self) -> None:
        for count in (16, 17, 32, 64, 65):
            with self.subTest(count=count):
                dark = [0.0] * (count * 3)
                for boundary in range(3, len(dark), 3):
                    dark[boundary - 1] = 1.0
                ranges = palette_segments.segment_ranges(
                    dark, [0.0] * len(dark), gap=0,
                    max_segments=av_config.PALTAB_MAX_SEG)
                self.assertEqual(len(ranges), min(count, 64))
                self.assertEqual(ranges[0][0], 0)
                self.assertEqual(ranges[-1][1], len(dark))
                if count <= 64:
                    self.assertEqual(
                        ranges, [(i * 3, (i + 1) * 3) for i in range(count)])
                for left, right in zip(ranges, ranges[1:]):
                    self.assertEqual(left[1], right[0])

    def test_switch_follows_the_dark_transition_frame(self) -> None:
        ranges = palette_segments.segment_ranges(
            [0.0, 0.1, 1.0, 0.2, 0.0],
            [0.0, 0.1, 1.0, 0.2, 0.0],
            gap=0,
        )
        self.assertEqual(ranges, [(0, 3), (3, 5)])

    def test_first_frame_of_a_dark_plateau_is_displayed_before_switch(self) -> None:
        ranges = palette_segments.segment_ranges(
            [0.0, 0.0, 1.0, 1.0, 0.4, 0.0],
            [0.0, 0.0, 1.0, 1.0, 0.4, 0.0],
            gap=1,
        )
        self.assertEqual(ranges, [(0, 3), (3, 6)])

    def test_nearby_dark_and_uniform_hits_share_one_boundary(self) -> None:
        ranges = palette_segments.segment_ranges(
            [0.0, 0.0, 1.0, 0.0, 0.0, 0.0],
            [0.0, 0.0, 0.0, 1.0, 0.0, 0.0],
            gap=0,
            uniform_near=2,
        )
        self.assertEqual(ranges, [(0, 3), (3, 6)])

    def test_separate_uniform_transition_adds_a_boundary(self) -> None:
        ranges = palette_segments.segment_ranges(
            [0.0] * 9,
            [0.0, 0.0, 1.0, 0.0, 0.0, 0.0, 1.0, 0.0, 0.0],
            gap=0,
            uniform_near=2,
        )
        self.assertEqual(ranges, [(0, 3), (3, 7), (7, 9)])

    def test_max_segments_merges_smallest_adjacent_ranges(self) -> None:
        dark = [0.0] * 12
        for cut in (2, 4, 6, 9):
            dark[cut] = 1.0
        ranges = palette_segments.segment_ranges(dark, [0.0] * 12, gap=0)
        self.assertEqual(len(ranges), 5)
        capped = palette_segments.segment_ranges(
            dark, [0.0] * 12, gap=0, max_segments=3)
        self.assertEqual(len(capped), 3)
        self.assertEqual(capped[0][0], 0)
        self.assertEqual(capped[-1][1], 12)
        for left, right in zip(capped, capped[1:]):
            self.assertEqual(left[1], right[0])


if __name__ == "__main__":
    unittest.main()
