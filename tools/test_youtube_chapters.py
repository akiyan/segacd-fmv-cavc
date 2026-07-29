#!/usr/bin/env python3
"""Tests for HUD-anchored playback chapter offsets."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import youtube_chapters


class HudChapterOffsetTests(unittest.TestCase):
    def write_gate(self, data: dict) -> Path:
        directory = tempfile.TemporaryDirectory()
        self.addCleanup(directory.cleanup)
        path = Path(directory.name) / "gate.json"
        path.write_text(json.dumps(data), encoding="utf-8")
        return path

    def test_uses_frame0_after_frame_minus_one_sentinel(self) -> None:
        gate = self.write_gate({
            "ocr_start_anchor": {
                "method": "frame_minus_one",
                "frame_minus_one_raw16": 0xFFFF,
                "frame0_time_first_s": 20.070049,
            },
        })
        self.assertEqual(
            youtube_chapters.content_offset_from_hud_gate(gate),
            20.070049,
        )

    def test_rejects_legacy_plausible_sequence_anchor(self) -> None:
        gate = self.write_gate({
            "ocr_start_anchor": {
                "method": "plausible_sequence",
                "frame0_time_first_s": 20.0,
            },
        })
        with self.assertRaisesRegex(ValueError, "frame=FFFF"):
            youtube_chapters.content_offset_from_hud_gate(gate)

    def test_rejects_missing_frame0_time(self) -> None:
        gate = self.write_gate({
            "ocr_start_anchor": {
                "method": "frame_minus_one",
                "frame_minus_one_raw16": 0xFFFF,
            },
        })
        with self.assertRaisesRegex(ValueError, "frame-0 timestamp"):
            youtube_chapters.content_offset_from_hud_gate(gate)


if __name__ == "__main__":
    unittest.main()
