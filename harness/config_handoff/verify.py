#!/usr/bin/env python3
"""Prove that packing is independent of inherited per-source CBRSIM values."""
from __future__ import annotations

import argparse
import hashlib
import os
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
sys.path.insert(0, str(TOOLS))


PER_SOURCE_ENV = {
    "CBRSIM_SRC", "CBRSIM_FPS", "CBRSIM_DURATION", "CBRSIM_SOURCE_SAR",
    "CBRSIM_W", "CBRSIM_H", "CBRSIM_GEOMETRY_FIT",
    "CBRSIM_ACTIVE_TILES",
    "CBRSIM_MASTER_VF", "CBRSIM_RAW_VF", "CBRSIM_OUT",
    "CBRSIM_VRAM_TILES", "CBRSIM_QUALITY_BUDGET_KB", "CBRSIM_RING_CAP_KB",
    "CBRSIM_MAX_COLD", "CBRSIM_COLD_CAP",
}
POLLUTED = {
    "CBRSIM_SRC": "wrong.mp4", "CBRSIM_FPS": "15",
    "CBRSIM_W": "320", "CBRSIM_H": "144",
    "CBRSIM_VRAM_TILES": "7", "CBRSIM_QUALITY_BUDGET_KB": "1",
    "CBRSIM_RING_CAP_KB": "1", "CBRSIM_MAX_COLD": "1",
    "CBRSIM_COLD_CAP": "1",
}
ARTIFACTS = ("HEADER.DAT", "BODY.DAT", "MOVIE.DAT", "paltab.bin", "palidx.bin")


def digest(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as source:
        while chunk := source.read(1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def run_pack(
        decision: Path, output: Path, extension: Path,
        env: dict[str, str]) -> None:
    command = [
        sys.executable, str(TOOLS / "pack_stream.py"),
        "--dec-log", str(decision), "--output", str(output),
        "--sp-extension", str(extension),
    ]
    subprocess.run(command, cwd=ROOT, env=env, check=True)






def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("decision", type=Path,
                        help="an existing decision log, preferably a 30fps/full-height one")
    parser.add_argument(
        "--sp-extension", required=True, type=Path,
        help="linked movieplay_sp_ext.bin to embed in the packed preload")
    args = parser.parse_args()
    decision = args.decision.resolve()
    if not decision.exists():
        raise SystemExit(f"not found: {decision}")
    extension = args.sp_extension.resolve()
    if not extension.exists():
        raise SystemExit(f"not found: {extension}")

    clean = {key: value for key, value in os.environ.items() if key not in PER_SOURCE_ENV}
    polluted = dict(clean)
    polluted.update(POLLUTED)
    with tempfile.TemporaryDirectory(prefix="config-handoff-") as td:
        temp = Path(td)
        run_pack(
            decision, temp / "clean" / "MOVIE.DAT", extension, clean)
        run_pack(
            decision, temp / "polluted" / "MOVIE.DAT", extension, polluted)
        for name in ARTIFACTS:
            clean_hash = digest(temp / "clean" / name)
            polluted_hash = digest(temp / "polluted" / name)
            if clean_hash != polluted_hash:
                raise SystemExit(
                    f"FAIL: {name} differs: clean={clean_hash} polluted={polluted_hash}")
            print(f"{name}: IDENTICAL {clean_hash}")
    print("PASS: pack output is independent of inherited per-source CBRSIM values")


if __name__ == "__main__":
    main()
