#!/usr/bin/env python3
"""Check in-game player playback in a BlastEm VDP trace against the SIM.

The in-game test host (PLAYER.md, In-game player) calls the movie with its
name table at --nt and its own plane B elsewhere. Once the host has set its
horizontal-interrupt line counter (register 10), a play starts when the movie
points plane B at its name table and ends when the host's plane B returns. For every play this checks, from VDP writes alone:

* one publication per movie frame (the first name-table row written by the
  movie), and every displayed field from frame 0 to the end shows exactly the
  SIM picture of the latest publication, so no pattern load disturbs a frame
  on screen;
* every VRAM, CRAM and VSRAM write of the movie lands inside a vertical blank
  (within 38 lines of the movie's VBlank hook entry, which BlastEm logs as
  the hook's register-15 write) and inside the movie's VRAM budget (pattern
  pool, its name table and the first horizontal-scroll entry);
* the publication cadence, reported as VBlanks between publications.

It then reads the host's result rows from its name table after each play.
This is a diagnostic, not a recording gate; no assembly is reimplemented.
"""
import argparse
import json
from pathlib import Path
import pickle
import struct
import sys
from collections import Counter

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "harness/blastem"))
import encode_config
from event_stream import iter_events, rgb333
from player_constants import parse_header_sector

LINE_CYCLES = 3420
VBLANK_LINES = 262 - 224
FONT_TILE = 1400            # boot/ingame_host_ip.s
# boot/ingame_host_ip.s: H-int line counter, every 96 lines, or 7 when the
# host carries the music-driver load (HOST_LOAD_LINES).
HOST_REG10 = (0x5F, 0x07)


def expected_pictures(profile_path, frames):
    """Return the SIM's per-frame picture hashes (palette applied)."""
    profile = encode_config.load_profile(profile_path)
    with profile.pack_decision_input() as path:
        with path.open("rb") as source:
            decisions = pickle.load(source)
    if np.any(decisions.get("scroll", {}).get("active", False)):
        raise ValueError("this check requires a non-scrolling movie")
    columns, rows, cells, tile = decisions["geom"]
    if tile != 8 or cells != columns * rows or len(decisions["frames"]) != frames:
        raise ValueError("SIM geometry or frame count differs from HEADER.DAT")
    indices = np.zeros((cells, 64), np.uint8)
    palettes = np.zeros(cells, np.uint8)
    expected = []
    for frame, updates in enumerate(decisions["frames"]):
        for cell, palette, key in updates:
            indices[cell] = np.frombuffer(key, np.uint8)
            palettes[cell] = palette
        rgb = np.zeros((4, 16, 3), np.uint16)
        rgb[:, 1:] = decisions["fade"]["active_frame_cram"][frame]
        cram = rgb[..., 0] | (rgb[..., 1] << 3) | (rgb[..., 2] << 6)
        expected.append(cram[palettes[:, None], indices].astype(">u2").tobytes())
    return columns, rows, expected


def picture(vram, cram, nt, col0, row0, columns, rows):
    """Return the displayed movie picture (rgb333 words) from VDP memory."""
    words = np.fromiter(map(rgb333, struct.unpack(">64H", cram)), np.uint16)
    entries = np.frombuffer(vram, ">u2", count=2048, offset=nt).reshape(32, 64)
    entries = entries[row0:row0 + rows, col0:col0 + columns].reshape(-1)
    patterns = np.frombuffer(vram, np.uint8).reshape(2048, 32)[entries & 0x7FF]
    indices = np.stack((patterns >> 4, patterns & 15), axis=2).reshape(-1, 8, 8)
    indices = np.where((entries & 0x800)[:, None, None], indices[:, :, ::-1], indices)
    indices = np.where((entries & 0x1000)[:, None, None], indices[:, ::-1, :], indices)
    colors = words[((entries >> 13) & 3)[:, None] * 16 + indices.reshape(-1, 64)]
    return colors.astype(">u2").tobytes()


def host_rows(vram, nt):
    """Decode the test host's result rows (4 hex digits per value); row 4
    holds the music-driver load statistics when the host carries one."""
    values = []
    for row in (2, 3, 4):
        entries = struct.unpack_from(">64H", vram, nt + row * 128)
        digits, row_values = [], []
        for entry in entries[1:31]:
            tile = entry & 0x7FF
            if FONT_TILE <= tile < FONT_TILE + 16:
                digits.append(tile - FONT_TILE)
            elif digits:
                row_values.append(int("".join(f"{d:X}" for d in digits), 16))
                digits = []
        values.append(row_values)
    return values


