#!/usr/bin/env python3
"""Tests for the multi-video manifest and generated tables."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import sys
sys.path.insert(0, str(Path(__file__).resolve().parent))

from gen_menu_font import generate as generate_font
from multimovie import (
    BuiltVideo,
    MenuVideo,
    load_manifest,
    render_launcher_include,
    render_menu_include,
    render_player_include,
)


class MultiMovieTests(unittest.TestCase):
    def _manifest(self, text: str) -> Path:
        directory = Path(self.tmp.name)
        path = directory / "menu.toml"
        path.write_text(text, encoding="utf-8")
        return path

    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        profile = Path(self.tmp.name) / "video.toml"
        profile.write_text("schema_version = 5\n", encoding="utf-8")
        self.profile = profile

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def test_manifest_assigns_fixed_8_3_names_and_keeps_order(self) -> None:
        path = self._manifest(
            "schema_version = 1\n"
            "[menu]\n"
            "title = 'PICK A MOVIE'\n"
            "[[videos]]\n"
            f"profile = '{self.profile.name}'\n"
            "title = 'First'\n"
            "[[videos]]\n"
            f"profile = '{self.profile.name}'\n"
            "title = 'Second'\n"
        )
        manifest = load_manifest(path)
        self.assertEqual([item.index for item in manifest.videos], [0, 1])
        self.assertEqual(manifest.videos[0].header_name, "V0000HDR.DAT")
        self.assertEqual(manifest.videos[0].body_name, "V0000BOD.DAT")
        self.assertEqual(manifest.videos[1].sp_name, "V0001SP.BIN")

    def test_manifest_rejects_non_ascii_menu_text(self) -> None:
        path = self._manifest(
            "schema_version = 1\n"
            "[menu]\n"
            "title = '動画'\n"
            "[[videos]]\n"
            f"profile = '{self.profile.name}'\n"
        )
        with self.assertRaisesRegex(ValueError, "ASCII"):
            load_manifest(path)

    def test_player_include_carries_fixed_addresses(self) -> None:
        item = MenuVideo(3, self.profile, "Fourth")
        include = render_player_include(item)
        self.assertIn("MULTI_MENU_IP_BYTES, 0x5000", include)
        self.assertIn("MULTI_PLAYER_SP_BASE, 0x00006000", include)
        self.assertIn("MULTI_PLAYER_BSS_BASE, 0x00FF6700", include)
        self.assertIn("MULTI_MENU_INFO_ADDR, 0x00007F20", include)
        self.assertIn("MULTI_LOOP_FLAG_ADDR, 0x00007F40", include)

    def test_menu_include_has_pointer_and_ip_size_tables(self) -> None:
        manifest = MenuManifestForTest.make(self.profile)
        item = manifest.videos[0]
        built = BuiltVideo(item, 300, 40, 28, 30, 2048, 4096, 1200, 800)
        include = render_menu_include(manifest, [built])
        self.assertIn(".equ MENU_COUNT, 1", include)
        self.assertIn("menu_detail_timing_ptrs:", include)
        self.assertIn(".word\t0x04B0", include)
        self.assertIn("0x41,0x44,0x50,0x43,0x4D,0x32,0x32", include)

    def test_launcher_include_contains_every_item_name(self) -> None:
        manifest = MenuManifestForTest.make(self.profile, count=2)
        include = render_launcher_include(manifest)
        self.assertIn("menu_player_ip_names:", include)
        self.assertIn("0x56,0x30,0x30,0x30,0x30,0x49,0x50", include)
        self.assertIn("0x56,0x30,0x30,0x30,0x31,0x53,0x50", include)
        self.assertIn("menu_player_header_names:", include)
        self.assertIn("menu_player_body_names:", include)
        self.assertIn("0x56,0x30,0x30,0x30,0x30,0x42,0x4F,0x44,0x2E", include)

    def test_menu_font_is_96_four_bpp_tiles(self) -> None:
        font = Path("/home/akiyan/toolchains/mars/m68k-elf/res/image/font_default.png")
        data = generate_font(font)
        self.assertEqual(len(data), 96 * 32)
        self.assertTrue(any(data))


class MenuManifestForTest:
    @staticmethod
    def make(profile: Path, count: int = 1):
        from multimovie import MenuManifest
        return MenuManifest(
            path=profile,
            title="PICK",
            subtitle="SELECT",
            output_stem="test",
            videos=tuple(
                MenuVideo(i, profile, f"Video {i}") for i in range(count)
            ),
        )


if __name__ == "__main__":
    unittest.main()
