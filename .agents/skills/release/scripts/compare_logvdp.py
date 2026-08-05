#!/usr/bin/env python3
"""Compare the GPGX LOGVDP DMA trace of a release recording with a DEBUG baseline.

A release build draws no DEBUG HUD, so it cannot produce a HUD TSV and the
frame-aligned `harness/gpgx_logvdp/extract_frame_tsv.py` equivalence check does
not apply to it. What remains available is the core's own DMA trace, which both
builds emit. When the packed stream is byte-identical, the release player must
do the same pattern work as the qualified DEBUG player, minus the HUD's
name-table writes, and it must not move DMA out of blanking.

This tool states that comparison exactly. It classifies every DMA update the
core logged, separates the player's own transfers from the BIOS/CD-player
startup, and reports the blanking/active-display split in the core's own unit
(the "access" counts the trace prints). It does not convert those counts into
VRAM words: the trace is a timing model, not the encoder's R2V accounting.
"""

from __future__ import annotations

import argparse
import collections
import json
import re
import sys
from pathlib import Path

# "[163(163)][796936(76)] DMA type 2 (204 access/line)(3344 cycles left)
#  -> 199 access (65535 remaining) (4ae)"
DMA_UPDATE = re.compile(
    r"^\[libretro ERROR\] "
    r"\[(?P<vcounter>\d+)\(\d+\)\]\[\d+\(\d+\)\] "
    r"DMA type (?P<dma_type>\d+) \((?P<rate>\d+) access/line\)"
    r"\(\d+ cycles left\)-> (?P<accesses>\d+) access "
    r"\(\d+ remaining\) \((?P<pc>[0-9a-f]+)\)"
)
DMA_ENDS = re.compile(r"-->DMA ends in \d+ cycles")
CPU_FROZEN = re.compile(r"-->CPU frozen for (?P<cycles>\d+) cycles")

# The player runs from 68000 work RAM. Its mirrors appear both as ff.... and as
# the sign-extended ffff.... form, so compare the low 24 bits.
WORK_RAM_START = 0xFF0000


def _program_counter(raw: str) -> int:
    return int(raw, 16) & 0xFFFFFF


def _is_player(pc: int) -> bool:
    return pc >= WORK_RAM_START


class Trace:
    """Per-region DMA accounting for one compact RetroArch log."""

    def __init__(self, path: Path) -> None:
        self.path = path
        self.updates = 0
        self.freeze_max = 0
        self.freeze_events = 0
        # region -> rate -> [events, accesses]
        self.by_rate: dict[str, dict[int, list[int]]] = {
            "player": collections.defaultdict(lambda: [0, 0]),
            "startup": collections.defaultdict(lambda: [0, 0]),
        }
        self.sites: dict[str, collections.Counter] = {
            "player": collections.Counter(),
            "startup": collections.Counter(),
        }
        self.core_errors: collections.Counter = collections.Counter()
        self._read()

    def _read(self) -> None:
        with self.path.open("r", errors="replace") as handle:
            for line in handle:
                match = DMA_UPDATE.match(line)
                if match:
                    self.updates += 1
                    pc = _program_counter(match["pc"])
                    region = "player" if _is_player(pc) else "startup"
                    rate = int(match["rate"])
                    bucket = self.by_rate[region][rate]
                    bucket[0] += 1
                    bucket[1] += int(match["accesses"])
                    self.sites[region][f"{pc:06x}"] += int(match["accesses"])
                    continue
                frozen = CPU_FROZEN.search(line)
                if frozen:
                    self.freeze_events += 1
                    self.freeze_max = max(self.freeze_max, int(frozen["cycles"]))
                    continue
                if line.startswith("[libretro ERROR]") and not DMA_ENDS.search(line):
                    self.core_errors[line.strip()[:120]] += 1

    def phase_split(self, region: str) -> dict:
        """Split one region's DMA into blanking and active display.

        The core reports how many accesses a DMA may perform per line, and that
        rate is what distinguishes the two phases: blanking allows many
        accesses per line, active display only a few. Take the highest rate the
        region actually used as its blanking rate rather than hard-coding a
        display mode, and treat every lower rate as active display.
        """
        rates = self.by_rate[region]
        if not rates:
            return {
                "blanking_events": 0,
                "blanking_accesses": 0,
                "active_events": 0,
                "active_accesses": 0,
                "active_share": 0.0,
                "blanking_rate": None,
                "rates": {},
            }
        blanking_rate = max(rates)
        blank = [0, 0]
        active = [0, 0]
        for rate, (events, accesses) in rates.items():
            target = blank if rate == blanking_rate else active
            target[0] += events
            target[1] += accesses
        total = blank[1] + active[1]
        return {
            "blanking_events": blank[0],
            "blanking_accesses": blank[1],
            "active_events": active[0],
            "active_accesses": active[1],
            "active_share": (active[1] / total) if total else 0.0,
            "blanking_rate": blanking_rate,
            "rates": {str(r): {"events": v[0], "accesses": v[1]} for r, v in sorted(rates.items())},
        }

    def summary(self) -> dict:
        return {
            "path": str(self.path),
            "dma_updates": self.updates,
            "cpu_freeze_events": self.freeze_events,
            "cpu_freeze_max_cycles": self.freeze_max,
            "player": self.phase_split("player"),
            "startup": self.phase_split("startup"),
            "player_sites": dict(self.sites["player"].most_common(8)),
            "core_errors": dict(self.core_errors.most_common(8)),
        }


