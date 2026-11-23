"""Independent BLSTEL v2 wire fixtures for the CAVC VDP reader."""

from pathlib import Path
import struct
import tempfile
import unittest
import zlib

from event_stream import Event, iter_events, iter_publications


def file_bytes(events):
    return b"BLSTEL\x02\x00\x01\x00\x04TEST" + zlib.compress(events)


def absolute_write(address, value):
    # Format 3: 16-bit delta 0, uncompressed VRAM byte payload.
    return b"\xe5\x00\x00" + struct.pack(">HB", address ^ 1, value)


class EventStreamTest(unittest.TestCase):
    def test_delta_repeat_auto_and_unwrapped_cycles(self):
        wire = bytes.fromhex(
            "40 01 04 "            # mode 5, +16 clocks
            "e4 00 01 0f 02 "      # autoincrement 2, +1
            "e5 00 05 00 01 aa "   # bus 0001 -> physical 0000, +5
            "d0 80 bb cc "         # two autoincrement writes, +16 per write
            "e1 00 01 00 00 00 20 "# cycle adjustment, +1
            "fb ff ff fe 02 0e ee "# signed -2, CRAM byte offset 2
            "eb 00 10 81 12 34 "   # VSRAM word index 1, +16
            "e0 12 34")            # scanout, +4660
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "vdp.blastel"
            path.write_bytes(file_bytes(wire))
            events = list(iter_events(path))
        self.assertEqual(events, [
            Event("REGISTER", 16, 1, b"\x04"),
            Event("REGISTER", 17, 15, b"\x02"),
            Event("VRAM", 22, 0, b"\xaa"),
            Event("VRAM", 38, 2, b"\xbb"),
            Event("VRAM", 54, 4, b"\xcc"),
            Event("CRAM", 53, 2, b"\x0e\xee"),
            Event("VSRAM", 69, 2, b"\x12\x34"),
            Event("FRAME", 4729, 0, b""),
        ])

    def test_hud_publication_uses_scanout_state_after_cram(self):
        wire = bytearray.fromhex("40 01 04 e0 00 00")
        marker = bytes.fromhex("4d50525400000000000000000001454e")
        for address in range(0, len(marker), 2):
            wire.extend(absolute_write(address + 1, marker[address + 1]))
            wire.extend(absolute_write(address, marker[address]))
        words = struct.pack(">40H", 1744, 1744, 1744, 1747, *([1744] * 36))
        for address in range(0, len(words), 2):
            wire.extend(absolute_write(0xF000 + address + 1, words[address + 1]))
            wire.extend(absolute_write(0xF000 + address, words[address]))
        wire.extend(bytes.fromhex("eb 00 01 02 0e ee e0 00 01 e0 00 01"))
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "vdp.blastel"
            path.write_bytes(file_bytes(wire))
            [picture] = iter_publications(path)
        self.assertEqual((picture.capture_index, picture.frame), (1, 3))
        self.assertEqual(picture.cram[2:4], b"\x0e\xee")
        self.assertEqual(picture.dispatcher, (0, 0, 1))

    def test_truncated_stream_does_not_pass_after_complete_event(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "vdp.blastel"
            path.write_bytes(file_bytes(b"\xe0\x00\x01")[:-2])
            with self.assertRaisesRegex(ValueError, "incomplete BLSTEL"):
                list(iter_events(path))
