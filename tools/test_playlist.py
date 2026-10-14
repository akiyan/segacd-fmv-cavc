from __future__ import annotations

import copy
import tempfile
import unittest
from pathlib import Path

import encode_config
import playlist


class PlaylistProfiles(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        source = Path(__file__).resolve().parents[1] / "profiles/sonic-jam-op.toml"
        self.base = self.root / "source.toml"
        self.base.write_bytes(source.read_bytes())
        self.original = self.base.read_bytes()
        self.path = self.root / "playlist.toml"
        self.data = {"schema_version": 1, "playlist": {"items": [
            {"id": "first", "profile": "source.toml"},
            {"id": "second", "profile": "source.toml",
             "overrides": {"encoder": {"cold_cap": 180, "auto_scroll": False}}}
        ]}}

    def write(self, data=None):
        # Playlist array-of-tables is a different schema from encode profiles.
        d = self.data if data is None else data
        lines = [f"schema_version = {d['schema_version']}", "[playlist]"]
        import json
        for item in d["playlist"]["items"]:
            lines.append("[[playlist.items]]")
            for key, value in item.items():
                if key != "overrides":
                    lines.append(f"{key} = {json.dumps(value)}")
            for section, values in item.get("overrides", {}).items():
                lines.append(f"[playlist.items.overrides.{section}]")
                lines.extend(f"{key} = {json.dumps(value)}" for key, value in values.items())
        if not d["playlist"]["items"]:
            lines.append("items = []")
        self.path.write_text("\n".join(lines) + "\n")
        return playlist.load(self.path)

    def test_resolve_keeps_source_and_isolates_entries(self):
        result = playlist.materialize(self.write(), self.root / "resolved")
        self.assertEqual(self.base.read_bytes(), self.original)
        self.assertEqual(result[0].section("encoder")["cold_cap"], 210)
        self.assertEqual(result[1].section("encoder")["cold_cap"], 180)
        self.assertIs(result[1].section("encoder")["auto_scroll"], False)
        self.assertNotEqual(result[0].artifact_stem, result[1].artifact_stem)
        # Includes nested comparison tables with keys containing spaces.
        self.assertEqual(result[0].data, encode_config.load_profile(self.base).data)
        again = playlist.materialize(self.write(), self.root / "resolved")
        self.assertEqual([p.sha256 for p in result], [p.sha256 for p in again])

    def test_changed_override_has_new_identity(self):
        original = playlist.materialize(self.write(), self.root / "resolved")
        self.data["playlist"]["items"][1]["overrides"]["encoder"]["cold_cap"] = 170
        changed = playlist.materialize(self.write(), self.root / "resolved")
        self.assertEqual(original[0].artifact_stem, changed[0].artifact_stem)
        self.assertNotEqual(original[1].artifact_stem, changed[1].artifact_stem)

    def test_upload_title_does_not_change_effective_profiles(self):
        original = playlist.materialize(self.write(), self.root / 'resolved')
        with self.path.open('a') as handle:
            handle.write('\n[youtube]\nplayback_title = "Continuous playback"\n')
        loaded = playlist.load(self.path)
        self.assertEqual(loaded.youtube['playback_title'], 'Continuous playback')
        actual = playlist.materialize(loaded, self.root / 'resolved')
        self.assertEqual([p.sha256 for p in original], [p.sha256 for p in actual])
        text = self.path.read_text()
        for replacement in ('"' + 'x' * 101 + '"', '" "', '3'):
            self.path.write_text(text.replace('"Continuous playback"', replacement))
            with self.assertRaises(ValueError):
                playlist.load(self.path)

    def test_variable_count_and_reordering_preserve_entry_identity(self):
        for count in (1, 3, 4, 5):
            self.data["playlist"]["items"] = [
                {"id": f"entry-{index}", "profile": "source.toml"}
                for index in range(count)]
            forward = playlist.materialize(self.write(), self.root / "resolved")
            self.data["playlist"]["items"].reverse()
            reverse = playlist.materialize(self.write(), self.root / "resolved")
            self.assertEqual([p.artifact_stem for p in reverse],
                             [p.artifact_stem for p in reversed(forward)])
            self.assertEqual(len(set(p.artifact_stem for p in forward)), count)

    def test_bad_manifests_fail(self):
        cases = []
        duplicate = copy.deepcopy(self.data)
        duplicate["playlist"]["items"][1]["id"] = "first"
        cases.append(duplicate)
        empty = copy.deepcopy(self.data)
        empty["playlist"]["items"] = []
        cases.append(empty)
        missing = copy.deepcopy(self.data)
        missing["playlist"]["items"][0]["profile"] = "missing.toml"
        cases.append(missing)
        extra = copy.deepcopy(self.data)
        extra["playlist"]["items"][1]["overrides"]["encoder"]["ring_size"] = 100
        cases.append(extra)
        for data in cases:
            with self.subTest(data=data), self.assertRaises((ValueError, FileNotFoundError)):
                self.write(data)

    def test_effective_profile_uses_existing_validation(self):
        self.data["playlist"]["items"][1]["overrides"]["encoder"]["auto_scroll"] = "false"
        with self.assertRaisesRegex(ValueError, "boolean"):
            playlist.materialize(self.write(), self.root / "resolved")

    def test_recursive_reference_rejected(self):
        self.write()
        self.data["playlist"]["items"][0]["profile"] = "playlist.toml"
        with self.assertRaises(ValueError):
            self.write()


if __name__ == "__main__":
    unittest.main()
