#!/usr/bin/env python3
"""Load one reproducible per-source encode profile from TOML.

The encoder still has mature ``CBRSIM_*`` internals.  This module is the only
translation layer from the public TOML profile to those internals.  Profile
values replace inherited per-source environment variables so a shell left over
from another encode cannot silently change the result.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path
from typing import Any, MutableMapping

import av_config
from disc_region import suffix as _region_suffix


SCHEMA_VERSION = 5
ARTIFACT_ROOT = Path("out")
TEMP_ROOT = Path("tmp")
_ARTIFACT_STEM_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._-]*")

# Compatibility names for player/tooling imports.  The fixed values live in
# av_config with the other shared hardware resources.
VRAM_PATTERN_BASE_TILE = av_config.VRAM_PATTERN_BASE_TILE
VRAM_FIRST_MOVIE_NT_TILE = av_config.VRAM_FIRST_MOVIE_NT_TILE
HUD_FONT_TILES = 16
VRAM_HUD_FONT_TILE = av_config.VRAM_HUD_FONT_TILE
MAX_RESIDENT_VRAM_TILES = av_config.VRAM_PATTERN_POOL_TILES

# (section, key): legacy internal variable.  Keeping this table in one place is
# deliberate: TOML is the user interface; CBRSIM_* is an implementation detail.
ENV_MAP = {
    ("source", "path"): "CBRSIM_SRC",
    ("source", "fps"): "CBRSIM_FPS",
    ("source", "duration"): "CBRSIM_DURATION",
    ("source", "sar"): "CBRSIM_SOURCE_SAR",
    ("source", "audio_filter"): "CBRSIM_AUDIO_AF",
    ("video", "width"): "CBRSIM_W",
    ("video", "height"): "CBRSIM_H",
    ("video", "active_tiles"): "CBRSIM_ACTIVE_TILES",
    ("video", "fit"): "CBRSIM_GEOMETRY_FIT",
    ("video", "resize_filter"): "CBRSIM_RESIZE_FILTER",
    ("video", "master_denoise"): "CBRSIM_MASTER_DENOISE",
    ("video", "output_dither"): "CBRSIM_OUTPUT_DITHER",
    ("video", "master_filter"): "CBRSIM_MASTER_VF",
    ("video", "raw_filter"): "CBRSIM_RAW_VF",
    ("output", "directory"): "CBRSIM_OUT",
    ("output", "reuse"): "CBRSIM_REUSE",
    ("output", "emit_decisions"): "CBRSIM_EMIT_DEC",
    ("encoder", "raw_prefetch"): "CBRSIM_RAW_PREFETCH",
    ("encoder", "cold_cap"): "CBRSIM_COLD_CAP",
    ("encoder", "cram_quality_priority_search_frames"):
        "CBRSIM_CRAM_QUALITY_PRIORITY_SEARCH_FRAMES",
    ("palette", "algorithm"): "CBRSIM_PAL_ALGO",
}
PROFILE_ENV_DEFAULTS = {
    # An empty audio filter chain means "extract the source audio as-is".
    # Always overwritten so an inherited shell value cannot leak between
    # profiles.
    "CBRSIM_AUDIO_AF": "",
    "CBRSIM_PREPROCESS_ENDPOINT_SNAP_BLACK_MAX": "-1",
    "CBRSIM_PREPROCESS_ENDPOINT_SNAP_WHITE_MIN": "256",
    "CBRSIM_PREPROCESS_AUTO_RANGE": "0",
    "CBRSIM_RESIZE_FILTER": "lanczos",
    "CBRSIM_MASTER_DENOISE": "1",
    "CBRSIM_OUTPUT_DITHER": "bayer",
    "CBRSIM_GPU": "1",
    "CBRSIM_VRAM_TILES": str(av_config.VRAM_PATTERN_POOL_TILES),
    "CBRSIM_SEGPAL": "1",
    "CBRSIM_NEAR": "1",
    "CBRSIM_BOOT_VRAM_PREFETCH": "1",
    "CBRSIM_RAW_PREFETCH": "1",
    "CBRSIM_CRAM_QUALITY_PRIORITY_SEARCH_FRAMES": str(
        av_config.CRAM_QUALITY_PRIORITY_SEARCH_FRAMES),
    "CBRSIM_PAL_MAP_WEIGHT": str(av_config.PALETTE_MAP_WEIGHT),
    "CBRSIM_PAL_SEAM_WEIGHT": str(av_config.PALETTE_SEAM_WEIGHT),
    "CBRSIM_PAL_SEAM_ITERATIONS": str(av_config.PALETTE_SEAM_ITERATIONS),
    "CBRSIM_PAL_SAMPLE_COUNTS": ",".join(
        str(value) for value in av_config.PALETTE_SAMPLE_COUNTS),
    "CBRSIM_PAL_VALIDATE_FRAMES": str(
        av_config.PALETTE_VALIDATE_FRAMES),
    "CBRSIM_PAL_SEG_TRAIN_FRAMES": str(
        av_config.PALETTE_SEGMENT_TRAIN_FRAMES),
    "CBRSIM_PAL_SEG_VALIDATE_FRAMES": str(
        av_config.PALETTE_SEGMENT_VALIDATE_FRAMES),
    "CBRSIM_PAL_SEG_GAIN_REL": str(
        av_config.PALETTE_SEGMENT_GAIN_RELATIVE),
    "CBRSIM_PAL_SEG_GAIN_ABS": str(
        av_config.PALETTE_SEGMENT_GAIN_PER_PIXEL),
}

ALLOWED = {
    "source": ({key for section, key in ENV_MAP if section == "source"}
               | {"preprocess"}),
    "video": {key for section, key in ENV_MAP if section == "video"},
    "output": {key for section, key in ENV_MAP if section == "output"},
    "encoder": {key for section, key in ENV_MAP if section == "encoder"},
    "palette": {key for section, key in ENV_MAP if section == "palette"},
    "analysis": {"source_canvas", "source_par", "source_spec",
                 "tail_seconds"},
    # Publication metadata only. Deliberately outside ENV_MAP so a title edit
    # cannot change the encode identity or invalidate a cached sim artifact.
    "youtube": {"analysis_title", "playback_title", "source_label",
                "source_label_ja", "source_url"},
    # Disc-image release metadata, for the same reason as [youtube]: naming a
    # release must not change the encode identity.
    "release": {"title", "title_ja"},
    # Comparison-video composition: which footage fills each panel, how the
    # panels are synchronised, and the text drawn on the frame. Also outside
    # ENV_MAP, for the same reason as [youtube] - retiming a panel or editing a
    # label must not change the encode identity. The nested [comparison.panels]
    # tables are validated by tools/comparison_layout.py, which owns their
    # meaning.
    "comparison": {"badge", "title", "audio_panel", "audio_intro_panel",
                   "audio_note", "output", "duration", "tail_seconds",
                   "panels", "youtube"},
}
REQUIRED = {
    "source": {"path", "fps", "duration"},
    "video": {"width", "height", "fit"},
    "output": {"directory", "emit_decisions"},
    "encoder": {"cold_cap"},
    "palette": {"algorithm"},
}


def _toml_scalar(value: Any) -> str:
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, list):
        return ",".join(_toml_scalar(item) for item in value)
    return str(value)


@dataclass(frozen=True)
class EncodeProfile:
    path: Path
    data: dict[str, Any]
    sha256: str

    def section(self, name: str) -> dict[str, Any]:
        return dict(self.data.get(name, {}))

    @property
    def output_dir(self) -> Path:
        """Direct managed path for this profile's disposable sim output."""

        from cbr_paths import sim_work_dir

        env: dict[str, str] = {}
        apply_profile_env(self, env)
        return sim_work_dir(env)

    @property
    def requested_output_dir(self) -> Path:
        """Profile spelling retained only as a human-readable artifact name."""

        return Path(self.data["output"]["directory"])

    @property
    def decision_log(self) -> Path:
        return self.output_dir / "decisions.pkl"

    @property
    def artifact_stem(self) -> str:
        """Stable build name derived only from the TOML filename."""
        stem = self.path.stem
        if not _ARTIFACT_STEM_RE.fullmatch(stem):
            raise ValueError(
                f"{self.path}: TOML filename stem must match "
                "[A-Za-z0-9][A-Za-z0-9._-]*")
        return stem

    @property
    def sim_stem(self) -> str:
        """Shared media stem used as the parallel-run isolation key."""
        from cbr_paths import sim_stem
        return sim_stem(
            self.data["source"]["path"],
            self.data["video"]["width"],
            self.data["video"]["height"],
        )

    @property
    def artifact_dir(self) -> Path:
        return ARTIFACT_ROOT / self.artifact_stem

    @property
    def pack_output(self) -> Path:
        return self.artifact_dir / "MOVIE.DAT"

    @property
    def temp_dir(self) -> Path:
        return TEMP_ROOT / self.artifact_stem

    @property
    def build_dir(self) -> Path:
        return self.temp_dir / "build"

    @property
    def disc_staging_dir(self) -> Path:
        return self.temp_dir / "disc"

    @property
    def disc_iso(self) -> Path:
        return ARTIFACT_ROOT / f"{self.artifact_stem}.iso"

    @property
    def disc_cue(self) -> Path:
        return ARTIFACT_ROOT / f"{self.artifact_stem}.cue"

    # A release build (DEBUG=0) writes its own disc so it never overwrites the
    # DEBUG disc built from the same packed stream.
    @property
    def release_disc_iso(self) -> Path:
        return ARTIFACT_ROOT / f"{self.artifact_stem}_release.iso"

    @property
    def release_disc_cue(self) -> Path:
        return ARTIFACT_ROOT / f"{self.artifact_stem}_release.cue"

    # Japan keeps the plain release name, matching the Makefile, so the paths
    # every other tool already uses stay valid. Another region gets its own
    # pair rather than overwriting it.
    def region_release_disc_iso(self, region: str) -> Path:
        return ARTIFACT_ROOT / f"{self.artifact_stem}{_region_suffix(region)}_release.iso"

    def region_release_disc_cue(self, region: str) -> Path:
        return ARTIFACT_ROOT / f"{self.artifact_stem}{_region_suffix(region)}_release.cue"

    @property
    def analysis_title(self) -> str | None:
        """Profile-authored YouTube title for the analysis render."""
        return self.data.get("youtube", {}).get("analysis_title")

    @property
    def playback_title(self) -> str | None:
        """Profile-authored YouTube title for the playback recording."""
        return self.data.get("youtube", {}).get("playback_title")

    @property
    def source_label(self) -> str | None:
        """One-line English source credit used by the description templates."""
        return self.data.get("youtube", {}).get("source_label")

    @property
    def source_label_ja(self) -> str | None:
        return self.data.get("youtube", {}).get("source_label_ja")

    @property
    def source_url(self) -> str | None:
        """Where the master came from. Optional; not every source has one."""
        return self.data.get("youtube", {}).get("source_url")

    @property
    def release_title(self) -> str:
        """Human name for the disc-image release. Falls back to the stem."""
        return self.data.get("release", {}).get("title") or self.artifact_stem

    @property
    def release_title_ja(self) -> str:
        return (self.data.get("release", {}).get("title_ja")
                or self.release_title)


