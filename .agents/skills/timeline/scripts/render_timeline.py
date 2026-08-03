#!/usr/bin/env python3
"""Render a detailed whole-movie codec timeline from analysis TSV data."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import pickle
import re
import subprocess
import sys
import tomllib
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont


SCRIPT = Path(__file__).resolve()
REPO = SCRIPT.parents[4]
TOOLS = REPO / "tools"
sys.path.insert(0, str(TOOLS))
import analysis_logs  # noqa: E402
import analysis_style as style  # noqa: E402
import layout_preview as layout  # noqa: E402
import r2v_model  # noqa: E402
import tmpfs_workspace  # noqa: E402


BG = (12, 12, 14)
PANEL = (20, 21, 25)
TEXT = (230, 230, 234)
DIM = (158, 160, 169)
GRID = (52, 54, 62)
SEGMENT = (105, 105, 118)
TAIL = (105, 42, 42, 82)

PLOT_LEFT = 220
TIMELINE_TOP = 185
REQ_HEIGHT = 347
SUPPLY_HEIGHT = 60
RUN_HEIGHT = 32
R2V_HEIGHT = 32
DIC_HEIGHT = 32
BAND_HEIGHT = 32
R2V_WORDS_PER_PATTERN = r2v_model.PATTERN_WORDS
R2V_PATTERN_WORD_COST = 1
R2V_DMA_REPAIR_WORDS = r2v_model.DMA_REPAIR_WORDS
DEFAULT_H40_NAME_TABLE_WORDS = r2v_model.name_table_words(
    "H40", 40, 28, 30)
P125_CRAM_WORDS = r2v_model.CRAM_WORDS

REQ_ORDER = tuple(style.REQ_TIMELINE_CATS)
REQ_COLORS = {name: style.CATEGORY_COLORS[name] for name in REQ_ORDER}
SUPPLY_SOURCE_ORDER = tuple(style.METER_SUPPLY_SOURCE_ORDER)
# The whole-movie totals legend mirrors the analysis overlay's category legend
# (tools/analysis_style.LEGEND_ORDER), with EVAL-scope tile totals per item.
LEGEND_TOTAL_ORDER = tuple(style.LEGEND_ORDER)

REQUIRED_COLUMNS = {
    "frame", "time_seconds", "palette_segment", "cells", "active_tiles",
    "cold_cap_tiles", "legend_raw", "legend_same", "legend_dic",
    "legend_prg", "legend_wr0", "legend_wr1", "legend_near",
    "legend_flbk", "legend_miss", "status_cold",
    "status_prg", "status_wr0", "status_wr1", "status_r2v", "status_run",
    "r2v_pattern_words", "r2v_repair_words", "r2v_name_table_words",
    "r2v_cram_words", "r2v_short_runs",
    "body_raw_payload_bytes", "body_prg_payload_bytes",
    "body_payload_bytes", "body_control_bytes", "body_pad_bytes",
    "body_physical_bytes", "body_useful_bytes",
    "quality_budget_remaining_bytes",
}
OPTIONAL_COLUMNS = {"status_dma"}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tsv", type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--sim-out", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--label", default="")
    parser.add_argument(
        "--evaluation-end-frame", type=int,
        help=("first excluded frame; defaults to the terminal suffix after "
              "the final Prg payload delivery"))
    parser.add_argument("--pixels-per-frame", type=int)
    parser.add_argument(
        "--r2v-workload-tsv", type=Path,
        help=(
            "packed-stream workload TSV from "
            "harness/cold_cap_model/extract_frames.py; adds an R2V row "
            "for pattern words at CPU 1x, DMA repairs, name-table words, "
            "and palette-switch CRAM words"
        ),
    )
    return parser.parse_args()


def number(value: str) -> float:
    if value == "":
        return 0.0
    return float(value)


def load_tsv(path: Path) -> tuple[list[dict[str, str]], dict[str, np.ndarray]]:
    with path.open("r", encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source, delimiter="\t")
        missing = REQUIRED_COLUMNS - set(reader.fieldnames or ())
        if missing:
            raise SystemExit(f"timeline TSV lacks columns: {sorted(missing)}")
        fieldnames = set(reader.fieldnames or ())
        rows = list(reader)
    if not rows:
        raise SystemExit("timeline TSV contains no frames")
    frames = np.asarray([int(row["frame"]) for row in rows], np.int64)
    if not np.array_equal(frames, np.arange(len(rows))):
        raise SystemExit("timeline TSV frames must be contiguous and start at zero")
    arrays = {
        key: np.asarray([number(row[key]) for row in rows], np.float64)
        for key in (
            (REQUIRED_COLUMNS | (OPTIONAL_COLUMNS & fieldnames)) - {"frame"}
        )
    }
    arrays["frame"] = frames
    return rows, arrays


def run_scale_max(values: np.ndarray) -> float:
    """Return the observed timed RUN maximum; frame 0 is boot-only."""

    timed = np.asarray(values, dtype=np.float64)[1:]
    timed = timed[np.isfinite(timed)]
    return max(float(timed.max(initial=0)), 1.0)


def r2v_scale_max(values: np.ndarray) -> int:
    """Return the exact calculated timed-frame maximum for the R2V axis."""

    timed = np.asarray(values, dtype=np.int64)[1:]
    return max(int(timed.max(initial=0)), 1)


def req_cold_cap_y(
    row_top: int,
    row_height: int,
    cells: float,
    cold_cap_tiles: float,
) -> int:
    """Map the configured cold-tile cap onto the REQ row's cell scale."""
    scale = max(float(cells), 1.0)
    cap = min(max(float(cold_cap_tiles), 0.0), scale)
    return row_top + row_height - 1 - int(
        round((row_height - 1) * cap / scale)
    )


