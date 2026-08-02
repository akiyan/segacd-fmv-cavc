#!/usr/bin/env python3
"""Focused control-block checks for automatic CRAM fade frames."""

import struct
import tempfile
import unittest
import wave
from pathlib import Path

import numpy as np

import pack_stream
import shadow_updates
import stream_schedule


class PackFadeTests(unittest.TestCase):
    def setUp(self):
        self.old_cells = pack_stream.C_CELLS
        self.old_rate = pack_stream.AUDIO_RATE
        self.old_pcm = pack_stream.AUDIO_PCM
        self.old_control = pack_stream.AUDIO_CONTROL
        pack_stream.C_CELLS = 1
        pack_stream.AUDIO_RATE = 22_050
        pack_stream.AUDIO_PCM = 736
        pack_stream.AUDIO_CONTROL = 372

        self.palette = np.arange(4 * 15 * 3, dtype=np.uint8).reshape(
            4, 15, 3) % 8
        self.fade_palette = (self.palette // 2).astype(np.uint8)

    def tearDown(self):
        pack_stream.C_CELLS = self.old_cells
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

    def fade_log(self):
        return {
            "seg_pals": [self.palette],
            "segment_entry_cram": np.asarray([self.palette]),
            "fade": {
                "schema_version": 1,
                "frame_types": np.asarray(
                    [shadow_updates.FRAME_NORMAL,
                     shadow_updates.FRAME_FADE_IN], np.uint8),
                "frame_cram": np.asarray([
                    np.zeros_like(self.fade_palette), self.fade_palette]),
            },
        }

    def test_inline_cram_round_trip(self):
        packed = pack_stream.pals_to_bytes_128(self.fade_palette)
        np.testing.assert_array_equal(
            pack_stream.bytes_128_to_pals(packed), self.fade_palette)

    def test_fade_control_replaces_bitmap_with_inline_cram(self):
        with tempfile.TemporaryDirectory() as tmp:
            blocks, _pcm = pack_stream.build_control(
                self.fade_log(),
                [([], [], []), ([], [], [])],
                np.asarray([0, 0]),
                self.audio_path(tmp),
            )
        block = blocks[1]
        raw_count = struct.unpack_from(">H", block, 4)[0]
        self.assertEqual(shadow_updates.decode_count(raw_count), (0, False))
        self.assertEqual(
            shadow_updates.decode_frame_type(raw_count),
            shadow_updates.FRAME_FADE_IN,
        )
        self.assertEqual(
            block[6:6 + shadow_updates.INLINE_CRAM_BYTES],
            pack_stream.pals_to_bytes_128(self.fade_palette),
        )
        self.assertEqual(
            pack_stream.control_audio_bounds(block),
            (6 + shadow_updates.INLINE_CRAM_BYTES,
             6 + shadow_updates.INLINE_CRAM_BYTES + pack_stream.AUDIO_CONTROL),
        )
        expected = stream_schedule.control_block_lengths(
            [0], [0], cells=1,
            audio_frame_bytes=pack_stream.AUDIO_CONTROL,
            frame_types=[shadow_updates.FRAME_FADE_IN],
        )
        self.assertEqual(len(block), int(expected[0]))

    def test_fade_control_rejects_name_updates(self):
        key = bytes([1] * 64)
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaisesRegex(ValueError, "fade frames cannot carry"):
                pack_stream.build_control(
                    self.fade_log(),
                    [([], [], []), ([0], [1], [False])],
                    np.asarray([0, 1]),
                    self.audio_path(tmp),
                )


if __name__ == "__main__":
    unittest.main()
