#!/usr/bin/env python3
"""Hash deterministic sim/pack outputs for sequential/parallel comparison."""

from __future__ import annotations

import argparse
import csv
import hashlib
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

from encode_config import load_profile  # noqa: E402


ARTIFACTS = ("HEADER.DAT", "BODY.DAT", "MOVIE.DAT")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def rows_for_profiles(profile_paths: list[Path]) -> list[dict[str, str]]:
    rows = []
    for profile_path in profile_paths:
        profile = load_profile(profile_path)
        decision = profile.decision_log
        if not decision.is_absolute():
            decision = ROOT / decision
        paths = [("decisions.pkl", decision)]
        paths.extend(
            (name, ROOT / profile.artifact_dir / name)
            for name in ARTIFACTS
        )
        for name, path in paths:
            if not path.is_file():
                raise FileNotFoundError(path)
            rows.append({
                "profile": str(profile.path),
                "artifact": name,
                "bytes": str(path.stat().st_size),
                "sha256": file_sha256(path),
            })
    return rows


def write_tsv(path: Path, rows: list[dict[str, str]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=("profile", "artifact", "bytes", "sha256"),
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(rows)


def read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open(encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("profiles", nargs="+", type=Path)
    parser.add_argument("--output", required=True, type=Path)
    parser.add_argument("--compare", type=Path)
    args = parser.parse_args()

    rows = rows_for_profiles(args.profiles)
    write_tsv(args.output, rows)
    print(f"snapshot: {args.output} ({len(rows)} artifacts)")
    if args.compare is not None:
        baseline = read_tsv(args.compare)
        if rows != baseline:
            print(
                f"artifact snapshot differs from {args.compare}",
                file=sys.stderr,
            )
            return 1
        print(f"artifact snapshot: MATCH {args.compare}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
