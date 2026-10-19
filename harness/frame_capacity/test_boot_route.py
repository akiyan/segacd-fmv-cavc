"""Prove sector-wise bank mirroring before changing the boot assembly."""

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import cavc_routing


def mirror_route(route, bank_bytes=0x20000):
    """Load into bank 0, then mirror through one Sub-owned 2 KiB sector."""
    offset = bank_bytes - len(route)
    banks = [bytearray(b"\xa5" * bank_bytes), bytearray(b"\x5a" * bank_bytes)]
    banks[0][offset:] = route
    owned = 0
    for start in range(offset, bank_bytes, 2048):
        scratch = bytes(banks[owned][start:start + 2048])
        owned ^= 1
        banks[owned][start:start + 2048] = scratch
        owned ^= 1
    assert owned == 0
    return banks


class BootRouteTests(unittest.TestCase):
    def test_every_route_entry_and_other_bank_bytes_survive(self):
        entries = [cavc_routing.encode_route(total - ctrl, ctrl, word)
                   for total in range(6) for ctrl in range(min(total, 3) + 1)
                   for word in range(min(total - ctrl, 4) + 1)]
        for frames in (16384, 16385, 32767, 32768, 32769, 65534, 65535, 65536, 65537, 83520):
            with self.subTest(frames=frames):
                route = bytes([0] + [entries[i % len(entries)] for i in range(1, frames)])
                route = route.ljust((frames + 2047) // 2048 * 2048, b"\0")
                banks = mirror_route(route)
                offset = 0x20000 - len(route)
                for bank, fill in zip(banks, (0xa5, 0x5a)):
                    self.assertEqual(bank[:offset], bytes([fill]) * offset)
                    self.assertEqual(bank[offset:], route)
                    for frame in range(frames):
                        # A complete long index addresses every route, including
                        # the signed-word and low-word wrap boundaries.
                        self.assertEqual(bank[offset + frame], route[frame])

    def test_existing_packed_routes_are_identical_in_both_banks(self):
        checked = 0
        for path in sorted((ROOT / "out").glob("*/HEADER.DAT")):
            import player_constants
            try:
                data = path.read_bytes()
                pc = player_constants.parse_header_sector(data[:2048])
            except ValueError:
                continue  # Archives with another layout are not current streams.
            start = len(data) - (pc.prebuf_sec + pc.routing_sec) * 2048
            route = data[start:start + pc.routing_sec * 2048]
            cavc_routing.validate_route_table(route, pc.frames, pc.routing_sec)
            for bank in mirror_route(route):
                self.assertEqual(bank[-len(route):], route)
            checked += 1
        self.assertGreater(checked, 0)


if __name__ == "__main__":
    unittest.main()
