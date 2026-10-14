"""Reject broken release evidence before spending a recording run."""
import copy
import json
import tempfile
import unittest
from pathlib import Path

from release import baseline_for
import playlist_build


class ReleaseBaselineTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        root = Path(self.temp.name)
        payload = root / "capture.bin"
        payload.write_bytes(b"immutable capture")
        item = dict(id="one", index=0, profile_sha256="profile", frames=2, fps=30,
                    palette_files={"paltab.bin": {"sha256": "palette"}},
                    files={"V0000HDR.DAT": {"sha256": "header"},
                           "V0000BOD.DAT": {"sha256": "body"}})
        base = dict(debug=1, versions=["e192", "p155"], iso_sha256="debug-iso", items=[item])
        manifest = root / "manifest.json"
        manifest.write_text(json.dumps(base))
        capture = dict(iso_sha256="debug-iso", manifest_sha256=playlist_build.digest(manifest))
        for name in ("recording", "full_log", "compact_log"):
            capture[name] = str(payload)
            capture[name + "_sha256"] = playlist_build.digest(payload)
        capture_path = root / "capture.json"
        capture_path.write_text(json.dumps(capture))
        gate = dict(gate="PASS", manifest=str(manifest), manifest_sha256=playlist_build.digest(manifest),
                    completed_visits=1, boundaries=1, capture_receipt=str(capture_path))
        self.gate = root / "gate.json"
        self.gate.write_text(json.dumps(gate))
        self.target = copy.deepcopy(base)
        self.target.update(debug=0, iso_sha256="release-iso")
        self.payload = payload

    def test_same_stream_with_different_player_is_accepted(self):
        self.target["items"][0]["files"]["V0000IP.BIN"] = {"sha256": "release-code"}
        baseline_for(self.target, self.gate)

    def test_changed_stream_palette_order_or_version_is_rejected(self):
        for field, value in (("frames", 3), ("id", "another"),
                             ("palette_files", {}), ("files", {})):
            with self.subTest(field=field):
                target = copy.deepcopy(self.target)
                target["items"][0][field] = value
                with self.assertRaises(ValueError):
                    baseline_for(target, self.gate)
        self.target["versions"] = ["e192", "p156"]
        with self.assertRaises(ValueError):
            baseline_for(self.target, self.gate)

    def test_changed_capture_and_failed_gate_are_rejected(self):
        self.payload.write_bytes(b"different")
        with self.assertRaises(ValueError):
            baseline_for(self.target, self.gate)
        gate = json.loads(self.gate.read_text())
        gate["gate"] = "FAIL"
        self.gate.write_text(json.dumps(gate))
        with self.assertRaises(ValueError):
            baseline_for(self.target, self.gate)


if __name__ == "__main__":
    unittest.main()