def calculate_r2v_words(
    pass2_words: np.ndarray,
    run_count: np.ndarray,
    short_run_count: np.ndarray,
    palette_switch: np.ndarray,
    name_table_word_count: int | np.ndarray = DEFAULT_H40_NAME_TABLE_WORDS,
) -> dict[str, np.ndarray]:
    """Return VDP-memory words from an external packed-stream workload."""
    words = np.asarray(pass2_words, np.int64)
    runs = np.asarray(run_count, np.int64)
    short = np.asarray(short_run_count, np.int64)
    if np.any(words % R2V_WORDS_PER_PATTERN):
        raise ValueError("R2V pattern words must be whole 16-word patterns")
    if words.shape != runs.shape or words.shape != short.shape:
        raise ValueError("R2V workload columns must have matching shapes")
    if np.any(short < 0) or np.any(short > runs):
        raise ValueError("R2V short-run count exceeds total run count")
    return r2v_model.calculate_words(
        words // R2V_WORDS_PER_PATTERN,
        runs,
        palette_switch,
        name_table_word_count,
    )


def r2v_from_timeline(data: dict[str, np.ndarray]) -> dict[str, np.ndarray]:
    """Load the R2V values already used by the analysis status bar."""
    result = {
        "words": np.rint(data["status_r2v"]).astype(np.int64),
        "pattern_words": np.rint(data["r2v_pattern_words"]).astype(np.int64),
        "repair_words": np.rint(data["r2v_repair_words"]).astype(np.int64),
        "name_table_words": np.rint(
            data["r2v_name_table_words"]).astype(np.int64),
        "cram_words": np.rint(data["r2v_cram_words"]).astype(np.int64),
        "short_runs": np.rint(data["r2v_short_runs"]).astype(np.int64),
    }
    calculated = (
        result["pattern_words"] + result["repair_words"]
        + result["name_table_words"] + result["cram_words"]
    )
    if not np.array_equal(calculated, result["words"]):
        mismatch = int(np.flatnonzero(calculated != result["words"])[0])
        raise SystemExit(
            f"timeline R2V component mismatch at frame {mismatch}: "
            f"{int(calculated[mismatch])} != "
            f"{int(result['words'][mismatch])}")
    return result


def load_r2v_workload(
    path: Path,
    *,
    frames: int,
    data: dict[str, np.ndarray],
) -> dict[str, np.ndarray]:
    """Load and cross-check the exact packed transfer workload."""

    required = {
        "frame", "n_runs", "loads_total", "pass2_words", "short_runs",
        "max_run_words", "pal_switch",
    }
    with path.open("r", encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source, delimiter="\t")
        missing = required - set(reader.fieldnames or ())
        if missing:
            raise SystemExit(
                f"R2V workload TSV lacks columns: {sorted(missing)}")
        rows = list(reader)
    if len(rows) != frames:
        raise SystemExit(
            f"R2V workload has {len(rows)} frames, expected {frames}")
    frame_trace = np.asarray([int(row["frame"]) for row in rows], np.int64)
    if not np.array_equal(frame_trace, np.arange(frames)):
        raise SystemExit(
            "R2V workload frames must be contiguous and start at zero")
    values = {
        key: np.asarray([int(row[key]) for row in rows], np.int64)
        for key in required - {"frame"}
    }
    expected_words = np.rint(
        np.asarray(data["r2v_pattern_words"], np.float64)).astype(np.int64)
    if not np.array_equal(values["pass2_words"][1:], expected_words[1:]):
        mismatch = int(np.flatnonzero(
            values["pass2_words"][1:] != expected_words[1:])[0]) + 1
        raise SystemExit(
            f"R2V workload/timeline cold mismatch at frame {mismatch}: "
            f"{values['pass2_words'][mismatch]} != "
            f"{expected_words[mismatch]} words")
    expected_runs = np.rint(
        np.asarray(data["status_run"], np.float64)).astype(np.int64)
    if not np.array_equal(values["n_runs"][1:], expected_runs[1:]):
        mismatch = int(np.flatnonzero(
            values["n_runs"][1:] != expected_runs[1:])[0]) + 1
        raise SystemExit(
            f"R2V workload/timeline run mismatch at frame {mismatch}: "
            f"{values['n_runs'][mismatch]} != "
            f"{expected_runs[mismatch]} runs")
    components = calculate_r2v_words(
        values["pass2_words"], values["n_runs"], values["short_runs"],
        values["pal_switch"],
        np.rint(data["r2v_name_table_words"]).astype(np.int64),
    )
    # Frame 0 is boot construction and is excluded from every timed row.
    for component in components.values():
        component[0] = 0
    expected_total = np.rint(data["status_r2v"]).astype(np.int64)
    if not np.array_equal(components["words"], expected_total):
        mismatch = int(np.flatnonzero(
            components["words"] != expected_total)[0])
        raise SystemExit(
            f"R2V workload/timeline total mismatch at frame {mismatch}: "
            f"{int(components['words'][mismatch])} != "
            f"{int(expected_total[mismatch])} words")
    return {
        **values,
        **components,
    }


def load_toml(path: Path | None) -> dict:
    if path is None:
        return {}
    with path.open("rb") as source:
        return tomllib.load(source)


def load_npz(path: Path) -> dict[str, np.ndarray]:
    if not path.exists():
        return {}
    with np.load(path, allow_pickle=True) as data:
        return {key: data[key].copy() for key in data.files}


def infer_evaluation_end(buffer: dict[str, np.ndarray], frames: int) -> int | None:
    """Exclude the terminal no-refill suffix from comparison aggregates."""
    payload = np.asarray(buffer.get("payload_sectors", ()), np.int64)
    if payload.shape != (frames,):
        return None
    delivered = np.flatnonzero(payload > 0)
    if not delivered.size:
        return None
    first_excluded = min(frames, int(delivered[-1]) + 1)
    return first_excluded if first_excluded < frames else None


def load_miss_masks(
    path: Path,
    *,
    frames: int,
    cells: int,
) -> np.ndarray | None:
    if not path.exists():
        return None
    masks = np.load(path, allow_pickle=False)
    if masks.ndim != 2 or masks.shape[0] != frames:
        raise SystemExit(
            f"miss mask shape {masks.shape} does not match {frames} frames")
    if masks.shape[1] == cells:
        return np.asarray(masks, bool)
    packed_columns = math.ceil(cells / 8)
    if masks.shape[1] != packed_columns:
        raise SystemExit(
            f"miss mask width {masks.shape[1]} is neither {cells} cells nor "
            f"{packed_columns} packed bytes")
    return np.unpackbits(
        np.asarray(masks, np.uint8), axis=1, bitorder="little")[:, :cells].astype(bool)


