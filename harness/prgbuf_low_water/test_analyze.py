from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


MODULE_PATH = Path(__file__).with_name("analyze.py")
SPEC = importlib.util.spec_from_file_location("prgbuf_low_water_analyze", MODULE_PATH)
assert SPEC and SPEC.loader
ANALYZE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = ANALYZE
SPEC.loader.exec_module(ANALYZE)


class AnalyzeTest(unittest.TestCase):
    def test_ranges_and_counter_transitions(self) -> None:
        timeline = [
            ANALYZE.TimelineRow(1, 300),
            ANALYZE.TimelineRow(2, 256),
            ANALYZE.TimelineRow(3, 1),
            ANALYZE.TimelineRow(4, 400),
            ANALYZE.TimelineRow(5, 200),
        ]
        ranges = ANALYZE.contiguous_ranges(timeline, 256)
        self.assertEqual([[2, 3], [5]], [[row.frame for row in item] for item in ranges])

        hud = {
            1: ANALYZE.HudRow(1, 0, 0),
            2: ANALYZE.HudRow(2, 0, 0),
            3: ANALYZE.HudRow(3, 1, 0),
            4: ANALYZE.HudRow(4, 1, 1),
            5: ANALYZE.HudRow(5, 3, 1),
        }
        self.assertEqual(
            [3, 5],
            ANALYZE.transition_frames(hud, "sector_slip"),
        )
        self.assertEqual(
            [4],
            ANALYZE.transition_frames(hud, "audio_resync"),
        )

    def test_poll_gap_backpressure_and_scanout_diagnostics(self) -> None:
        hud = {
            10: ANALYZE.HudRow(
                10, 0, 0,
                capture_first=100,
                pump_gap_ticks=275,
                apply_backpressure=1,
                msf_gap_recoveries=0,
                transport_retry_recoveries=0,
            ),
            11: ANALYZE.HudRow(
                11, 1, 0,
                capture_first=103,
                pump_gap_ticks=280,
                apply_backpressure=0,
                msf_gap_recoveries=1,
                transport_retry_recoveries=0,
            ),
            12: ANALYZE.HudRow(
                12, 1, 0,
                capture_first=105,
                pump_gap_ticks=276,
                apply_backpressure=0,
                msf_gap_recoveries=1,
                transport_retry_recoveries=0,
            ),
        }
        self.assertEqual([10], ANALYZE.apply_block_frames(hud))
        self.assertEqual(10, ANALYZE.prior_frame([10], 11))
        self.assertEqual(
            1,
            ANALYZE.interval_extra_scanouts(hud, 10, 11, 2),
        )

    def test_tsv_writers_use_tabs(self) -> None:
        timeline = [
            ANALYZE.TimelineRow(1, 200),
            ANALYZE.TimelineRow(2, 100),
        ]
        hud = {
            1: ANALYZE.HudRow(1, 0, 0),
            2: ANALYZE.HudRow(2, 1, 0),
        }
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ranges_path = root / "ranges.tsv"
            events_path = root / "events.tsv"
            ANALYZE.write_ranges(ranges_path, [timeline], hud, [2], [])
            ANALYZE.write_events(events_path, timeline, hud, [2], [], 256)
            ranges_text = ranges_path.read_text(encoding="utf-8")
            events_text = events_path.read_text(encoding="utf-8")
        self.assertIn("\t", ranges_text.splitlines()[0])
        self.assertIn("\t", events_text.splitlines()[0])
        self.assertIn("sector_slip", events_text)
        self.assertIn("prior_apply_block_frame", events_text.splitlines()[0])


if __name__ == "__main__":
    unittest.main()
