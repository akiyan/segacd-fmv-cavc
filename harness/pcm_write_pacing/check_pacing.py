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

1. ``write_wave_chunk`` contains no batched (MOVEP) wave write at all. The
   writer sets control-register bit 7 on every bank select, so by the
   manual's definition the IC is sounding on every call — including the
   untimed boot prefill. There is no state in which a burst is legal here,
   so the safe contract is the absence of the instruction, not a guard.
2. Every wave-RAM strobe in the paced path is at least MIN_PROJECT CPU
   cycles after the previous one, on every path through the loop bodies.
3. Every internal-register write in the writer, in ``pcm_on`` and in the boot
   init path is followed by an explicit delay. Those need 384 cycles while
   sounding, so the wave-RAM bank select in the control register must not be
   followed immediately by a wave write: the byte could still reach the
   previously selected bank.

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
# Internal registers of the RF5C164, addressed through the Sub CPU bus. Writes
# to these need 384 or more source clock cycles between accesses while
# sounding, versus 16 for external wave memory.
INTERNAL_REG = re.compile(
    r"move\.b\s+\S+\s*,\s*\((?:PCM_ENV|PCM_PAN|PCM_FDL|PCM_FDH|PCM_LSL|"
    r"PCM_LSH|PCM_ST|PCM_ONOFF|PCM_CTRL)\)\.l")
# Taken dbra adds 10 cycles between the last strobe of one iteration and the
# first strobe of the next.
DBRA_TAKEN = 10


def strip_comment(raw: str) -> str:
    return re.sub(r"/\*.*?\*/", "", raw).strip()


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

    # Contract 1: no batched wave write survives anywhere in the writer.
    writer_start = text.index("write_wave_chunk:")
    writer_end = text.index("sp_int2:")
    writer = re.sub(r"/\*.*?\*/", "", text[writer_start:writer_end], flags=re.S)
    if "movep" in writer.lower():
        print("FAIL  write_wave_chunk contains a MOVEP; that batches strobes "
              "below the RF5C164 minimum access period, and control bit 7 is "
              "set on every call so the chip is always sounding here")
        return 1

    failures = 0
    for label, end, extra in (("wwc_paced_loop8", "wwc_paced_tail", DBRA_TAKEN),
                              ("wwc_paced_tail_loop", "wwc_chunk_done", DBRA_TAKEN)):
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

    # Contract 3: every internal-register write in the boot init path is
    # followed by an explicit delay. Line-based, so no regex backtracking can
    # accept a bare newline as the required wait.
    naked = []
    checked = 0
    for path, start_label in ((SOURCE.parent / "movieplay_sp_ext.s",
                               "pcm_boot_init:"),
                              (SOURCE, "pcm_on:")):
        src_lines = path.read_text(encoding="utf-8").splitlines()
        begin = next(i for i, l in enumerate(src_lines)
                     if l.startswith(start_label))
        for i in range(begin, len(src_lines)):
            code = strip_comment(src_lines[i])
            if not INTERNAL_REG.search(code):
                continue
            checked += 1
            nxt = next((strip_comment(src_lines[j])
                        for j in range(i + 1, len(src_lines))
                        if strip_comment(src_lines[j])), "")
            if not nxt.startswith("PCM_REG_WAIT"):
                naked.append((path.name, i + 1, code))
    if naked:
        failures += 1
        print(f"FAIL  {len(naked)} internal-register write(s) are not followed "
              "by PCM_REG_WAIT; while sounding they need 384 or more cycles "
              "before the next access to the IC")
        for name, line_no, code in naked:
            print(f"      {name}:{line_no}: {code}")
    else:
        print(f"internal registers: all {checked} write(s) in the writer, "
              "pcm_on and pcm_boot_init are followed by PCM_REG_WAIT "
              "(384-cycle spacing) ok")

    if failures:
        print("pcm write pacing: FAIL")
        return 1
    print("pcm write pacing: OK")
    return 0


if __name__ == "__main__":
    sys.exit(main())
