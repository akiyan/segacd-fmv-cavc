#!/usr/bin/env python3
"""Unit tests for the per-region release packaging."""

import tempfile
import unittest
import zipfile
from pathlib import Path

import disc_region
import region_release
from encode_config import load_profile

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROFILE = PROJECT_ROOT / "profiles" / "bad-apple.toml"


class DiscRegionTests(unittest.TestCase):
    def test_release_regions_are_ntsc_only(self):
        self.assertEqual(set(disc_region.RELEASE_REGIONS), {"jp", "us"})

    def test_europe_is_known_but_not_a_release_target(self):
        self.assertFalse(disc_region.region("eu").releasable)
        with self.assertRaises(ValueError):
            disc_region.release_region("eu")

    def test_unknown_region_is_rejected(self):
        with self.assertRaises(KeyError):
            disc_region.region("br")

    def test_japan_keeps_the_unsuffixed_name(self):
        self.assertEqual(disc_region.suffix("jp"), "")
        self.assertEqual(disc_region.suffix("us"), "_us")

    def test_header_fields_are_16_bytes(self):
        for region in disc_region.REGIONS.values():
            self.assertEqual(len(region.hardware_type),
                             disc_region.FIELD_LENGTH, region.code)
            self.assertEqual(len(region.region_field),
                             disc_region.FIELD_LENGTH, region.code)

    def test_header_fields_match_the_assembler_includes(self):
        """The Python table and boot/region_<code>.inc must not drift apart."""

        for region in disc_region.REGIONS.values():
            text = (PROJECT_ROOT / "boot" / f"region_{region.code}.inc"
                    ).read_text(encoding="utf-8")
            self.assertIn(f'.ascii "{region.hardware_type}"', text, region.code)
            self.assertIn(f'.ascii "{region.region_field}"', text, region.code)


class ProfilePathTests(unittest.TestCase):
    def setUp(self):
        self.profile = load_profile(PROFILE)

    def test_release_disc_paths_follow_the_makefile(self):
        self.assertEqual(str(self.profile.region_release_disc_iso("jp")),
                         "out/bad-apple_release.iso")
        self.assertEqual(str(self.profile.region_release_disc_iso("us")),
                         "out/bad-apple_us_release.iso")
        self.assertEqual(str(self.profile.region_release_disc_cue("us")),
                         "out/bad-apple_us_release.cue")


class NamingTests(unittest.TestCase):
    def setUp(self):
        self.profile = load_profile(PROFILE)

    def test_asset_stem_carries_region_date_and_versions(self):
        stem = region_release.asset_stem(self.profile, "us", "20260806")
        self.assertRegex(stem, r"^bad-apple_US_20260806\.e\d+\.p\d+$")

    def test_disc_stem_is_the_name_inside_the_zip(self):
        self.assertEqual(region_release.disc_stem(self.profile, "jp"),
                         "bad-apple_JP")

    def test_release_tag_names_the_build_not_a_title(self):
        self.assertRegex(region_release.release_tag("20260806"),
                         r"^disc-20260806\.e\d+\.p\d+$")

    def test_cue_names_the_iso_beside_it(self):
        self.assertIn('FILE "bad-apple_US.iso" BINARY',
                      region_release.cue_text("bad-apple_US"))


class ReadmeTests(unittest.TestCase):
    def setUp(self):
        self.profile = load_profile(PROFILE)

    def _readme(self, region_code):
        with tempfile.NamedTemporaryFile(suffix=".iso") as handle:
            handle.write(b"\0" * 4096)
            handle.flush()
            return region_release.readme_text(
                self.profile, region_code, Path(handle.name), "20260806")

    def test_states_the_region_and_both_languages(self):
        text = self._readme("us")
        self.assertIn("North America", text)
        self.assertIn("リージョン", text)

    def test_states_ntsc_only_in_both_languages(self):
        text = self._readme("jp")
        self.assertIn("NTSC only", text)
        self.assertIn("NTSC 専用", text)

    def test_names_the_files_packed_beside_it(self):
        text = self._readme("jp")
        self.assertIn("bad-apple_JP.iso", text)
        self.assertIn("bad-apple_JP.cue", text)

    def test_credits_the_source(self):
        text = self._readme("jp")
        self.assertIn(self.profile.source_label, text)
        self.assertIn(self.profile.source_url, text)

    def test_uses_crlf_for_a_text_file_read_on_windows(self):
        self.assertIn("\r\n", self._readme("jp"))


class ZipTests(unittest.TestCase):
    def test_same_inputs_produce_the_same_bytes(self):
        members = [("a.txt", b"one"), ("b.txt", b"two")]
        with tempfile.TemporaryDirectory() as work:
            first = Path(work) / "first.zip"
            second = Path(work) / "second.zip"
            region_release.write_zip(first, members, "20260806")
            region_release.write_zip(second, members, "20260806")
            self.assertEqual(first.read_bytes(), second.read_bytes())

    def test_members_keep_the_order_they_were_given(self):
        members = [("z.txt", b"last"), ("a.txt", b"first")]
        with tempfile.TemporaryDirectory() as work:
            path = Path(work) / "ordered.zip"
            region_release.write_zip(path, members, "20260806")
            with zipfile.ZipFile(path) as archive:
                self.assertEqual(archive.namelist(), ["z.txt", "a.txt"])


class NotesTests(unittest.TestCase):
    def setUp(self):
        self.profiles = [
            load_profile(PROFILE),
            load_profile(PROJECT_ROOT / "profiles" / "tears-of-steel.toml"),
        ]

    def _notes(self, work):
        zips = []
        for profile in self.profiles:
            for code in ("jp", "us"):
                path = Path(work) / (
                    region_release.asset_stem(profile, code, "20260806")
                    + ".zip")
                path.write_bytes(b"\0" * 1024)
                zips.append(path)
        return region_release.release_notes(
            self.profiles, ["jp", "us"], "20260806", zips), zips

    def test_lists_every_region_and_the_ntsc_limit(self):
        with tempfile.TemporaryDirectory() as work:
            notes, _ = self._notes(work)
        self.assertIn("Japan", notes)
        self.assertIn("North America", notes)
        self.assertIn("NTSC only", notes)

    def test_one_body_covers_every_title_and_asset(self):
        with tempfile.TemporaryDirectory() as work:
            notes, zips = self._notes(work)
        for profile in self.profiles:
            self.assertIn(f"## {profile.release_title}", notes)
        for path in zips:
            self.assertIn(path.name, notes)

    def test_release_body_is_english_only(self):
        with tempfile.TemporaryDirectory() as work:
            notes, _ = self._notes(work)
        japanese = [char for char in notes
                    if "぀" <= char <= "ヿ"
                    or "一" <= char <= "鿿"]
        self.assertEqual(japanese, [])

    def test_assets_are_grouped_under_their_own_title(self):
        with tempfile.TemporaryDirectory() as work:
            notes, zips = self._notes(work)
        sections = notes.split("## ")
        for profile in self.profiles:
            section = next(part for part in sections
                           if part.startswith(profile.release_title))
            for path in zips:
                belongs = path.name.startswith(f"{profile.artifact_stem}_")
                self.assertEqual(path.name in section, belongs, path.name)


if __name__ == "__main__":
    unittest.main()