def check(trace, header, profile, nt, hscroll, profile_log=False):
    constants = parse_header_sector(header.read_bytes()[:2048], ingame=True)
    columns, rows, expected = expected_pictures(profile, constants.frames)
    col0, row0 = (40 - columns) // 2, (28 - rows) // 2
    pool_end = (1 + constants.pool) * 32
    first_entry = nt + 2 * (row0 * 64 + col0)
    allowed = ((0x20, pool_end), (nt, nt + 0x1000), (hscroll, hscroll + 4))
    movie_reg4 = nt >> 13
    blank_cycles = VBLANK_LINES * LINE_CYCLES
    vram, cram = bytearray(0x10000), bytearray(128)
    plays = []
    play = None
    host = False
    hook_cycle = None
    for event in iter_events(trace):
        if event.kind == "FRAME":
            # Between plays, keep the latest result rows the host drew.
            if play is None and plays:
                rows_now = host_rows(bytes(vram), nt)
                if any(rows_now):
                    plays[-1]["host_rows"] = rows_now
            continue
        if event.kind == "REGISTER":
            if event.address == 10 and event.data[0] in HOST_REG10:
                host = True
            if event.address == 15 and event.data[0] == 2 and play is not None:
                # The movie's VBlank hook starts here: the picture of the
                # active period that just ended is complete.
                hook_cycle = event.cycle
                if play["published"]:
                    index = len(play["published"]) - 1
                    shown = picture(vram, cram, nt, col0, row0, columns, rows)
                    if index >= len(expected) or shown != expected[index]:
                        play["wrong_blanks"].append((play["blanks"], index))
                play["blanks"] += 1
            if event.address == 4 and host:
                if event.data[0] == movie_reg4 and play is None:
                    play = dict(published=[], wrong_blanks=[], outside_blank=[],
                                outside_budget=[], latest=0, blanks=0)
                    hook_cycle = event.cycle
                elif event.data[0] != movie_reg4 and play is not None:
                    play["complete"] = True
                    plays.append(play)
                    play = None
            continue
        memory = {"VRAM": vram, "CRAM": cram}.get(event.kind)
        if memory is not None:
            memory[event.address:event.address + len(event.data)] = event.data
        if play is None:
            continue
        offset = event.cycle - hook_cycle
        play["latest"] = max(play["latest"], offset)
        if offset > blank_cycles:
            play["outside_blank"].append((play["blanks"], event.kind, event.address,
                                          round(offset / LINE_CYCLES, 1)))
        if event.kind == "VRAM":
            if not any(lo <= event.address < hi for lo, hi in allowed):
                play["outside_budget"].append((play["blanks"], event.address))
            # BlastEm records each VRAM word low byte first.
            if event.address == first_entry + 1:
                play["published"].append(play["blanks"])
        elif (event.kind == "VSRAM" and event.address >= 4
              and not (profile_log and 0x40 <= event.address < 0x50)):
            play["outside_budget"].append((play["blanks"], f"VSRAM {event.address}"))
    if play is not None:
        play["complete"] = False
        plays.append(play)
    if not plays:
        raise ValueError("no movie play found in the trace")
    results = []
    for number, play in enumerate(plays, 1):
        published = play["published"]
        gaps = Counter(b - a for a, b in zip(published, published[1:]))
        # Lateness against frame 1's publication, as the player measures it.
        late = [max(0, at - published[1] - constants.vsync_n * (i - 1))
                for i, at in enumerate(published) if i >= 1] if len(published) > 1 else []
        results.append({
            "play": number,
            "complete": play["complete"],
            "publications": len(published),
            "expected_frames": constants.frames,
            "blanks_before_frame0": published[0] if published else None,
            "blanks_frame0_to_last": published[-1] - published[0] if published else None,
            "nominal_blanks_frame0_to_last": (constants.frames - 1) * constants.vsync_n,
            "blanks_between_publications": dict(sorted(gaps.items())),
            "late_frames": sum(1 for value in late if value),
            "max_lateness_blanks": max(late, default=0),
            "mean_lateness_blanks": round(sum(late) / len(late), 1) if late else 0,
            "publications_after_a_longer_gap": sum(
                n for gap, n in gaps.items() if gap > constants.vsync_n),
            "blanks_showing_a_wrong_picture": len(play["wrong_blanks"]),
            "first_wrong": play["wrong_blanks"][:5],
            "writes_outside_vblank": len(play["outside_blank"]),
            "first_outside_vblank": play["outside_blank"][:5],
            "latest_write_lines_after_hook_entry": round(play["latest"] / LINE_CYCLES, 1),
            "writes_outside_budget": len(play["outside_budget"]),
            "first_outside_budget": play["outside_budget"][:5],
            "host_rows_after": play.get("host_rows"),
        })
    ok = all(r["publications"] == constants.frames and not r["blanks_showing_a_wrong_picture"]
             and not r["writes_outside_vblank"] and not r["writes_outside_budget"]
             for r in results if r["complete"])
    return {"result": "PASS" if ok else "FAIL", "plays": results}


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("trace", type=Path, help="BlastEm BLSTEL VDP event log")
    parser.add_argument("--header", type=Path, required=True, help="the stream's HEADER.DAT")
    parser.add_argument("--profile", type=Path, required=True)
    parser.add_argument("--nt", type=lambda v: int(v, 0), default=0xC000)
    parser.add_argument("--hscroll", type=lambda v: int(v, 0), default=0xF400)
    parser.add_argument("--profile-log", action="store_true",
                        help="allow the IDLE_PROFILE build's VSRAM 0x40..0x4F log")
    parser.add_argument("--json", type=Path)
    args = parser.parse_args()
    report = check(args.trace, args.header, args.profile, args.nt, args.hscroll,
                   args.profile_log)
    text = json.dumps(report, indent=1)
    if args.json:
        args.json.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if report["result"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