def load_profile(path: str | os.PathLike[str]) -> EncodeProfile:
    profile_path = Path(path).expanduser().resolve()
    raw = profile_path.read_bytes()
    data = tomllib.loads(raw.decode("utf-8"))
    version = data.pop("schema_version", None)
    if version != SCHEMA_VERSION:
        raise ValueError(
            f"{profile_path}: schema_version must be {SCHEMA_VERSION}, got {version!r}")
    unknown_sections = set(data) - set(ALLOWED)
    if unknown_sections:
        raise ValueError(
            f"{profile_path}: unknown sections: {', '.join(sorted(unknown_sections))}")
    for section, values in data.items():
        if not isinstance(values, dict):
            raise ValueError(f"{profile_path}: [{section}] must be a table")
        unknown = set(values) - ALLOWED[section]
        if unknown:
            raise ValueError(
                f"{profile_path}: unknown [{section}] keys: {', '.join(sorted(unknown))}")
    for section, keys in REQUIRED.items():
        missing = keys - set(data.get(section, {}))
        if missing:
            raise ValueError(
                f"{profile_path}: missing [{section}] keys: {', '.join(sorted(missing))}")
    if int(data["video"]["width"]) % 8 or int(data["video"]["height"]) % 8:
        raise ValueError(f"{profile_path}: video width and height must be multiples of 8")
    if (int(data["video"]["width"]) > av_config.SCREEN_WIDTH
            or int(data["video"]["height"]) > av_config.SCREEN_HEIGHT):
        raise ValueError(
            f"{profile_path}: video {data['video']['width']}x"
            f"{data['video']['height']} exceeds the H40 "
            f"{av_config.SCREEN_WIDTH}x{av_config.SCREEN_HEIGHT} aperture")
    total_tiles = int(data["video"]["width"]) * int(data["video"]["height"]) // 64
    active_tiles = int(data["video"].get("active_tiles", total_tiles))
    if not 1 <= active_tiles <= total_tiles:
        raise ValueError(
            f"{profile_path}: video.active_tiles must be within 1..{total_tiles}")
    requested_cold_cap = data["encoder"]["cold_cap"]
    if isinstance(requested_cold_cap, bool) or not isinstance(
            requested_cold_cap, (int, str)):
        raise ValueError(
            f"{profile_path}: encoder.cold_cap must be an integer or a "
            "'vblanks:cap' spec string")
    try:
        cold_ceiling = av_config.cold_cap(requested_cold_cap)
        # A per-interval spec must match the profile's VBlank cadence; fail
        # at profile load instead of deep inside sim/pack.
        av_config.frame_cold_caps(
            2, str(data["source"]["fps"]), requested_cold_cap)
    except ValueError as exc:
        raise ValueError(f"{profile_path}: encoder.cold_cap: {exc}") from exc
    if cold_ceiling > av_config.VRAM_PATTERN_POOL_TILES:
        raise ValueError(
            f"{profile_path}: encoder.cold_cap {cold_ceiling} exceeds "
            f"the {av_config.VRAM_PATTERN_POOL_TILES}-tile resident pool")
    cram_priority_search_frames = data.get(
        "encoder", {}).get("cram_quality_priority_search_frames")
    if cram_priority_search_frames is not None:
        if isinstance(cram_priority_search_frames, bool) or not isinstance(
                cram_priority_search_frames, int):
            raise ValueError(
                f"{profile_path}: encoder.cram_quality_priority_search_frames "
                "must be an integer")
        if cram_priority_search_frames < 0:
            raise ValueError(
                f"{profile_path}: encoder.cram_quality_priority_search_frames "
                "must be non-negative")
    if str(data["video"]["fit"]).lower() not in {"pad", "crop"}:
        raise ValueError(f"{profile_path}: video.fit must be 'pad' or 'crop'")
    resize_filter = str(data["video"].get("resize_filter", "lanczos")).lower()
    if resize_filter not in {"area", "bicubic", "bilinear", "lanczos", "neighbor"}:
        raise ValueError(
            f"{profile_path}: video.resize_filter must be area, bicubic, "
            "bilinear, lanczos, or neighbor")
    output_dither = str(
        data["video"].get("output_dither", "bayer")).lower()
    if output_dither not in {
            "bayer", "edge-attenuated-bayer", "none"}:
        raise ValueError(
            f"{profile_path}: video.output_dither must be bayer, "
            "edge-attenuated-bayer, or none")
    youtube = data.get("youtube", {})
    if not isinstance(youtube, dict):
        raise ValueError(f"{profile_path}: [youtube] must be a table")
    for key in ("analysis_title", "playback_title", "source_label",
                "source_label_ja"):
        if key not in youtube:
            continue
        title = youtube[key]
        if not isinstance(title, str) or not title.strip():
            raise ValueError(
                f"{profile_path}: youtube.{key} must be a non-empty string")
        if "\n" in title:
            raise ValueError(
                f"{profile_path}: youtube.{key} must be a single line")
        if key.endswith("title") and len(title) > 100:
            raise ValueError(
                f"{profile_path}: youtube.{key} is {len(title)} characters; "
                "YouTube truncates a title at 100")
    release = data.get("release", {})
    if not isinstance(release, dict):
        raise ValueError(f"{profile_path}: [release] must be a table")
    for key in ("title", "title_ja"):
        if key not in release:
            continue
        title = release[key]
        if not isinstance(title, str) or not title.strip():
            raise ValueError(
                f"{profile_path}: release.{key} must be a non-empty string")
        if "\n" in title:
            raise ValueError(
                f"{profile_path}: release.{key} must be a single line")
    preprocess = data["source"].get("preprocess", {})
    if not isinstance(preprocess, dict):
        raise ValueError(f"{profile_path}: [source.preprocess] must be a table")
    unknown_preprocess = set(preprocess) - {"endpoint_snap", "auto_range"}
    if unknown_preprocess:
        raise ValueError(
            f"{profile_path}: unknown [source.preprocess] keys: "
            f"{', '.join(sorted(unknown_preprocess))}")
    if "endpoint_snap" in preprocess:
        endpoint_snap = preprocess["endpoint_snap"]
        if not isinstance(endpoint_snap, dict):
            raise ValueError(
                f"{profile_path}: [source.preprocess.endpoint_snap] must be a table")
        unknown_snap = set(endpoint_snap) - {"black_max", "white_min"}
        if unknown_snap:
            raise ValueError(
                f"{profile_path}: unknown [source.preprocess.endpoint_snap] keys: "
                f"{', '.join(sorted(unknown_snap))}")
        missing_snap = {"black_max", "white_min"} - set(endpoint_snap)
        if missing_snap:
            raise ValueError(
                f"{profile_path}: missing [source.preprocess.endpoint_snap] keys: "
                f"{', '.join(sorted(missing_snap))}")
        black_max = int(endpoint_snap["black_max"])
        white_min = int(endpoint_snap["white_min"])
        if not 0 <= black_max <= 255 or not 0 <= white_min <= 255:
            raise ValueError(
                f"{profile_path}: endpoint snap limits must be within 0..255")
        if black_max >= white_min:
            raise ValueError(
                f"{profile_path}: endpoint snap black_max must be below white_min")
    if "auto_range" in preprocess and not isinstance(
            preprocess["auto_range"], bool):
        raise ValueError(
            f"{profile_path}: source.preprocess.auto_range must be a boolean")
    source_canvas = data.get("analysis", {}).get("source_canvas")
    if source_canvas is not None:
        if (not isinstance(source_canvas, list) or len(source_canvas) != 2
                or any(isinstance(value, bool) or not isinstance(value, int)
                       or value <= 0 for value in source_canvas)):
            raise ValueError(
                f"{profile_path}: analysis.source_canvas must be "
                "[positive_width, positive_height]")
    profile = EncodeProfile(profile_path, data, hashlib.sha256(raw).hexdigest())
    # Validate the filename while loading so every consumer agrees on paths.
    profile.artifact_stem
    return profile


