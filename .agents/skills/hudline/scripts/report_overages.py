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
import tmpfs_workspace  # noqa: E402


GATE_COLUMNS = {
    "sector_slip": "sector_slip",
    "control_desync": "control_desync",
    "audio_resync": "audio_resync",
    "vblank_spill": "vblank_spill",
    "prgbuf_jitter_peak_kib": "prgbuf_jitter_peak_kib",
}

MAXIMUM_COLUMNS = {
    **GATE_COLUMNS,
    "cd_wait_count": "cd_wait_count",
}

# The first three fields are cumulative counters and PrgBuf jitter is a sticky
# maximum. Repeating an over-limit value is state, not a new event.
TRANSITION_FIELDS = {
    "sector_slip",
    "control_desync",
    "audio_resync",
    "prgbuf_jitter_peak_kib",
}

HUD_COLUMNS = (
    ("palette_segment", "palette_segment", 1),
    ("sector_slip", "sector_slip", 1),
    ("control_desync", "control_desync", 1),
    ("audio_resync", "audio_resync", 1),
    ("audio_lead_256b", "audio_lead_256b", 2),
    ("cd_wait_count", "cd_wait_count", 1),
    ("sub_wait_scanlines", "sub_wait_scanlines", 2),
    ("vblank_spill", "vblank_spill", 1),
    ("adpcm_decode_units", "adpcm_decode_units", 2),
    ("transfer_ticks", "transfer_ticks", 3),
    ("cold_runs", "cold_runs", 2),
    ("prgbuf_jitter_peak_kib", "prgbuf_jitter_peak_kib", 2),
    ("flip_vcounter", "flip_vcounter", 2),
    ("first_share_exit_vcounter", "first_share_exit_vcounter", 2),
    ("pass2_delay_q4", "pass2_delay_q4", 2),
    ("pump_gap_ticks", "pump_gap_ticks", 3),
    ("apply_backpressure", "apply_backpressure", 1),
    ("msf_gap_recoveries", "msf_gap_recoveries", 1),
    ("reader_ahead_frames", "reader_ahead_frames", 1),
    ("reader_slot_sector", "reader_slot_sector", 1),
    ("transfer_vblanks", "transfer_vblanks", 1),
    ("transfer_end_vcounter", "transfer_end_vcounter", 2),
    ("pattern_dma_ready_vcounter", "pattern_dma_ready_vcounter", 2),
    (
        "name_table_dma_ready_vcounter",
        "name_table_dma_ready_vcounter",
        2,
    ),
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
        # The analyzer preserves V-counter fields as hexadecimal glyph text
        # such as "EE".
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


def cd_wait_statistics(
    rows: list[dict[str, str]],
) -> dict[str, int | float]:
    return field_statistics(rows, "cd_wait_count")


def adpcm_decode_statistics(
    rows: list[dict[str, str]],
) -> dict[str, int | float]:
    return field_statistics(rows, "adpcm_decode_units")


def pump_gap_statistics(
    rows: list[dict[str, str]],
) -> dict[str, int | float]:
    return field_statistics(rows, "pump_gap_ticks")


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


def format_cd_wait_statistics(result: dict[str, int | float]) -> str:
    return format_field_statistics("cd_wait_count", result)


def format_adpcm_decode_statistics(
    result: dict[str, int | float],
) -> str:
    return format_field_statistics("adpcm_decode_units", result)


def load_rows(path: Path) -> tuple[list[dict[str, str]], list[str]]:
    with path.open("r", encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source, delimiter="\t")
        fields = list(reader.fieldnames or ())
        required = {
            "loop",
            "frame",
            "capture_first",
            *MAXIMUM_COLUMNS.values(),
            "adpcm_decode_units",
            "pattern_dma_ready_vcounter",
            "name_table_dma_ready_vcounter",
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
    if int(gate.get("schema_version", 0)) != 16:
        raise SystemExit("overage report requires descriptive HUD gate schema 16")
    if "cd_wait_count" not in gate["maxima"]:
        raise SystemExit("gate JSON lacks diagnostic cd_wait_count maximum")
    if "cd_wait_count" in gate["limits"]:
        raise SystemExit("gate must not define a cd_wait_count limit")
    if list(gate.get("gate_fields", ())) != list(GATE_COLUMNS):
        raise SystemExit("gate_fields do not match the descriptive HUD gate")
    if list(gate.get("warning_fields", ())) != ["vblank_spill"]:
        raise SystemExit("warning_fields must contain only vblank_spill")
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
        (
            "cd_wait_count",
            "cd_wait_statistics",
            cd_wait_statistics(rows),
        ),
        (
            "adpcm_decode_units",
            "adpcm_decode_statistics",
            adpcm_decode_statistics(rows),
        ),
    ):
        recorded = gate.get(statistics_key)
        if recorded is None:
            raise SystemExit(f"gate JSON lacks {statistics_key}")
        for key in ("minimum", "maximum", "sample_count"):
            if int(recorded[key]) != int(expected[key]):
                raise SystemExit(
                    f"gate {field} {key} {recorded[key]} does not match "
                    f"TSV value {expected[key]}"
                )
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
    for column, gate_key in (
        ("reader_ahead_frames", "reader_ahead_max_frames"),
        ("reader_slot_sector", "reader_slot_sector_max"),
        ("transfer_vblanks", "transfer_vblanks_max"),
        ("transfer_end_vcounter", "transfer_end_vcounter_max"),
        (
            "first_share_exit_vcounter",
            "first_share_exit_vcounter_max",
        ),
        (
            "pattern_dma_ready_vcounter",
            "pattern_dma_ready_vcounter_max",
        ),
        (
            "name_table_dma_ready_vcounter",
            "name_table_dma_ready_vcounter_max",
        ),
    ):
        present = has_values(rows, column)
        declared = column in gate.get("diagnostic_fields", ())
        if present:
            actual = max(
                (as_int(row, column) for row in rows[1:]),
                default=0,
            )
            if gate_key not in gate:
                raise SystemExit(f"gate JSON lacks {gate_key}")
            if int(gate[gate_key]) != actual:
                raise SystemExit(
                    f"gate {column} maximum {gate[gate_key]} does not match "
                    f"TSV maximum {actual}"
                )
            if not declared:
                raise SystemExit(
                    f"gate diagnostic_fields omit available {column}")
        elif declared:
            raise SystemExit(
                f"gate declares {column} but HUD TSV has no {column} values")


def displayed_vblanks(rows: list[dict[str, str]]) -> list[int | None]:
    starts = [as_int(row, "capture_first") for row in rows]
    values: list[int | None] = [None] * len(rows)
    for index in range(1, len(rows) - 1):
        span = starts[index + 1] - starts[index]
        if span <= 0:
            raise SystemExit("capture_first must increase between content frames")
        values[index] = span
    return values


def cadence_normal_vblanks(content_fps: float) -> tuple[int, ...] | None:
    """Return the authoritative repeating cadence, when one is qualified."""
    return av_config.vblank_cadence_pattern(content_fps)


def cadence_target_for_display_frame(
    frame: int,
    cadence_pattern: tuple[int, ...] | None,
) -> int | None:
    """Return the phase target for the visible span stored at ``frame``."""
    if cadence_pattern is None or frame <= 0:
        return None
    return cadence_pattern[frame % len(cadence_pattern)]


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
    content_fps = float(gate["content_fps"])
    expected_frames = int(gate["expected_frames"])
    cadence_pattern = cadence_normal_vblanks(content_fps)
    edge_frames = (
        hud_gate.cadence_alert_edge_frames(content_fps)
        if cadence_pattern is not None else 0
    )
    vblank_targets = [
        cadence_target_for_display_frame(
            as_int(row, "frame"), cadence_pattern)
        for row in rows
    ]
    eligible_vblanks = [
        value is not None
        and not hud_gate.cadence_alert_frame_is_exempt(
            as_int(row, "frame"),
            expected_frames,
            content_fps,
        )
        for row, value in zip(rows, vblanks, strict=True)
    ]
    evaluated_vblanks = sum(eligible_vblanks)
    vblank_warning_count = (
        sum(
            eligible and value != target
            for eligible, value, target in zip(
                eligible_vblanks, vblanks, vblank_targets, strict=True)
        )
        if cadence_pattern is not None
        else None
    )
    vblank_exempted_warning_count = (
        sum(
            value is not None
            and not eligible
            and value != target
            for eligible, value, target in zip(
                eligible_vblanks, vblanks, vblank_targets, strict=True)
        )
        if cadence_pattern is not None
        else None
    )
    if "display_vblank_edge_exempt_frames" in gate:
        for key, actual in (
            ("display_vblank_alert_evaluated_frames", evaluated_vblanks),
            ("display_vblank_edge_exempt_frames", edge_frames),
            (
                "display_vblank_exempted_violation_count",
                vblank_exempted_warning_count,
            ),
            ("display_vblank_violation_count", vblank_warning_count),
        ):
            if (
                key in gate
                and actual is not None
                and int(gate[key]) != int(actual)
            ):
                raise SystemExit(
                    f"gate {key} {gate[key]} does not match "
                    f"HUD TSV value {actual}"
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
        if column in fields and has_values(rows, column)
    ]
    summary = []
    summary.append(f"HUD gate: {gate['gate']}; alert: {alert}.")
    summary.append(
        "Frame 0 is untimed boot staging and is excluded from every metric, "
        "gate, scale, and VBLANK statistic."
    )
    summary.append(
        format_cd_wait_statistics(cd_wait_statistics(rows))
    )
    summary.append(
        format_adpcm_decode_statistics(adpcm_decode_statistics(rows))
    )
    if "pump_gap_ticks" in fields and has_values(rows, "pump_gap_ticks"):
        summary.append(
            format_field_statistics(
                "pump_gap_ticks",
                pump_gap_statistics(rows),
            )
        )
    if (
        "apply_backpressure" in fields
        and has_values(rows, "apply_backpressure")
    ):
        blocked = sum(
            as_int(row, "apply_backpressure") != 0
            for row in rows[1:]
        )
        summary.append(
            "APPLY back-pressure frames "
            f"(timed first loop): {blocked}."
        )
    if (
        "reader_ahead_frames" in fields
        and has_values(rows, "reader_ahead_frames")
    ):
        reader_ahead_frames = max(
            as_int(row, "reader_ahead_frames")
            for row in rows[1:]
        )
        reader_slot_sector = max(
            as_int(row, "reader_slot_sector")
            for row in rows[1:]
        )
        summary.append(
            "Reader lead (timed first loop): "
            f"{reader_ahead_frames} complete frame slots + "
            f"sector {reader_slot_sector}."
        )
    if all(
        column in fields and has_values(rows, column)
        for column in (
            "pattern_dma_ready_vcounter",
            "name_table_dma_ready_vcounter",
            "first_share_exit_vcounter",
            "transfer_vblanks",
            "transfer_end_vcounter",
        )
    ):
        summary.append(
            "Main transfer maxima (timed first loop): "
            "pattern/NT ready V-counter "
            f"{max(as_int(row, 'pattern_dma_ready_vcounter') for row in rows[1:]):02X}/"
            f"{max(as_int(row, 'name_table_dma_ready_vcounter') for row in rows[1:]):02X}, "
            "first-share exit V-counter "
            f"{max(as_int(row, 'first_share_exit_vcounter') for row in rows[1:]):02X}, "
            "opened VBlank budget count "
            f"{max(as_int(row, 'transfer_vblanks') for row in rows[1:])}, "
            "final exit V-counter "
            f"{max(as_int(row, 'transfer_end_vcounter') for row in rows[1:]):02X}."
        )
    summary.append(
        "cd_wait_count is diagnostic only and does not affect the HUD gate status."
    )
    expected_frames = int(gate["expected_frames"])
    if expected_frames != len(rows):
        summary.append(
            f"Incomplete failed first loop: observed {len(rows)} / "
            f"expected {expected_frames} frames."
        )
    if cadence_pattern is None:
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
            f"(normal phase "
            f"{'/'.join(hex_value(value) for value in cadence_pattern)}; "
            f"first/last "
            f"{edge_frames} content frames excluded from ALERT; "
            f"{vblank_exempted_warning_count} observed edge violation(s))."
        )
    summary.append(
        f"Gate conditions: {gate_warning_count} warning, "
        f"{gate_failure_count} failure."
    )
    if not events:
        return "\n".join(summary) + "\n"
    headers = [
        "frame",
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
        "edge values remain diagnostic, but the first/last 4 content frames "
        "at 30 fps and 2 at 15 fps do not raise its ALERT; frame 0 and the "
        "terminal hold are not reported."
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    args = parse_args()
    rows, fields = load_rows(args.tsv)
    gate = load_gate(args.gate_json)
    validate(rows, gate)
    report = render_markdown(rows, fields, gate)
    if args.output is not None:
        actual_output, lease = tmpfs_workspace.allocate_file(
            args.output,
            kind="hud-overage-report",
            key=f"{args.tsv.stem}-{args.gate_json.stem}",
            required_bytes=1024 * 1024,
        )
        try:
            actual_output.write_text(report, encoding="utf-8")
        finally:
            lease.release()
        print(f"REPORT={actual_output}")
    print(report, end="")


if __name__ == "__main__":
    main()
