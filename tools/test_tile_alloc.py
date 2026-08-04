#!/usr/bin/env python3
"""Tests for displayed and speculative VRAM residency."""
from __future__ import annotations

import unittest
from pathlib import Path
import sys

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tile_alloc import (
    FrameTransitionGuard,
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

    def test_mandatory_prefetch_preserves_previous_display(self) -> None:
        alloc = TileAllocator(1, 2)
        alloc.place_frame([(0, b"previous")], 0)
        alloc.place_frame([(0, b"current")], 1)

        self.assertIsNone(alloc.prefetch(b"soft", 1, 2))
        result = alloc.prefetch(b"fade", 1, 2, mandatory=True)

        self.assertIsNone(result)
        self.assertTrue(alloc.is_resident(b"previous"))
        self.assertFalse(alloc.is_resident(b"fade"))

        # Once another frame has completed, the old slot is cache history and
        # can safely receive the delayed mandatory prefetch.
        alloc.place_frame([(0, b"current")], 2)
        result = alloc.prefetch(b"fade", 2, 3, mandatory=True)
        self.assertIsNotNone(result)
        self.assertTrue(result[1])
        self.assertFalse(alloc.is_resident(b"previous"))
        self.assertTrue(alloc.is_mandatory_pinned(b"fade", 3))

    def test_forced_fade_slot_preserves_previous_display(self) -> None:
        alloc = TileAllocator(1, 3)
        previous_slot = alloc.place_frame([(0, b"previous")], 0)[0][0]
        alloc.place_frame([(0, b"current")], 1)

        result = alloc.prefetch(
            b"fade",
            1,
            3,
            forced_slot=previous_slot,
            mandatory=True,
            relocate=True,
        )

        self.assertIsNone(result)
        self.assertTrue(alloc.is_resident(b"previous"))

        alloc.place_frame([(0, b"current")], 2)
        result = alloc.prefetch(
            b"fade",
            2,
            3,
            forced_slot=previous_slot,
            mandatory=True,
            relocate=True,
        )
        self.assertEqual(result, (previous_slot, True))
        self.assertFalse(alloc.is_resident(b"previous"))

    def test_fade_block_uses_an_available_slot_instead_of_waiting(self) -> None:
        alloc = TileAllocator(1, 4)
        blocked_slot = alloc.place_frame([(0, b"previous")], 0)[0][0]
        alloc.place_frame([(0, b"current")], 1)

        slot = alloc.find_prefetch_slot_in_block(
            b"fade",
            1,
            0,
            3,
            avoid_keys={b"current"},
        )

        self.assertNotEqual(slot, blocked_slot)
        self.assertEqual(slot, 2)
        self.assertEqual(
            alloc.prefetch(
                b"fade",
                1,
                3,
                forced_slot=slot,
                avoid_keys={b"current"},
                mandatory=True,
                relocate=True,
            ),
            (2, True),
        )

    def test_fade_block_keeps_a_resident_reference_in_place(self) -> None:
        alloc = TileAllocator(1, 4)
        resident_slot = alloc.place_frame([(0, b"fade")], 0)[0][0]

        slot = alloc.find_prefetch_slot_in_block(
            b"fade", 0, 0, 3, assigned_slots={1})

        self.assertEqual(slot, resident_slot)
        self.assertEqual(
            alloc.prefetch(
                b"fade",
                0,
                3,
                forced_slot=slot,
                mandatory=True,
                relocate=True,
            ),
            (resident_slot, False),
        )

    def test_mandatory_block_keeps_a_resident_key_outside_block(self) -> None:
        alloc = TileAllocator(1, 4)
        resident_slot = alloc.place_frame([(0, b"fade")], 0)[0][0]

        result = alloc.prefetch_mandatory_in_block(
            b"fade", 0, 3, 2, 2)

        self.assertEqual(result, (resident_slot, False, False, False))
        self.assertTrue(alloc.is_mandatory_pinned(b"fade", 3))

    def test_mandatory_block_spills_only_to_a_safe_slot(self) -> None:
        alloc = TileAllocator(1, 4)
        alloc.place_frame([(0, b"previous")], 0)
        alloc.place_frame([(0, b"current")], 1)

        result = alloc.prefetch_mandatory_in_block(
            b"fade", 1, 3, 0, 2, avoid_keys={b"current"})

        self.assertEqual(result, (2, True, False, False))
        self.assertTrue(alloc.is_mandatory_pinned(b"fade", 3))

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

    def test_fade_reference_can_relocate_from_a_displayed_slot(self) -> None:
        alloc = TileAllocator(1, 3)
        old_slot = alloc.place_frame([(0, b"fade")], 0)[0][0]

        new_slot, cold = alloc.prefetch(
            b"fade",
            0,
            2,
            forced_slot=2,
            mandatory=True,
            relocate=True,
        )

        self.assertTrue(cold)
        self.assertEqual(new_slot, 2)
        self.assertEqual(alloc.key_slot[b"fade"], 2)
        self.assertIsNone(alloc.slot_key[old_slot])
        self.assertEqual(int(alloc.slot_refs[old_slot]), 1)
        self.assertEqual(alloc.place_frame([(0, b"fade")], 2), [(2, False)])
        self.assertEqual(int(alloc.slot_refs[old_slot]), 0)

    def test_fade_block_minimizes_live_slots(self) -> None:
        alloc = TileAllocator(2, 6)
        alloc.place_frame([(0, b"a"), (1, b"b")], 0)

        self.assertEqual(alloc.least_live_contiguous_block(2, 1), 4)

    def test_fade_block_counts_the_preceding_display(self) -> None:
        alloc = TileAllocator(2, 6)
        alloc.place_frame([(0, b"previous-a"), (1, b"previous-b")], 0)
        alloc.place_frame([(0, b"current-a"), (1, b"current-b")], 1)

        self.assertEqual(alloc.least_live_contiguous_block(2, 1), 4)

    def test_forced_fade_block_does_not_redirect_visible_hand(self) -> None:
        alloc = TileAllocator(1, 3)
        alloc.place_frame([(0, b"shown")], 0)
        alloc.prefetch(b"cache-a", 0, 3)
        alloc.prefetch(b"cache-b", 0, 3)
        alloc.hand = 1

        result = alloc.prefetch(
            b"fade",
            1,
            4,
            forced_slot=2,
            mandatory=True,
            relocate=True,
        )

        self.assertIsNotNone(result)
        self.assertEqual(alloc.hand, 1)

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

    def test_display_rebase_copies_slots_and_releases_guard(self) -> None:
        alloc = TileAllocator(8, 8)
        alloc.place_frame([
            (2, b"left"),
            (3, b"right"),
            (4, b"guard"),
        ], 0)
        old_slots = alloc.cur_slot.copy()
        old_previous = alloc.prev_slot.copy()

        alloc.replace_display_cells(((0, 3), (1, 4)), clear_others=True)

        self.assertEqual(int(alloc.cur_slot[0]), int(old_slots[3]))
        self.assertEqual(int(alloc.cur_slot[1]), int(old_slots[4]))
        self.assertTrue(np.all(alloc.cur_slot[2:] == -1))
        self.assertTrue(np.array_equal(alloc.prev_slot, old_previous))
        self.assertEqual(int(alloc.slot_refs.sum()), 2)

    def test_display_rebase_reads_sources_before_writing_destinations(self) -> None:
        alloc = TileAllocator(3, 3)
        alloc.place_frame([(0, b"a"), (1, b"b"), (2, b"c")], 0)
        before = alloc.cur_slot.copy()

        alloc.replace_display_cells(((0, 1), (1, 2), (2, 0)))

        self.assertEqual(
            alloc.cur_slot.tolist(),
            [int(before[1]), int(before[2]), int(before[0])],
        )

    def test_display_rebase_rejects_duplicate_destinations(self) -> None:
        alloc = TileAllocator(3, 3)
        with self.assertRaisesRegex(ValueError, "destinations must be unique"):
            alloc.replace_display_cells(((0, 1), (0, 2)))

    def test_cell_domain_expansion_preserves_cache_and_maps_history(self) -> None:
        alloc = TileAllocator(2, 4)
        alloc.place_frame([(0, b"a"), (1, b"b")], 0)
        before_keys = dict(alloc.key_slot)

        alloc.expand_cell_domain(8, ((0, 0), (4, 1)))

        self.assertEqual(alloc.C_CELLS, 8)
        self.assertEqual(alloc.key_slot, before_keys)
        self.assertEqual(int(alloc.cur_slot[0]), before_keys[b"a"])
        self.assertEqual(int(alloc.cur_slot[4]), before_keys[b"b"])
        self.assertEqual(int(alloc.prev_slot[0]), before_keys[b"a"])
        self.assertEqual(int(alloc.prev_slot[4]), before_keys[b"b"])
        self.assertEqual(int(alloc.slot_refs.sum()), 2)


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


class FrameTransitionGuardTests(unittest.TestCase):
    def test_previous_display_and_new_keys_share_the_pool(self):
        alloc = TileAllocator(2, 3)
        alloc.place_frame([(0, b"old-a"), (1, b"old-b")], 0)
        guard = FrameTransitionGuard(alloc)

        self.assertEqual(guard.capacity, 1)
        self.assertTrue(guard.fits(0, b"new-a"))
        guard.commit(0, b"new-a")
        self.assertFalse(guard.fits(1, b"new-b"))

    def test_resident_preceding_key_needs_no_extra_slot(self):
        alloc = TileAllocator(2, 2)
        alloc.place_frame([(0, b"old-a"), (1, b"old-b")], 0)
        guard = FrameTransitionGuard(alloc)

        self.assertEqual(guard.capacity, 0)
        self.assertTrue(guard.fits(0, b"old-b"))
        guard.commit(0, b"old-b")
        self.assertEqual(guard.used, 0)

    def test_replacing_a_cell_releases_its_unique_reservation(self):
        alloc = TileAllocator(2, 3)
        alloc.place_frame([(0, b"old-a"), (1, b"old-b")], 0)
        guard = FrameTransitionGuard(alloc)

        guard.commit(0, b"discarded")
        self.assertTrue(guard.fits(0, b"replacement"))
        guard.commit(0, b"replacement")
        self.assertEqual(guard.used, 1)

    def test_duplicate_new_key_uses_one_reservation(self):
        alloc = TileAllocator(2, 3)
        alloc.place_frame([(0, b"old-a"), (1, b"old-b")], 0)
        guard = FrameTransitionGuard(alloc)

        guard.commit(0, b"shared")
        self.assertTrue(guard.fits(1, b"shared"))
        guard.commit(1, b"shared")
        self.assertEqual(guard.used, 1)


if __name__ == "__main__":
    unittest.main()
