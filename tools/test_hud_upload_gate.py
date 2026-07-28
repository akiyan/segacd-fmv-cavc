#!/usr/bin/env python3
"""Regression tests for the recording HUD upload gate."""
from __future__ import annotations

import importlib.util
import csv
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "startup_resync_analyze", ROOT / "harness/startup_resync/analyze.py"
)
assert SPEC and SPEC.loader
analyze = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = analyze
SPEC.loader.exec_module(analyze)


def groups(count: int, **peaks: int):
    result = []
    for frame in range(count):
        values = {field: 0 for field in "SDRCMJ"}
        if frame == count - 1:
            values.update(peaks)
        values["F"] = frame
        result.append(analyze.FrameGroup(
            loop=0, capture_first=frame * 2, capture_last=frame * 2 + 1,
            time_first=frame / 30, time_last=(frame + 0.5) / 30,
            sample_count=2, confidence=1.0, values=values,
        ))
    return result


class HudUploadGateTests(unittest.TestCase):
    def evaluate(self, rows, expected, content_fps=30):
        with tempfile.NamedTemporaryFile() as recording:
            return analyze.evaluate_upload_gate(
                rows, expected, Path(recording.name), content_fps)

    def test_h32_and_h40_profiles_select_combined_layout_by_default(self):
        class Profile:
            def __init__(self, mode):
                self.data = {"video": {"mode": mode}}

        for mode in ("H32", "H40"):
            with self.subTest(mode=mode):
                self.assertTrue(analyze.standard_combined_fields(
                    Profile(mode),
                    flip_fields=False,
                    poll_gap_fields=False,
                    combined_fields=False,
                ))
        self.assertFalse(analyze.standard_combined_fields(
            Profile("H40"),
            flip_fields=True,
            poll_gap_fields=False,
            combined_fields=False,
        ))

    def test_clean_complete_loop_passes(self):
        result = self.evaluate(groups(4, M=1, J=25), 4)
        self.assertTrue(result["pass"], result["failures"])
        self.assertEqual(result["gate"], "PASS")
        self.assertEqual(result["alert"], "NONE")
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["warnings"], [])
        self.assertFalse(result["requires_explicit_upload_approval"])
        self.assertEqual(result["evaluation_first_frame"], 1)
        self.assertEqual(result["evaluated_timed_frames"], 3)

    def test_frame_zero_is_excluded_from_every_gate_metric(self):
        rows = groups(4)
        rows[0].values.update({
            "S": 255,
            "D": 255,
            "R": 255,
            "C": 255,
            "M": 255,
            "J": 255,
        })
        result = self.evaluate(rows, 4, 15)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(
            result["maxima"],
            {field: 0 for field in "SDRCMJ"},
        )

    def test_c_and_a_statistics_exclude_frame_zero_and_later_loops(self):
        rows = groups(4)
        for row, c_value, a_value in zip(
            rows,
            (255, 0, 2, 4),
            (254, 60, 64, 64),
            strict=True,
        ):
            row.values.update({
                "P": 0,
                "L": 0,
                "C": c_value,
                "W": 0,
                "A": a_value,
            })
        later = analyze.FrameGroup(
            loop=1,
            capture_first=8,
            capture_last=9,
            time_first=4 / 30,
            time_last=4.5 / 30,
            sample_count=2,
            confidence=1.0,
            values={**rows[0].values, "F": 0, "C": 255, "A": 255},
        )
        all_rows = [*rows, later]
        c_stats = analyze.c_statistics(all_rows)
        self.assertEqual(c_stats["minimum"], 0)
        self.assertEqual(c_stats["mean"], 2.0)
        self.assertEqual(c_stats["median"], 2)
        self.assertEqual(c_stats["maximum"], 4)
        self.assertEqual(c_stats["sample_count"], 3)
        a_stats = analyze.a_statistics(all_rows)
        self.assertEqual(a_stats["minimum"], 60)
        self.assertAlmostEqual(a_stats["mean"], 62.666666666666664)
        self.assertEqual(a_stats["median"], 64)
        self.assertEqual(a_stats["maximum"], 64)
        self.assertEqual(a_stats["sample_count"], 3)

        output = io.StringIO()
        with redirect_stdout(output):
            analyze.print_report(all_rows, context=0)
        self.assertIn(
            "C statistics (timed first loop; frame 0 excluded): "
            "min=0 mean=2.000 median=2 max=4 n=3",
            output.getvalue(),
        )
        self.assertIn(
            "A statistics (timed first loop; frame 0 excluded): "
            "min=60 mean=62.667 median=64 max=64 n=3",
            output.getvalue(),
        )

        result = self.evaluate(all_rows, 4)
        self.assertEqual(result["schema_version"], 6)
        self.assertEqual(result["gate_fields"], ["S", "D", "R", "M", "J"])
        self.assertEqual(result["diagnostic_fields"], ["C", "A"])
        self.assertEqual(result["c_statistics"], c_stats)
        self.assertEqual(result["a_statistics"], a_stats)

    def test_each_unsafe_metric_blocks_upload(self):
        for field, value in {"S": 1, "D": 1, "R": 1,
                             "M": 2, "J": 26}.items():
            with self.subTest(field=field):
                result = self.evaluate(groups(4, **{field: value}), 4)
                self.assertFalse(result["pass"])
                self.assertEqual(result["gate"], "FAIL")
                self.assertEqual(result["alert"], "FAIL")
                self.assertEqual(result["status"], "FAIL")
                self.assertTrue(any(text.startswith(field) for text in result["failures"]))

    def test_c_is_diagnostic_and_never_changes_gate_status(self):
        result = self.evaluate(groups(4, C=255), 4)
        self.assertTrue(result["pass"], result["failures"])
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["failures"], [])
        self.assertEqual(result["warnings"], [])
        self.assertEqual(result["maxima"]["C"], 255)
        self.assertNotIn("C", result["limits"])

    def test_fixed_n4_15fps_uses_three_work_fields(self):
        result = self.evaluate(groups(4, C=255, M=3, J=45), 4, 15)
        self.assertTrue(result["pass"], result["failures"])
        self.assertEqual(result["cadence"], "fixed_n4")
        self.assertNotIn("C", result["limits"])
        self.assertEqual(result["limits"]["M"], 3)
        self.assertEqual(result["limits"]["J"], 45)
        self.assertEqual(result["prg_buf_cap_kib"], 376)
        self.assertEqual(result["jitter_headroom_kib"], 40)
        self.assertEqual(result["delivery_limit_kib"], 376)
        result = self.evaluate(groups(4, M=4), 4, 15)
        self.assertFalse(result["pass"])
        self.assertEqual(result["status"], "FAIL")
        self.assertTrue(any(
            text.startswith("M") for text in result["failures"]))

    def test_delivery_paced_24fps_uses_variable_slot_and_field_budget(self):
        result = self.evaluate(groups(4, C=255, M=3, J=30), 4, 24)
        self.assertTrue(result["pass"], result["failures"])
        self.assertNotIn("C", result["limits"])
        self.assertEqual(result["limits"]["M"], 3)
        self.assertEqual(result["limits"]["J"], 30)
        self.assertEqual(result["prg_buf_cap_kib"], 391)
        self.assertEqual(result["jitter_headroom_kib"], 25)

    def test_each_cadence_rejects_a_full_physical_ring(self):
        for fps, first_failing_j in ((15, 46), (24, 31), (30, 26)):
            with self.subTest(fps=fps):
                result = self.evaluate(
                    groups(4, J=first_failing_j), 4, fps)
                self.assertFalse(result["pass"])
                self.assertTrue(any(
                    text.startswith("J") for text in result["failures"]))

    def test_missing_movie_frame_blocks_upload(self):
        rows = groups(4)
        rows.pop(2)
        result = self.evaluate(rows, 4)
        self.assertFalse(result["pass"])
        self.assertTrue(any("incomplete" in text for text in result["failures"]))

    def test_hud_log_is_tab_separated(self):
        rows = groups(1)
        rows[0].values.update({
            "P": 0,
            "L": 0,
            "W": 0,
            "A": 0,
        })
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "hud.tsv"
            analyze.write_tsv(path, rows, [])
            raw = path.read_text(encoding="utf-8")
            header = raw.splitlines()[0]
            self.assertIn("\t", header)
            self.assertNotIn(",", header)
            with path.open(encoding="utf-8", newline="") as handle:
                parsed = list(csv.DictReader(handle, delimiter="\t"))
            self.assertEqual(parsed[0]["frame"], "0")

    def test_h40_q_is_preserved_and_decoded_as_signed_patterns(self):
        rows = groups(2)
        for row, raw in zip(rows, (0x0001, 0xFFFD), strict=True):
            row.values.update({
                "P": 0,
                "L": 0,
                "W": 0,
                "A": 0,
                "Q": raw,
            })
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "hud.tsv"
            analyze.write_tsv(path, rows, [])
            with path.open(encoding="utf-8", newline="") as handle:
                parsed = list(csv.DictReader(handle, delimiter="\t"))
        self.assertEqual(parsed[0]["prgbuf_min_patterns_raw16"], "1")
        self.assertEqual(parsed[0]["prgbuf_min_patterns_signed"], "1")
        self.assertEqual(parsed[0]["prgbuf_underflow_patterns"], "0")
        self.assertEqual(parsed[1]["prgbuf_min_patterns_raw16"], "65533")
        self.assertEqual(parsed[1]["prgbuf_min_patterns_signed"], "-3")
        self.assertEqual(parsed[1]["prgbuf_underflow_patterns"], "3")
        result = self.evaluate(rows, 2)
        self.assertEqual(result["diagnostic_fields"], ["C", "A", "Q"])
        self.assertEqual(result["prgbuf_minimum_patterns"], -3)
        self.assertEqual(result["prgbuf_underflow_peak_patterns"], 3)
        self.assertEqual(
            result["maxima"],
            {field: 0 for field in "SDRCMJ"},
        )

    def test_h40_combined_diagnostics_preserve_q_g_b_k_h_x(self):
        rows = groups(3)
        for row, gap, slip, msf_gap, prg_min, physical_peak, reader_ahead in zip(
            rows,
            (0x0FFF, 0x8000 | 120, 240),
            (0, 3, 5),
            (0, 2, 4),
            (64, 32, 16),
            (1, 13376, 12000),
            (0, 0x0203, 0x0108),
            strict=True,
        ):
            row.values.update({
                "P": 0,
                "S": slip,
                "L": 0,
                "W": 0,
                "A": 0,
                "Q": prg_min,
                "G": gap,
                "K": msf_gap,
                "H": physical_peak,
                "X": reader_ahead,
            })
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "hud.tsv"
            analyze.write_tsv(path, rows, [])
            with path.open(encoding="utf-8", newline="") as handle:
                parsed = list(csv.DictReader(handle, delimiter="\t"))
        self.assertEqual(parsed[1]["sub_poll_gap_ticks"], "120")
        self.assertEqual(parsed[1]["sub_poll_gap_ms"], "3.68640")
        self.assertEqual(parsed[1]["sub_poll_gap_raw16"], str(0x8000 | 120))
        self.assertEqual(parsed[1]["apply_guard_blocked"], "1")
        self.assertEqual(parsed[1]["slip_msf_gap_count"], "2")
        self.assertEqual(parsed[1]["slip_trn_retry_count"], "1")
        self.assertEqual(parsed[1]["prgbuf_physical_peak_patterns"], "13376")
        self.assertEqual(parsed[1]["reader_ahead_raw16"], str(0x0203))
        self.assertEqual(parsed[1]["reader_ahead_frames"], "2")
        self.assertEqual(parsed[1]["reader_slot_sector"], "3")
        rows[1].values["S"] = 1
        rows[1].values["K"] = 255
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "hud.tsv"
            analyze.write_tsv(path, rows, [])
            with path.open(encoding="utf-8", newline="") as handle:
                wrapped = list(csv.DictReader(handle, delimiter="\t"))
        self.assertEqual(wrapped[1]["slip_trn_retry_count"], "2")
        for row in rows:
            row.values["S"] = 0
            row.values["K"] = 0
        result = self.evaluate(rows, 3)
        self.assertEqual(
            result["diagnostic_fields"],
            ["C", "A", "Q", "G", "B", "K", "H", "X"],
        )
        self.assertEqual(result["prgbuf_minimum_patterns"], 16)
        self.assertEqual(result["apply_guard_blocked_frames"], 1)
        self.assertEqual(
            result["sub_poll_gap_statistics"],
            {
                "minimum": 120,
                "mean": 180.0,
                "median": 180.0,
                "maximum": 240,
                "sample_count": 2,
            },
        )
        self.assertEqual(result["prgbuf_physical_peak_patterns"], 13376)
        self.assertEqual(result["reader_ahead_max_raw16"], 0x0203)
        self.assertEqual(result["reader_ahead_max_frames"], 2)
        self.assertEqual(result["reader_ahead_max_slot_sector"], 3)
        self.assertEqual(result["status"], "PASS")


if __name__ == "__main__":
    unittest.main()
