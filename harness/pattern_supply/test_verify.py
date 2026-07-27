from __future__ import annotations

import unittest

import verify


def decision_fixture() -> dict:
    return {
        "raw_prefetch": {
            "schema_version": 3,
            "enabled": True,
            "boot_inline_requests": 2,
            "boot_sidecar_requests": 1,
            "requests": (
                (
                    (bytes([5] * 64), 2, 5),
                    (bytes([1] * 64), 2, 1),
                    (bytes([4] * 64), 2, 4),
                ),
                (
                    (bytes([3] * 64), 2, 3),
                    (bytes([2] * 64), 2, 2),
                ),
            ),
            "cold": (3, 2),
        },
    }


class RawPrefetchExpectationsTests(unittest.TestCase):
    def test_disabled_feature_has_no_records(self) -> None:
        inline, sidecar = verify.raw_prefetch_expectations({}, 2, 8, False)
        self.assertEqual(inline, ((), ()))
        self.assertEqual(sidecar, ())

    def test_sorts_each_suffix_and_splits_frame_zero(self) -> None:
        inline, sidecar = verify.raw_prefetch_expectations(
            decision_fixture(), 2, 8, True)

        self.assertEqual([slot for slot, _pattern in inline[0]], [1, 4])
        self.assertEqual([slot for slot, _pattern in sidecar], [5])
        self.assertEqual([slot for slot, _pattern in inline[1]], [2, 3])
        self.assertEqual(inline[1][0][1], bytes([0x22] * 32))

    def test_rejects_request_count_that_differs_from_cold_trace(self) -> None:
        decisions = decision_fixture()
        decisions["raw_prefetch"]["cold"] = (2, 2)
        with self.assertRaisesRegex(
                AssertionError, "requests/cold count differ"):
            verify.raw_prefetch_expectations(decisions, 2, 8, True)

    def test_rejects_header_decision_feature_mismatch(self) -> None:
        with self.assertRaisesRegex(
                AssertionError, "decision/header feature state differs"):
            verify.raw_prefetch_expectations(
                decision_fixture(), 2, 8, False)


if __name__ == "__main__":
    unittest.main()
