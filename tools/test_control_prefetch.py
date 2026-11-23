"""Regression coverage for repacking authenticated control-sector routes."""

import unittest

import numpy as np

from control_prefetch import apply_to_schedule
from stream_schedule import rate_deltas, useful_body_delivery_trace


def packed_schedule(*, word_prefix):
    """Frame 3 needs two controls; only slot 2 can supply its prefix."""
    lengths = np.array([100, 1024, 1024, 3000, 1000])
    control = np.array([0, 1, 0, 2, 0])
    word = np.array([0, 0, word_prefix, 0, 0])
    payload = np.array([0, 1, word_prefix, 0, 1])
    physical = rate_deltas(len(lengths), fps=30)
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
        baseline = packed_schedule(word_prefix=0)
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


if __name__ == "__main__":
    unittest.main()
