#!/usr/bin/env python3
"""Prove the playback wave-RAM writer obeys the RF5C164 access-period spec.

The official MEGA-CD HARDWARE MANUAL "PCM SOUND SOURCE" (VER 1.0 1991/10/14),
section 4-5, requires external wave-memory writes to be spaced 16 or more
source clock cycles apart while the IC is sounding. The Sub CPU and the
RF5C164 share the 12.5 MHz clock (32,552 Hz x 384), so 16 source clocks are
16 CPU cycles. Writing faster is not rejected by any bus signal: the real
chip silently drops or corrupts the over-paced bytes, which reached playback
as a continuous periodic hiss (issue #81). Emulators and the Mega EverDrive
Pro FPGA do not model the minimum access period, so only real hardware
exposes a violation — which is exactly why this must be a build-time proof
rather than a recording gate.

The check reads ``boot/movieplay_sp.s`` and verifies two contracts:

1. ``write_wave_chunk`` selects the paced path whenever ``pcm_running`` is
   nonzero, so the MOVEP burst core is reachable only while sounding is
   suspended (where the manual allows unrestricted writes).
2. Every wave-RAM strobe in the paced path is at least MIN_PROJECT CPU
   cycles after the previous one, on every path through the loop bodies.

The cycle table below covers only the instructions the paced block is allowed
to contain. An unknown instruction is a failure, not a guess: whoever edits
the loop must re-derive its timing here.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

SOURCE = Path(__file__).resolve().parents[2] / "boot" / "movieplay_sp.s"

# Spec floor and project margin, in CPU cycles at the shared 12.5 MHz clock.
MIN_SPEC = 16
MIN_PROJECT = 20

# 68000 cycle counts for the exact operand forms the paced block may use.
# The strobe instruction itself counts toward the distance to the NEXT strobe:
# distance = cycles(strobe) + cycles(instructions between strobes).
CYCLES = {
    ("move.b", "(a0)+", "(a1)"): 12,
    ("addq.w", "#2", "a1"): 8,
    ("subq.w", "#1", "d1"): 4,
    ("subq.w", "#1", "d4"): 4,
    ("andi.w", "#0x0007", "d4"): 8,
    ("tst.w", "d4", None): 4,
    ("lsr.w", "#3", "d1"): 12,          # 6 + 2*3
    ("move.w", "d4", "d1"): 4,
}
STROBE = ("move.b", "(a0)+", "(a1)")
# Taken dbra adds 10 cycles between the last strobe of one iteration and the
# first strobe of the next.
DBRA_TAKEN = 10


def parse_block(lines: list[str], start: str, end: str) -> list[tuple[str, str, str | None]]:
    """Return (mnemonic, src, dst) tuples between two labels, comments stripped."""
    grabbing = False
    block: list[tuple[str, str, str | None]] = []
    for raw in lines:
        line = re.sub(r"/\*.*?\*/", "", raw).strip()
        if line.startswith(start + ":"):
            grabbing = True
            continue
        if grabbing and line.startswith(end + ":"):
            return block
        if not grabbing or not line or line.endswith(":"):
            continue
        parts = line.split(None, 1)
        mnemonic = parts[0]
        operands = [p.strip() for p in parts[1].split(",")] if len(parts) > 1 else []
        src = operands[0] if operands else None
        dst = operands[1] if len(operands) > 1 else None
        block.append((mnemonic, src, dst))
    raise SystemExit(f"{SOURCE}: block {start}..{end} not found")


def strobe_distances(block: list[tuple[str, str, str | None]],
                     loop_extra: int) -> list[int]:
    """Cycle distances between consecutive strobes, including the loop seam."""
    distances = []
    accumulating = None
    first_prefix = 0
    for instruction in block:
        mnemonic, src, dst = instruction
        if mnemonic in ("dbra", "beq", "bne", "bra"):
            continue  # flow control handled via loop_extra
        key = (mnemonic, src, dst)
        if key not in CYCLES:
            raise SystemExit(
                f"{SOURCE}: unknown instruction in paced block: "
                f"{mnemonic} {src},{dst} — add its exact 68000 cycle count "
                "to CYCLES and re-derive the pacing proof")
        if key == STROBE:
            if accumulating is None:
                first_prefix = 0
            else:
                distances.append(accumulating)
            accumulating = CYCLES[key]
        elif accumulating is not None:
            accumulating += CYCLES[key]
        else:
            first_prefix += CYCLES[key]
    if accumulating is None:
        raise SystemExit(f"{SOURCE}: paced block contains no wave-RAM strobe")
    # Loop seam: last strobe -> (rest of body) -> dbra -> (pre-strobe prefix) -> first strobe
    distances.append(accumulating + loop_extra + first_prefix)
    return distances


def main() -> int:
    text = SOURCE.read_text(encoding="utf-8")
    lines = text.splitlines()

    # Contract 1: sounding selects the paced path before the burst core.
    guard = re.search(
        r"tst\.w\s+pcm_running\s*(?:/\*.*?\*/\s*)?\n\s*beq\s+wwc_burst",
        text)
    if not guard:
        print("FAIL  write_wave_chunk no longer routes sounding writes away "
              "from the burst core (tst.w pcm_running / beq wwc_burst missing)")
        return 1
    burst_index = text.index("wwc_burst:")
    if "movep.l" not in text[burst_index:burst_index + 4000].lower():
        print("FAIL  the burst core after wwc_burst no longer contains MOVEP — "
              "re-check which path is which before trusting this proof")
        return 1
    paced_index = text.index("wwc_paced:")
    if "movep" in text[paced_index:burst_index].lower():
        print("FAIL  the paced block contains a MOVEP; that batches strobes "
              "below the RF5C164 minimum access period")
        return 1

    failures = 0
    for label, end, extra in (("wwc_paced_loop8", "wwc_paced_tail", DBRA_TAKEN),
                              ("wwc_paced_tail_loop", "wwc_burst", DBRA_TAKEN)):
        block = parse_block(lines, label, end)
        distances = strobe_distances(block, extra)
        worst = min(distances)
        status = "ok" if worst >= MIN_PROJECT else "FAIL"
        print(f"{label}: {len(distances)} strobe gaps, worst {worst} cycles "
              f"(spec >= {MIN_SPEC}, project >= {MIN_PROJECT}) {status}")
        if worst < MIN_PROJECT:
            failures += 1
            if worst < MIN_SPEC:
                print(f"      {worst} cycles VIOLATES the RF5C164 sounding-time "
                      "spec; the real chip will corrupt these writes")
            else:
                print(f"      {worst} cycles meets the bare spec but not the "
                      f"{MIN_PROJECT}-cycle project margin that covers cycle-"
                      "table uncertainty")

    if failures:
        print("pcm write pacing: FAIL")
        return 1
    print("pcm write pacing: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
