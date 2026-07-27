#!/usr/bin/env python3
"""Small atomic filesystem publication helpers."""

from __future__ import annotations

import os
from pathlib import Path
import uuid


def replace_symlink(alias: Path, target: Path, *, directory: bool = False) -> None:
    """Atomically replace a file/symlink alias with a new symlink."""

    alias = Path(alias).absolute()
    target = Path(target).resolve()
    alias.parent.mkdir(parents=True, exist_ok=True)
    if alias.exists() and alias.is_dir() and not alias.is_symlink():
        raise IsADirectoryError(f"symlink alias is a directory: {alias}")
    temporary = alias.parent / (
        f".{alias.name}.{os.getpid()}.{uuid.uuid4().hex}.tmp")
    try:
        temporary.symlink_to(target, target_is_directory=directory)
        os.replace(temporary, alias)
    finally:
        temporary.unlink(missing_ok=True)
