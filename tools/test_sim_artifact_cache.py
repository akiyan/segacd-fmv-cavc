from __future__ import annotations

from pathlib import Path
import pickle
import tempfile
import unittest
from unittest.mock import patch

import numpy as np

import sim_artifact_cache as cache


class SimArtifactCacheTests(unittest.TestCase):
    def _write_completed_data(self, root: Path, *, categories=True) -> dict:
        data = root / "data"
        data.mkdir()
        decisions = {
            "frames": [[(0, 0, b"\x01" * 64)]],
            "frame_seg": np.zeros(1, np.int32),
            "geom": (1, 1, 1, 8),
            "max_cold": 1,
        }
        if categories:
            decisions["display_category_masks"] = {
                "schema_version": 1,
                "bit_order": (
                    "Raw", "Near", "Flbk", "Prg",
                    "Wr0", "Wr1", "Dic", "Miss",
                ),
                "rows": [b"\x00\x00"],
            }
        with (data / "decisions.pkl").open("wb") as output:
            pickle.dump(decisions, output)
        np.savez(data / "stats.npz", stats=np.zeros((1, 1)))
        for name in (
                "buffer_remaining.npz", "miss_masks.npy", "palettes.bin",
                "seg_palettes.npz", "audio_22k05_s16_mono.wav",
                "audio_playback_adpcm22_rf5c.wav"):
            (data / name).touch()
        for directory in ("master", "raw"):
            path = data / directory
            path.mkdir()
            (path / "00001.png").touch()
        return {"data": data, "decisions": decisions}

    def test_completed_data_does_not_require_analysis_panel_pngs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = self._write_completed_data(Path(tmp))
            result = cache.validate_completed_data(fixture["data"], {})
        self.assertEqual(result, {"frames": 1})

    def test_completed_data_requires_per_cell_analysis_category_masks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = self._write_completed_data(
                Path(tmp), categories=False)
            with self.assertRaisesRegex(
                    cache.CacheValidationError, "per-cell category masks"):
                cache.validate_completed_data(fixture["data"], {})

    def test_identity_ignores_paths_and_output_controls(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "movie.mp4"
            source.write_bytes(b"same source bytes")
            common = {
                "CBRSIM_W": "320",
                "CBRSIM_H": "224",
                "CBRSIM_FPS": "30",
                "CBRSIM_COLD_CAP": "190",
            }
            first_env = {
                **common,
                "CBRSIM_SRC": "/one/movie.mp4",
                "CBRSIM_OUT": "tmpfs/one/sim",
                "CBRSIM_REUSE": "0",
                "CBRSIM_CONFIG": "/one/profile.toml",
            }
            second_env = {
                **common,
                "CBRSIM_SRC": "/two/renamed.mp4",
                "CBRSIM_OUT": "tmpfs/two/sim",
                "CBRSIM_REUSE": "1",
                "CBRSIM_CONFIG": "/two/renamed.toml",
            }
            with patch.object(
                    cache, "encoder_version", return_value="e123"):
                first = cache.build_identity(
                    source=source,
                    emit_decisions=True, environ=first_env)
                second = cache.build_identity(
                    source=source,
                    emit_decisions=True, environ=second_env)
            self.assertEqual(first, second)

    def test_encoder_setting_and_source_content_change_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "movie.mp4"
            source.write_bytes(b"revision one")
            env = {"CBRSIM_COLD_CAP": "190"}
            with patch.object(
                    cache, "encoder_version", return_value="e123"):
                first = cache.build_identity(
                    source=source,
                    emit_decisions=True, environ=env)
                changed_setting = cache.build_identity(
                    source=source, emit_decisions=True,
                    environ={**env, "CBRSIM_COLD_CAP": "191"})
                source.write_bytes(b"revision two")
                changed_source = cache.build_identity(
                    source=source,
                    emit_decisions=True, environ=env)
            self.assertNotEqual(
                cache.identity_sha256(first),
                cache.identity_sha256(changed_setting))
            self.assertNotEqual(
                cache.identity_sha256(first),
                cache.identity_sha256(changed_source))

    def test_readable_key_exposes_major_conditions(self) -> None:
        identity = {
            "source": {"name": "SonicJamOp", "sha256": "1" * 64},
            "effective_environment": {"CBRSIM_COLD_CAP": "190"},
            "emit_decisions": True,
            "encoder_version": "e123",
        }
        key = cache.readable_key(
            identity,
            mode="H40", width=320, height=224, fps="30",
            fit="crop", cold_cap=190)
        self.assertIn("SonicJamOp-H40-320x224-30fps-fit-crop-cold190", key)
        self.assertIn("src11111111", key)
        self.assertIn("enc-e123", key)

    def test_encoder_version_change_invalidates_identity(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            source = Path(tmp) / "movie.mp4"
            source.write_bytes(b"same source")
            with patch.object(
                    cache, "encoder_version", side_effect=("e123", "e124")):
                first = cache.build_identity(
                    source=source, emit_decisions=True, environ={})
                second = cache.build_identity(
                    source=source, emit_decisions=True, environ={})
            self.assertNotEqual(first, second)


if __name__ == "__main__":
    unittest.main()