def load_decisions(path: Path) -> dict:
    if not path.exists():
        return {}
    with path.open("rb") as source:
        return pickle.load(source)


def ffprobe_metadata(source: Path | None) -> dict:
    if source is None or not source.exists():
        return {}
    command = [
        "ffprobe", "-v", "error", "-show_entries",
        "format=duration:stream=index,codec_type,codec_name,width,height,"
        "r_frame_rate,sample_aspect_ratio,display_aspect_ratio,sample_rate,channels",
        "-of", "json", str(source),
    ]
    try:
        return json.loads(subprocess.check_output(command, text=True))
    except (OSError, subprocess.CalledProcessError, json.JSONDecodeError):
        return {}


def env_default(text: str, name: str, fallback: str = "?") -> str:
    match = re.search(
        rf'os\.environ\.get\(\s*"{re.escape(name)}"\s*,\s*"([^"]+)"',
        text,
    )
    return match.group(1) if match else fallback


def literal_value(text: str, name: str, fallback: str = "?") -> str:
    match = re.search(rf"(?m)^{re.escape(name)}\s*=\s*([^#\n]+)", text)
    return match.group(1).strip() if match else fallback


def code_settings(
    fps: float,
    *,
    sim_out: Path | None = None,
    buffer: dict[str, np.ndarray] | None = None,
) -> list[str]:
    sim_text = (TOOLS / "sim.py").read_text(encoding="utf-8")
    schedule_text = (TOOLS / "stream_schedule.py").read_text(encoding="utf-8")
    near = "/".join(env_default(sim_text, key) for key in (
        "CBRSIM_NEAR_YM", "CBRSIM_NEAR_YP", "CBRSIM_NEAR_C"))
    flbk = "/".join(env_default(sim_text, key) for key in (
        "CBRSIM_TFLBK_YM", "CBRSIM_TFLBK_YP", "CBRSIM_TFLBK_C"))
    ghost_seconds = float(env_default(
        sim_text, "CBRSIM_GHOST_ESCALATE_SEC", "0"))
    ghost_frames = max(1, math.floor(ghost_seconds * fps)) if ghost_seconds else 0
    run_bytes = literal_value(schedule_text, "RUN_DESCRIPTOR_BYTES")
    run_accounting = None
    if buffer and "run_selection_worst_case" in buffer:
        run_worst_case = bool(np.asarray(
            buffer["run_selection_worst_case"]).item())
        run_solvency = bool(np.asarray(
            buffer.get("run_solvency_worst_case", True)).item())
        stored_run_bytes = int(np.asarray(
            buffer.get("run_descriptor_bytes", run_bytes)).item())
        run_accounting = (
            f"fixed envelope {stored_run_bytes}B/cold; unused stays pad"
            if run_worst_case else
            f"exact late {stored_run_bytes}B/source-aware-run, "
            f"solvency/cold={run_solvency}"
        )
    if run_accounting is None and sim_out:
        report_path = sim_out / "report.txt"
        if report_path.exists():
            for line in report_path.read_text(encoding="utf-8").splitlines():
                if line.startswith("run_control_accounting="):
                    run_accounting = line.split("=", 1)[1]
                    break
                if line.startswith("incremental_run_control_reservation="):
                    run_accounting = (
                        "selection " + line.split("=", 1)[1])
                    break
    if run_accounting is None:
        run_worst_case = literal_value(
            sim_text, "RUN_SELECTION_WORST_CASE", "True")
        run_solvency = literal_value(
            sim_text, "RUN_SOLVENCY_WORST_CASE", "False")
        run_accounting = (
            f"fixed envelope {run_bytes}B/cold; unused stays pad"
            if run_worst_case == "True" else
            f"exact late {run_bytes}B/source-aware-run, "
            f"solvency/cold={run_solvency}"
        )
    return [
        f"F3 Ym/Yp/C  Near {near}  Flbk {flbk}",
        "Resident mean-colour search K=%s BW=%s" % (
            env_default(sim_text, "CBRSIM_RESIDENT_K"),
            literal_value(sim_text, "RESIDENT_BW"),
        ),
        "Priority detail=%s; aging=%s cap=%s dist-ref=%s step-cap=%s; edge=%stiles x%s" % (
            env_default(sim_text, "CBRSIM_DETAIL_ALPHA", "?"),
            literal_value(sim_text, "AGING_ALPHA"),
            literal_value(sim_text, "WAIT_CAP"),
            env_default(sim_text, "CBRSIM_AGING_DIST_REF", "?"),
            env_default(sim_text, "CBRSIM_AGING_STEP_CAP", "?"),
            literal_value(sim_text, "BORDER_TILES"),
            literal_value(sim_text, "BORDER_WEIGHT"),
        ),
        f"Persistent approximation rescue={ghost_seconds:g}s={ghost_frames} frames",
        f"Run accounting={run_accounting}; allocator slots are physical",
    ]


def source_lines(config: dict, config_path: Path | None, probe: dict) -> list[str]:
    source = config.get("source", {})
    video = config.get("video", {})
    audio = config.get("audio", {})
    src_path = source.get("path", "?")
    streams = probe.get("streams", [])
    vstream = next((item for item in streams if item.get("codec_type") == "video"), {})
    astream = next((item for item in streams if item.get("codec_type") == "audio"), {})
    sha = "?"
    if config_path and config_path.exists():
        sha = hashlib.sha256(config_path.read_bytes()).hexdigest()[:12]
    coded = (
        f"{vstream.get('width', '?')}x{vstream.get('height', '?')} "
        f"{vstream.get('codec_name', '?')} {vstream.get('r_frame_rate', '?')}fps"
    )
    display = (
        f"SAR {vstream.get('sample_aspect_ratio', source.get('sar', '?'))} "
        f"DAR {vstream.get('display_aspect_ratio', '?')}"
    )
    audio_meta = (
        f"{astream.get('codec_name', '?')} {astream.get('sample_rate', '?')}Hz "
        f"{astream.get('channels', '?')}ch -> {audio.get('kind', '?')}"
    )
    return [
        f"Source {src_path}",
        f"Input {coded}; {display}",
        f"Audio {audio_meta}",
        "Output %s %sx%s fit=%s; active canvas from profile" % (
            video.get("mode", "?"), video.get("width", "?"),
            video.get("height", "?"), video.get("fit", "?")),
        f"Profile {config_path or '?'} sha256={sha}",
    ]


