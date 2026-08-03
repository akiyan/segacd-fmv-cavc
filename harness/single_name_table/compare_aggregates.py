#!/usr/bin/env python3
"""Compare every saved codec and playback aggregate without rerunning either."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path


OUTPUT_COLUMNS = (
    "source",
    "scope",
    "metric",
    "statistic",
    "main_value",
    "candidate_value",
    "delta",
    "delta_percent",
    "comparison",
)

HEX_FIELDS = {
    "frame_hex",
    "audio_lead_hex",
    "transfer_end_vcounter",
    "pattern_dma_ready_vcounter",
    "name_table_dma_ready_vcounter",
    "flip_vcounter",
    "first_share_exit_vcounter",
}

SIM_SUMMARY_PREFIXES = (
    "physical budget final:",
    "WordBuf ring:",
    "resolution=",
    "body_gross_bytes_per_frame=",
    "body_fixed_control_bytes_per_frame=",
    "body_variable_supply_bytes_per_frame=",
    "identity_run_control_reservation=",
    "physical_delivery_plan=",
    "PrgBuf_geometry=",
    "avg_codec_work_bytes_per_frame=",
    "VRAM_tiles=",
    "avg_PrgBuf_loads_per_frame=",
    "boot_vram_prefetch=",
    "boot_preload_patterns=",
    "WordBuf_ring=",
    "avg_L2_dedup_hit_per_frame=",
    "avg_L3_hit_per_frame=",
    "avg_noncurrent_budget_exact_loads=",
    "total_PrgBuf_pattern_bytes=",
    "L3_saved_CD_bytes=",
    "dedup_saved_ratio=",
    "quality_budget=",
    "PrgBuf:",
    "starved_frames=",
    "codec_work_bps=",
    "body_useful_bps=",
    "shadow_update_lists=",
    "upgrade(",
)

NUMBER_TOKEN_RE = re.compile(
    r"(?P<name>[A-Za-z][A-Za-z0-9_/-]*)="
    r"(?P<value>[+-]?(?:\d+(?:\.\d*)?|\.\d+))"
)
STARVED_PERCENT_RE = re.compile(
    r"starved_frames=\d+ \((?P<value>\d+(?:\.\d+)?)%\)"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--main-timeline", type=Path, required=True)
    parser.add_argument("--candidate-timeline", type=Path, required=True)
    parser.add_argument("--main-hud", type=Path, required=True)
    parser.add_argument("--candidate-hud", type=Path, required=True)
    parser.add_argument("--main-gate", type=Path, required=True)
    parser.add_argument("--candidate-gate", type=Path, required=True)
    parser.add_argument("--main-sim-log", type=Path, required=True)
    parser.add_argument("--candidate-sim-log", type=Path, required=True)
    parser.add_argument(
        "--main-sim-report",
        type=Path,
        help="optional completed sim report supplementing the main log",
    )
    parser.add_argument(
        "--candidate-sim-report",
        type=Path,
        help="optional completed sim report supplementing the candidate log",
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.suffix != ".tsv":
        parser.error("--output must use .tsv")
    return args


def digest(path: Path) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def decimal_text(value: Decimal) -> str:
    if value == value.to_integral_value():
        return str(int(value))
    return format(value.normalize(), "f")


def compare_values(main: Decimal, candidate: Decimal) -> tuple[str, str, str]:
    delta = candidate - main
    percent = ""
    if main != 0:
        percent = decimal_text(delta / abs(main) * Decimal(100))
    comparison = "equal" if delta == 0 else ("increase" if delta > 0 else "decrease")
    return decimal_text(delta), percent, comparison


def add_numeric(
    output: list[dict[str, str]],
    *,
    source: str,
    scope: str,
    metric: str,
    statistic: str,
    main: Decimal,
    candidate: Decimal,
) -> None:
    delta, percent, comparison = compare_values(main, candidate)
    output.append({
        "source": source,
        "scope": scope,
        "metric": metric,
        "statistic": statistic,
        "main_value": decimal_text(main),
        "candidate_value": decimal_text(candidate),
        "delta": delta,
        "delta_percent": percent,
        "comparison": comparison,
    })


def add_text(
    output: list[dict[str, str]],
    *,
    source: str,
    scope: str,
    metric: str,
    statistic: str,
    main: object,
    candidate: object,
) -> None:
    main_text = str(main)
    candidate_text = str(candidate)
    output.append({
        "source": source,
        "scope": scope,
        "metric": metric,
        "statistic": statistic,
        "main_value": main_text,
        "candidate_value": candidate_text,
        "delta": "",
        "delta_percent": "",
        "comparison": "equal" if main_text == candidate_text else "changed",
    })


def load_tsv(path: Path) -> tuple[list[str], list[dict[str, str]]]:
    with path.open("r", encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source, delimiter="\t")
        fields = list(reader.fieldnames or ())
        rows = list(reader)
    if not fields or not rows:
        raise ValueError(f"TSV is empty: {path}")
    return fields, rows


def parse_number(field: str, value: str) -> Decimal | None:
    value = value.strip()
    if not value:
        return None
    try:
        if field in HEX_FIELDS:
            return Decimal(int(value.removeprefix("0x"), 16))
        return Decimal(value)
    except (InvalidOperation, ValueError):
        return None


def median(values: list[Decimal]) -> Decimal:
    ordered = sorted(values)
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return (ordered[middle - 1] + ordered[middle]) / 2


def statistics(values: list[Decimal]) -> dict[str, Decimal]:
    total = sum(values, Decimal(0))
    return {
        "count": Decimal(len(values)),
        "sum": total,
        "mean": total / len(values),
        "median": median(values),
        "minimum": min(values),
        "maximum": max(values),
        "last": values[-1],
        "nonzero_count": Decimal(sum(value != 0 for value in values)),
    }


def compare_tsv(
    output: list[dict[str, str]],
    *,
    source_name: str,
    main_path: Path,
    candidate_path: Path,
) -> None:
    main_fields, main_rows = load_tsv(main_path)
    candidate_fields, candidate_rows = load_tsv(candidate_path)
    if main_fields != candidate_fields:
        raise ValueError(f"{source_name} schemas differ")
    if len(main_rows) != len(candidate_rows):
        raise ValueError(f"{source_name} frame counts differ")
    if "frame" in main_fields:
        main_axis = [int(row["frame"]) for row in main_rows]
        candidate_axis = [int(row["frame"]) for row in candidate_rows]
        if main_axis != candidate_axis:
            raise ValueError(f"{source_name} frame axes differ")

    for scope, first in (("movie", 0), ("timed", 1)):
        scoped_main = main_rows[first:]
        scoped_candidate = candidate_rows[first:]
        for field in main_fields:
            main_values = [
                parse_number(field, row[field]) for row in scoped_main
            ]
            candidate_values = [
                parse_number(field, row[field]) for row in scoped_candidate
            ]
            main_numeric = [value for value in main_values if value is not None]
            candidate_numeric = [
                value for value in candidate_values if value is not None
            ]
            if (len(main_numeric) != len(candidate_numeric)
                    or not main_numeric):
                main_unique = sorted({row[field] for row in scoped_main})
                candidate_unique = sorted({row[field] for row in scoped_candidate})
                add_text(
                    output,
                    source=source_name,
                    scope=scope,
                    metric=field,
                    statistic="unique_values",
                    main=json.dumps(main_unique, ensure_ascii=False),
                    candidate=json.dumps(candidate_unique, ensure_ascii=False),
                )
                continue
            main_statistics = statistics(main_numeric)
            candidate_statistics = statistics(candidate_numeric)
            for statistic, main_value in main_statistics.items():
                candidate_value = candidate_statistics[statistic]
                add_numeric(
                    output,
                    source=source_name,
                    scope=scope,
                    metric=field,
                    statistic=statistic,
                    main=main_value,
                    candidate=candidate_value,
                )


def flatten_json(value: object, prefix: str = "") -> dict[str, object]:
    if isinstance(value, dict):
        flattened: dict[str, object] = {}
        for key in sorted(value):
            child = f"{prefix}.{key}" if prefix else str(key)
            flattened.update(flatten_json(value[key], child))
        return flattened
    if isinstance(value, list):
        return {prefix: json.dumps(value, ensure_ascii=False, sort_keys=True)}
    return {prefix: value}


def compare_gate(
    output: list[dict[str, str]], main_path: Path, candidate_path: Path
) -> None:
    main = flatten_json(json.loads(main_path.read_text(encoding="utf-8")))
    candidate = flatten_json(
        json.loads(candidate_path.read_text(encoding="utf-8")))
    for metric in sorted(set(main) | set(candidate)):
        main_value = main.get(metric, "<missing>")
        candidate_value = candidate.get(metric, "<missing>")
        if (isinstance(main_value, (int, float))
                and not isinstance(main_value, bool)
                and isinstance(candidate_value, (int, float))
                and not isinstance(candidate_value, bool)):
            add_numeric(
                output,
                source="gate_json",
                scope="recording",
                metric=metric,
                statistic="value",
                main=Decimal(str(main_value)),
                candidate=Decimal(str(candidate_value)),
            )
        else:
            add_text(
                output,
                source="gate_json",
                scope="recording",
                metric=metric,
                statistic="value",
                main=main_value,
                candidate=candidate_value,
            )


def summary_lines(paths: list[Path]) -> dict[str, str]:
    selected: dict[str, str] = {}
    for path in paths:
        for raw_line in path.read_text(
                encoding="utf-8", errors="replace").splitlines():
            line = raw_line.strip()
            for prefix in SIM_SUMMARY_PREFIXES:
                if line.startswith(prefix):
                    selected[prefix] = line
                    break
    return selected


def line_numbers(line: str) -> dict[str, Decimal]:
    values: dict[str, Decimal] = {}
    counts: dict[str, int] = {}
    for match in NUMBER_TOKEN_RE.finditer(line):
        name = match.group("name")
        counts[name] = counts.get(name, 0) + 1
        key = name if counts[name] == 1 else f"{name}[{counts[name]}]"
        values[key] = Decimal(match.group("value"))
    starved = STARVED_PERCENT_RE.search(line)
    if starved:
        values["starved_percent"] = Decimal(starved.group("value"))
    return values


def compare_sim_log(
    output: list[dict[str, str]], main_paths: list[Path],
    candidate_paths: list[Path],
) -> None:
    main = summary_lines(main_paths)
    candidate = summary_lines(candidate_paths)
    for prefix in SIM_SUMMARY_PREFIXES:
        main_line = main.get(prefix, "<missing>")
        candidate_line = candidate.get(prefix, "<missing>")
        metric_prefix = prefix.rstrip(":=")
        add_text(
            output,
            source="sim_log",
            scope="movie",
            metric=metric_prefix,
            statistic="raw_line",
            main=main_line,
            candidate=candidate_line,
        )
        main_numbers = line_numbers(main_line)
        candidate_numbers = line_numbers(candidate_line)
        for token in sorted(set(main_numbers) & set(candidate_numbers)):
            add_numeric(
                output,
                source="sim_log",
                scope="movie",
                metric=f"{metric_prefix}.{token}",
                statistic="value",
                main=main_numbers[token],
                candidate=candidate_numbers[token],
            )


def main() -> None:
    args = parse_args()
    paths = {
        name: getattr(args, name)
        for name in (
            "main_timeline",
            "candidate_timeline",
            "main_hud",
            "candidate_hud",
            "main_gate",
            "candidate_gate",
            "main_sim_log",
            "candidate_sim_log",
        )
    }
    for name in ("main_sim_report", "candidate_sim_report"):
        path = getattr(args, name)
        if path is not None:
            paths[name] = path
    for name, path in paths.items():
        if not path.is_file():
            raise SystemExit(f"{name} does not exist: {path}")

    output: list[dict[str, str]] = []
    try:
        compare_tsv(
            output,
            source_name="codec_tsv",
            main_path=args.main_timeline,
            candidate_path=args.candidate_timeline,
        )
        compare_tsv(
            output,
            source_name="hud_tsv",
            main_path=args.main_hud,
            candidate_path=args.candidate_hud,
        )
        compare_gate(output, args.main_gate, args.candidate_gate)
        compare_sim_log(
            output,
            [path for path in (args.main_sim_log, args.main_sim_report)
             if path is not None],
            [path for path in (
                args.candidate_sim_log, args.candidate_sim_report)
             if path is not None],
        )
    except ValueError as exc:
        raise SystemExit(str(exc)) from exc

    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8", newline="") as target:
        writer = csv.DictWriter(
            target,
            fieldnames=OUTPUT_COLUMNS,
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        writer.writerows(output)

    receipt = {
        "schema_version": 1,
        "kind": "saved-main-vs-candidate-aggregate-comparison",
        "inputs": {
            name: {"path": str(path.resolve()), "sha256": digest(path)}
            for name, path in paths.items()
        },
        "output": str(args.output.resolve()),
        "output_sha256": digest(args.output),
        "rows": len(output),
        "scopes": ["movie", "timed", "recording"],
        "reran_simulation": False,
    }
    receipt_path = Path(str(args.output) + ".json")
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(args.output.resolve())
    print(receipt_path.resolve())
    print(f"comparison rows: {len(output)}")


if __name__ == "__main__":
    main()
