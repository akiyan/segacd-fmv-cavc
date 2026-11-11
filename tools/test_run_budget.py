"""Exercise run admission against actual allocation and physical source splits."""
import unittest

import pattern_supply as supply
from run_budget import RunAdmission, check_run_cap, count_runs
from tile_alloc import TileAllocator


class RunBudgetTests(unittest.TestCase):
    def test_contiguous_colds_are_not_limited_to_run_count(self):
        alloc = TileAllocator(6, 16)
        alloc.place_frame([(0, b"old")], 0)
        before = alloc.state_digest()
        guard = RunAdmission(alloc, 1, 1, {})
        for cell in range(6):
            key = bytes([cell])
            self.assertTrue(guard.fits(cell, key, {}, supply.SOURCE_PRG, cell + 1))
            guard.commit(cell, key)
        self.assertEqual(alloc.state_digest(), before)
        keys = [bytes([cell]) for cell in range(6)]
        placed = alloc.place_frame(list(enumerate(keys)), 1)
        self.assertEqual(count_runs(placed, keys, {}, {}), 1)

    def test_source_switch_rejects_cold_but_keeps_warm_choice(self):
        alloc = TileAllocator(4, 16)
        alloc.place_frame([(0, b"old")], 0)
        guard = RunAdmission(alloc, 1, 1, {})
        sources = {b"a": supply.SOURCE_WR}
        guard.commit(1, b"a")
        self.assertFalse(guard.fits(2, b"b", sources, supply.SOURCE_PRG, 2))
        self.assertTrue(guard.fits(2, b"b", sources, supply.SOURCE_WR, 2))
        self.assertTrue(guard.fits(2, b"old", sources, supply.SOURCE_PRG, 1))

    def test_dictionary_block_and_ring_end_are_counted(self):
        boundary = supply.DIC_RUN_BLOCK
        runs = supply.source_runs([10, 11], [supply.SOURCE_DIC] * 2,
                                  [boundary - 1, boundary])
        self.assertEqual(len(runs), 2)
        runs, _ = supply.split_word_ring_runs(
            [(20, 4, supply.SOURCE_WR, 0)], capacity=8, cursor=6)
        with self.assertRaisesRegex(ValueError, "frame 1"):
            check_run_cap([100, len(runs)], 1)
        check_run_cap([100, 1], 1)

    def test_warm_protection_cannot_split_an_accepted_batch_past_cap(self):
        alloc = TileAllocator(4, 8)
        alloc.place_frame([(i, bytes([i])) for i in range(4)], 0)
        for i in range(4, 8):
            alloc.prefetch(bytes([i]), 0, 1)
        guard = RunAdmission(alloc, 2, 1, {})
        for cell, key in enumerate((b"new-a", b"new-b")):
            self.assertTrue(guard.fits(cell, key, {}, supply.SOURCE_PRG, cell + 1))
            guard.commit(cell, key)
        # Reusing slot 5 protects a hole between the two new destinations.
        self.assertFalse(guard.fits(2, bytes([5]), {}, supply.SOURCE_PRG, 2))



if __name__ == "__main__":
    unittest.main()
