import unittest

import numpy as np

from harness.pipeline_speedup.verify_main_fastpaths import ControlBlock
from harness.pt_prework import analyze
from tools import shadow_updates


class PtPreworkTests(unittest.TestCase):
    def test_h40_nt_stage_copy_cycles(self) -> None:
        self.assertEqual(analyze.nt_stage_copy_cycles(40, 28), 11_750)
        self.assertAlmostEqual(
            float(analyze.cycles_to_scanlines(11_750)),
            24.077868852459016,
        )

    def test_pass2_to_ready_cycles(self) -> None:
        self.assertEqual(analyze.pass2_to_ready_cycles(), 448)
        self.assertAlmostEqual(
            float(analyze.cycles_to_scanlines(448)),
            0.9180327868852459,
        )

    def test_shadow_paths_match_shared_cycle_model(self) -> None:
        bitmap = ControlBlock(
            seq=1,
            bitmap=b"\x05",
            entries=(0x1234, 0x5678),
            use_list=False,
            total_len=0,
        )
        listed = ControlBlock(
            seq=1,
            bitmap=b"\x05",
            entries=(0x1234, 0x5678),
            use_list=True,
            total_len=0,
        )
        self.assertEqual(
            analyze.shadow_update_cycles(bitmap, 8),
            shadow_updates.legacy_bitmap_cycles([0, 2], 8),
        )
        self.assertEqual(
            analyze.shadow_update_cycles(listed, 8),
            shadow_updates.update_list_cycles(2),
        )

    def test_ready_pressure_keeps_head_and_marks_later_blank(self) -> None:
        self.assertEqual(analyze.ready_pressure(0), 0)
        self.assertEqual(analyze.ready_pressure(0xDF), 0xDF)
        self.assertEqual(analyze.ready_pressure(0xE0), 0xE0)
        self.assertEqual(analyze.ready_pressure(0xE1), 0x100)
        self.assertEqual(analyze.ready_pressure(0xFF), 0x100)

    def test_summary_uses_inclusive_endpoints(self) -> None:
        item = analyze.summarize(
            "metric",
            "subset",
            np.asarray([0.0, 10.0, 20.0, 30.0, 40.0]),
        )
        self.assertEqual(item.samples, 5)
        self.assertEqual(item.minimum, 0.0)
        self.assertEqual(item.p50, 20.0)
        self.assertEqual(item.maximum, 40.0)
        self.assertEqual(item.mean, 20.0)


if __name__ == "__main__":
    unittest.main()