def apply_profile_env(
        profile: EncodeProfile,
        environ: MutableMapping[str, str] | None = None) -> dict[str, str]:
    """Apply all TOML-backed values, replacing inherited values unconditionally."""
    env = os.environ if environ is None else environ
    # PrgBuf, delivery jitter, and the matching quality capacity are derived
    # from content fps in av_config. Remove retired overrides so a parent shell
    # cannot turn them back into profile/session knobs.
    for retired in (
            "CBRSIM_DITHER",
            "CBRSIM_QUALITY_BUDGET_KB",
            "CBRSIM_RING_CAP_KB",
            "CBRSIM_TANK_KB"):
        env.pop(retired, None)
    applied: dict[str, str] = {}
    for (section, key), name in ENV_MAP.items():
        values = profile.data.get(section, {})
        if key not in values:
            continue
        value = _toml_scalar(values[key])
        env[name] = value
        applied[name] = value
    # Profiles without confirmed black-only tiles conservatively use the full
    # output grid. Always overwrite an inherited value so one source cannot
    # silently lend its smaller active area to the next encode.
    if "CBRSIM_ACTIVE_TILES" not in applied:
        video = profile.data["video"]
        value = str(int(video["width"]) * int(video["height"]) // 64)
        env["CBRSIM_ACTIVE_TILES"] = value
        applied["CBRSIM_ACTIVE_TILES"] = value
    for name, value in PROFILE_ENV_DEFAULTS.items():
        if name not in applied:
            env[name] = value
            applied[name] = value
    endpoint_snap = (profile.data["source"].get("preprocess", {})
                     .get("endpoint_snap"))
    if endpoint_snap is not None:
        snap_env = {
            "CBRSIM_PREPROCESS_ENDPOINT_SNAP_BLACK_MAX": endpoint_snap["black_max"],
            "CBRSIM_PREPROCESS_ENDPOINT_SNAP_WHITE_MIN": endpoint_snap["white_min"],
        }
        for name, value in snap_env.items():
            scalar = _toml_scalar(value)
            env[name] = scalar
            applied[name] = scalar
    auto_range = (profile.data["source"].get("preprocess", {})
                  .get("auto_range"))
    if auto_range is not None:
        scalar = _toml_scalar(auto_range)
        env["CBRSIM_PREPROCESS_AUTO_RANGE"] = scalar
        applied["CBRSIM_PREPROCESS_AUTO_RANGE"] = scalar
    env["CBRSIM_CONFIG"] = str(profile.path)
    applied["CBRSIM_CONFIG"] = str(profile.path)
    return applied


def consume_config_arg(
    argv: list[str] | None = None,
    *,
    required: bool = False,
) -> EncodeProfile | None:
    """Consume a required first positional profile and apply it immediately.

    ``sim.py`` and ``render_analysis.py`` evaluate settings at import time, so
    this small pre-parser must run before their other local imports. Import-only
    callers pass ``required=False`` and retain the historical no-profile test
    defaults; executable entry points pass ``required=True``.
    """
    args = sys.argv if argv is None else argv
    if not required:
        return None
    if len(args) < 2:
        raise SystemExit(
            "encode profile is required as the first positional argument: "
            f"{Path(args[0]).name} PROFILE.toml")
    config = args[1]
    if config == "--config" or config.startswith("--config="):
        raise SystemExit(
            "encode profile is positional; do not use --config: "
            f"{Path(args[0]).name} PROFILE.toml")
    if config.startswith("-"):
        raise SystemExit(
            "encode profile must be the first positional argument: "
            f"{Path(args[0]).name} PROFILE.toml")
    del args[1]
    try:
        profile = load_profile(config)
    except (OSError, ValueError, tomllib.TOMLDecodeError) as exc:
        raise SystemExit(f"invalid encode profile: {exc}") from exc
    apply_profile_env(profile)
    return profile


def profile_identity(profile: EncodeProfile | None) -> dict[str, Any] | None:
    if profile is None:
        return None
    return {"path": str(profile.path), "sha256": profile.sha256,
            "schema_version": SCHEMA_VERSION}


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("config")
    output = parser.add_mutually_exclusive_group()
    output.add_argument("--print-env", action="store_true")
    output.add_argument("--print-stem", action="store_true")
    output.add_argument("--print-sim-output", action="store_true")
    output.add_argument("--print-artifacts", action="store_true")
    args = parser.parse_args()
    try:
        profile = load_profile(args.config)
    except (OSError, ValueError, tomllib.TOMLDecodeError) as exc:
        raise SystemExit(str(exc)) from exc
    if args.print_env:
        print(json.dumps(apply_profile_env(profile, {}), indent=2, sort_keys=True))
    elif args.print_stem:
        print(profile.artifact_stem)
    elif args.print_sim_output:
        print(profile.output_dir)
    elif args.print_artifacts:
        print(json.dumps({
            "stem": profile.artifact_stem,
            "sim": str(profile.output_dir),
            "directory": str(profile.artifact_dir),
            "pack": str(profile.pack_output),
            "temporary": str(profile.temp_dir),
            "build": str(profile.build_dir),
            "disc_staging": str(profile.disc_staging_dir),
            "iso": str(profile.disc_iso),
            "cue": str(profile.disc_cue),
            "release_iso": str(profile.release_disc_iso),
            "release_cue": str(profile.release_disc_cue),
            "analysis_title": profile.analysis_title,
            "playback_title": profile.playback_title,
        }, indent=2, sort_keys=True))
    else:
        print(json.dumps({"path": str(profile.path), "sha256": profile.sha256,
                          "output": str(profile.output_dir),
                          "artifacts": str(profile.artifact_dir)}, indent=2))


if __name__ == "__main__":
    main()
