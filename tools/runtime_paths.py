"""Runtime storage choices, independent of source profiles and codec decisions."""

from __future__ import annotations

import os
from pathlib import Path


DEFAULT_WORKSPACE = Path(__file__).resolve().parents[1] / "tmp" / "workspace"


def workspace_root() -> Path:
    # Preserve existing launchers while allowing ordinary disk filesystems.
    return Path(os.environ.get("CAVC_WORKSPACE_ROOT") or os.environ.get(
        "SEGACD_TMPFS_ROOT") or DEFAULT_WORKSPACE).expanduser().resolve()


def scratch_root() -> Path:
    path = Path(os.environ.get("CAVC_SCRATCH_ROOT") or os.environ.get(
        "TMPDIR") or workspace_root() / "scratch").expanduser().resolve()
    path.mkdir(parents=True, exist_ok=True)
    return path


def array_storage() -> str:
    value = os.environ.get("CAVC_ARRAY_STORAGE", "memory")
    if value not in ("memory", "disk"):
        raise ValueError("CAVC_ARRAY_STORAGE must be memory or disk")
    return value
