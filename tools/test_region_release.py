#!/usr/bin/env python3
"""Unit tests for the per-region release packaging."""

import tempfile
import unittest
from pathlib import Path

import disc_region
import region_release
from encode_config import load_profile

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PROFILE = PROJECT_ROOT / "profiles" / "bad-apple.toml"


class DiscRegionTests(unittest.TestCase):

    def test_europe_is_known_but_not_a_release_target(self):
        self.assertFalse(disc_region.region("eu").releasable)
        with self.assertRaises(ValueError):
            disc_region.release_region("eu")

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


class ReadmeTests(unittest.TestCase):
    def setUp(self):
        self.profile = load_profile(PROFILE)

    def _readme(self, region_code):
        with tempfile.NamedTemporaryFile(suffix=".iso") as handle:
            handle.write(b"\0" * 4096)
            handle.flush()
            return region_release.readme_text(
                self.profile, region_code, Path(handle.name), "20260806")

    def test_readme_identifies_the_disc_and_credits_the_source(self):
        for code, console, label in (("jp", "MEGA-CD", "Japan"), ("us", "SEGA-CD", "North America")):
            with self.subTest(region=code):
                text = self._readme(code)
                for required in (label, "リージョン", "NTSC only", "NTSC 専用",
                                 f"bad-apple_{console}_{code.upper()}.iso",
                                 f"bad-apple_{console}_{code.upper()}.cue",
                                 self.profile.source_label, self.profile.source_url, "\r\n"):
                    self.assertIn(required, text)
                self.assertNotIn("License", text)
                self.assertNotIn("ライセンス", text)


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

    def test_bilingual_license_keeps_credit_terms_and_modification_notice(self):
        for heading in ("License", "ライセンス"):
            body = self._section(heading)
            self.assertTrue(body[0].startswith("(CC) Blender Foundation | mango.blender.org"))
            self.assertEqual(body[-1], self.profile.source_license_url)
        self.assertIn("modified version", " ".join(self._section("License")))
        self.assertIn("改変版", "".join(self._section("ライセンス")))


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
