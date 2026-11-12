"""Catch late-publication overflow without reducing the movie cold cap."""

import unittest

import av_config
import final_vblank
import pattern_supply
from tile_alloc import FrameTransitionGuard, TileAllocator, cold_transfer_order


class FinalPublicationTests(unittest.TestCase):
    def test_fragmented_tail_is_redirected_without_dropping_updates(self):
        pool, tail = av_config.VRAM_PATTERN_POOL_TILES, av_config.FINAL_VBLANK_SLOT
        alloc = TileAllocator(1120, pool)
        alloc.place_frame([(i, str(i).encode()) for i in range(1120)], 0)
        for i in range(1120, pool):
            alloc.prefetch(str(i).encode(), 0, 1)
        alloc.hand = tail
        alloc.final_pattern_limit = final_vblank.pattern_limit(40, 28, scroll_build=True)
        updates = [(i, f"new{i}".encode()) for i in range(11)]
        placed = alloc.place_frame(updates, 2)
        sources = [0, 2, 0, 2, 2, 0, 0, 0, 0, 0, 2]
        indices = [-1, 241, -1, 397, 125, -1, -1, -1, -1, -1, 242]
        old_runs = pattern_supply.source_runs(range(tail, tail + 11), sources, indices)
        with self.assertRaisesRegex(ValueError, "3220/3200"):
            final_vblank.verify_runs(old_runs, 40, 28, scroll_build=True)
        order = cold_transfer_order(placed)
        runs = pattern_supply.source_runs(
            [placed[i][0] for i in order], [sources[i] for i in order],
            [indices[i] for i in order])
        self.assertLessEqual(final_vblank.verify_runs(runs, 40, 28, scroll_build=True), 3200)
        self.assertTrue(all(cold for _, cold in placed))
        self.assertEqual([alloc.slot_key[slot] for slot, _ in placed], [key for _, key in updates])
        self.assertEqual(alloc.tearing, 0)
        self.assertEqual(sum(slot >= tail for slot, _ in placed), 7)

    def test_prefetch_and_warm_reuse_share_one_frame_reservation(self):
        tail = av_config.FINAL_VBLANK_SLOT
        alloc = TileAllocator(1, av_config.VRAM_PATTERN_POOL_TILES)
        alloc.final_pattern_limit = 1
        alloc.place_frame([(0, b"shown")], 1)
        self.assertEqual(alloc.prefetch(b"future", 1, 3, forced_slot=tail), (tail, True))
        self.assertIsNone(alloc.prefetch(b"overflow", 1, 3, forced_slot=tail+1))
        self.assertEqual(alloc.prefetch(b"future", 1, 3, forced_slot=tail), (tail, False))
        alloc.place_frame([], 2)
        self.assertEqual(alloc.prefetch(b"next", 2, 4, forced_slot=tail+1), (tail+1, True))

    def test_display_reservations_cover_cram_scroll_and_fragmentation(self):
        for scroll, vertical, cram in ((False, False, False), (True, False, True),
                                       (True, True, False)):
            with self.subTest(scroll=scroll, vertical=vertical, cram=cram):
                display = dict(scroll_build=scroll, vertical=vertical, cram=cram)
                limit = final_vblank.pattern_limit(40, 28, **display)
                # Dic singleton descriptors remain fragmented even when their
                # destinations are adjacent; WordBuf wrapping cannot cost more.
                runs = [(av_config.FINAL_VBLANK_SLOT+i, 1, 2, i*2) for i in range(limit)]
                self.assertLessEqual(final_vblank.verify_runs(runs, 40, 28, **display), 3200)
                with self.assertRaises(ValueError):
                    final_vblank.verify_runs(runs + [(av_config.FINAL_VBLANK_SLOT+limit, 1, 2, 99)],
                                             40, 28, **display)
        alloc = TileAllocator(1120, av_config.VRAM_PATTERN_POOL_TILES)
        alloc.final_pattern_limit = 0
        self.assertEqual(FrameTransitionGuard(alloc).capacity, av_config.FINAL_VBLANK_SLOT)


if __name__ == "__main__":
    unittest.main()