def fmt_int(value: float | int) -> str:
    return f"{int(round(float(value))):,}"


def fmt_frame(frame_index: int, frames: int) -> str:
    width = max(3, len(f"{max(frames - 1, 0):X}"))
    return f"f0x{frame_index:0{width}X}"


def prg_cap_summary(measured_cap: int) -> str:
    """Describe the fixed cold cap and construction-time physical planning."""
    return (
        f"Cold cap fixed at {measured_cap}; Prg limits come from the one-pass "
        "cadence-sector prefix ledger before each frame; exact rate lead stays zero")


def true_run_lengths(mask: np.ndarray) -> np.ndarray:
    values = np.asarray(mask, bool)
    padded = np.r_[False, values, False]
    starts = np.flatnonzero(~padded[:-1] & padded[1:])
    ends = np.flatnonzero(padded[:-1] & ~padded[1:])
    return ends - starts


def miss_streak_lines(
    miss_masks: np.ndarray | None,
    selection: np.ndarray,
    expected_counts: np.ndarray,
) -> list[str]:
    if miss_masks is None:
        return ["Miss burst/streak detail unavailable (miss_masks.npy absent)"]
    selected = miss_masks[selection]
    simultaneous = selected.sum(axis=1)
    if not np.array_equal(simultaneous, expected_counts.astype(np.int64)):
        raise SystemExit("miss_masks.npy does not match TSV legend_miss counts")
    affected = simultaneous[simultaneous > 0]
    if affected.size:
        p50, p95 = np.percentile(affected, (50, 95))
        peak = int(affected.max())
    else:
        p50 = p95 = 0.0
        peak = 0
    frame_runs = true_run_lengths(simultaneous > 0)
    frame_max = int(frame_runs.max(initial=0))
    frame_multi = int(np.count_nonzero(frame_runs >= 2))

    cell_events = 0
    cell_one = 0
    cell_multi = 0
    cell_max = 0
    for cell in range(selected.shape[1]):
        lengths = true_run_lengths(selected[:, cell])
        if not lengths.size:
            continue
        cell_events += len(lengths)
        cell_one += int(np.count_nonzero(lengths == 1))
        cell_multi += int(np.count_nonzero(lengths >= 2))
        cell_max = max(cell_max, int(lengths.max()))
    one_percent = 100.0 * cell_one / cell_events if cell_events else 0.0
    return [
        "Miss simultaneous affected-frame p50/p95/max %.0f/%.0f/%s tiles" % (
            p50, p95, fmt_int(peak)),
        "Miss streak any-frame max %s frames (multi-frame runs %s); "
        "same-cell one-frame %.1f%%, multi-frame events %s, max %s frames" % (
            fmt_int(frame_max), fmt_int(frame_multi), one_percent,
            fmt_int(cell_multi), fmt_int(cell_max)),
    ]


def summarize(
    data: dict[str, np.ndarray], selection: np.ndarray, buffer: dict,
    miss_masks: np.ndarray | None, label: str,
) -> list[str]:
    if not selection.size:
        return [f"{label}: empty"]
    take = lambda key: data[key][selection]
    frames = len(selection)
    miss = take("legend_miss")
    flbk = take("legend_flbk")
    cold = take("status_cold")
    runs = take("status_run")
    prg_load = take("legend_prg")
    physical = take("body_physical_bytes").sum()
    useful = take("body_useful_bytes").sum()
    pad = take("body_pad_bytes").sum()
    body_bps = useful * 153600.0 / physical if physical else 0.0
    unused_run_envelope = np.maximum(cold - runs, 0) * 4
    prefix = (
        f"{label} f{int(selection[0])}-{int(selection[-1])} ({frames} frames)"
    )
    lines = [
        prefix,
        "Categories Raw %s Same %s Near %s Flbk %s Miss %s" % tuple(
            fmt_int(take(f"legend_{name}").sum())
            for name in ("raw", "same", "near", "flbk", "miss")),
        "Exact sources Prg %s Wr0 %s Wr1 %s Dic %s" % tuple(
            fmt_int(take(f"legend_{name}").sum())
            for name in ("prg", "wr0", "wr1", "dic")),
        "Flbk avg/p95/max %.1f / %.0f / %.0f; Miss frames/tiles/max %s/%s/%s" % (
            flbk.mean(), np.percentile(flbk, 95), flbk.max(),
            fmt_int(np.count_nonzero(miss)), fmt_int(miss.sum()), fmt_int(miss.max())),
        *miss_streak_lines(miss_masks, selection, miss),
        "Cold total/avg/max %s / %.1f / %.0f; Run total/avg/max %s / %.1f / %.0f" % (
            fmt_int(cold.sum()), cold.mean(), cold.max(), fmt_int(runs.sum()),
            runs.mean(), runs.max()),
        "Prg exact total/avg %s / %.1f tiles (%s MiB); unused 1/cold control envelope avg/p95 %.0f/%.0f B" % (
            fmt_int(prg_load.sum()), prg_load.mean(),
            f"{prg_load.sum() * 32 / 1048576:.2f}",
            unused_run_envelope.mean(),
            np.percentile(unused_run_envelope, 95)),
        "BODY useful %.1f KiB/s; useful/pad %s/%s bytes (pad %.1f%%)" % (
            body_bps / 1024.0, fmt_int(useful), fmt_int(pad),
            100.0 * pad / physical if physical else 0.0),
    ]
    if buffer:
        capacity = int(np.asarray(buffer.get("prg_capacity", 0)).item())
        remaining = np.asarray(buffer.get("prg_remaining", ()), np.float64)
        quality = np.asarray(buffer.get("quality_budget_remaining", ()), np.float64)
        if len(remaining) > int(selection[-1]):
            values = remaining[selection]
            lines.append(
                "PrgBuf median/min/>=95%% %s/%s/%.1f%% of %s patterns" % (
                    fmt_int(np.median(values)), fmt_int(values.min()),
                    100.0 * np.mean(values >= capacity * 0.95), fmt_int(capacity)))
        if len(quality) > int(selection[-1]):
            values = quality[selection]
            lines.append(
                "Quality allowance median/min/end %s/%s/%s patterns" % (
                    fmt_int(np.median(values)), fmt_int(values.min()),
                    fmt_int(values[-1])))
    return lines


