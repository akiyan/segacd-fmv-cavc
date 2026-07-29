import unittest

from harness.pattern_supply import verify


class LoadsV2ReplicaTest(unittest.TestCase):
    def test_round_trip_matches_source_runs(self) -> None:
        patterns = tuple(bytes([value]) * 32 for value in range(1, 5))
        transfers = [
            (2, verify.SOURCE_PRG, 0, patterns[:2]),
            (8, verify.SOURCE_WR, 0, patterns[2:3]),
            (12, verify.SOURCE_DIC, 7, patterns[3:]),
        ]
        word_ptrs = [0x1000, 0x2000]
        output, external = verify.encode_loads_v2(
            transfers,
            parity=0,
            base=1,
            word_ptrs=word_ptrs,
            word_starts=(0x1000, 0x2000),
            word_ends=(0x3000, 0x4000),
        )
        self.assertEqual(
            len(output),
            verify.OUTPUT_HEADER_BYTES
            + 3 * verify.OUTPUT_RUN_RECORD_BYTES
            + 2 * verify.PATTERN_BYTES,
        )
        self.assertEqual(word_ptrs, [0x1020, 0x2000])
        self.assertEqual(
            verify.decode_loads_v2(output, external, base=1),
            tuple(transfers),
        )

    def test_word_run_wraps_only_at_generated_end(self) -> None:
        pattern = bytes(range(32))
        word_ptrs = [0x1800, 0x2000]
        transfers = [(0, verify.SOURCE_WR, 0, (pattern,))]
        output, external = verify.encode_loads_v2(
            transfers,
            parity=0,
            base=1,
            word_ptrs=word_ptrs,
            word_starts=(0x1000, 0x2000),
            word_ends=(0x1800, 0x3000),
        )
        self.assertEqual(word_ptrs[0], 0x1020)
        self.assertEqual(
            verify.decode_loads_v2(output, external, base=1),
            tuple(transfers),
        )

    def test_corrupt_prebuilt_register_is_rejected(self) -> None:
        pattern = bytes(range(32))
        output, external = verify.encode_loads_v2(
            [(0, verify.SOURCE_PRG, 0, (pattern,))],
            parity=0,
            base=1,
            word_ptrs=[0x1000, 0x2000],
            word_starts=(0x1000, 0x2000),
            word_ends=(0x3000, 0x4000),
        )
        corrupt = bytearray(output)
        corrupt[6] ^= 1
        with self.assertRaisesRegex(AssertionError, "length registers"):
            verify.decode_loads_v2(bytes(corrupt), external, base=1)


if __name__ == "__main__":
    unittest.main()
