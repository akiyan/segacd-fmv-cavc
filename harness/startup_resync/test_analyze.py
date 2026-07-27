#!/usr/bin/env python3
"""Tests for exact DEBUG HUD movie-start selection."""

from __future__ import annotations

import unittest

import analyze
import read_frameno


def group(frame: int, capture: int) -> analyze.FrameGroup:
    return analyze.FrameGroup(
        loop=0,
        capture_first=capture,
        capture_last=capture,
        time_first=capture / 60,
        time_last=capture / 60,
        sample_count=1,
        confidence=1.0,
        values={"F": frame},
    )


class MovieAnchorTest(unittest.TestCase):
    def test_frame_minus_one_sentinel_wins_over_earlier_plausible_zero(self) -> None:
        raw = [
            group(0, 0), group(1, 1), group(2, 2), group(3, 3),
            group(read_frameno.FRAME_MINUS_ONE, 4),
            group(0, 5), group(1, 6), group(2, 7), group(3, 8),
        ]

        selected = analyze.select_movie_groups(raw, anchor_run=4, max_step=4)

        self.assertEqual(selected[0].capture_first, 5)
        self.assertEqual([row.values["F"] for row in selected[:4]], [0, 1, 2, 3])

    def test_legacy_recording_without_sentinel_still_anchors(self) -> None:
        raw = [group(0, 0), group(1, 1), group(2, 2), group(3, 3)]

        selected = analyze.select_movie_groups(raw, anchor_run=4, max_step=4)

        self.assertEqual([row.values["F"] for row in selected], [0, 1, 2, 3])


if __name__ == "__main__":
    unittest.main()
