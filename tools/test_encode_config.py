#!/usr/bin/env python3
"""Regression tests for TOML-derived artifact names."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
import os
import sys
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
import av_config
from encode_config import (
    apply_profile_env,
    consume_config_arg,
    load_profile,
)


PROFILE = """\
schema_version = 5

[source]
path = "assets/source.mp4"
fps = "30"
duration = "1"

[video]
width = 320
height = 224
fit = "pad"

[output]
directory = "tmpfs/test/sim"
emit_decisions = true

[encoder]
cold_cap = 200

[palette]
algorithm = "mosaic-gm"
"""


class EncodeProfileArtifactTests(unittest.TestCase):
    def test_removed_schema_v4_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "old-schema.toml"
            path.write_text(PROFILE.replace(
                "schema_version = 5", "schema_version = 4"))
            with self.assertRaisesRegex(ValueError, "schema_version must be 5"):
                load_profile(path)

    def test_removed_video_mode_key_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "with-mode.toml"
            path.write_text(PROFILE.replace(
                "[video]", '[video]\nmode = "H40"'))
            with self.assertRaisesRegex(
                    ValueError, "unknown \\[video\\] keys.*mode"):
                load_profile(path)

    def test_raster_wider_than_the_h40_aperture_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "too-wide.toml"
            path.write_text(PROFILE.replace("width = 320", "width = 328"))
            with self.assertRaisesRegex(
                    ValueError, "exceeds the H40 320x224 aperture"):
                load_profile(path)

    def test_required_profile_preserves_following_frame_range(self) -> None:
        root = Path(__file__).resolve().parents[1]
        profile_path = root / "profiles" / "bad-apple.toml"
        argv = ["render_analysis.py", str(profile_path), "10", "20"]
        with patch.dict(os.environ, {}, clear=False):
            consume_config_arg(argv, required=True)
        self.assertEqual(argv, ["render_analysis.py", "10", "20"])

    def test_missing_required_profile_is_rejected(self) -> None:
        with self.assertRaisesRegex(SystemExit, "profile is required.*positional"):
            consume_config_arg(["sim.py"], required=True)

    def test_legacy_config_option_is_rejected(self) -> None:
        with self.assertRaisesRegex(SystemExit, "positional; do not use --config"):
            consume_config_arg(
                ["sim.py", "--config", "profiles/bad-apple.toml"],
                required=True,
            )

    def test_all_repository_profiles_have_explicit_cold_caps(self) -> None:
        root = Path(__file__).resolve().parents[1]
        for path in sorted((root / "profiles").glob("*.toml")):
            with self.subTest(profile=path.name):
                load_profile(path)

    def test_analysis_source_canvas_requires_two_positive_integers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad-analysis-canvas.toml"
            path.write_text(PROFILE + "\n[analysis]\nsource_canvas = [320, 0]\n")
            with self.assertRaisesRegex(
                    ValueError, "analysis.source_canvas must be"):
                load_profile(path)

    def test_profile_without_preprocess_clears_inherited_snap(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "no-preprocess.toml"
            path.write_text(PROFILE)
            env = apply_profile_env(load_profile(path), {
                "CBRSIM_PREPROCESS_ENDPOINT_SNAP_BLACK_MAX": "2",
                "CBRSIM_PREPROCESS_ENDPOINT_SNAP_WHITE_MIN": "253",
                "CBRSIM_OUTPUT_DITHER": "edge-attenuated-bayer",
                "CBRSIM_DITHER": "0",
            })
        self.assertEqual(
            env["CBRSIM_PREPROCESS_ENDPOINT_SNAP_BLACK_MAX"], "-1")
        self.assertEqual(
            env["CBRSIM_PREPROCESS_ENDPOINT_SNAP_WHITE_MIN"], "256")
        self.assertEqual(env["CBRSIM_RESIZE_FILTER"], "lanczos")
        self.assertEqual(env["CBRSIM_MASTER_DENOISE"], "1")
        self.assertEqual(env["CBRSIM_OUTPUT_DITHER"], "bayer")
        self.assertEqual(env["CBRSIM_RAW_PREFETCH"], "1")
        self.assertEqual(
            env["CBRSIM_CRAM_QUALITY_PRIORITY_SEARCH_FRAMES"],
            str(av_config.CRAM_QUALITY_PRIORITY_SEARCH_FRAMES))
        self.assertEqual(env["CBRSIM_COLD_CAP"], "200")
        self.assertEqual(
            env["CBRSIM_VRAM_TILES"],
            str(av_config.VRAM_PATTERN_POOL_TILES))
        self.assertEqual(env["CBRSIM_GPU"], "1")
        self.assertNotIn("CBRSIM_DITHER", env)
        self.assertEqual(env["CBRSIM_SEGPAL"], "1")
        self.assertEqual(env["CBRSIM_NEAR"], "1")
        self.assertEqual(env["CBRSIM_BOOT_VRAM_PREFETCH"], "1")

    def test_profile_may_disable_raw_prefetch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "raw-prefetch-off.toml"
            path.write_text(PROFILE.replace(
                "cold_cap = 200",
                "cold_cap = 200\nraw_prefetch = false"))
            env = apply_profile_env(
                load_profile(path), {"CBRSIM_RAW_PREFETCH": "1"})
        self.assertEqual(env["CBRSIM_RAW_PREFETCH"], "0")

    def test_profile_cold_cap_replaces_inherited_environment(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "explicit-cold-cap.toml"
            path.write_text(PROFILE.replace(
                "cold_cap = 200", "cold_cap = 210"))
            env = apply_profile_env(
                load_profile(path), {"CBRSIM_COLD_CAP": "999"})
        self.assertEqual(env["CBRSIM_COLD_CAP"], "210")

    def test_profile_cold_cap_is_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "missing-cold-cap.toml"
            path.write_text(PROFILE.replace(
                "[encoder]\ncold_cap = 200\n\n", ""))
            with self.assertRaisesRegex(
                    ValueError, r"missing \[encoder\] keys: cold_cap"):
                load_profile(path)

    def test_profile_cold_cap_must_be_an_integer(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "invalid-cold-cap.toml"
            path.write_text(PROFILE.replace(
                "cold_cap = 200", "cold_cap = 180.5"))
            with self.assertRaisesRegex(
                    ValueError, "cold_cap must be an integer"):
                load_profile(path)

    def test_profile_cold_cap_must_be_positive_and_fit_the_grid(self) -> None:
        for value, message in (
                ("0", "cold cap must be positive"),
                ("1744", "exceeds the 1743-tile resident pool")):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "invalid-cold-cap.toml"
                path.write_text(PROFILE.replace(
                    "cold_cap = 200", f"cold_cap = {value}"))
                with self.assertRaisesRegex(ValueError, message):
                    load_profile(path)

    def test_profile_interval_cold_cap_spec_matches_the_cadence(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "multi-cold-cap.toml"
            path.write_text(PROFILE.replace(
                'fps = "30"', 'fps = "24"').replace(
                "cold_cap = 200", 'cold_cap = "2:170,3:250"'))
            env = apply_profile_env(load_profile(path), {})
            self.assertEqual(env["CBRSIM_COLD_CAP"], "2:170,3:250")
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "multi-cold-cap-pool.toml"
            path.write_text(PROFILE.replace(
                'fps = "30"', 'fps = "24"').replace(
                "cold_cap = 200", 'cold_cap = "2:170,3:1744"'))
            with self.assertRaisesRegex(
                    ValueError, "exceeds the 1743-tile resident pool"):
                load_profile(path)
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "multi-cold-cap-30.toml"
            path.write_text(PROFILE.replace(
                "cold_cap = 200", 'cold_cap = "2:170,3:250"'))
            with self.assertRaisesRegex(ValueError, "never uses"):
                load_profile(path)

    def test_profile_may_override_cram_quality_priority_search_frames(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "cram-priority.toml"
            path.write_text(PROFILE.replace(
                "cold_cap = 200",
                "cold_cap = 200\n"
                "cram_quality_priority_search_frames = 0"))
            env = apply_profile_env(load_profile(path), {})
        self.assertEqual(
            env["CBRSIM_CRAM_QUALITY_PRIORITY_SEARCH_FRAMES"], "0")

    def test_cram_quality_priority_search_frames_must_be_non_negative_integer(
        self,
    ) -> None:
        for value in ("-1", "true", "1.5"):
            with self.subTest(value=value), tempfile.TemporaryDirectory() as tmp:
                path = Path(tmp) / "invalid-cram-priority.toml"
                path.write_text(PROFILE.replace(
                    "cold_cap = 200",
                    "cold_cap = 200\n"
                    "cram_quality_priority_search_frames = "
                    f"{value}"))
                with self.assertRaisesRegex(
                        ValueError, "cram_quality_priority_search_frames"):
                    load_profile(path)

    def test_endpoint_snap_limits_must_be_ordered(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "endpoint-snap.toml"
            path.write_text(PROFILE.replace(
                "[video]",
                "[source.preprocess.endpoint_snap]\nblack_max = 253\n"
                "white_min = 2\n\n[video]"))
            with self.assertRaisesRegex(ValueError, "black_max must be below"):
                load_profile(path)

    def test_endpoint_snap_requires_both_limits(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "endpoint-snap.toml"
            path.write_text(PROFILE.replace(
                "[video]",
                "[source.preprocess.endpoint_snap]\nblack_max = 2\n\n[video]"))
            with self.assertRaisesRegex(ValueError, "missing.*white_min"):
                load_profile(path)

    def test_auto_range_must_be_boolean(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "auto-range.toml"
            path.write_text(PROFILE.replace(
                "[video]",
                "[source.preprocess]\nauto_range = 1\n\n[video]"))
            with self.assertRaisesRegex(ValueError, "auto_range must be a boolean"):
                load_profile(path)

    def test_auto_range_exports_preprocess_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "auto-range.toml"
            path.write_text(PROFILE.replace(
                "[video]",
                "[source.preprocess]\nauto_range = true\n\n[video]"))
            env = apply_profile_env(load_profile(path), {})
            self.assertEqual(env["CBRSIM_PREPROCESS_AUTO_RANGE"], "1")

    def test_profile_without_auto_range_disables_inherited_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "auto-range.toml"
            path.write_text(PROFILE)
            env = apply_profile_env(
                load_profile(path), {"CBRSIM_PREPROCESS_AUTO_RANGE": "1"})
            self.assertEqual(env["CBRSIM_PREPROCESS_AUTO_RANGE"], "0")

    def test_unknown_resize_filter_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "resize-filter.toml"
            path.write_text(PROFILE.replace(
                "fit = \"pad\"", "fit = \"pad\"\nresize_filter = \"magic\""))
            with self.assertRaisesRegex(ValueError, "video.resize_filter"):
                load_profile(path)

    def test_output_dither_accepts_only_named_modes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "output-dither.toml"
            path.write_text(PROFILE.replace(
                "fit = \"pad\"",
                "fit = \"pad\"\noutput_dither = \"edge-attenuated-bayer\""))
            env = apply_profile_env(load_profile(path), {})
            self.assertEqual(
                env["CBRSIM_OUTPUT_DITHER"], "edge-attenuated-bayer")

            path.write_text(PROFILE.replace(
                "fit = \"pad\"",
                "fit = \"pad\"\noutput_dither = \"diffusion\""))
            with self.assertRaisesRegex(ValueError, "video.output_dither"):
                load_profile(path)

    def test_active_tiles_must_fit_the_output_grid(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad-active-tiles.toml"
            path.write_text(PROFILE.replace(
                'fit = "pad"', 'fit = "pad"\nactive_tiles = 1121'))
            with self.assertRaisesRegex(ValueError, "video.active_tiles"):
                load_profile(path)

    def test_source_audio_filter_maps_to_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "loud.toml"
            path.write_text(PROFILE.replace(
                'duration = "1"',
                'duration = "1"\naudio_filter = "loudnorm=I=-8:TP=-1:LRA=7"'))
            env = apply_profile_env(load_profile(path), {})
        self.assertEqual(env["CBRSIM_AUDIO_AF"], "loudnorm=I=-8:TP=-1:LRA=7")

    def test_absent_audio_filter_overwrites_inherited_env(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "plain.toml"
            path.write_text(PROFILE)
            env = {"CBRSIM_AUDIO_AF": "loudnorm=I=-8:TP=-1:LRA=7"}
            apply_profile_env(load_profile(path), env)
        self.assertEqual(env["CBRSIM_AUDIO_AF"], "")

    def test_artifacts_follow_toml_filename(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sakura-op.toml"
            path.write_text(PROFILE)
            profile = load_profile(path)

        self.assertEqual(profile.artifact_stem, "sakura-op")
        self.assertEqual(profile.artifact_dir, Path("out/sakura-op"))
        self.assertEqual(profile.pack_output, Path("out/sakura-op/MOVIE.DAT"))
        self.assertEqual(profile.temp_dir, Path("tmp/sakura-op"))
        self.assertEqual(profile.build_dir, Path("tmp/sakura-op/build"))
        self.assertEqual(profile.disc_staging_dir, Path("tmp/sakura-op/disc"))
        self.assertEqual(profile.disc_iso, Path("out/sakura-op.iso"))
        self.assertEqual(profile.disc_cue, Path("out/sakura-op.cue"))
        self.assertEqual(
            profile.release_disc_iso, Path("out/sakura-op_release.iso"))
        self.assertEqual(
            profile.release_disc_cue, Path("out/sakura-op_release.cue"))

    def test_unsafe_filename_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "unsafe name.toml"
            path.write_text(PROFILE)
            with self.assertRaisesRegex(ValueError, "filename stem"):
                load_profile(path)


if __name__ == "__main__":
    unittest.main()