def metadata_lines(
    data: dict[str, np.ndarray], config: dict, config_path: Path | None,
    sim_out: Path | None, buffer: dict, decisions: dict, probe: dict,
    miss_masks: np.ndarray | None, evaluation_end: int | None,
) -> tuple[list[str], list[str], list[str]]:
    fps = 1.0 / (data["time_seconds"][1] - data["time_seconds"][0]) if len(data["frame"]) > 1 else 0.0
    source = source_lines(config, config_path, probe)
    hardware = (
        decisions.get("hardware", {})
        or (decisions.get("config", {}).get("hardware", {})))
    run_trace = np.asarray(
        (decisions.get("pattern_transfers") or {}).get("runs", ()), np.int64)
    run_max = fmt_int(run_trace[1:].max(initial=0)) if run_trace.size else "?"
    delivery_summary = (
        "Physical Prg delivery: normal=%s KiB + jitter=%s KiB; "
        "limit=%s KiB; ring=%s KiB; one-pass shared-sector limits, "
        "no reactive feedback" % (
            hardware.get("prg_buf_kb", "?"),
            hardware.get("prg_jitter_headroom_kb", "?"),
            hardware.get("prg_delivery_cap_kb", "?"),
            hardware.get("prg_physical_ring_kb", "?"),
        )
    )
    reserve_mode = buffer.get("quality_reserve_mode", np.array("forecast_pair"))
    reserve_mode = str(np.asarray(reserve_mode).item())
    reserve = np.asarray(buffer.get("upgrade_reserve_bytes", ()), np.float64)
    reserve_summary = "n/a"
    if reserve.size:
        reserve_summary = "median %.1f / peak %.1f KiB" % (
            np.median(reserve) / 1024.0, reserve.max() / 1024.0)
    internals = [
        "Frames %s; %.3fs; %.3ffps; cells=%s active=%s segments=%s" % (
            fmt_int(len(data["frame"])), data["time_seconds"][-1] + 1 / fps,
            fps, fmt_int(data["cells"][0]), fmt_int(data["active_tiles"][0]),
            fmt_int(len(np.unique(data["palette_segment"])))),
        "VRAM=%s tiles; cold cap=%s; normal PrgBuf=%s KiB; quality cap=%s KiB" % (
            hardware.get("vram_tiles", config.get("encoder", {}).get("vram_tiles", "?")),
            fmt_int(data["cold_cap_tiles"][0]),
            hardware.get("prg_buf_kb", "?"), hardware.get("quality_budget_kb", "?")),
        delivery_summary,
        f"Player runs=source-aware; allocator slots=physical; max={run_max}",
        f"Reserve mode={reserve_mode}; {reserve_summary}",
    ] + code_settings(
        fps,
        sim_out=sim_out,
        buffer=buffer,
    )
    full = np.arange(1, len(data["frame"]), dtype=np.int64)
    if evaluation_end is None:
        evaluation = full
    else:
        evaluation = np.arange(1, min(evaluation_end, len(data["frame"])), dtype=np.int64)
    totals = summarize(data, evaluation, buffer, miss_masks, "EVAL")
    if evaluation_end is not None and evaluation_end < len(data["frame"]):
        totals += summarize(data, full, buffer, miss_masks, "FULL")[:9]
    if sim_out:
        totals.append(f"Simulation {sim_out}")
    return source, internals, totals


def font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(layout.FONT, size)


def draw_text_block(
    draw: ImageDraw.ImageDraw, xy: tuple[int, int], heading: str,
    lines: list[str], width: int,
) -> None:
    x, y = xy
    draw.text((x, y), heading, fill=TEXT, font=font(26))
    y += 35
    body = font(19)
    max_chars = max(30, int(width / 11.5))
    for raw in lines:
        chunks = [raw[i:i + max_chars] for i in range(0, len(raw), max_chars)] or [""]
        for chunk in chunks:
            draw.text((x, y), chunk, fill=DIM, font=body)
            y += 25


def compute_legend_totals(
    data: dict[str, np.ndarray], selection: np.ndarray,
) -> dict[str, int]:
    """Whole-movie displayed-cell totals per analysis legend category."""
    take = lambda key: int(data[key][selection].sum())
    totals = {}
    for name in LEGEND_TOTAL_ORDER:
        if name == "Wrd":
            totals[name] = take("legend_wr0") + take("legend_wr1")
        else:
            totals[name] = take(f"legend_{name.lower()}")
    return totals


def draw_legend(
    draw: ImageDraw.ImageDraw, x: int, y: int,
    totals: dict[str, int], scope_label: str,
) -> None:
    label_font = font(19)
    draw.text((x, y), scope_label, fill=DIM, font=label_font)
    x += int(draw.textlength(scope_label, font=label_font)) + 26
    for name in LEGEND_TOTAL_ORDER:
        color = style.CATEGORY_COLORS[name]
        draw.rectangle((x, y + 3, x + 21, y + 23), fill=color)
        text = f"{name} {fmt_int(totals[name])}"
        draw.text((x + 29, y), text, fill=TEXT, font=label_font)
        x += 29 + int(draw.textlength(text, font=label_font)) + 34


