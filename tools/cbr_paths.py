#!/usr/bin/env python3
"""Shared direct paths for codec sim outputs and derived video artifacts."""
import os
import re
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _clean_part(value):
    text = str(value).strip() or "unknown"
    return re.sub(r"[^A-Za-z0-9._-]+", "_", text).strip("_") or "unknown"


def sim_stem(src=None, mode=None, width=None, height=None):
    src = src or os.environ.get("CBRSIM_SRC", "movies/disc1/061.mp4")
    mode = mode or os.environ.get("CBRSIM_MODE", "H32")
    width = int(width or os.environ.get("CBRSIM_W", "256"))
    height = int(height or os.environ.get("CBRSIM_H", "144"))
    return "%s_%s_%dx%d_%s" % (
        _clean_part(Path(src).stem),
        _clean_part(mode),
        width,
        height,
        "adpcm22",
    )


def _truthy(value):
    return str(value or "").strip().lower() in {"1", "true", "yes", "on"}


def _cold_cap_key(env):
    """Return the artifact-name cold cap identity for the effective env."""
    raw = env.get("CBRSIM_COLD_CAP", "").strip()
    if not raw:
        return "0"
    import av_config

    return av_config.cold_cap_key(raw)


def _below_retired_media_dir(path):
    try:
        Path(path).absolute().relative_to((PROJECT_ROOT / "videos").absolute())
    except ValueError:
        return False
    return True


def sim_cache_key(environ=None):
    """Return the deterministic managed-sim key for effective settings."""

    env = os.environ if environ is None else environ
    import sim_artifact_cache

    source = env.get("CBRSIM_SRC", "movies/disc1/061.mp4")
    identity = sim_artifact_cache.build_identity(
        source=source,
        emit_decisions=_truthy(env.get("CBRSIM_EMIT_DEC")),
        environ=env,
    )
    return sim_artifact_cache.readable_key(
        identity,
        mode=env.get("CBRSIM_MODE", "H32"),
        width=int(env.get("CBRSIM_W", "256")),
        height=int(env.get("CBRSIM_H", "144")),
        fps=env.get("CBRSIM_FPS", "15"),
        fit=env.get("CBRSIM_GEOMETRY_FIT", "pad"),
        cold_cap=_cold_cap_key(env),
    )


def sim_work_dir(environ=None):
    env = os.environ if environ is None else environ
    explicit = env.get("CBRSIM_OUT")
    if explicit:
        requested = Path(explicit)
        if not env.get("CBRSIM_CONFIG") and not _below_retired_media_dir(
                requested):
            return requested
        import tmpfs_workspace

        return tmpfs_workspace.managed_directory_path(
            kind="sim", key=sim_cache_key(env))
    import tmpfs_workspace

    # Make expands a few artifact prerequisites before the profile handoff
    # supplies CBRSIM_CONFIG/CBRSIM_SRC. Keep that parse-time placeholder
    # deterministic without hashing the obsolete default source path.
    if not env.get("CBRSIM_CONFIG"):
        return tmpfs_workspace.managed_directory_path(
            kind="sim", key=f"manual-{sim_stem()}")
    return tmpfs_workspace.managed_directory_path(
        kind="sim", key=sim_cache_key(env))


def artifact_path(suffix, ext="mp4", sim_dir=None):
    stem = sim_stem()
    return Path(f"{stem}_{suffix}.{ext}")
