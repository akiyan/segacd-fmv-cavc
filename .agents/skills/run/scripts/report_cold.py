#!/usr/bin/env python3
"""Report the configured and realized timed cold delivery from one sim run."""

from __future__ import annotations

import argparse
import csv
import json
import pickle
from pathlib import Path
from typing import Any


def _configured_cap(decisions: dict[str, Any]) -> int:
    try:
        return int(decisions["config"]["hardware"]["max_cold"])
    except (KeyError, TypeError, ValueError):
        return int(decisions["max_cold"])


def cold_report(decisions: dict[str, Any]) -> dict[str, Any]:
    transfers = decisions.get("pattern_transfers")
    if not isinstance(transfers, dict) or "tiles" not in transfers:
        raise ValueError("decisions.pkl has no physical pattern_transfers.tiles trace")

    tiles = [int(value) for value in transfers["tiles"]]
    if len(tiles) < 2:
        raise ValueError("physical cold trace has no timed frames after frame 0")

    timed = tiles[1:]
    realized_max = max(timed)
    matching_frames = [
        frame_no
        for frame_no, value in enumerate(tiles)
        if frame_no > 0 and value == realized_max
    ]
    configured_cap = _configured_cap(decisions)
    if realized_max > configured_cap:
        raise ValueError(
            f"realized timed cold {realized_max} exceeds configured cap "
            f"{configured_cap}"
        )

    profile = decisions.get("config", {}).get("profile", {})
    return {
        "configured_cold_cap": configured_cap,
        "realized_timed_max_cold": realized_max,
        "frames_at_max": len(matching_frames),
        "first_frame_at_max": matching_frames[0],
        "last_frame_at_max": matching_frames[-1],
        "frame0_cold_excluded": tiles[0],
        "timed_frame_count": len(timed),
        "profile": profile.get("path"),
        "profile_sha256": profile.get("sha256"),
    }


def analysis_timed_max(path: Path) -> int:
    values: list[int] = []
    with path.open("r", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle, delimiter="\t")
        if reader.fieldnames is None or "status_cold" not in reader.fieldnames:
            raise ValueError(f"{path} has no status_cold column")
        for row_no, row in enumerate(reader):
            frame_text = row.get("frame")
            frame_no = int(frame_text) if frame_text not in (None, "") else row_no
            if frame_no > 0:
                values.append(int(row["status_cold"]))
    if not values:
        raise ValueError(f"{path} has no timed status_cold rows")
    return max(values)


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Report configured cold cap and realized physical timed maximum; "
            "frame 0 is boot-loaded and excluded."
        )
    )
    parser.add_argument("decisions", type=Path, help="completed sim decisions.pkl")
    parser.add_argument(
        "--analysis-tsv",
        type=Path,
        help="optional final analysis TSV whose status_cold maximum must match",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="emit one JSON object instead of the human-readable summary",
    )
    args = parser.parse_args()

    with args.decisions.open("rb") as handle:
        decisions = pickle.load(handle)
    report = cold_report(decisions)

    if args.analysis_tsv is not None:
        tsv_max = analysis_timed_max(args.analysis_tsv)
        report["analysis_timed_max_cold"] = tsv_max
        if tsv_max != report["realized_timed_max_cold"]:
            raise ValueError(
                f"analysis status_cold max {tsv_max} does not match physical "
                f"transfer max {report['realized_timed_max_cold']}"
            )

    if args.json:
        print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    else:
        print(
            "cold delivery: "
            f"configured_cap={report['configured_cold_cap']} "
            f"realized_timed_max={report['realized_timed_max_cold']} "
            f"frames_at_max={report['frames_at_max']} "
            f"first_frame={report['first_frame_at_max']} "
            f"last_frame={report['last_frame_at_max']} "
            f"frame0_excluded={report['frame0_cold_excluded']}"
        )
        if "analysis_timed_max_cold" in report:
            print(
                "analysis cross-check: "
                f"status_cold_max={report['analysis_timed_max_cold']} MATCH"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
