"""Regression coverage for repacking authenticated control-sector routes."""

import unittest

import numpy as np

from control_prefetch import apply_to_schedule
from stream_schedule import rate_deltas, useful_body_delivery_trace


def packed_schedule(*, word_prefix=0, fps=30, first_sector_only=False):
    """Frame 3 needs control sectors that can be moved to slot 2."""
    lengths = np.array([100, 1024, 1024, 1000 if first_sector_only else 3000, 1000])
    control = np.array([0, 1, 0, 1 if first_sector_only else 2, 0])
    word = np.array([0, 0, word_prefix, 0, 0])
    payload = np.array([0, 1, word_prefix, 0, 1])
    physical = rate_deltas(len(lengths), fps=fps)
    return {
        "blk_len": lengths,
        "n_ctrl_sec": control,
        "n_pay_sec": payload,
        "word_stage_sectors": word,
        "fsec": physical,
        **useful_body_delivery_trace(
            payload, control, physical,
            body_control_bytes=int(lengths[1:].sum()),
            body_payload_bytes=int(payload.sum()) * 2048,
        ),
    }


class ControlPrefetchTests(unittest.TestCase):
    def test_advance_control_using_physical_padding(self):
        baseline = packed_schedule()
        updated, stats = apply_to_schedule(baseline, fps=30)

        np.testing.assert_array_equal(baseline["n_ctrl_sec"], [0, 1, 0, 2, 0])
        np.testing.assert_array_equal(updated["n_ctrl_sec"], [0, 1, 1, 1, 0])
        np.testing.assert_array_equal(updated["n_pay_sec"], baseline["n_pay_sec"])
        np.testing.assert_array_equal(updated["fsec"], baseline["fsec"])
        np.testing.assert_array_equal(
            updated["body_useful_control_bytes"], [0, 2048, 2048, 1952, 0])
        np.testing.assert_array_equal(
            updated["body_useful_control_bytes"]
            + updated["body_useful_payload_bytes"] + updated["body_pad_bytes"],
            baseline["body_physical_bytes"],
        )
        self.assertEqual((stats.multi_sector_before, stats.multi_sector_after), (1, 0))

    def test_donor_cannot_displace_word_prefix(self):
        baseline = packed_schedule(word_prefix=1)
        updated, stats = apply_to_schedule(baseline, fps=30)

        np.testing.assert_array_equal(updated["n_ctrl_sec"], baseline["n_ctrl_sec"])
        np.testing.assert_array_equal(
            updated["word_stage_sectors"], baseline["word_stage_sectors"])
        self.assertEqual((stats.multi_sector_after, stats.changed_slots), (1, 0))

    def test_short_two_sector_interval_can_advance_both_sectors(self):
        baseline = packed_schedule(fps=24)
        updated, stats = apply_to_schedule(baseline, fps=24)

        np.testing.assert_array_equal(updated["n_ctrl_sec"], [0, 1, 2, 0, 0])
        np.testing.assert_array_equal(updated["fsec"], baseline["fsec"])
        np.testing.assert_array_equal(updated["n_pay_sec"], baseline["n_pay_sec"])
        self.assertEqual((stats.short_first_sector_before, stats.short_first_sector_after), (1, 0))

    def test_first_sector_only_wait_depends_on_cadence(self):
        for fps, expected in ((24, [0, 1, 1, 0, 0]), (30, [0, 1, 0, 1, 0])):
            with self.subTest(fps=fps):
                baseline = packed_schedule(fps=fps, first_sector_only=True)
                updated, stats = apply_to_schedule(baseline, fps=fps)

                np.testing.assert_array_equal(updated["n_ctrl_sec"], expected)
                self.assertEqual(stats.multi_sector_before, 0)


if __name__ == "__main__":
    unittest.main()
