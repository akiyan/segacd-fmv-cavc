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

    def test_each_region_names_the_console_it_was_sold_as(self):
        self.assertEqual(disc_region.region("jp").console, "MEGA-CD")
        self.assertEqual(disc_region.region("us").console, "SEGA-CD")

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

    def test_asset_stem_carries_console_region_date_and_versions(self):
        stem = region_release.asset_stem(self.profile, "us", "20260806")
        self.assertRegex(
            stem, r"^bad-apple_SEGA-CD_US_20260806\.e\d+\.p\d+$")

    def test_disc_stem_names_the_console_that_region_was_sold_as(self):
        self.assertEqual(region_release.disc_stem(self.profile, "jp"),
                         "bad-apple_MEGA-CD_JP")
        self.assertEqual(region_release.disc_stem(self.profile, "us"),
                         "bad-apple_SEGA-CD_US")

    def test_release_tag_names_the_build_not_a_title(self):
        self.assertRegex(region_release.release_tag("20260806"),
                         r"^disc-20260806\.e\d+\.p\d+$")

    def test_cue_names_the_iso_beside_it(self):
        self.assertIn('FILE "bad-apple_SEGA-CD_US.iso" BINARY',
                      region_release.cue_text("bad-apple_SEGA-CD_US"))


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
        self.assertIn("bad-apple_MEGA-CD_JP.iso", text)
        self.assertIn("bad-apple_MEGA-CD_JP.cue", text)

    def test_credits_the_source(self):
        text = self._readme("jp")
        self.assertIn(self.profile.source_label, text)
        self.assertIn(self.profile.source_url, text)

    def test_uses_crlf_for_a_text_file_read_on_windows(self):
        self.assertIn("\r\n", self._readme("jp"))

    def test_a_source_with_no_licence_notice_gets_no_licence_section(self):
        """bad-apple cites its master but carries no licence keys."""

        self.assertIsNone(self.profile.source_license)
        text = self._readme("us")
        self.assertNotIn("License", text)
        self.assertNotIn("ライセンス", text)


class FoldTests(unittest.TestCase):
    def test_english_breaks_at_spaces(self):
        folded = region_release._fold("one two three four five", 10)
        self.assertEqual(folded, ["one two", "three four", "five"])

    def test_japanese_breaks_between_characters(self):
        folded = region_release._fold("あいうえおかきくけこ", 8)
        self.assertEqual(folded, ["あいうえ", "おかきく", "けこ"])

    def test_a_japanese_full_stop_is_never_stranded(self):
        folded = region_release._fold("あいう。えお", 6)
        self.assertEqual(folded, ["あいう。", "えお"])

    def test_every_line_fits_the_page(self):
        text = ("(CC) Rights Holder | example.org。クリエイティブ・コモンズ "
                "表示 3.0 非移植 にもとづいて利用しています。")
        for line in region_release._fold(text, 40):
            self.assertLessEqual(region_release._columns(line), 40, line)


class LicenceReadmeTests(unittest.TestCase):
    """A master offered under an attribution licence is credited in the zip."""

    def setUp(self):
        self.profile = load_profile(PROJECT_ROOT / "profiles"
                                    / "tears-of-steel.toml")
        with tempfile.NamedTemporaryFile(suffix=".iso") as handle:
            handle.write(b"\0" * 4096)
            handle.flush()
            self.text = region_release.readme_text(
                self.profile, "jp", Path(handle.name), "20260807")
        self.lines = self.text.split(region_release.README_NEWLINE)

    def _section(self, heading):
        start = self.lines.index(heading) + 1
        end = self.lines.index("", start)
        return [line[2:] for line in self.lines[start:end]]

    def test_both_halves_carry_a_licence_section(self):
        self.assertIn("License", self.lines)
        self.assertIn("ライセンス", self.lines)

    def test_the_credit_is_the_one_the_licensor_asks_for(self):
        credit = "(CC) Blender Foundation | mango.blender.org"
        for heading in ("License", "ライセンス"):
            self.assertTrue(self._section(heading)[0].startswith(credit),
                            heading)

    def test_the_terms_link_closes_each_section_unbroken(self):
        for heading in ("License", "ライセンス"):
            self.assertEqual(self._section(heading)[-1],
                             self.profile.source_license_url, heading)

    def test_says_the_disc_is_a_modified_version(self):
        self.assertIn("modified version", " ".join(self._section("License")))
        self.assertIn("改変版", "".join(self._section("ライセンス")))

    def test_folds_the_notice_instead_of_running_it_on(self):
        """A plain-text reader must not get one 190-column line."""

        for heading in ("License", "ライセンス"):
            body = self._section(heading)
            self.assertGreater(len(body), 2, heading)
            for line in body:
                self.assertLessEqual(region_release._columns(line) + 2,
                                     region_release.README_WIDTH, line)


class ReleaseNotesLicenceTests(unittest.TestCase):
    def test_the_release_page_states_the_licence_of_each_title(self):
        licensed = load_profile(PROJECT_ROOT / "profiles"
                                / "tears-of-steel.toml")
        plain = load_profile(PROFILE)
        notes = region_release.release_notes(
            [licensed, plain], ["jp"], "20260807", [])
        self.assertIn(f"- License: {licensed.source_license} "
                      f"{licensed.source_license_url}", notes)
        self.assertEqual(notes.count("- License:"), 1)


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
