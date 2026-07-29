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


def _below_videos(path):
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
        cold_cap=int(env.get("CBRSIM_COLD_CAP", "0")),
    )


def sim_work_dir(environ=None):
    env = os.environ if environ is None else environ
    explicit = env.get("CBRSIM_OUT")
    if explicit:
        requested = Path(explicit)
        if not _below_videos(requested):
            return requested
        if not env.get("CBRSIM_CONFIG"):
            return requested
        import tmpfs_workspace

        return tmpfs_workspace.managed_directory_path(
            kind="sim", key=sim_cache_key(env))
    return Path("videos") / sim_stem() / "tmp"


def artifact_path(suffix, ext="mp4", sim_dir=None):
    stem = sim_stem()
    return Path("videos") / f"{stem}_{suffix}.{ext}"
