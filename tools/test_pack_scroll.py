#!/usr/bin/env python3
"""Focused control-block checks for automatic rolling-plane scroll frames."""

from __future__ import annotations

import struct
import tempfile
import unittest
import wave
from pathlib import Path

import numpy as np

import pack_stream
import shadow_updates
import stream_schedule
import cavc_routing


class PackScrollTests(unittest.TestCase):
    def setUp(self):
        self.old_cells = pack_stream.C_CELLS
        self.old_columns = pack_stream.TCOLS
        self.old_rows = pack_stream.TROWS
        self.old_rate = pack_stream.AUDIO_RATE
        self.old_pcm = pack_stream.AUDIO_PCM
        self.old_control = pack_stream.AUDIO_CONTROL
        pack_stream.C_CELLS = 1
        pack_stream.TCOLS = 1
        pack_stream.TROWS = 1
        pack_stream.AUDIO_RATE = 22_050
        pack_stream.AUDIO_PCM = 736
        pack_stream.AUDIO_CONTROL = 372
        self.palette = np.zeros((4, 15, 3), np.uint8)

    def tearDown(self):
        pack_stream.C_CELLS = self.old_cells
        pack_stream.TCOLS = self.old_columns
        pack_stream.TROWS = self.old_rows
        pack_stream.AUDIO_RATE = self.old_rate
        pack_stream.AUDIO_PCM = self.old_pcm
        pack_stream.AUDIO_CONTROL = self.old_control

    def audio_path(self, directory):
        path = Path(directory) / "audio.wav"
        with wave.open(str(path), "wb") as wav:
            wav.setnchannels(1)
            wav.setsampwidth(2)
            wav.setframerate(pack_stream.AUDIO_RATE)
            wav.writeframes(np.zeros(
                pack_stream.AUDIO_PCM * 2, dtype="<i2").tobytes())
        return path

    def scroll_log(self):
        return {
            "seg_pals": [self.palette],
            "segment_entry_cram": np.asarray([self.palette]),
            "scroll": {
                "schema_version": 1,
                "active": np.asarray([False, True]),
                "positions": np.asarray([[0, 0], [-5, 0]], np.int16),
            },
        }

    def test_scroll_control_round_trip_layout(self):
        with tempfile.TemporaryDirectory() as tmp:
            blocks, _pcm = pack_stream.build_control(
                self.scroll_log(),
                [([], [], []), ([0, 2047], [1, 2], [False, False])],
                np.asarray([0, 2]),
                self.audio_path(tmp),
                update_lists=np.asarray([False, True]),
            )
        block = blocks[1]
        raw_count = struct.unpack_from(">H", block, 4)[0]
        self.assertEqual(shadow_updates.decode_count(raw_count), (2, True))
        self.assertEqual(raw_count & shadow_updates.COUNT_MASK, 3)
        self.assertEqual(
            shadow_updates.decode_frame_type(raw_count),
            shadow_updates.FRAME_SCROLL,
        )
        self.assertEqual(struct.unpack_from(">hh", block, 6), (-5, 0))
        self.assertEqual(
            struct.unpack_from(">4H", block, 10),
            (0, 1, 4094, 2),
        )
        self.assertEqual(
            pack_stream.control_audio_bounds(block),
            (18, 18 + pack_stream.AUDIO_CONTROL),
        )
        expected = stream_schedule.control_block_lengths(
            [2], [0], cells=1,
            audio_frame_bytes=pack_stream.AUDIO_CONTROL,
            update_lists=[True],
            frame_types=[shadow_updates.FRAME_SCROLL],
        )
        self.assertEqual(len(block), int(expected[0]))

    def test_scroll_metadata_rejects_vertical_or_diagonal_motion(self):
        log = self.scroll_log()
        log["scroll"]["positions"][1] = (-5, 3)
        with self.assertRaisesRegex(SystemExit, "horizontal-only"):
            pack_stream.control_arrays(log, 2)

    def test_horizontal_controls_select_scroll_feature(self):
        horizontal = self.scroll_log()
        self.assertEqual(
            pack_stream.scroll_feature_bits(horizontal, 2),
            cavc_routing.FEATURE_SCROLL,
        )

    def test_vertical_controls_are_rejected(self):
        vertical = self.scroll_log()
        vertical["scroll"]["positions"][1] = (0, -5)
        with self.assertRaisesRegex(SystemExit, "horizontal-only"):
            pack_stream.scroll_feature_bits(vertical, 2)

    def test_scroll_requires_completed_update_list(self):
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "require"):
                pack_stream.build_control(
                    self.scroll_log(),
                    [([], [], []), ([0], [1], [False])],
                    np.asarray([0, 1]),
                    self.audio_path(tmp),
                    update_lists=np.asarray([False, False]),
                )

    def test_resolve_rebases_the_final_viewport_without_reloading_patterns(self):
        pack_stream.TCOLS = 2
        pack_stream.TROWS = 1
        pack_stream.C_CELLS = 2
        key_a = bytes([1] * 64)
        key_b = bytes([2] * 64)
        key_c = bytes([3] * 64)
        log = {
            "frames": [
                [(0, 0, key_a), (1, 0, key_b)],
                [(2, 0, key_c)],
                [],
            ],
            "frame_seg": np.zeros(3, np.int16),
            "scroll": {
                "schema_version": 1,
                "active": np.asarray([False, True, False]),
                "positions": np.asarray(
                    [[0, 0], [-8, 0], [0, 0]], np.int16),
            },
        }

        per, _prefetch, _orders, loads, updates, _pal, _patterns, tearing = (
            pack_stream.resolve(log, POOL=8)
        )

        self.assertEqual(per[1][0], [2])
        self.assertEqual(loads.tolist(), [2, 1, 0])
        self.assertEqual(updates.tolist(), [2, 1, 0])
        self.assertEqual(tearing, 0)

    def test_resolve_rejects_screen_space_prefetch_during_scroll(self):
        key = bytes([1] * 64)
        log = {
            "frames": [[(0, 0, key)], []],
            "frame_seg": np.zeros(2, np.int16),
            "scroll": {
                "schema_version": 1,
                "active": np.asarray([False, True]),
                "positions": np.asarray(
                    [[0, 0], [-5, 0]], np.int16),
            },
            "raw_prefetch": {
                "schema_version": 6,
                "enabled": True,
                "requests": [[], [(key, 1, 1, False, False, False)]],
                "cold": np.asarray([0, 1], np.uint16),
            },
        }

        with self.assertRaisesRegex(SystemExit, "screen-space raw prefetch"):
            pack_stream.resolve(log, POOL=4)


if __name__ == "__main__":
    unittest.main()
