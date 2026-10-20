"""Pack real palette tables and check format boundaries."""

import contextlib
import io
import struct
import tempfile
import unittest
from pathlib import Path

from harness.palette_capacity.build_fixture import (
    ROOT, find_tool, fixture_log, pack_fixture, run,
)


class PackedFixtureTestCase(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.temporary.cleanup)
        cls.directory = Path(cls.temporary.name)
        obj = cls.directory / "extension.o"
        binary = obj.with_suffix(".bin")
        run([str(find_tool("m68k-elf-as")), "-m68000",
             "--register-prefix-optional", "--bitwise-or",
             "-I", str(ROOT / "boot"), str(ROOT / "boot/movieplay_sp_ext.s"),
             "-o", str(obj)])
        run([str(find_tool("m68k-elf-ld")), "-nostdlib", "--oformat", "binary",
             "-T", str(ROOT / "cfg/sp_ext.ld"), "-o", str(binary), str(obj)])
        cls.extension = binary.read_bytes()

    def pack(self, name, segments, fps=30):
        directory = self.directory / name
        with contextlib.redirect_stdout(io.StringIO()):
            pack_fixture(directory, fixture_log(segments, fps), self.extension)
        return directory


class PaletteCapacityTests(PackedFixtureTestCase):

    def test_17_and_64_segments_pack_with_the_last_switch_before_the_sentinel(self):
        for fps in (15, 30):
            for segments in (17, 64):
                with self.subTest(fps=fps, segments=segments):
                    directory = self.pack(f"n{segments}-f{fps}", segments, fps)
                    index = (directory / "palidx.bin").read_bytes()
                    self.assertEqual(len(index), 256)
                    self.assertEqual(struct.unpack_from(">HH", index, (segments - 2) * 4),
                                     ((segments - 1) * 4, segments - 1))
                    self.assertEqual(struct.unpack_from(">HH", index, (segments - 1) * 4),
                                     (0xFFFF, 0))

    def test_packer_rejects_65_segment_log(self):
        with self.assertRaisesRegex(SystemExit, "palette segments 65 > PALTAB capacity 64"):
            self.pack("n65", 65)


if __name__ == "__main__":
    unittest.main()
