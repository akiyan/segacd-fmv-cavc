import tempfile
import unittest
from pathlib import Path

import av_config
import sp_extension


class SpExtensionTests(unittest.TestCase):
    def test_metadata_round_trip_binds_size_hash_and_addresses(self) -> None:
        binary = bytes(range(64))
        values = sp_extension.metadata(binary)
        self.assertEqual(values.load_base, 0x7D260)
        self.assertEqual(values.exec_base, 0x76800)
        self.assertEqual(values.size, 64)
        self.assertEqual(values.longs, 16)
        self.assertEqual(
            sp_extension.parse_include(
                sp_extension.render_include(values)),
            values,
        )

    def test_generate_writes_a_stable_include(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            root = Path(td)
            binary = root / "extension.bin"
            output = root / "sp_extension.inc"
            binary.write_bytes(b"\x12\x34\x56\x78" * 3)
            expected = sp_extension.generate(binary, output)
            first = output.read_bytes()
            self.assertEqual(sp_extension.generate(binary, output), expected)
            self.assertEqual(output.read_bytes(), first)

    def test_rejects_unaligned_or_oversized_binary(self) -> None:
        with self.assertRaisesRegex(ValueError, "multiple of four"):
            sp_extension.metadata(b"\0")
        with self.assertRaisesRegex(ValueError, "exceeds"):
            sp_extension.metadata(
                bytes(av_config.SUB_BOOT_EXTENSION_MAX_BYTES + 4))

    def test_adpcm_preload_uses_existing_five_sector_padding(self) -> None:
        table = b"T" * 8800
        binary = b"\x12\x34\x56\x78" * 23
        image = sp_extension.adpcm_preload_image(table, binary)
        self.assertEqual(len(image), 5 * 2048)
        self.assertEqual(image[:8800], table)
        self.assertEqual(image[8800:8800 + len(binary)], binary)
        self.assertEqual(
            image[8800 + len(binary):],
            b"\0" * (5 * 2048 - 8800 - len(binary)),
        )

    def test_adpcm_preload_rejects_padding_overflow(self) -> None:
        with self.assertRaisesRegex(ValueError, "padding"):
            sp_extension.adpcm_preload_image(
                b"T" * 9000,
                b"\x12\x34\x56\x78" * 350,
            )


if __name__ == "__main__":
    unittest.main()
