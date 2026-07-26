from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path

import numpy as np


MODULE_PATH = Path(__file__).with_name("analyze.py")
SPEC = importlib.util.spec_from_file_location(
    "apply_backpressure_analyze", MODULE_PATH
)
assert SPEC and SPEC.loader
ANALYZE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = ANALYZE
SPEC.loader.exec_module(ANALYZE)


class AnalyzeTest(unittest.TestCase):
    def test_repaid_rate_debt_becomes_irreversible_producer_lead(
        self,
    ) -> None:
        lead, peak = ANALYZE.lead_trace(
            np.asarray([0, 3, 1, 2], np.int64),
            np.asarray([0, 2, 2, 2], np.int64),
        )
        np.testing.assert_array_equal(lead, [0, 1, 0, 0])
        np.testing.assert_array_equal(peak - lead, [0, 0, 1, 1])

    def test_apply_guard_counts_sector_padding_and_exact_consumption(
        self,
    ) -> None:
        physical = np.asarray([0, 1, 2], np.int64)
        control = np.asarray([0, 1, 1], np.int64)
        payload = np.asarray([0, 0, 0], np.int64)
        kinds = ANALYZE.sector_kinds(physical, control, payload)
        prefix = ANALYZE.control_prefix(kinds)
        slot_end = np.cumsum(physical)
        consumed = np.asarray([0, 100, 200], np.int64)

        cursor, delivered, occupancy, next_kind, blocked = (
            ANALYZE.apply_state(
                frame=1,
                ahead_sectors=1,
                slot_end_cursors=slot_end,
                kinds=kinds,
                control_sector_prefix=prefix,
                consumed_control_bytes=consumed,
                guard_bytes=1900,
            )
        )

        self.assertEqual(cursor, 2)
        self.assertEqual(delivered, 2)
        self.assertEqual(occupancy, 3996)
        self.assertEqual(next_kind, "pad")
        self.assertEqual(blocked, 0)

    def test_control_next_sector_triggers_guard(self) -> None:
        kinds = np.asarray(["control", "control"], dtype="<U7")
        cursor, delivered, occupancy, next_kind, blocked = (
            ANALYZE.apply_state(
                frame=0,
                ahead_sectors=0,
                slot_end_cursors=np.asarray([1], np.int64),
                kinds=kinds,
                control_sector_prefix=ANALYZE.control_prefix(kinds),
                consumed_control_bytes=np.asarray([0], np.int64),
                guard_bytes=2048,
            )
        )
        self.assertEqual((cursor, delivered, occupancy), (1, 1, 2048))
        self.assertEqual(next_kind, "control")
        self.assertEqual(blocked, 1)

    def test_stateful_producer_stops_and_retries_the_same_control(
        self,
    ) -> None:
        kinds = np.asarray(
            ["control", "payload", "control"], dtype="<U7"
        )
        first = ANALYZE.advance_apply_producer(
            producer_cursor=0,
            target_cursor=3,
            delivered_control_sectors=0,
            consumed_control_bytes=0,
            kinds=kinds,
            guard_bytes=2048,
        )
        self.assertEqual(first, (2, 1, 2048, "control", 1))
        second = ANALYZE.advance_apply_producer(
            producer_cursor=first[0],
            target_cursor=3,
            delivered_control_sectors=first[1],
            consumed_control_bytes=1024,
            kinds=kinds,
            guard_bytes=2048,
        )
        self.assertEqual(second, (3, 2, 3072, "end", 0))

    def test_hud_delay_is_converted_to_cd_read_ahead(self) -> None:
        hud = {
            10: ANALYZE.HudRow(10, 100, 0, 0),
            11: ANALYZE.HudRow(11, 103, 0, 0),
            12: ANALYZE.HudRow(12, 105, 0, 0),
        }
        extra = ANALYZE.cumulative_extra_scanouts(
            hud, anchor_frame=10, normal_scanouts=2
        )
        self.assertEqual(extra, {10: 0, 11: 1, 12: 1})

    def test_writer_is_utf8_tsv(self) -> None:
        row = ANALYZE.ReplayRow(
            frame=1,
            physical_sectors=2,
            rate_sectors=2,
            rate_lead=0,
            peak_rate_lead=0,
            conservative_ahead_sectors=0,
            extra_scanouts=None,
            extra_cd_sectors=None,
            observed_ahead_sectors=None,
            producer_sector_cursor=2,
            delivered_control_sectors=1,
            consumed_control_bytes=100,
            apply_occupancy_bytes=1948,
            next_sector_kind="payload",
            predicted_apply_blocked=0,
            observed_apply_blocked=None,
            observed_slip=None,
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "replay.tsv"
            ANALYZE.write_replay(path, [row])
            text = path.read_text(encoding="utf-8")
        self.assertIn("\t", text.splitlines()[0])
        self.assertIn("\t\t", text.splitlines()[1])


if __name__ == "__main__":
    unittest.main()
