#!/usr/bin/env python3
"""Report exact DEBUG HUD frames that exceed an upload-gate limit."""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import sys
from collections import defaultdict
from pathlib import Path


SCRIPT = Path(__file__).resolve()
REPO = SCRIPT.parents[4]
TOOLS = REPO / "tools"
sys.path.insert(0, str(TOOLS))
import av_config  # noqa: E402
import hud_gate  # noqa: E402


GATE_COLUMNS = {
    "S": "slip",
    "D": "desync",
    "R": "resync",
    "M": "main_vblank_wait",
    "J": "prgbuf_jitter_peak_kib",
}

MAXIMUM_COLUMNS = {
    **GATE_COLUMNS,
    "C": "cd_wait",
}

# S/D/R are cumulative counters and J is a sticky maximum. Once they exceed a
# limit, repeating the same value on every later frame is state, not another
# event. Report the transition into each new over-limit value instead.
TRANSITION_FIELDS = {"S", "D", "R", "J"}

HUD_COLUMNS = (
    ("P", "palette", 2),
    ("S", "slip", 2),
    ("D", "desync", 2),
    ("R", "resync", 2),
    ("L", "lead_256b", 2),
    ("C", "cd_wait", 2),
    ("W", "sub_wait_lines", 2),
    ("M", "main_vblank_wait", 2),
    ("A", "sub_adpcm_decode_units", 2),
    ("U", "main_pattern_ticks", 4),
    ("N", "cold_runs_low8", 2),
    ("J", "prgbuf_jitter_peak_kib", 2),
    ("Q", "prgbuf_min_patterns_raw16", 4),
    ("G", "sub_poll_gap_ticks", 4),
    ("B", "apply_guard_blocked", 2),
    ("K", "slip_msf_gap_count", 2),
    ("H", "prgbuf_physical_peak_patterns", 4),
    ("X", "reader_ahead_raw16", 4),
    ("Y", "pattern_vblank1_words", 3),
    ("O", "pattern_vblank1_exit_vcounter", 2),
    ("Z", "pattern_vblank2_words", 3),
    ("Y3", "pattern_vblank3_words", 3),
    ("Y4", "pattern_vblank4_words", 3),
    ("T", "pattern_transfer_vblanks", 1),
    ("I", "pattern_exit_vcounter", 2),
    ("V", "flip_vcounter", 2),
    ("E", "pass2_entry_q4", 2),
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tsv", type=Path)
    parser.add_argument("--gate-json", type=Path, required=True)
    parser.add_argument(
        "--output",
        type=Path,
        help="also write the Markdown report to this path",
    )
    args = parser.parse_args()
    if args.tsv.suffix.lower() != ".tsv":
        parser.error("HUD input must use the .tsv extension")
    return args


def as_int(row: dict[str, str], column: str) -> int:
    text = row.get(column, "").strip()
    if not text:
        return 0
    try:
        return int(round(float(text)))
    except ValueError:
        # The analyzer preserves some HUD-native fields, notably H40's V
        # counter, as hexadecimal glyph text such as "EE".
        return int(text, 16)


def has_values(rows: list[dict[str, str]], column: str) -> bool:
    """Return true only when the optional HUD field was actually decoded."""
    return bool(rows and column in rows[0]) and any(
        row.get(column, "").strip() for row in rows
    )


def hex_value(value: int, digits: int = 2) -> str:
    return f"0x{value:0{max(digits, len(f'{value:X}'))}X}"


def field_statistics(
    rows: list[dict[str, str]],
    column: str,
) -> dict[str, int | float]:
    """Summarize one HUD field over timed first-loop frames only."""
    values = (
        [as_int(row, column) for row in rows[1:]]
        if rows and column in rows[0]
        else []
    )
    if not values:
        return {
            "minimum": 0,
            "mean": 0.0,
            "median": 0.0,
            "maximum": 0,
            "sample_count": 0,
        }
    return {
        "minimum": min(values),
        "mean": statistics.fmean(values),
        "median": statistics.median(values),
        "maximum": max(values),
        "sample_count": len(values),
    }


def c_statistics(rows: list[dict[str, str]]) -> dict[str, int | float]:
    return field_statistics(rows, "cd_wait")


def a_statistics(rows: list[dict[str, str]]) -> dict[str, int | float]:
    return field_statistics(rows, "sub_adpcm_decode_units")


def g_statistics(rows: list[dict[str, str]]) -> dict[str, int | float]:
    return field_statistics(rows, "sub_poll_gap_ticks")


def format_field_statistics(
    field: str,
    result: dict[str, int | float],
) -> str:
    return (
        f"{field} statistics (timed first loop; frame 0 excluded): "
        f"min={int(result['minimum'])} "
        f"mean={float(result['mean']):.3f} "
        f"median={float(result['median']):g} "
        f"max={int(result['maximum'])} "
        f"n={int(result['sample_count'])}."
    )


def format_c_statistics(result: dict[str, int | float]) -> str:
    return format_field_statistics("C", result)


def format_a_statistics(result: dict[str, int | float]) -> str:
    return format_field_statistics("A", result)


def load_rows(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open("r", encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source, delimiter="\t")
        fields = list(reader.fieldnames or ())
        required = {
            "loop",
            "frame",
            "capture_first",
            *MAXIMUM_COLUMNS.values(),
            "sub_adpcm_decode_units",
        }
        missing = required - set(fields)
        if missing:
            raise SystemExit(f"HUD TSV lacks columns: {sorted(missing)}")
        rows = [row for row in reader if as_int(row, "loop") == 0]
    if not rows:
        raise SystemExit("HUD TSV contains no first-loop rows")
    frames = [as_int(row, "frame") for row in rows]
    if frames != list(range(len(rows))):
        raise SystemExit("first-loop HUD frames must be contiguous and start at zero")
    return rows, fields


def load_gate(path: Path) -> dict:
    raw_gate = json.loads(path.read_text(encoding="utf-8"))
    try:
        gate = hud_gate.normalize_result(raw_gate)
    except ValueError as exc:
        raise SystemExit(f"invalid HUD gate JSON: {exc}") from exc
    for key in (
        "content_fps",
        "expected_frames",
        "observed_first_loop_frames",
        "limits",
        "maxima",
    ):
        if key not in gate:
            raise SystemExit(f"gate JSON lacks {key}")
    for key in GATE_COLUMNS:
        if key not in gate["limits"] or key not in gate["maxima"]:
            raise SystemExit(f"gate JSON lacks {key} limit or maximum")
    if "C" not in gate["maxima"]:
        raise SystemExit("gate JSON lacks diagnostic C maximum")
    if int(gate.get("schema_version", 0)) >= 5:
        if "C" in gate["limits"]:
            raise SystemExit("schema-5+ gate must not define a C limit")
        if list(gate.get("gate_fields", ())) != list(GATE_COLUMNS):
            raise SystemExit("schema-5+ gate_fields do not match the HUD gate")
    return gate


def validate(rows: list[dict[str, str]], gate: dict) -> None:
    frames = len(rows)
    if int(gate["observed_first_loop_frames"]) != frames:
        raise SystemExit("gate observed_first_loop_frames does not match HUD TSV")
    expected = int(gate["expected_frames"])
    if expected != frames:
        incomplete_failure = (
            gate["gate"] == "FAIL"
            and frames < expected
            and any(
                "first loop is incomplete" in str(message)
                for message in gate.get("failures", ())
            )
        )
        if not incomplete_failure:
            raise SystemExit(
                f"gate expected {expected} frames, TSV has {frames}")
    for field, column in MAXIMUM_COLUMNS.items():
        actual = max(
            (as_int(row, column) for row in rows[1:]),
            default=0,
        )
        if actual != int(gate["maxima"][field]):
            raise SystemExit(
                f"gate {field} maximum {gate['maxima'][field]} "
                f"does not match TSV maximum {actual}"
            )
    if int(gate.get("evaluation_first_frame", 1)) != 1:
        raise SystemExit("HUD gate must exclude untimed frame 0")
    for field, statistics_key, expected in (
        ("C", "c_statistics", c_statistics(rows)),
        ("A", "a_statistics", a_statistics(rows)),
    ):
        recorded = gate.get(statistics_key)
        if recorded is None:
            if int(gate.get("schema_version", 0)) >= 4:
                raise SystemExit(f"gate JSON lacks {statistics_key}")
            continue
        for key in ("minimum", "maximum", "sample_count"):
            if int(recorded[key]) != int(expected[key]):
                raise SystemExit(
                    f"gate {field} {key} {recorded[key]} does not match "
                    f"TSV value {expected[key]}"
                )
    for field, column, gate_key in (
        ("H", "prgbuf_physical_peak_patterns",
         "prgbuf_physical_peak_patterns"),
        ("X", "reader_ahead_raw16", "reader_ahead_max_raw16"),
        ("Y", "pattern_vblank1_words", "pattern_vblank1_max_words"),
        ("O", "pattern_vblank1_exit_vcounter",
         "pattern_vblank1_exit_vcounter_max"),
        ("Z", "pattern_vblank2_words", "pattern_vblank2_max_words"),
        ("Y3", "pattern_vblank3_words", "pattern_vblank3_max_words"),
        ("Y4", "pattern_vblank4_words", "pattern_vblank4_max_words"),
        ("T", "pattern_transfer_vblanks", "pattern_transfer_vblank_max"),
        ("I", "pattern_exit_vcounter", "pattern_exit_vcounter_max"),
    ):
        present = has_values(rows, column)
        declared = field in gate.get("diagnostic_fields", ())
        if present:
            actual = max(
                (as_int(row, column) for row in rows[1:]),
                default=0,
            )
            if gate_key not in gate:
                raise SystemExit(f"gate JSON lacks {gate_key}")
            if int(gate[gate_key]) != actual:
                raise SystemExit(
                    f"gate {field} maximum {gate[gate_key]} does not match "
                    f"TSV maximum {actual}"
                )
            if not declared:
                raise SystemExit(
                    f"gate diagnostic_fields omit available {field}")
        elif declared:
            raise SystemExit(
                f"gate declares {field} but HUD TSV has no {column} values")
        for key in ("mean", "median"):
            if not math.isclose(
                float(recorded[key]),
                float(expected[key]),
                abs_tol=1e-12,
            ):
                raise SystemExit(
                    f"gate {field} {key} {recorded[key]} does not match "
                    f"TSV value {expected[key]}"
                )


def displayed_vblanks(rows: list[dict[str, str]]) -> list[int | None]:
    starts = [as_int(row, "capture_first") for row in rows]
    values: list[int | None] = [None] * len(rows)
    for index in range(1, len(rows) - 1):
        span = starts[index + 1] - starts[index]
        if span <= 0:
            raise SystemExit("capture_first must increase between content frames")
        values[index] = span
    return values


def cadence_normal_vblanks(content_fps: float) -> int | None:
    """Return an exact integer cadence, or None for rates such as 24 fps."""
    expected = av_config.vsync_n_for_fps(content_fps)
    integer_rate = av_config.NTSC_VSYNC / expected
    playback_rate = av_config.playback_fps_for_content(content_fps)
    if math.isclose(playback_rate, integer_rate, abs_tol=1e-9):
        return expected
    return None


def gate_overage_events(
    rows: list[dict[str, str]],
    gate: dict,
) -> dict[int, list[tuple[str, str, int, str, int]]]:
    events: dict[int, list[tuple[str, str, int, str, int]]] = defaultdict(list)
    for field, column in GATE_COLUMNS.items():
        limit = int(gate["limits"][field])
        if int(gate["maxima"][field]) <= limit:
            continue
        previous: int | None = None
        previous = as_int(rows[0], column)
        for index, row in enumerate(rows[1:], start=1):
            value = as_int(row, column)
            over = value > limit
            changed = previous is None or value != previous
            if over and (field not in TRANSITION_FIELDS or changed):
                severity = (
                    "WARNING"
                    if field in gate.get("warning_fields", ())
                    else "FAIL"
                )
                events[index].append((severity, field, value, ">", limit))
            previous = value
    return dict(sorted(events.items()))


def render_markdown(
    rows: list[dict[str, str]],
    fields: list[str],
    gate: dict,
) -> str:
    vblanks = displayed_vblanks(rows)
    events = gate_overage_events(rows, gate)
    normal_vblanks = cadence_normal_vblanks(float(gate["content_fps"]))

    evaluated_vblanks = sum(value is not None for value in vblanks)
    vblank_warning_count = (
        sum(
            value is not None and value != normal_vblanks
            for value in vblanks
        )
        if normal_vblanks is not None
        else None
    )
    gate_warning_count = sum(
        severity == "WARNING"
        for triggers in events.values()
        for severity, *_rest in triggers
    )
    gate_failure_count = sum(
        severity == "FAIL"
        for triggers in events.values()
        for severity, *_rest in triggers
    )
    alert = str(gate["alert"])
    if alert == "NONE" and vblank_warning_count:
        alert = "WARNING"
    available_hud = [
        (name, column, digits)
        for name, column, digits in HUD_COLUMNS
        if (
            column in fields
            and (
                column not in {
                    "prgbuf_min_patterns_raw16",
                    "sub_poll_gap_ticks",
                    "apply_guard_blocked",
                    "slip_msf_gap_count",
                    "prgbuf_physical_peak_patterns",
                    "reader_ahead_raw16",
                    "pattern_vblank1_words",
                    "pattern_vblank1_exit_vcounter",
                    "pattern_vblank2_words",
                    "pattern_vblank3_words",
                    "pattern_vblank4_words",
                    "pattern_transfer_vblanks",
                    "pattern_exit_vcounter",
                    "flip_vcounter",
                    "pass2_entry_q4",
                }
                or has_values(rows, column)
            )
        )
    ]
    summary = []
    summary.append(f"HUD gate: {gate['gate']}; alert: {alert}.")
    summary.append(
        "Frame 0 is untimed boot staging and is excluded from every metric, "
        "gate, scale, and VBLANK statistic."
    )
    summary.append(format_c_statistics(c_statistics(rows)))
    summary.append(format_a_statistics(a_statistics(rows)))
    if (
        "prgbuf_min_patterns_signed" in fields
        and has_values(rows, "prgbuf_min_patterns_signed")
    ):
        q_minimum = min(
            as_int(row, "prgbuf_min_patterns_signed")
            for row in rows[1:]
        )
        summary.append(
            f"Q logical minimum (timed first loop): {q_minimum} patterns; "
            f"underflow peak={max(0, -q_minimum)} patterns."
        )
    if "sub_poll_gap_ticks" in fields and has_values(rows, "sub_poll_gap_ticks"):
        summary.append(format_field_statistics("G", g_statistics(rows)))
    if (
        "apply_guard_blocked" in fields
        and has_values(rows, "apply_guard_blocked")
    ):
        blocked = sum(
            as_int(row, "apply_guard_blocked") != 0
            for row in rows[1:]
        )
        summary.append(
            "B APPLY back-pressure frames "
            f"(timed first loop): {blocked}."
        )
    if (
        "prgbuf_physical_peak_patterns" in fields
        and has_values(rows, "prgbuf_physical_peak_patterns")
    ):
        physical_peak = max(
            as_int(row, "prgbuf_physical_peak_patterns")
            for row in rows[1:]
        )
        summary.append(
            f"H physical PrgBuf peak (timed first loop): {physical_peak} "
            f"patterns ({physical_peak * 32} bytes)."
        )
    if (
        "reader_ahead_raw16" in fields
        and has_values(rows, "reader_ahead_raw16")
    ):
        reader_ahead = max(
            as_int(row, "reader_ahead_raw16")
            for row in rows[1:]
        )
        summary.append(
            "X reader lead (timed first loop): "
            f"{reader_ahead >> 8} complete frame slots + "
            f"sector {reader_ahead & 0xFF}."
        )
    split_columns = (
        ("Y", "pattern_vblank1_words"),
        ("O", "pattern_vblank1_exit_vcounter"),
        ("Z", "pattern_vblank2_words"),
        ("T", "pattern_transfer_vblanks"),
        ("I", "pattern_exit_vcounter"),
    )
    if all(
        column in fields and has_values(rows, column)
        for _field, column in split_columns
    ):
        split_maxima = {
            field: max(as_int(row, column) for row in rows[1:])
            for field, column in split_columns
        }
        later_columns = (
            ("Y3", "pattern_vblank3_words"),
            ("Y4", "pattern_vblank4_words"),
        )
        later_maxima = {
            field: max(as_int(row, column) for row in rows[1:])
            for field, column in later_columns
            if column in fields and has_values(rows, column)
        }
        later_text = (
            f", VB3/VB4 {later_maxima['Y3']}/{later_maxima['Y4']} words"
            if len(later_maxima) == 2 else ""
        )
        summary.append(
            "Y/O/Z/T/I/Y3/Y4 Main transfer-budget maxima "
            f"(timed first loop): {split_maxima['Y']}/"
            f"{split_maxima['Z']} words "
            f"({split_maxima['Y'] / 16:g}/"
            f"{split_maxima['Z'] / 16:g} patterns)"
            f"{later_text}, "
            f"first exit V-counter {split_maxima['O']:02X}, "
            f"opened VBlank budget count {split_maxima['T']}, "
            f"final exit V-counter {split_maxima['I']:02X}."
        )
    summary.append(
        "C is diagnostic only and does not affect the HUD gate status."
    )
    expected_frames = int(gate["expected_frames"])
    if expected_frames != len(rows):
        summary.append(
            f"Incomplete failed first loop: observed {len(rows)} / "
            f"expected {expected_frames} frames."
        )
    if normal_vblanks is None:
        summary.append(
            f"VBLANK warning rule: deferred for "
            f"{float(gate['content_fps']):g} fps."
        )
    else:
        warning_rate = (
            100.0 * vblank_warning_count / evaluated_vblanks
            if evaluated_vblanks
            else 0.0
        )
        summary.append(
            f"VBLANK warning rate / count / total: "
            f"{warning_rate:.2f}% / {vblank_warning_count} / "
            f"{evaluated_vblanks} "
            f"(normal {hex_value(normal_vblanks)})."
        )
    summary.append(
        f"Gate conditions: {gate_warning_count} warning, "
        f"{gate_failure_count} failure."
    )
    if not events:
        return "\n".join(summary) + "\n"
    headers = [
        "F",
        "Warning / over limit",
        "VBLANK",
        *[name for name, _, _ in available_hud],
    ]
    lines = [
        *summary,
        "",
        "| " + " | ".join(headers) + " |",
        "|" + "|".join("---" for _ in headers) + "|",
    ]
    frame_digits = max(4, len(f"{len(rows) - 1:X}"))
    for index, triggers in events.items():
        row = rows[index]
        trigger_text = ", ".join(
            f"{severity} {name} {hex_value(value)} {operator} "
            f"{hex_value(reference)}"
            for severity, name, value, operator, reference in triggers
        )
        vblank = (
            "—"
            if vblanks[index] is None
            else hex_value(int(vblanks[index]))
        )
        values = [
            hex_value(as_int(row, column), digits)
            for _name, column, digits in available_hud
        ]
        lines.append(
            "| "
            + " | ".join(
                [
                    hex_value(as_int(row, "frame"), frame_digits),
                    trigger_text,
                    vblank,
                    *values,
                ]
            )
            + " |"
        )
    lines.append("")
    lines.append(
        "VBLANK is derived from the next frame's capture start; "
        "frame 0 and the terminal hold are not reported."
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    args = parse_args()
    rows, fields = load_rows(args.tsv)
    gate = load_gate(args.gate_json)
    validate(rows, gate)
    report = render_markdown(rows, fields, gate)
    if args.output is not None:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding="utf-8")
    print(report, end="")


if __name__ == "__main__":
    main()
