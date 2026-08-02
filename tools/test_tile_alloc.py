#!/usr/bin/env python3
"""Tests for displayed and speculative VRAM residency."""
from __future__ import annotations

import unittest
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tile_alloc import (
    TileAllocator,
    cold_transfer_order,
    count_slot_runs,
)


class TileAllocatorPrefetchTests(unittest.TestCase):
    def test_prefetched_pattern_is_warm_at_its_first_display_use(self) -> None:
        alloc = TileAllocator(2, 4)
        alloc.place_frame([(0, b"shown")], 0)
        slot, cold = alloc.prefetch(b"future", 0, 3)
        self.assertTrue(cold)
        self.assertEqual(alloc.place_frame([(1, b"future")], 3), [(slot, False)])
        self.assertEqual(int(alloc.slot_pin_until[slot]), -1)

    def test_normal_update_may_reclaim_a_pin_before_tearing_display(self) -> None:
        alloc = TileAllocator(1, 2)
        alloc.place_frame([(0, b"shown")], 0)
        _slot, cold = alloc.prefetch(b"future", 0, 5)
        self.assertTrue(cold)
        result = alloc.place_frame([(0, b"replacement")], 1)
        self.assertTrue(result[0][1])
        self.assertEqual(alloc.prefetch_evictions, 1)
        self.assertEqual(alloc.tearing, 0)

    def test_normal_update_preserves_a_mandatory_fade_pin(self) -> None:
        alloc = TileAllocator(1, 3)
        alloc.place_frame([(0, b"shown")], 0)
        fade_slot, cold = alloc.prefetch(
            b"fade", 0, 5, mandatory=True)
        self.assertTrue(cold)
        cache_slot, cache_cold = alloc.prefetch(b"cache", 0, 4)
        self.assertTrue(cache_cold)

        result = alloc.place_frame([(0, b"replacement")], 1)

        self.assertTrue(result[0][1])
        self.assertTrue(alloc.is_mandatory_pinned(b"fade", 5))
        self.assertEqual(alloc.key_slot[b"fade"], fade_slot)
        self.assertFalse(alloc.is_resident(b"cache"))
        self.assertNotEqual(result[0][0], fade_slot)
        self.assertEqual(cache_slot, result[0][0])

    def test_resident_key_can_be_upgraded_to_a_mandatory_pin(self) -> None:
        alloc = TileAllocator(1, 3)
        shown_slot = alloc.place_frame([(0, b"fade")], 0)[0][0]
        slot, cold = alloc.prefetch(b"fade", 1, 4, mandatory=True)

        self.assertFalse(cold)
        self.assertEqual(slot, shown_slot)
        self.assertTrue(alloc.is_mandatory_pinned(b"fade", 4))
        self.assertEqual(alloc.pinned_count, 1)

        alloc.place_frame([(0, b"fade")], 4)
        self.assertFalse(alloc.is_mandatory_pinned(b"fade", 4))
        self.assertEqual(alloc.pinned_count, 0)

    def test_mandatory_prefetch_may_replace_previous_frame_cache(self) -> None:
        alloc = TileAllocator(1, 2)
        alloc.place_frame([(0, b"previous")], 0)
        alloc.place_frame([(0, b"current")], 1)

        self.assertIsNone(alloc.prefetch(b"soft", 1, 2))
        result = alloc.prefetch(b"fade", 1, 2, mandatory=True)

        self.assertIsNotNone(result)
        self.assertTrue(result[1])
        self.assertFalse(alloc.is_resident(b"previous"))
        self.assertTrue(alloc.is_mandatory_pinned(b"fade", 2))

    def test_visible_work_reclaims_fade_pin_before_tearing(self) -> None:
        alloc = TileAllocator(1, 2)
        alloc.place_frame([(0, b"shown")], 0)
        alloc.prefetch(b"fade", 0, 4, mandatory=True)

        result = alloc.place_frame([(0, b"replacement")], 1)

        self.assertTrue(result[0][1])
        self.assertFalse(alloc.is_resident(b"fade"))
        self.assertEqual(alloc.mandatory_prefetch_evictions, 1)
        self.assertEqual(alloc.tearing, 0)

    def test_fade_prefetch_replaces_a_soft_prefetch_first(self) -> None:
        alloc = TileAllocator(1, 2)
        alloc.place_frame([(0, b"shown")], 0)
        alloc.prefetch(b"soft", 0, 4)

        result = alloc.prefetch(b"fade", 0, 3, mandatory=True)

        self.assertIsNotNone(result)
        self.assertFalse(alloc.is_resident(b"soft"))
        self.assertTrue(alloc.is_mandatory_pinned(b"fade", 3))
        self.assertEqual(alloc.prefetch_evictions, 1)

    def test_prefetch_skips_when_only_a_displayed_slot_exists(self) -> None:
        alloc = TileAllocator(1, 1)
        alloc.place_frame([(0, b"shown")], 0)
        self.assertIsNone(alloc.prefetch(b"future", 0, 2))

    def test_prefetch_may_replace_unused_cache_but_not_next_frame_key(self) -> None:
        alloc = TileAllocator(1, 3)
        alloc.place_frame([(0, b"old-shown")], 0)
        alloc.place_frame([(0, b"keep-next")], 1)
        alloc.place_frame([(0, b"shown")], 2)
        result = alloc.prefetch(
            b"future", 2, 3, avoid_keys={b"keep-next"})
        self.assertIsNotNone(result)
        self.assertTrue(result[1])
        self.assertTrue(alloc.is_resident(b"keep-next"))
        self.assertEqual(alloc.prefetch_cache_evictions, 1)


class ColdRunTests(unittest.TestCase):
    def test_identity_contiguous_allocation_matches_legacy_and_suffix_runs(self):
        alloc = TileAllocator(4, 6)
        frames = [
            [(0, b"a"), (1, b"b"), (2, b"c"), (3, b"d")],
            [(0, b"e"), (1, b"b"), (2, b"f"), (3, b"g")],
            [(0, b"h"), (1, b"i"), (2, b"f"), (3, b"j")],
        ]
        for frame, updates in enumerate(frames):
            placements = alloc.place_frame(updates, frame)
            legacy_slots = [slot for slot, cold in placements if cold]
            suffix_slots = [
                placements[index][0]
                for index in cold_transfer_order(placements)
            ]
            self.assertEqual(
                count_slot_runs(legacy_slots),
                count_slot_runs(suffix_slots),
            )

    def test_transfer_order_follows_physical_slots(self):
        placements = [(5, True), (2, False), (1, True), (3, True)]
        self.assertEqual(cold_transfer_order(placements), (2, 3, 0))


if __name__ == "__main__":
    unittest.main()
