from __future__ import annotations

from datetime import datetime, timezone
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import analysis_logs


class Profile:
    path = Path("/repo/profiles/sonic-jam-op.toml")
    sha256 = "4dd3ae5754c01c1d4f3948a8eddc8a5f19a5739b03c26eeb32c385502fecffdb"


class AnalysisLogTests(unittest.TestCase):
    def test_unique_name_contains_required_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, patch.dict(
                os.environ, {"ANALYSIS_LOG_DIR": tmp}):
            path = analysis_logs.unique_tsv_path(
                Profile(), kind="timeline", now=datetime(
                    2026, 7, 23, 12, 34, 56, 123456, tzinfo=timezone.utc))
            self.assertRegex(
                path.name,
                r"^20260723-123456-123456_sonic-jam-op_"
                r"4dd3ae5754_e\d+_p\d+_timeline\.tsv$")

    def test_av_versions_include_encoder_and_player(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "av_version.txt"
            path.write_text(
                "# test\ndate=20260725\ne=132\np=90\n",
                encoding="utf-8",
            )
            self.assertEqual(
                analysis_logs.av_versions(path),
                ("e132", "p90"),
            )

    def test_metadata_path_is_persistent_and_content_keyed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict(os.environ, {"ANALYSIS_LOG_DIR": tmp}):
                path = analysis_logs.metadata_path(
                    Path("movie_timeline.png"),
                    kind="layout",
                    sha256="abcdef0123456789",
                )
            self.assertEqual(
                path,
                Path(tmp) / "movie_timeline_abcdef0123_layout.json",
            )


if __name__ == "__main__":
    unittest.main()
