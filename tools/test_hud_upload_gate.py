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
from dataclasses import replace
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "startup_resync_analyze", ROOT / "harness/startup_resync/analyze.py"
)
assert SPEC and SPEC.loader
analyze = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = analyze
SPEC.loader.exec_module(analyze)


def groups(count: int, capture_interval: int = 2, **peaks: int):
    result = []
    for frame in range(count):
        values = {
            field: 0 for field in analyze.read_frameno.HUD_FIELDS
        }
        if frame == count - 1:
            values.update(peaks)
        values["frame"] = frame
        capture_first = frame * capture_interval
        result.append(analyze.FrameGroup(
            loop=0, capture_first=capture_first,
            capture_last=capture_first + capture_interval - 1,
            time_first=frame / 30, time_last=(frame + 0.5) / 30,
            sample_count=capture_interval, confidence=1.0, values=values,
        ))
    return result


def add_display_hold(rows, frame: int, vblanks: int = 1):
    """Keep ``frame`` visible longer by shifting every later capture start."""
    rows[frame + 1:] = [
        replace(
            row,
            capture_first=row.capture_first + vblanks,
            capture_last=row.capture_last + vblanks,
        )
        for row in rows[frame + 1:]
    ]


class HudUploadGateTests(unittest.TestCase):
    def evaluate(self, rows, expected, content_fps=30):
        with tempfile.NamedTemporaryFile() as recording:
            return analyze.evaluate_upload_gate(
                rows, expected, Path(recording.name), content_fps)

    def test_clean_complete_loop_passes(self):
        result = self.evaluate(groups(4, vblank_spill=1, prgbuf_jitter_peak_kib=25), 4)
        self.assertTrue(result["pass"], result["failures"])
        self.assertEqual(result["gate"], "PASS")
        self.assertEqual(result["alert"], "NONE")
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["warnings"], [])
        self.assertFalse(result["requires_explicit_upload_approval"])
        self.assertEqual(result["evaluation_first_frame"], 1)
        self.assertEqual(result["evaluated_timed_frames"], 3)
        self.assertEqual(result["display_vblank_expected"], 2)
        self.assertEqual(result["display_vblank_evaluated_frames"], 2)
        self.assertEqual(result["display_vblank_alert_evaluated_frames"], 0)
        self.assertEqual(result["display_vblank_edge_exempt_frames"], 4)
        self.assertEqual(result["display_vblank_histogram"], {"2": 2})
        self.assertEqual(result["display_vblank_violation_count"], 0)
        self.assertEqual(result["display_vblank_violations"], [])
        self.assertEqual(
            result["display_vblank_exempted_violation_count"], 0)
        self.assertEqual(result["display_vblank_exempted_violations"], [])

    def test_frame_zero_is_excluded_from_every_gate_metric(self):
        rows = groups(4, capture_interval=4)
        rows[0].values.update({
            "sector_slip": 255,
            "control_desync": 255,
            "audio_resync": 255,
            "cd_wait_count": 255,
            "vblank_spill": 255,
            "prgbuf_jitter_peak_kib": 255,
        })
        result = self.evaluate(rows, 4, 15)
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(
            result["maxima"],
            {
                field: 0 for field in (
                    "sector_slip", "control_desync", "audio_resync",
                    "vblank_spill", "prgbuf_jitter_peak_kib",
                    "cd_wait_count",
                )
            },
        )
        self.assertEqual(result["display_vblank_histogram"], {"4": 2})

    def test_c_and_a_statistics_exclude_frame_zero_and_later_loops(self):
        rows = groups(4)
        for row, c_value, a_value in zip(
            rows,
            (255, 0, 2, 4),
            (254, 60, 64, 64),
            strict=True,
        ):
            row.values.update({
                "palette_segment": 0,
                "audio_lead_256b": 0,
                "cd_wait_count": c_value,
                "sub_wait_scanlines": 0,
                "adpcm_decode_units": a_value,
            })
        later = analyze.FrameGroup(
            loop=1,
            capture_first=8,
            capture_last=9,
            time_first=4 / 30,
            time_last=4.5 / 30,
            sample_count=2,
            confidence=1.0,
            values={**rows[0].values, "frame": 0, "cd_wait_count": 255, "adpcm_decode_units": 255},
        )
        all_rows = [*rows, later]
        c_stats = analyze.cd_wait_statistics(all_rows)
        self.assertEqual(c_stats["minimum"], 0)
        self.assertEqual(c_stats["mean"], 2.0)
        self.assertEqual(c_stats["median"], 2)
        self.assertEqual(c_stats["maximum"], 4)
        self.assertEqual(c_stats["sample_count"], 3)
        a_stats = analyze.adpcm_decode_statistics(all_rows)
        self.assertEqual(a_stats["minimum"], 60)
        self.assertAlmostEqual(a_stats["mean"], 62.666666666666664)
        self.assertEqual(a_stats["median"], 64)
        self.assertEqual(a_stats["maximum"], 64)
        self.assertEqual(a_stats["sample_count"], 3)

        output = io.StringIO()
        with redirect_stdout(output):
            analyze.print_report(all_rows, context=0)
        self.assertIn(
            "cd_wait_count statistics (timed first loop; frame 0 excluded): "
            "min=0 mean=2.000 median=2 max=4 n=3",
            output.getvalue(),
        )
        self.assertIn(
            "adpcm_decode_units statistics "
            "(timed first loop; frame 0 excluded): "
            "min=60 mean=62.667 median=64 max=64 n=3",
            output.getvalue(),
        )

        result = self.evaluate(all_rows, 4)
        self.assertEqual(result["schema_version"], 15)
        self.assertEqual(result["gate_fields"], [
            "sector_slip", "control_desync", "audio_resync",
            "vblank_spill", "prgbuf_jitter_peak_kib",
        ])
        self.assertEqual(result["warning_fields"], ["vblank_spill"])
        self.assertEqual(result["diagnostic_fields"], [
            "cd_wait_count", "adpcm_decode_units", "pump_gap_ticks",
            "apply_backpressure", "msf_gap_recoveries",
            "reader_ahead_frames", "reader_slot_sector", "cold_runs",
            "transfer_ticks", "transfer_vblanks", "transfer_end_vcounter",
            "pattern_dma_ready_vcounter",
            "name_table_dma_ready_vcounter",
            "sub_wait_scanlines", "flip_vcounter",
            "first_share_exit_vcounter", "pass2_delay_q4",
        ])
        self.assertEqual(result["cd_wait_statistics"], c_stats)
        self.assertEqual(result["adpcm_decode_statistics"], a_stats)

    def test_each_unsafe_metric_blocks_upload(self):
        for field, value in {"sector_slip": 1, "control_desync": 1, "audio_resync": 1, "prgbuf_jitter_peak_kib": 26}.items():
            with self.subTest(field=field):
                result = self.evaluate(groups(4, **{field: value}), 4)
                self.assertFalse(result["pass"])
                self.assertEqual(result["gate"], "FAIL")
                self.assertEqual(result["alert"], "FAIL")
                self.assertEqual(result["status"], "FAIL")
                self.assertTrue(any(text.startswith(field) for text in result["failures"]))

    def test_m_overage_warns_without_blocking_upload(self):
        result = self.evaluate(groups(4, vblank_spill=2), 4)
        self.assertTrue(result["pass"])
        self.assertEqual(result["gate"], "PASS")
        self.assertEqual(result["alert"], "WARNING")
        self.assertEqual(result["status"], "WARNING")
        self.assertEqual(result["failures"], [])
        self.assertTrue(any(
            text.startswith("vblank_spill") for text in result["warnings"]))

    def test_c_is_diagnostic_and_never_changes_gate_status(self):
        result = self.evaluate(groups(4, cd_wait_count=255), 4)
        self.assertTrue(result["pass"], result["failures"])
        self.assertEqual(result["status"], "PASS")
        self.assertEqual(result["failures"], [])
        self.assertEqual(result["warnings"], [])
        self.assertEqual(result["maxima"]["cd_wait_count"], 255)
        self.assertNotIn("cd_wait_count", result["limits"])

    def test_fixed_n4_15fps_uses_three_work_fields(self):
        result = self.evaluate(
            groups(4, capture_interval=4, cd_wait_count=255, vblank_spill=3, prgbuf_jitter_peak_kib=45), 4, 15)
        self.assertTrue(result["pass"], result["failures"])
        self.assertEqual(result["cadence"], "fixed_n4")
        self.assertNotIn("cd_wait_count", result["limits"])
        self.assertEqual(result["limits"]["vblank_spill"], 3)
        self.assertEqual(result["limits"]["prgbuf_jitter_peak_kib"], 45)
        self.assertEqual(result["prg_buf_cap_kib"], 374)
        self.assertEqual(result["jitter_headroom_kib"], 40)
        self.assertEqual(result["delivery_limit_kib"], 374)
        result = self.evaluate(
            groups(4, capture_interval=4, vblank_spill=4), 4, 15)
        self.assertTrue(result["pass"])
        self.assertEqual(result["status"], "WARNING")
        self.assertTrue(any(
            text.startswith("vblank_spill") for text in result["warnings"]))

    def test_delivery_paced_24fps_uses_variable_slot_and_field_budget(self):
        result = self.evaluate(groups(4, cd_wait_count=255, vblank_spill=3, prgbuf_jitter_peak_kib=30), 4, 24)
        self.assertTrue(result["pass"], result["failures"])
        self.assertNotIn("cd_wait_count", result["limits"])
        self.assertEqual(result["limits"]["vblank_spill"], 3)
        self.assertEqual(result["limits"]["prgbuf_jitter_peak_kib"], 30)
        self.assertEqual(result["prg_buf_cap_kib"], 389)
        self.assertEqual(result["jitter_headroom_kib"], 25)

    def test_each_cadence_rejects_a_full_physical_ring(self):
        for fps, first_failing_j in ((15, 46), (24, 31), (30, 26)):
            with self.subTest(fps=fps):
                capture_interval = 4 if fps == 15 else 2
                result = self.evaluate(
                    groups(
                        4,
                        capture_interval=capture_interval,
                        prgbuf_jitter_peak_kib=first_failing_j,
                    ),
                    4,
                    fps,
                )
                self.assertFalse(result["pass"])
                self.assertTrue(any(
                    text.startswith("prgbuf_jitter_peak_kib") for text in result["failures"]))

    def test_fixed_n_display_hold_warns_without_blocking_upload(self):
        rows = groups(12)
        add_display_hold(rows, 5)
        result = self.evaluate(rows, 12)
        self.assertTrue(result["pass"])
        self.assertEqual(result["gate"], "PASS")
        self.assertEqual(result["alert"], "WARNING")
        self.assertEqual(result["display_vblank_expected"], 2)
        self.assertEqual(
            result["display_vblank_histogram"], {"2": 9, "3": 1})
        self.assertEqual(result["display_vblank_violation_count"], 1)
        self.assertEqual(
            result["display_vblank_violations"][0]["frame"], 5)
        self.assertTrue(any(
            "fixed_n2 display cadence missed 1 deadline(s) outside the "
            "4-frame edge exception" in text
            for text in result["warnings"]
        ))

    def test_30fps_edge_holds_remain_diagnostic_but_do_not_alert(self):
        rows = groups(12)
        for frame in (1, 5, 10):
            add_display_hold(rows, frame)
        result = self.evaluate(rows, 12, 30)
        self.assertEqual(result["display_vblank_evaluated_frames"], 10)
        self.assertEqual(result["display_vblank_alert_evaluated_frames"], 4)
        self.assertEqual(result["display_vblank_edge_exempt_frames"], 4)
        self.assertEqual(result["display_vblank_violation_count"], 1)
        self.assertEqual(
            [row["frame"] for row in result["display_vblank_violations"]],
            [5],
        )
        self.assertEqual(
            result["display_vblank_exempted_violation_count"], 2)
        self.assertEqual(
            [
                row["frame"]
                for row in result["display_vblank_exempted_violations"]
            ],
            [1, 10],
        )
        self.assertEqual(result["alert"], "WARNING")

    def test_15fps_edge_holds_remain_diagnostic_but_do_not_alert(self):
        rows = groups(10, capture_interval=4)
        for frame in (1, 4, 8):
            add_display_hold(rows, frame)
        result = self.evaluate(rows, 10, 15)
        self.assertEqual(result["display_vblank_evaluated_frames"], 8)
        self.assertEqual(result["display_vblank_alert_evaluated_frames"], 6)
        self.assertEqual(result["display_vblank_edge_exempt_frames"], 2)
        self.assertEqual(result["display_vblank_violation_count"], 1)
        self.assertEqual(
            [row["frame"] for row in result["display_vblank_violations"]],
            [4],
        )
        self.assertEqual(
            result["display_vblank_exempted_violation_count"], 2)
        self.assertEqual(
            [
                row["frame"]
                for row in result["display_vblank_exempted_violations"]
            ],
            [1, 8],
        )
        self.assertEqual(result["alert"], "WARNING")

    def test_edge_holds_alone_leave_the_alert_clear(self):
        rows = groups(12)
        for frame in (1, 10):
            add_display_hold(rows, frame)
        result = self.evaluate(rows, 12, 30)
        self.assertEqual(result["display_vblank_violation_count"], 0)
        self.assertEqual(
            result["display_vblank_exempted_violation_count"], 2)
        self.assertEqual(result["warnings"], [])
        self.assertEqual(result["alert"], "NONE")

    def test_frame_zero_and_terminal_hold_are_not_cadence_gated(self):
        rows = groups(4)
        rows[0] = replace(
            rows[0], capture_first=-20, capture_last=-1)
        rows[-1] = replace(rows[-1], capture_last=999)
        result = self.evaluate(rows, 4)
        self.assertTrue(result["pass"], result["failures"])
        self.assertEqual(result["display_vblank_histogram"], {"2": 2})
        self.assertEqual(result["display_vblank_violation_count"], 0)

    def test_delivery_paced_cadence_is_recorded_but_not_exact_gated(self):
        rows = groups(5)
        starts = (0, 2, 5, 7, 10)
        rows = [
            replace(
                row,
                capture_first=start,
                capture_last=start + 1,
            )
            for row, start in zip(rows, starts, strict=True)
        ]
        result = self.evaluate(rows, 5, 24)
        self.assertTrue(result["pass"], result["failures"])
        self.assertIsNone(result["display_vblank_expected"])
        self.assertEqual(result["display_vblank_histogram"], {"2": 1, "3": 2})
        self.assertEqual(result["display_vblank_violation_count"], 0)

    def test_missing_movie_frame_blocks_upload(self):
        rows = groups(4)
        rows.pop(2)
        result = self.evaluate(rows, 4)
        self.assertFalse(result["pass"])
        self.assertTrue(any("incomplete" in text for text in result["failures"]))

    def test_hud_log_is_tab_separated(self):
        rows = groups(1)
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

    def test_standard_diagnostics_use_descriptive_columns_and_gate_keys(self):
        rows = groups(3)
        for (
            row, gap, blocked, slip, msf_gap, reader_ahead, reader_slot,
            first_exit, transfer_vblanks, exit_vcounter,
            pattern_start, nt_start,
        ) in zip(
            rows,
            (0x0FFF, 120, 240),
            (0, 1, 0),
            (0, 3, 5),
            (0, 2, 4),
            (0, 2, 1),
            (0, 3, 8),
            (0, 0xE8, 0xF1),
            (0, 2, 2),
            (0, 0xE9, 0xF2),
            (0, 0xD4, 0xC8),
            (0, 0xEE, 0xF0),
            strict=True,
        ):
            row.values.update({
                "sector_slip": slip,
                "pump_gap_ticks": gap,
                "apply_backpressure": blocked,
                "msf_gap_recoveries": msf_gap,
                "reader_ahead_frames": reader_ahead,
                "reader_slot_sector": reader_slot,
                "first_share_exit_vcounter": first_exit,
                "transfer_vblanks": transfer_vblanks,
                "transfer_end_vcounter": exit_vcounter,
                "pattern_dma_ready_vcounter": pattern_start,
                "name_table_dma_ready_vcounter": nt_start,
            })
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "hud.tsv"
            analyze.write_tsv(path, rows, [])
            with path.open(encoding="utf-8", newline="") as handle:
                parsed = list(csv.DictReader(handle, delimiter="\t"))
        self.assertEqual(parsed[1]["pump_gap_ticks"], "120")
        self.assertEqual(parsed[1]["pump_gap_ms"], "3.68640")
        self.assertEqual(parsed[1]["apply_backpressure"], "1")
        self.assertEqual(parsed[1]["msf_gap_recoveries"], "2")
        self.assertEqual(parsed[1]["transport_retry_recoveries"], "1")
        self.assertEqual(parsed[1]["reader_ahead_frames"], "2")
        self.assertEqual(parsed[1]["reader_slot_sector"], "3")
        self.assertEqual(parsed[1]["first_share_exit_vcounter"], "E8")
        self.assertEqual(parsed[1]["transfer_vblanks"], "2")
        self.assertEqual(parsed[1]["transfer_end_vcounter"], "E9")
        self.assertEqual(parsed[1]["pattern_dma_ready_vcounter"], "D4")
        self.assertEqual(parsed[1]["name_table_dma_ready_vcounter"], "EE")
        rows[1].values["sector_slip"] = 1
        rows[1].values["msf_gap_recoveries"] = 15
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "hud.tsv"
            analyze.write_tsv(path, rows, [])
            with path.open(encoding="utf-8", newline="") as handle:
                wrapped = list(csv.DictReader(handle, delimiter="\t"))
        self.assertEqual(wrapped[1]["transport_retry_recoveries"], "2")
        for row in rows:
            row.values["sector_slip"] = 0
            row.values["msf_gap_recoveries"] = 0
        result = self.evaluate(rows, 3)
        self.assertEqual(
            result["diagnostic_fields"],
            [
                "cd_wait_count", "adpcm_decode_units", "pump_gap_ticks",
                "apply_backpressure", "msf_gap_recoveries",
                "reader_ahead_frames", "reader_slot_sector", "cold_runs",
                "transfer_ticks", "transfer_vblanks",
                "transfer_end_vcounter", "pattern_dma_ready_vcounter",
                "name_table_dma_ready_vcounter", "sub_wait_scanlines",
                "flip_vcounter", "first_share_exit_vcounter",
                "pass2_delay_q4",
            ],
        )
        self.assertEqual(result["apply_backpressure_frames"], 1)
        self.assertEqual(
            result["pump_gap_statistics"],
            {
                "minimum": 120,
                "mean": 180.0,
                "median": 180.0,
                "maximum": 240,
                "sample_count": 2,
            },
        )
        self.assertEqual(result["reader_ahead_max_frames"], 2)
        self.assertEqual(result["reader_slot_sector_max"], 8)
        self.assertEqual(result["first_share_exit_vcounter_max"], 0xF1)
        self.assertEqual(result["transfer_vblanks_max"], 2)
        self.assertEqual(result["transfer_end_vcounter_max"], 0xF2)
        self.assertEqual(result["pattern_dma_ready_vcounter_max"], 0xD4)
        self.assertEqual(
            result["name_table_dma_ready_vcounter_max"], 0xF0)
        self.assertEqual(result["status"], "PASS")

    def test_transfer_vblank_count_over_fixed_n_is_warning(self):
        rows = groups(4)
        for row in rows:
            row.values["transfer_vblanks"] = 3
        result = self.evaluate(rows, 4, 30)
        self.assertEqual(result["gate"], "PASS")
        self.assertEqual(result["alert"], "WARNING")
        self.assertTrue(any(
            "transfer_vblanks peak 3 exceeds fixed-N transfer window count 2"
            in text
            for text in result["warnings"]
        ))


if __name__ == "__main__":
    unittest.main()