def _fmt(value: int) -> str:
    return f"{value:,}"


def _report_region(name: str, split: dict) -> None:
    total = split["blanking_accesses"] + split["active_accesses"]
    print(f"  {name}: {_fmt(total)} accesses, blanking rate {split['blanking_rate']}/line")
    print(
        f"    blanking      : {_fmt(split['blanking_accesses']):>14} accesses"
        f"  events={_fmt(split['blanking_events'])}"
    )
    print(
        f"    active display: {_fmt(split['active_accesses']):>14} accesses"
        f"  events={_fmt(split['active_events'])}"
        f"  ({100 * split['active_share']:.3f}%)"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Compare a release recording's LOGVDP DMA trace with a qualified DEBUG baseline."
    )
    parser.add_argument(
        "--baseline",
        required=True,
        type=Path,
        help="compact RetroArch log of the gate-PASS DEBUG recording",
    )
    parser.add_argument(
        "--release",
        required=True,
        type=Path,
        help="compact RetroArch log of the release recording",
    )
    parser.add_argument("--json", type=Path, help="write the full comparison as JSON")
    parser.add_argument(
        "--tolerance",
        type=float,
        default=0.05,
        help="fraction the release may exceed the baseline by, absorbing the "
        "different Replay start frame and bounded window (default: 0.05)",
    )
    args = parser.parse_args(argv)

    for path in (args.baseline, args.release):
        if not path.is_file():
            parser.error(f"log not found: {path}")

    baseline = Trace(args.baseline)
    release = Trace(args.release)

    print(f"=== DEBUG baseline === {args.baseline}")
    print(f"  DMA updates {_fmt(baseline.updates)}   CPU freeze max {_fmt(baseline.freeze_max)} cycles")
    _report_region("player  ", baseline.phase_split("player"))
    _report_region("startup ", baseline.phase_split("startup"))
    print(f"=== release === {args.release}")
    print(f"  DMA updates {_fmt(release.updates)}   CPU freeze max {_fmt(release.freeze_max)} cycles")
    _report_region("player  ", release.phase_split("player"))
    _report_region("startup ", release.phase_split("startup"))

    base_player = baseline.phase_split("player")
    rel_player = release.phase_split("player")
    findings: list[str] = []

    new_errors = {
        text: count
        for text, count in release.core_errors.items()
        if text not in baseline.core_errors
    }
    if new_errors:
        findings.append(f"core reported {len(new_errors)} error kind(s) absent from the baseline")

    # Judge the absolute amount of DMA that reaches active display, not its
    # share. Removing the HUD lowers the total, so an unchanged absolute spill
    # necessarily raises the share; that is bookkeeping, not a regression. What
    # corrupts a frame is DMA actually running while the raster is live.
    #
    # The two runs use separately generated input Replays, so START lands on a
    # different emulator frame and the bounded window ends at a different point
    # in the movie. Allow a small tolerance for that instead of demanding
    # equality the harness never promises.
    tolerance = 1.0 + args.tolerance
    if base_player["active_accesses"] and (
        rel_player["active_accesses"] > base_player["active_accesses"] * tolerance
    ):
        findings.append(
            "player DMA reaches active display more than the baseline does "
            f"({_fmt(rel_player['active_accesses'])} vs {_fmt(base_player['active_accesses'])}"
            f" accesses, tolerance {100 * args.tolerance:.0f}%)"
        )

    base_total = base_player["blanking_accesses"] + base_player["active_accesses"]
    rel_total = rel_player["blanking_accesses"] + rel_player["active_accesses"]
    if base_total and rel_total > base_total * tolerance:
        findings.append(
            "release player DMA does more work than the DEBUG baseline "
            f"({_fmt(rel_total)} vs {_fmt(base_total)} accesses); a release build "
            "should never exceed the build that also drew the HUD"
        )

    print()
    print("player DMA in blanking:")
    print(
        f"  baseline {100 * (1 - base_player['active_share']):.3f}%"
        f"   release {100 * (1 - rel_player['active_share']):.3f}%"
    )
    print("player DMA reaching active display (the gated quantity):")
    print(
        f"  baseline {_fmt(base_player['active_accesses'])}"
        f"   release {_fmt(rel_player['active_accesses'])} accesses"
    )
    print(f"core errors outside the DMA trace: baseline {len(baseline.core_errors)}, release {len(release.core_errors)}")

    verdict = "PASS" if not findings else "FAIL"
    print()
    print(f"LOGVDP comparison: {verdict}")
    for finding in findings:
        print(f"  - {finding}")

    if args.json:
        args.json.write_text(
            json.dumps(
                {
                    "verdict": verdict,
                    "findings": findings,
                    "baseline": baseline.summary(),
                    "release": release.summary(),
                },
                indent=2,
                sort_keys=True,
            ),
            encoding="utf-8",
        )
        print(f"JSON: {args.json}")

    return 0 if verdict == "PASS" else 1


if __name__ == "__main__":
    sys.exit(main())
