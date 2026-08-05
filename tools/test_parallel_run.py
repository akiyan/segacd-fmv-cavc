from __future__ import annotations

import csv
from pathlib import Path
import tempfile
import unittest

import parallel_run
from encode_config import load_profile


def write_profile(path: Path, *, source: str, width: int = 320) -> None:
    path.write_text(f"""\
schema_version = 5

[source]
path = "{source}"
fps = "30"
duration = "8"

[video]
width = {width}
height = 224
fit = "pad"

[output]
directory = "tmpfs/{Path(source).stem}_H40_{width}x224_adpcm22/sim"
emit_decisions = true

[encoder]
cold_cap = 200

[palette]
algorithm = "mosaic-gm"
""", encoding="utf-8")


class ParallelRunTests(unittest.TestCase):
    def test_rejects_duplicate_video_stems(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            first = root / "first.toml"
            second = root / "second.toml"
            write_profile(first, source="assets/same.mp4")
            write_profile(second, source="assets/same.mp4")
            with self.assertRaises(parallel_run.ParallelRunError):
                parallel_run.validate_distinct_stems([
                    load_profile(first), load_profile(second)])

    def test_stage_commands_stop_at_requested_boundary(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            profile_path = Path(tmp) / "movie.toml"
            write_profile(profile_path, source="assets/movie.mp4")
            profile = load_profile(profile_path)
            commands = parallel_run.stage_commands(
                profile,
                through="record",
                use_gpu=False,
                record_seconds=41,
            )
            self.assertEqual(
                [stage for stage, _command in commands],
                ["sim", "disc", "record"],
            )
            record = commands[-1][1]
            self.assertIn("320x224", record)
            self.assertIn("41", record)
            self.assertNotIn("--gpu", commands[0][1])

    def test_default_record_seconds_adds_startup_margin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            profile_path = Path(tmp) / "movie.toml"
            write_profile(profile_path, source="assets/movie.mp4")
            profile = load_profile(profile_path)
            # 14.9 s measured Mega-CD startup plus the player's 15 s
            # end-of-movie hold must both fit inside the bounded capture.
            self.assertEqual(parallel_run.RECORD_MARGIN_SECONDS, 30)
            self.assertGreaterEqual(parallel_run.RECORD_MARGIN_SECONDS, 15 + 15)
            self.assertEqual(
                parallel_run._record_seconds(profile, None),
                8 + parallel_run.RECORD_MARGIN_SECONDS,
            )
            self.assertEqual(parallel_run._record_seconds(profile, 41), 41)

    def test_summary_is_tsv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "summary.tsv"
            result = parallel_run.JobResult(
                Path("profiles/a.toml"),
                "movie_H40_320x224_adpcm22",
                "PASS",
                "",
                1.25,
                Path("logs/a.log"),
                "",
            )
            parallel_run._write_summary(path, [result])
            with path.open(encoding="utf-8", newline="") as handle:
                rows = list(csv.DictReader(handle, delimiter="\t"))
            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["status"], "PASS")
            self.assertEqual(rows[0]["elapsed_seconds"], "1.250")


if __name__ == "__main__":
    unittest.main()