def draw_timeline(
    image: Image.Image, data: dict[str, np.ndarray], left: int, top: int,
    ppf: int, evaluation_end: int | None,
    r2v: dict[str, np.ndarray] | None = None,
) -> tuple[int, int]:
    draw = ImageDraw.Draw(image)
    n = len(data["frame"])
    width = n * ppf
    req_h = REQ_HEIGHT
    supply_h = SUPPLY_HEIGHT
    run_h = RUN_HEIGHT
    r2v_h = R2V_HEIGHT if r2v is not None else 0
    dic_h = DIC_HEIGHT
    band_h = BAND_HEIGHT
    req_top = top
    supply_top = req_top + req_h
    run_top = supply_top + supply_h
    r2v_top = run_top + run_h
    dic_top = r2v_top + r2v_h
    band_top = dic_top + dic_h
    bottom = band_top + band_h
    panel_rows = [
        (req_top, req_h),
        (supply_top, supply_h),
        (run_top, run_h),
        (dic_top, dic_h),
        (band_top, band_h),
    ]
    if r2v is not None:
        panel_rows.insert(3, (r2v_top, r2v_h))
    for y0, height in panel_rows:
        draw.rectangle((left, y0, left + width - 1, y0 + height - 1), fill=PANEL, outline=GRID)

    cells = max(float(data["cells"][0]), 1.0)
    capacities = {
        name: max(float(data[f"status_{name.lower()}"] .max()), 1.0)
        for name in SUPPLY_SOURCE_ORDER
    }
    total_capacity = sum(capacities.values())
    run_capacity = run_scale_max(data["status_run"])
    r2v_capacity = (
        r2v_scale_max(r2v["words"]) if r2v is not None else 1
    )
    dic_capacity = run_scale_max(data["legend_dic"])
    for frame_index in range(n):
        x0 = left + frame_index * ppf
        x1 = x0 + ppf - 1
        y = req_top + req_h
        for name in REQ_ORDER:
            value = data[f"legend_{name.lower()}"][frame_index]
            height = int(req_h * value / cells)
            if height:
                draw.rectangle((x0, y - height, x1, y - 1), fill=REQ_COLORS[name])
                y -= height

        y = supply_top + supply_h
        supply_remaining = {
            name: data[f"status_{name.lower()}"][frame_index]
            for name in SUPPLY_SOURCE_ORDER
        }
        for name, height in style.meter_supply_segments(
            supply_remaining,
            capacities,
            supply_h,
        ):
            if height:
                draw.rectangle(
                    (x0, y - height, x1, y - 1),
                    fill=style.SUPPLY_COLORS[name],
                )
                y -= height

        run_value = min(float(data["status_run"][frame_index]), run_capacity)
        run_height = int(run_h * run_value / run_capacity)
        if run_height:
            draw.rectangle(
                (x0, run_top + run_h - run_height, x1, run_top + run_h - 1),
                fill=style.COL_RUN,
            )

        if r2v is not None:
            r2v_value = int(r2v["words"][frame_index])
            r2v_height = int(
                r2v_h * min(r2v_value, r2v_capacity) / r2v_capacity
            )
            if r2v_height:
                draw.rectangle(
                    (
                        x0,
                        r2v_top + r2v_h - r2v_height,
                        x1,
                        r2v_top + r2v_h - 1,
                    ),
                    fill=style.COL_DMA,
                )

        dic_value = min(float(data["legend_dic"][frame_index]), dic_capacity)
        dic_height = int(dic_h * dic_value / dic_capacity)
        if dic_height:
            draw.rectangle(
                (x0, dic_top + dic_h - dic_height, x1, dic_top + dic_h - 1),
                fill=style.CATEGORY_COLORS["Dic"],
            )

        physical = max(float(data["body_physical_bytes"][frame_index]), 1.0)
        raw_h = int(
            band_h * data["body_raw_payload_bytes"][frame_index] / physical)
        payload_h = int(band_h * data["body_payload_bytes"][frame_index] / physical)
        useful_h = int(band_h * data["body_useful_bytes"][frame_index] / physical)
        if raw_h:
            draw.rectangle(
                (x0, band_top + band_h - raw_h, x1, band_top + band_h - 1),
                fill=style.CAT_RAW,
            )
        if payload_h > raw_h:
            draw.rectangle(
                (x0, band_top + band_h - payload_h,
                 x1, band_top + band_h - raw_h - 1),
                fill=style.COL_PRG,
            )
        if useful_h > payload_h:
            draw.rectangle(
                (x0, band_top + band_h - useful_h, x1, band_top + band_h - payload_h - 1),
                fill=style.COL_OVH,
            )

    scale_font = font(15)

    def draw_scale(
        row_top: int,
        row_height: int,
        maximum: float,
        *,
        percent: bool = False,
        show_midpoint: bool = True,
    ) -> None:
        fractions = (1.0, 0.5, 0.0) if show_midpoint else (1.0, 0.0)
        row_scale_font = font(13) if row_height <= 32 else scale_font
        edge_offset = 8 if row_height <= 32 else 11
        for fraction in fractions:
            y = row_top + int(round((1.0 - fraction) * (row_height - 1)))
            draw.line(
                (left, y, left + width - 1, y),
                fill=(62, 64, 72),
                width=1,
            )
            if percent:
                label = f"{int(round(fraction * 100))}%"
            else:
                label = fmt_int(maximum * fraction)
            label_y = y
            if fraction == 1.0:
                label_y += edge_offset
            elif fraction == 0.0:
                label_y -= edge_offset
            draw.text(
                (left - 10, label_y),
                label,
                fill=(185, 187, 196),
                font=row_scale_font,
                anchor="rm",
            )

    draw_scale(req_top, req_h, cells)
    cold_cap_tiles = float(data["cold_cap_tiles"][0])
    cold_cap_y = req_cold_cap_y(
        req_top,
        req_h,
        cells,
        cold_cap_tiles,
    )
    draw.line(
        (left, cold_cap_y, left + width - 1, cold_cap_y),
        fill=style.COL_LIMIT,
        width=2,
    )
    draw.text(
        (left - 10, cold_cap_y),
        f"{fmt_int(cold_cap_tiles)} cap",
        fill=style.COL_LIMIT,
        font=scale_font,
        anchor="rm",
    )
    draw_scale(supply_top, supply_h, total_capacity)
    draw_scale(run_top, run_h, run_capacity, show_midpoint=False)
    if r2v is not None:
        draw_scale(r2v_top, r2v_h, r2v_capacity, show_midpoint=False)
    draw_scale(dic_top, dic_h, dic_capacity, show_midpoint=False)
    draw_scale(
        band_top,
        band_h,
        1.0,
        percent=True,
        show_midpoint=False,
    )

    fps = 1.0 / (data["time_seconds"][1] - data["time_seconds"][0]) if n > 1 else 1.0
    duration = n / fps
    for second in range(0, math.ceil(duration) + 1):
        frame_index = min(round(second * fps), n - 1)
        x = left + frame_index * ppf
        major = second % 5 == 0
        color = (75, 77, 88) if major else (38, 40, 47)
        draw.line((x, req_top, x, bottom), fill=color, width=1)
        if major:
            draw.text((x + 3, bottom + 10), f"{second}s", fill=DIM, font=font(19))
            draw.text(
                (x + 3, bottom + 35),
                fmt_frame(frame_index, n),
                fill=(115, 117, 126),
                font=font(16),
            )

    segments = data["palette_segment"].astype(np.int64)
    for frame_index in np.flatnonzero(np.r_[False, segments[1:] != segments[:-1]]):
        x = left + int(frame_index) * ppf
        draw.line((x, req_top, x, bottom), fill=SEGMENT, width=2)
        draw.text((x + 3, req_top + 3), f"PL{segments[frame_index]:02d}", fill=(185, 185, 195), font=font(16))

    if evaluation_end is not None and 0 <= evaluation_end < n:
        x = left + evaluation_end * ppf
        overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
        odraw = ImageDraw.Draw(overlay)
        odraw.rectangle((x, req_top, left + width, bottom), fill=TAIL)
        odraw.line((x, req_top, x, bottom), fill=(255, 100, 100, 255), width=3)
        odraw.text(
            (x + 8, req_top + 28),
            f"evaluation ends {fmt_frame(evaluation_end, n)}",
            fill=(255, 180, 180, 255),
            font=font(19),
        )
        image.alpha_composite(overlay)

    label_font = font(22)
    small = font(17)
    draw = ImageDraw.Draw(image)
    draw.text((18, req_top + 8), "REQ", fill=TEXT, font=label_font)
    draw.text((18, req_top + 37), "cells", fill=DIM, font=small)
    draw.text((18, supply_top + 8), "SUPPLY", fill=TEXT, font=label_font)
    draw.text((18, supply_top + 37), "patterns", fill=DIM, font=small)
    draw.text((18, run_top + 3), "RUN", fill=TEXT, font=label_font)
    if r2v is not None:
        draw.text((18, r2v_top + 3), "R2V", fill=TEXT, font=label_font)
    draw.text((18, dic_top + 3), "DIC", fill=TEXT, font=label_font)
    draw.text((18, band_top + 3), "BAND", fill=TEXT, font=label_font)
    return width, bottom


