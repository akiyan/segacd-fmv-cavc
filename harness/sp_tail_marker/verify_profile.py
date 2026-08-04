#!/usr/bin/env python3
"""Guard the diagnostic SP-tail marker build against pending-sector overlap."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))

import player_constants  # noqa: E402
import cavc_routing  # noqa: E402


def routing_bytes(header: bytes, constants: player_constants.PlayerConstants) -> bytes:
    """Return the exact route entries from the packed HEADER preload."""
    route_sector = (
        1
        + constants.paltab_sec
        + constants.dic_sectors
        + constants.adpcm_table_sectors
        + constants.wr0_sectors
        + constants.wr1_sectors
    )
    start = route_sector * player_constants.SECTOR
    stop = start + constants.routing_sec * player_constants.SECTOR
    region = header[start:stop]
    expected = constants.routing_sec * player_constants.SECTOR
    if len(region) != expected:
        raise ValueError(
            f"routing preload is truncated: {len(region)} bytes, expected {expected}")
    cavc_routing.validate_route_table(
        region, constants.frames, constants.routing_sec)
    return region[:constants.frames]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--header", required=True, type=Path)
    parser.add_argument("--max-pending-sectors", required=True, type=int)
    args = parser.parse_args()

    raw = args.header.read_bytes()
    constants = player_constants.parse_header_sector(
        raw[:player_constants.SECTOR])
    routes = routing_bytes(raw, constants)
    word_counts = [
        cavc_routing.decode_word_sectors(entry)
        for entry in routes
    ]
    maximum = max(word_counts, default=0)
    frames = [
        frame for frame, count in enumerate(word_counts)
        if count == maximum
    ]
    if maximum > args.max_pending_sectors:
        raise SystemExit(
            "SP tail marker build has only two relocated pending destinations: "
            f"route maximum is {maximum} sectors at frames {frames[:8]}, "
            f"limit is {args.max_pending_sectors}")
    print(
        "SP tail marker profile guard: "
        f"max Word pending={maximum} sectors at frames={frames[:8]} "
        f"(limit {args.max_pending_sectors})")


if __name__ == "__main__":
    main()
