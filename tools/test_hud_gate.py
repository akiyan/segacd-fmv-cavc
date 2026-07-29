#!/usr/bin/env python3
"""Regression tests for HUD gate and alert result semantics."""

from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import hud_gate


class HudGateTests(unittest.TestCase):
    def test_cadence_alert_edge_windows_follow_content_fps(self):
        for fps, expected in (
            (30, 4),
            (29.97, 4),
            (15, 2),
            (14.985, 2),
            (24, 0),
        ):
            with self.subTest(fps=fps):
                self.assertEqual(
                    hud_gate.cadence_alert_edge_frames(fps),
                    expected,
                )

    def test_cadence_alert_edge_frames_use_the_expected_movie_length(self):
        self.assertTrue(
            hud_gate.cadence_alert_frame_is_exempt(3, 100, 30))
        self.assertFalse(
            hud_gate.cadence_alert_frame_is_exempt(4, 100, 30))
        self.assertFalse(
            hud_gate.cadence_alert_frame_is_exempt(95, 100, 30))
        self.assertTrue(
            hud_gate.cadence_alert_frame_is_exempt(96, 100, 30))
        self.assertTrue(
            hud_gate.cadence_alert_frame_is_exempt(1, 100, 15))
        self.assertFalse(
            hud_gate.cadence_alert_frame_is_exempt(2, 100, 15))
        self.assertFalse(
            hud_gate.cadence_alert_frame_is_exempt(97, 100, 15))
        self.assertTrue(
            hud_gate.cadence_alert_frame_is_exempt(98, 100, 15))

    def test_classification_keeps_warning_upload_capable(self):
        for failures, warnings, alert, gate in (
            ([], [], "NONE", "PASS"),
            ([], ["review"], "WARNING", "PASS"),
            (["unsafe"], [], "FAIL", "FAIL"),
            (["unsafe"], ["review"], "FAIL", "FAIL"),
        ):
            with self.subTest(alert=alert):
                actual_alert = hud_gate.classify_alert(failures, warnings)
                self.assertEqual(actual_alert, alert)
                self.assertEqual(hud_gate.gate_for_alert(actual_alert), gate)

    def test_schema_6_requires_consistent_gate_and_alert(self):
        result = hud_gate.normalize_result({
            "schema_version": 6,
            "gate": "PASS",
            "alert": "WARNING",
            "status": "WARNING",
            "pass": True,
        })
        self.assertEqual(result["gate"], "PASS")
        self.assertEqual(result["alert"], "WARNING")
        with self.assertRaisesRegex(ValueError, "disagrees"):
            hud_gate.normalize_result({
                "schema_version": 6,
                "gate": "FAIL",
                "alert": "WARNING",
            })

    def test_schema_5_is_normalized_for_compatibility(self):
        result = hud_gate.normalize_result({
            "schema_version": 5,
            "status": "WARNING",
            "pass": True,
        })
        self.assertEqual(result["gate"], "PASS")
        self.assertEqual(result["alert"], "WARNING")


if __name__ == "__main__":
    unittest.main()
