"""Prove the 17-bit count contract without processing real movie footage."""

import struct
import sys
import unittest
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import cavc_routing as routing
import pattern_supply
import player_constants
from tools.test_player_constants import make_header
from upgrade_planner import DemandPrediction


class ExtendedFrameTests(unittest.TestCase):
    def test_header_size_offsets_and_full_aperture_at_every_boundary(self):
        for frames in (65534, 65535, 65536, 65537, 81920, 83520):
            with self.subTest(frames=frames):
                header = make_header(frames=frames, features=(
                    routing.FEATURE_COLD_RUNS | routing.FEATURE_VBLANK_CADENCE
                    | routing.FEATURE_PATTERN_SUPPLY
                    | routing.FEATURE_DICBUF_INDEXED_RUNS))
                parsed = player_constants.parse_header_sector(header)
                self.assertEqual(parsed.frames, frames)
                self.assertEqual(routing.frame_count_from_header(header), frames)
                self.assertEqual((parsed.tcols, parsed.trows), (40, 28))
                self.assertEqual(player_constants.FIXED_HEADER_BYTES, 62)
                self.assertEqual(len(header), 2048)
                self.assertEqual(struct.unpack_from(">H", header, 4)[0], frames & 65535)
                self.assertEqual(header[37], frames >> 16)

    def test_full_frame0_and_both_fixed_tails_fit_at_maximum(self):
        layout = pattern_supply.word_ram_layout(83520, 1120, 210)
        self.assertEqual(layout.routing_bytes, 82 * 1024)
        self.assertEqual(layout.wr0_offset, 35872)
        self.assertEqual(layout.status_offset - layout.wr0_offset, 736)
        self.assertEqual((layout.wr0_patterns, layout.wr1_patterns), (0, 0))
        self.assertEqual(layout.wr0_end, layout.wr0_offset)
        self.assertEqual(layout.wr1_end, layout.wr1_offset)
        for frames in (65536, 65537, 81920, 83520):
            layout = pattern_supply.word_ram_layout(frames, 1120, 210)
            self.assertEqual((layout.wr0_patterns, layout.wr1_patterns), (0, 0))
        short = pattern_supply.word_ram_layout(65535, 1120, 210)
        self.assertGreater(short.wr0_patterns, 0)
        self.assertGreater(short.wr1_patterns, 0)

    def test_palette_bit16_and_ffff_switch_are_distinct_from_terminator(self):
        for frame in (1, 32768, 65534, 65535, 65536, 65537, 83519):
            for segment in range(1, 64):
                words = routing.palette_switch_words(frame, segment)
                self.assertEqual(routing.palette_switch_value(*words), (frame, segment))
                self.assertEqual(len(struct.pack(">HH", *words)), 4)
                if frame < 65536:
                    self.assertEqual(words, (frame, segment))
        self.assertEqual(routing.palette_switch_value(65535, 0), (0xFFFFFFFF, 0))

    def test_long_route_keeps_one_byte_per_frame_and_rejects_wordbuf(self):
        frames = routing.MAX_FRAMES
        sectors = routing.routing_sector_count(frames)
        self.assertEqual(sectors, 41)
        table = bytearray(sectors * 2048)
        for frame in range(1, frames):
            table[frame] = routing.encode_route(frame % 3, 1)
        routing.validate_route_table(table, frames, sectors)
        for frame in (65535, 65536, 83519):
            old = table[frame]
            table[frame] = routing.encode_route(1, 1, 1)
            with self.assertRaisesRegex(ValueError, "WordBuf"):
                routing.validate_route_table(table, frames, sectors)
            table[frame] = old
        with self.assertRaises(ValueError):
            routing.routing_sector_count(83521)

    def test_quality_planning_cannot_spend_wordbuf_credit_in_long_movies(self):
        for frames in (65535, 65536, 83520):
            prediction = DemandPrediction(
                exact_bytes=np.full(frames, 32, np.int64),
                protected_bytes=np.zeros(frames, np.int64),
                exact_cold=np.ones(frames, np.int64),
                protected_cold=np.zeros(frames, np.int64))
            plan = pattern_supply.plan_frame_budgets(
                prediction, wr0_patterns=100, wr1_patterns=100, dic_patterns=0)
            self.assertEqual(int(plan.wr.sum()), 200 if frames <= 65535 else 0)


if __name__ == "__main__":
    unittest.main()