def main() -> None:
    args = parse_args()
    tsv = args.tsv.resolve()
    config_path = args.config.resolve() if args.config else None
    sim_out = args.sim_out.resolve() if args.sim_out else None
    requested_output = args.output or Path(tsv.stem + "_timeline.png")
    rows, data = load_tsv(tsv)
    n = len(rows)
    ppf = args.pixels_per_frame or max(1, min(4, math.ceil(4200 / n)))
    if ppf <= 0:
        raise SystemExit("pixels per frame must be positive")
    if args.evaluation_end_frame is not None and args.evaluation_end_frame <= 1:
        raise SystemExit("evaluation end frame must be greater than frame 1")
    r2v_path = (
        args.r2v_workload_tsv.resolve()
        if args.r2v_workload_tsv else None
    )
    r2v = r2v_from_timeline(data)
    if r2v_path is not None:
        # The packed-stream extraction is an independent verification source.
        r2v = load_r2v_workload(r2v_path, frames=n, data=data)
    buffer = load_npz(sim_out / "buffer_remaining.npz") if sim_out else {}
    measured_cold_cap = int(round(float(data["cold_cap_tiles"][0])))
    evaluation_end = args.evaluation_end_frame
    if evaluation_end is None:
        evaluation_end = infer_evaluation_end(buffer, n)

    left = PLOT_LEFT
    timeline_top = TIMELINE_TOP + (25 if r2v is not None else 0)
    timeline_width = n * ppf
    width = left + timeline_width + 45
    height = (
        timeline_top
        + REQ_HEIGHT
        + SUPPLY_HEIGHT
        + RUN_HEIGHT
        + (R2V_HEIGHT if r2v is not None else 0)
        + DIC_HEIGHT
        + BAND_HEIGHT
        + 105
    )
    image = Image.new("RGBA", (width, height), BG + (255,))
    draw = ImageDraw.Draw(image)
    title = args.label or tsv.stem
    draw.text((24, 18), title, fill=TEXT, font=font(38))
    draw.text(
        (24, 68),
        f"Detailed codec timeline | {n} frames | {ppf} px/frame | {tsv}",
        fill=DIM, font=font(20),
    )
    draw.text(
        (24, 101),
        prg_cap_summary(measured_cold_cap),
        fill=style.COL_PRG_CAP, font=font(18),
    )
    if r2v is not None:
        r2v_max_words = r2v_scale_max(r2v["words"])
        name_table_max = int(
            np.asarray(r2v["name_table_words"], np.int64)[1:].max(initial=0))
        draw.text(
            (24, 126),
            (
                f"R2V = pattern DMA x{R2V_PATTERN_WORD_COST} + repair + "
                f"NT up to {name_table_max} + CRAM {P125_CRAM_WORDS}"
                f"@switch; timed max={fmt_int(r2v_max_words)} words"
            ),
            fill=style.COL_DMA,
            font=font(18),
        )
    eval_last = (n if evaluation_end is None else min(evaluation_end, n)) - 1
    eval_selection = np.arange(1, eval_last + 1, dtype=np.int64)
    totals = compute_legend_totals(data, eval_selection)
    legend_scope = (
        f"EVAL totals {fmt_frame(1, n)}-{fmt_frame(eval_last, n)}"
    )
    draw_legend(draw, left, timeline_top - 42, totals, legend_scope)
    _, bottom = draw_timeline(
        image, data, left, timeline_top, ppf, evaluation_end,
        r2v=r2v)
    draw = ImageDraw.Draw(image)
    draw.text(
        (left, bottom + 69),
        "Frame 0 is boot construction. Segment lines are labelled PL. Shaded tail remains visible but is excluded from EVAL totals.",
        fill=DIM, font=font(18),
    )
    sim_lease = (
        tmpfs_workspace.lease_managed_path(sim_out)
        if sim_out is not None else None)
    png_lease = None
    actual_output = requested_output
    try:
        actual_output, png_lease = tmpfs_workspace.allocate_file(
            requested_output,
            kind="timeline-png",
            key=f"{tsv.stem}-{hashlib.sha256(tsv.read_bytes()).hexdigest()[:10]}",
            required_bytes=max(width * height * 4, 128 * 1024 ** 2),
        )
        image.convert("RGB").save(actual_output, optimize=True)
        print(actual_output)
    finally:
        if png_lease is not None:
            png_lease.release()
        if sim_lease is not None:
            sim_lease.release()

    fps = (
        1.0 / (data["time_seconds"][1] - data["time_seconds"][0])
        if n > 1 else 0.0
    )
    receipt_rows = [
        {
            "key": "req",
            "top": timeline_top,
            "height": REQ_HEIGHT,
            "unit": "cells",
        },
        {
            "key": "supply",
            "top": timeline_top + REQ_HEIGHT,
            "height": SUPPLY_HEIGHT,
            "unit": "patterns",
        },
        {
            "key": "run",
            "top": timeline_top + REQ_HEIGHT + SUPPLY_HEIGHT,
            "height": RUN_HEIGHT,
            "unit": "runs",
        },
    ]
    if r2v is not None:
        receipt_rows.append({
            "key": "r2v",
            "top": (
                timeline_top + REQ_HEIGHT + SUPPLY_HEIGHT + RUN_HEIGHT
            ),
            "height": R2V_HEIGHT,
            "unit": (
                "VDP-memory words: pattern DMA + repair + NT + CRAM"
            ),
        })
    receipt_rows.extend([
        {
            "key": "dic",
            "top": (
                timeline_top
                + REQ_HEIGHT
                + SUPPLY_HEIGHT
                + RUN_HEIGHT
                + (R2V_HEIGHT if r2v is not None else 0)
            ),
            "height": DIC_HEIGHT,
            "unit": "tiles served from DicBuf",
        },
        {
            "key": "band",
            "top": (
                timeline_top
                + REQ_HEIGHT
                + SUPPLY_HEIGHT
                + RUN_HEIGHT
                + (R2V_HEIGHT if r2v is not None else 0)
                + DIC_HEIGHT
            ),
            "height": BAND_HEIGHT,
            "unit": "percent of physical slot",
        },
    ])
    receipt = {
        "schema_version": 2,
        "kind": "timeline",
        "label": title,
        "image": str(actual_output),
        "image_sha256": hashlib.sha256(actual_output.read_bytes()).hexdigest(),
        "tsv": str(tsv),
        "tsv_sha256": hashlib.sha256(tsv.read_bytes()).hexdigest(),
        "config": str(config_path) if config_path else None,
        "config_sha256": (
            hashlib.sha256(config_path.read_bytes()).hexdigest()
            if config_path else None
        ),
        "sim_out": str(sim_out) if sim_out else None,
        "frames": n,
        "fps": fps,
        "pixels_per_frame": ppf,
        "plot_left": left,
        "plot_top": timeline_top,
        "plot_width": timeline_width,
        "frame_x": "plot_left + frame * pixels_per_frame",
        "frame_label_format": "f0xHEX",
        "evaluation_end_frame": evaluation_end,
        "cold_cap_tiles": measured_cold_cap,
        "run_max": run_scale_max(data["status_run"]),
        "r2v_model": (
            "mode-grid-aware-debug-vdp-memory-payload"
            if r2v is not None else None
        ),
        "r2v_workload_tsv": str(r2v_path) if r2v_path else None,
        "r2v_workload_tsv_sha256": (
            hashlib.sha256(r2v_path.read_bytes()).hexdigest()
            if r2v_path else None
        ),
        "r2v_pattern_word_cost": (
            R2V_PATTERN_WORD_COST if r2v is not None else None
        ),
        "r2v_dma_repair_words_per_run": (
            R2V_DMA_REPAIR_WORDS if r2v is not None else None
        ),
        "r2v_scale_mode": (
            "timed-calculated-maximum" if r2v is not None else None
        ),
        "r2v_axis_max_words": (
            r2v_scale_max(r2v["words"]) if r2v is not None else None
        ),
        "r2v_max_words": (
            r2v_scale_max(r2v["words"])
            if r2v is not None else None
        ),
        "r2v_pattern_words_total": (
            int(r2v["pattern_words"][1:].sum())
            if r2v is not None else None
        ),
        "r2v_dma_repair_words_total": (
            int(r2v["repair_words"][1:].sum())
            if r2v is not None else None
        ),
        "r2v_name_table_words_per_frame": (
            (
                int(np.asarray(
                    r2v["name_table_words"], np.int64)[1:].max(initial=0))
                if r2v is not None else None
            )
        ),
        "r2v_name_table_words_total": (
            int(r2v["name_table_words"][1:].sum())
            if r2v is not None else None
        ),
        "r2v_cram_words_per_switch": (
            P125_CRAM_WORDS if r2v is not None else None
        ),
        "r2v_cram_words_total": (
            int(r2v["cram_words"][1:].sum())
            if r2v is not None else None
        ),
        "dic_max": run_scale_max(data["legend_dic"]),
        "legend_totals": totals,
        "legend_totals_order": list(LEGEND_TOTAL_ORDER),
        "legend_totals_scope": legend_scope,
        "prg_cap_summary": prg_cap_summary(measured_cold_cap),
        "rows": receipt_rows,
    }
    receipt_path = analysis_logs.metadata_path(
        requested_output,
        kind="timeline-layout",
        sha256=receipt["image_sha256"],
    )
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(receipt_path)


if __name__ == "__main__":
    main()
