#!/usr/bin/env python3
"""Tests for the CRAM palette-switch count published in upload descriptions."""

from __future__ import annotations

import pickle
import tempfile
import unittest
from pathlib import Path

import cram_switches


class SegmentStartTests(unittest.TestCase):
    def test_counts_every_segment_change(self) -> None:
        self.assertEqual(
            cram_switches.segment_starts([0, 0, 1, 1, 1, 2]),
            [0, 2, 5],
        )

    def test_single_segment_has_one_start(self) -> None:
        self.assertEqual(cram_switches.segment_starts([0, 0, 0]), [0])


class CountTests(unittest.TestCase):
    def write_log(self, frame_seg) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        out_dir = Path(directory.name)
        with open(out_dir / "decisions.pkl", "wb") as handle:
            pickle.dump({"frame_seg": frame_seg, "fps": 30.0}, handle)
        return out_dir

    def test_switches_are_one_less_than_segments(self) -> None:
        out_dir = self.write_log([0, 0, 1, 1, 2, 2, 3])
        self.assertEqual(cram_switches.counts(out_dir), (4, 3))

    def test_single_segment_movie_has_no_switch(self) -> None:
        out_dir = self.write_log([0, 0, 0, 0])
        self.assertEqual(cram_switches.counts(out_dir), (1, 0))


if __name__ == "__main__":
    unittest.main()
