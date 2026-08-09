#!/usr/bin/env python3
"""Regression tests for the isolated JP security experiment builder."""

from __future__ import annotations

import csv
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


HERE = Path(__file__).resolve().parent
REPOSITORY = HERE.parents[1]
BUILDER = HERE / "build_jp_experiment.py"
CANONICAL_SECURITY = REPOSITORY / "boot/sec_jp.bin"
DISC_IDS = {
    "disc": b"SEGADISC        ",
    "system": b"SEGADISCSYSTEM  ",
}


class BuilderTest(unittest.TestCase):
    def make_source(self, root: Path) -> Path:
        image = bytearray(0x9000)
        image[:16] = DISC_IDS["system"]
        image[0x200:0x356] = CANONICAL_SECURITY.read_bytes()
        source = root / "source.iso"
        source.write_bytes(image)
        return source

    def run_builder(
        self, source: Path, output: Path, name: str, *options: str
    ) -> subprocess.CompletedProcess[str]:
        return subprocess.run(
            [
                sys.executable,
                str(BUILDER),
                str(source),
                "--name",
                name,
                "--output-dir",
                str(output),
                "--canonical-security",
                str(CANONICAL_SECURITY),
                *options,
            ],
            check=True,
            text=True,
            capture_output=True,
        )

    def test_default_build_is_byte_identical(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self.make_source(root)
            original = source.read_bytes()
            output = root / "out"

            self.run_builder(source, output, "baseline")

            built = (output / "source_jpsec_baseline.iso").read_bytes()
            self.assertEqual(built, original)
            self.assertEqual(source.read_bytes(), original)

    def test_disc_id_build_changes_only_the_id(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = self.make_source(root)
            original = source.read_bytes()
            output = root / "out"

            self.run_builder(source, output, "disc", "--disc-id", "disc")

            built_path = output / "source_jpsec_disc.iso"
            built = built_path.read_bytes()
            expected = bytearray(original)
            expected[:16] = DISC_IDS["disc"]
            self.assertEqual(built, expected)
            with (output / "source_jpsec_disc.tsv").open(
                encoding="utf-8", newline=""
            ) as receipt:
                row = next(csv.DictReader(receipt, delimiter="\t"))
            self.assertEqual(row["disc_id"], DISC_IDS["disc"].decode("ascii"))
            self.assertEqual(row["security_verifier"], "no")


if __name__ == "__main__":
    unittest.main()
