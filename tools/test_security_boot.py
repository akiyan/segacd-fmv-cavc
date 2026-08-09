#!/usr/bin/env python3
"""Tests for the post-validation single-video boot image."""

from __future__ import annotations

import unittest
from pathlib import Path

import security_boot


ROOT = Path(__file__).resolve().parents[1]


class SecurityBootTests(unittest.TestCase):
    def security(self, region: str) -> bytes:
        return (ROOT / "boot" / f"sec_{region}.bin").read_bytes()

    def inputs(self, region: str) -> tuple[bytes, bytes, bytes]:
        security = self.security(region)
        ip = security + bytes.fromhex("60 00 00 02 4e 75")
        boot = bytearray(security_boot.IP_SLOT_BYTES)
        boot[security_boot.IP_DISC_OFFSET:
             security_boot.IP_DISC_OFFSET + len(ip)] = ip
        boot[0x6000:0x6008] = b"SUBIMAGE"
        return bytes(boot), ip, security

    def test_jp_replaces_only_the_display_call(self) -> None:
        boot, ip, security = self.inputs("jp")
        alternate = security_boot.alternate_slot(boot, ip, security, "jp")
        self.assertEqual(alternate[0x26:0x2A], security_boot.NOP_PAIR)
        differences = [
            index for index, (original, patched) in
            enumerate(zip(ip, alternate)) if original != patched
        ]
        self.assertEqual(differences, [0x27, 0x28, 0x29])
        self.assertEqual(len(alternate), security_boot.IP_SLOT_BYTES)

    def test_us_replaces_only_the_display_call(self) -> None:
        boot, ip, security = self.inputs("us")
        alternate = security_boot.alternate_slot(boot, ip, security, "us")
        self.assertEqual(alternate[0x04:0x08], security_boot.NOP_PAIR)
        differences = [
            index for index, (original, patched) in
            enumerate(zip(ip, alternate)) if original != patched
        ]
        self.assertEqual(differences, [0x05, 0x06, 0x07])

    def test_eu_keeps_its_diagnostic_buildable(self) -> None:
        boot, ip, security = self.inputs("eu")
        alternate = security_boot.alternate_slot(boot, ip, security, "eu")
        self.assertEqual(alternate[0x04:0x08], security_boot.NOP_PAIR)

    def test_wrap_file_places_the_alternate_ip_at_0x40200(self) -> None:
        boot, ip, security = self.inputs("us")
        staged = security_boot.wrap_file(boot, ip, security, "us")
        self.assertEqual(len(staged), security_boot.ALT_FILE_BYTES)
        offset = security_boot.ALT_IP_FILE_OFFSET
        self.assertEqual(
            staged[offset:offset + security_boot.IP_SLOT_BYTES],
            security_boot.alternate_slot(boot, ip, security, "us"),
        )
        self.assertEqual(
            security_boot.ALT_FILE_LBA * security_boot.SECTOR_BYTES + offset,
            security_boot.ALT_IP_DISC_OFFSET,
        )
        self.assertEqual(
            staged[offset + 0x5E00:offset + 0x5E08], b"SUBIMAGE")

    def test_rejects_an_ip_with_the_wrong_region_security_code(self) -> None:
        us_boot, us_ip, _ = self.inputs("us")
        with self.assertRaisesRegex(ValueError, "does not start"):
            security_boot.alternate_slot(
                us_boot, us_ip, self.security("jp"), "jp")


if __name__ == "__main__":
    unittest.main()
