#!/usr/bin/env python3
"""Focused tests for the refillable WordBuf ring planner."""

import unittest

import numpy as np

import pattern_supply
import wordbuf_ring


class WordBufRingTest(unittest.TestCase):
    @staticmethod
    def _replay(**overrides):
        values = {
            "prg_loads": [0, 64, 320, 256, 256, 320],
            "wr0_loads": [64, 0, 0, 0, 64, 0],
            "wr1_loads": [0, 64, 0, 0, 0, 64],
            "block_lengths": [0, 0, 0, 0, 0, 0],
            "payload_sectors": [0, 5, 5, 5, 5, 5],
            "control_sectors": [0, 0, 0, 0, 0, 0],
            "word_stage_sectors": [0, 0, 1, 1, 0, 0],
            "fps": 15.0,
            "prebuffer_patterns": 64,
            "prg_capacity_patterns": 640,
            "word_capacities": (64, 64),
            "boot_patterns": (64, 64),
            "f0_cold": 0,
        }
        values.update(overrides)
        return wordbuf_ring.replay_frozen_schedule(**values)

    def test_transfer_run_counter_keeps_prefetch_boundary(self):
        entries = [1, 2]
        colds = [True, True]
        sources = [pattern_supply.SOURCE_WR] * 2
        self.assertEqual(
            wordbuf_ring._transfer_runs(
                entries,
                colds,
                sources,
                [(2, True, b"x")],
                [-1, -1],
                [0, 1],
            ),
            2,
        )

    def test_remaining_source_is_parity_specific(self):
        items = [
            wordbuf_ring.Item(2, 0, 10, (0,)),
            wordbuf_ring.Item(3, 1, 20, (0,)),
        ]
        state = wordbuf_ring._State(
            sources=np.asarray([
                pattern_supply.SOURCE_WR,
                pattern_supply.SOURCE_WR,
            ], np.int8),
            delivered=np.asarray([4, 5], np.int64),
            prg_occupancy=0,
            word_occupancy=[4, 5],
            prg_remaining=0,
            word_remaining=[6, 15],
            prg_cursor=0,
            word_cursor=[0, 0],
        )
        self.assertEqual(
            wordbuf_ring._remaining_source(
                items, state, pattern_supply.SOURCE_WR, 0),
            6,
        )
        self.assertEqual(
            wordbuf_ring._remaining_source(
                items, state, pattern_supply.SOURCE_WR, 1),
            15,
        )

    def test_word_sector_uses_only_runs_completed_in_that_sector(self):
        items = [
            wordbuf_ring.Item(10, 0, 51, (0,)),
            wordbuf_ring.Item(12, 0, 18, (0,)),
        ]
        state = wordbuf_ring._State(
            sources=np.full(2, wordbuf_ring.UNKNOWN, np.int8),
            delivered=np.zeros(2, np.int64),
            prg_occupancy=0,
            word_occupancy=[0, 0],
            prg_remaining=0,
            word_remaining=[0, 0],
            prg_cursor=0,
            word_cursor=[0, 0],
        )
        transaction = wordbuf_ring._Transaction(state)
        delivered = wordbuf_ring._deliver_word(
            2,
            0,
            items,
            [[0, 1], []],
            [0, 0],
            state,
            64,
            64,
            transaction,
            np.full(16, 64, np.int64),
            12,
        )
        self.assertEqual(delivered, 0)
        transaction.rollback()
        np.testing.assert_array_equal(
            state.sources,
            [wordbuf_ring.UNKNOWN, wordbuf_ring.UNKNOWN],
        )
        np.testing.assert_array_equal(state.delivered, [0, 0])
        self.assertEqual(state.word_occupancy, [0, 0])

    def test_word_sector_combines_complete_runs_exactly(self):
        items = [
            wordbuf_ring.Item(10, 0, 40, (0,)),
            wordbuf_ring.Item(12, 0, 24, (0,)),
        ]
        state = wordbuf_ring._State(
            sources=np.full(2, wordbuf_ring.UNKNOWN, np.int8),
            delivered=np.zeros(2, np.int64),
            prg_occupancy=0,
            word_occupancy=[0, 0],
            prg_remaining=0,
            word_remaining=[0, 0],
            prg_cursor=0,
            word_cursor=[0, 0],
        )
        transaction = wordbuf_ring._Transaction(state)
        delivered = wordbuf_ring._deliver_word(
            2,
            0,
            items,
            [[0, 1], []],
            [0, 0],
            state,
            64,
            64,
            transaction,
            np.full(16, 64, np.int64),
            12,
        )
        self.assertEqual(delivered, 64)
        np.testing.assert_array_equal(
            state.sources,
            [pattern_supply.SOURCE_WR, pattern_supply.SOURCE_WR],
        )
        np.testing.assert_array_equal(state.delivered, [40, 24])
        self.assertEqual(state.word_occupancy, [64, 0])
        self.assertEqual(state.word_remaining, [0, 0])

    def test_boot_starts_at_legacy_prg_pressure_not_movie_start(self):
        items = [
            wordbuf_ring.Item(2, 0, 32, (0,)),
            wordbuf_ring.Item(4, 0, 32, (0,)),
            wordbuf_ring.Item(10, 0, 40, (0,)),
            wordbuf_ring.Item(12, 0, 24, (0,)),
        ]
        state = wordbuf_ring._State(
            sources=np.full(4, wordbuf_ring.UNKNOWN, np.int8),
            delivered=np.zeros(4, np.int64),
            prg_occupancy=0,
            word_occupancy=[0, 0],
            prg_remaining=0,
            word_remaining=[0, 0],
            prg_cursor=0,
            word_cursor=[0, 0],
        )
        loaded, end_frames = wordbuf_ring._assign_boot(
            items,
            [[0, 1, 2, 3], []],
            [0, 0, 20, 10],
            state,
            (64, 64),
            np.full(16, 64, np.int64),
        )
        self.assertEqual(loaded, (64, 0))
        self.assertEqual(end_frames, (12, 0))
        np.testing.assert_array_equal(
            state.sources,
            [
                pattern_supply.SOURCE_PRG,
                pattern_supply.SOURCE_PRG,
                pattern_supply.SOURCE_WR,
                pattern_supply.SOURCE_WR,
            ],
        )

    def test_word_sector_targets_next_prg_pressure(self):
        items = [
            wordbuf_ring.Item(4, 0, 32, (0,)),
            wordbuf_ring.Item(6, 0, 32, (0,)),
            wordbuf_ring.Item(10, 0, 32, (0,)),
            wordbuf_ring.Item(10, 0, 32, (0,)),
        ]
        state = wordbuf_ring._State(
            sources=np.full(4, wordbuf_ring.UNKNOWN, np.int8),
            delivered=np.zeros(4, np.int64),
            prg_occupancy=0,
            word_occupancy=[0, 0],
            prg_remaining=0,
            word_remaining=[0, 0],
            prg_cursor=0,
            word_cursor=[0, 0],
        )
        transaction = wordbuf_ring._Transaction(state)
        delivered = wordbuf_ring._deliver_word(
            2,
            0,
            items,
            [[0, 1, 2, 3], []],
            [0, 0, 1, 1],
            state,
            64,
            64,
            transaction,
            np.full(16, 64, np.int64),
            10,
        )
        self.assertEqual(delivered, 64)
        np.testing.assert_array_equal(
            state.sources,
            [
                pattern_supply.SOURCE_PRG,
                pattern_supply.SOURCE_PRG,
                pattern_supply.SOURCE_WR,
                pattern_supply.SOURCE_WR,
            ],
        )

    def test_immediate_batch_can_complete_a_run_across_sectors(self):
        items = [
            wordbuf_ring.Item(10, 0, 90, (0,)),
            wordbuf_ring.Item(12, 0, 38, (0,)),
        ]
        state = wordbuf_ring._State(
            sources=np.full(2, wordbuf_ring.UNKNOWN, np.int8),
            delivered=np.zeros(2, np.int64),
            prg_occupancy=0,
            word_occupancy=[0, 0],
            prg_remaining=0,
            word_remaining=[0, 0],
            prg_cursor=0,
            word_cursor=[0, 0],
        )
        transaction = wordbuf_ring._Transaction(state)
        delivered = wordbuf_ring._deliver_word(
            2,
            0,
            items,
            [[0, 1], []],
            [1, 1],
            state,
            128,
            128,
            transaction,
            np.full(16, 64, np.int64),
            12,
        )
        self.assertEqual(delivered, 128)
        np.testing.assert_array_equal(
            state.sources,
            [pattern_supply.SOURCE_WR, pattern_supply.SOURCE_WR],
        )
        np.testing.assert_array_equal(state.delivered, [90, 38])
        self.assertEqual(state.word_occupancy, [128, 0])

    def test_prg_forecast_finds_future_deadline_not_average_supply(self):
        items = [
            wordbuf_ring.Item(1, 1, 10, (0,)),
            wordbuf_ring.Item(3, 1, 100, (0,)),
        ]
        state = wordbuf_ring._State(
            sources=np.asarray(
                [pattern_supply.SOURCE_PRG, wordbuf_ring.UNKNOWN],
                np.int8,
            ),
            delivered=np.asarray([10, 0], np.int64),
            prg_occupancy=70,
            word_occupancy=[0, 0],
            prg_remaining=0,
            word_remaining=[0, 0],
            prg_cursor=1,
            word_cursor=[0, 0],
        )
        target = wordbuf_ring._next_prg_pressure_frame(
            frame=1,
            items=items,
            frame_items=[[], [0], [], [1]],
            state=state,
            payload_capacity=np.zeros(4, np.int64),
            prg_capacity=128,
        )
        self.assertEqual(target, 3)

    def test_replay_proves_two_independent_parity_turns(self):
        schedule = self._replay()
        np.testing.assert_array_equal(
            schedule["word_occupancy"],
            [
                [0, 64],
                [0, 0],
                [64, 0],
                [64, 64],
                [0, 64],
                [0, 0],
            ],
        )
        self.assertEqual(schedule["rate_lead_peak"], 0)
        self.assertEqual(schedule["under"], 0)

    def test_replay_rejects_word_refill_after_its_deadline(self):
        with self.assertRaisesRegex(
                ValueError, "frame 4: WordBuf0 deadline is short"):
            self._replay(
                word_stage_sectors=[0, 0, 0, 1, 1, 0],
            )

    def test_replay_rejects_word_refill_count_not_in_route(self):
        with self.assertRaisesRegex(
                ValueError, "refill counts differ from routed sectors"):
            self._replay(
                word_stage_sectors=[0, 0, 1, 0, 0, 0],
            )

    def test_replay_rejects_six_useful_sectors_at_15_fps(self):
        with self.assertRaisesRegex(
                ValueError, "exceeds the physical slot"):
            self._replay(
                payload_sectors=[0, 6, 5, 5, 5, 5],
            )


if __name__ == "__main__":
    unittest.main()
