#!/usr/bin/env python3
"""Render a frame-aligned whole-movie timeline from DEBUG HUD OCR data."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from dataclasses import dataclass
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFont


SCRIPT = Path(__file__).resolve()
REPO = SCRIPT.parents[4]
TOOLS = REPO / "tools"
sys.path.insert(0, str(TOOLS))
import analysis_style as style  # noqa: E402
import analysis_logs  # noqa: E402
import av_config  # noqa: E402
import hud_gate  # noqa: E402
import layout_preview as layout  # noqa: E402
import tmpfs_workspace  # noqa: E402


BG = (12, 12, 14)
PANEL = (20, 21, 25)
TEXT = (230, 230, 234)
DIM = (158, 160, 169)
GRID = (52, 54, 62)
MAJOR_GRID = (75, 77, 88)
WARN = (246, 190, 72)
FAIL = (244, 87, 87)
PASS_GUIDE = (84, 204, 139)
LIMIT = (248, 174, 58)
NORMAL_LIMIT = (246, 220, 96)
INCOMPLETE_TAIL = (92, 25, 31, 150)
DEFAULT_ROW_HEIGHT = 46
DMA_START_LINE_SCALE = 3
DMA_START_LINE_HEIGHT = DEFAULT_ROW_HEIGHT * DMA_START_LINE_SCALE
PATTERN_READY_DEADLINE_SCANLINE = 0xE0
PATTERN_READY_MISSED_PRESSURE = 0x100
# One NTSC V28 blank is 38 scanlines, just under twenty groups of four
# 30.72-us stopwatch ticks. A blank-phase ready sample inside this bound after
# the preceding flip still belongs to that preceding blank, not PT VBlank 1.
PATTERN_READY_SAME_BLANK_Q4_MAX = 20
NT_READY_DEADLINE_SCANLINE = 0xE0
NT_READY_MISSED_PRESSURE = 0x100


@dataclass(frozen=True)
class RowSpec:
    key: str
    label: str
    unit: str
    maximum: float
    color: tuple[int, int, int]
    gate_key: str | None = None
    eight_bit_scale: bool = False
    normal_value: float | None = None
    normal_key: str | None = None
    height: int = DEFAULT_ROW_HEIGHT
    point_plot: bool = False
    show_unit: bool = True
    show_zero: bool = False
    deadline_value: float | None = None
    deadline_label: str | None = None


GATE_COLUMN = {
    "sector_slip": "sector_slip",
    "control_desync": "control_desync",
    "audio_resync": "audio_resync",
    "vblank_spill": "vblank_spill",
    "prgbuf_jitter_peak_kib": "prgbuf_jitter_peak_kib",
}

MAXIMUM_COLUMN = {
    **GATE_COLUMN,
    "cd_wait_count": "cd_wait_count",
}

HEX_COLUMNS = {
    "flip_vcounter",
    "first_share_exit_vcounter",
    "transfer_end_vcounter",
    "pattern_dma_ready_vcounter",
    "name_table_dma_ready_vcounter",
}

GPGX_VDP_COLUMNS = (
    "pattern_dma_commands",
    "pattern_dma_updates",
    "pattern_dma_blank_words",
    "pattern_dma_active_words",
    "pattern_cpu_blank_words",
    "pattern_cpu_active_words",
    "pattern_cpu_boundary_words",
    "name_table_dma_blank_words",
    "name_table_dma_active_words",
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("tsv", type=Path)
    parser.add_argument("--gate-json", type=Path, required=True)
    parser.add_argument(
        "--gpgx-vdp-tsv",
        type=Path,
        help="optional frame TSV from harness/gpgx_logvdp/extract_frame_tsv.py",
    )
    parser.add_argument("--config", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--label", default="")
    parser.add_argument("--pixels-per-frame", type=int)
    args = parser.parse_args()
    if args.tsv.suffix.lower() != ".tsv":
        parser.error("HUD input must use the .tsv extension")
    return args


def font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(layout.FONT, size)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_gpgx_vdp_tsv(
    path: Path,
    hud_path: Path,
    hud_data: dict[str, np.ndarray],
) -> tuple[dict[str, np.ndarray], dict, Path]:
    with path.open("r", encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source, delimiter="\t")
        fields = set(reader.fieldnames or ())
        missing = {"frame", *GPGX_VDP_COLUMNS} - fields
        if missing:
            raise SystemExit(f"GPGX VDP TSV lacks columns: {sorted(missing)}")
        rows = list(reader)
    frames = np.asarray([int(row["frame"]) for row in rows], np.int64)
    if not np.array_equal(frames, hud_data["frame"]):
        raise SystemExit("GPGX VDP TSV frame axis does not match the HUD TSV")
    arrays = {
        key: np.asarray([int(row[key]) for row in rows], np.float64)
        for key in GPGX_VDP_COLUMNS
    }
    arrays["pattern_cpu_active_edge_words"] = (
        arrays["pattern_cpu_active_words"]
        + arrays["pattern_cpu_boundary_words"]
    )

    receipt_path = Path(str(path) + ".json")
    if not receipt_path.is_file():
        raise SystemExit(f"GPGX VDP TSV receipt is missing: {receipt_path}")
    receipt = json.loads(receipt_path.read_text(encoding="utf-8"))
    if receipt.get("kind") != "gpgx-logvdp-frame-transfer":
        raise SystemExit("GPGX VDP TSV receipt has the wrong kind")
    if int(receipt.get("frames", -1)) != len(rows):
        raise SystemExit("GPGX VDP TSV receipt frame count does not match")
    if str(receipt.get("output_tsv_sha256")) != digest(path):
        raise SystemExit("GPGX VDP TSV hash does not match its receipt")
    if str(receipt.get("hud_tsv_sha256")) != digest(hud_path):
        raise SystemExit("GPGX VDP TSV was extracted against another HUD TSV")

    return arrays, receipt, receipt_path


def parse_value(key: str, text: str) -> float:
    value = text.strip()
    if not value:
        return 0.0
    if key in HEX_COLUMNS:
        return float(int(value, 16))
    return float(value)


def load_tsv(path: Path) -> tuple[list[dict[str, str]], dict[str, np.ndarray], list[str]]:
    with path.open("r", encoding="utf-8", newline="") as source:
        reader = csv.DictReader(source, delimiter="\t")
        fields = list(reader.fieldnames or ())
        missing = {
            "loop",
            "frame",
            *MAXIMUM_COLUMN.values(),
            "adpcm_decode_units",
        } - set(fields)
        if missing:
            raise SystemExit(f"HUD TSV lacks columns: {sorted(missing)}")
        all_rows = list(reader)
    rows = [row for row in all_rows if int(row["loop"]) == 0]
    if not rows:
        raise SystemExit("HUD TSV contains no first-loop rows")
    frames = np.asarray([int(row["frame"]) for row in rows], np.int64)
    if not np.array_equal(frames, np.arange(len(rows))):
        raise SystemExit("first-loop HUD frames must be contiguous and start at zero")
    arrays: dict[str, np.ndarray] = {"frame": frames}
    for key in fields:
        if key in {
            "loop", "frame", "frame_hex", "audio_lead_hex",
            "audio_resync_transition",
        }:
            continue
        texts = [row[key].strip() for row in rows]
        if not any(texts):
            continue
        try:
            arrays[key] = np.asarray(
                [parse_value(key, value) for value in texts], np.float64)
        except ValueError:
            continue
    return rows, arrays, fields


def load_gate(path: Path) -> dict:
    raw_gate = json.loads(path.read_text(encoding="utf-8"))
    try:
        gate = hud_gate.normalize_result(raw_gate)
    except ValueError as exc:
        raise SystemExit(f"invalid HUD gate JSON: {exc}") from exc
    for key in (
        "expected_frames", "observed_first_loop_frames", "maxima", "limits",
        "pass", "recording", "recording_size", "recording_mtime_ns",
        "content_fps", "profile_sha256",
    ):
        if key not in gate:
            raise SystemExit(f"gate JSON lacks {key}")
    if int(gate.get("schema_version", 0)) != 16:
        raise SystemExit("hudline requires descriptive HUD gate schema 16")
    if "cd_wait_count" not in gate["maxima"]:
        raise SystemExit("gate JSON lacks cd_wait_count maximum")
    if "cd_wait_count" in gate["limits"]:
        raise SystemExit("gate must not define a cd_wait_count limit")
    if list(gate.get("gate_fields", ())) != list(GATE_COLUMN):
        raise SystemExit("gate_fields do not match the descriptive HUD gate")
    if list(gate.get("warning_fields", ())) != ["vblank_spill"]:
        raise SystemExit("warning_fields must contain only vblank_spill")
    diagnostics = set(gate.get("diagnostic_fields", ()))
    for field in (
        "cold_runs",
        "pattern_dma_ready_vcounter",
        "name_table_dma_ready_vcounter",
    ):
        if field not in diagnostics:
            raise SystemExit(f"diagnostic_fields omit required {field}")
    return gate


def field_statistics(
    data: dict[str, np.ndarray],
    column: str,
) -> dict[str, int | float]:
    """Summarize one HUD field over timed first-loop frames only."""
    values = np.asarray(data.get(column, np.asarray([]))[1:], dtype=np.float64)
    if not values.size:
        return {
            "minimum": 0,
            "mean": 0.0,
            "median": 0.0,
            "maximum": 0,
            "sample_count": 0,
        }
    return {
        "minimum": int(values.min()),
        "mean": float(values.mean()),
        "median": float(np.median(values)),
        "maximum": int(values.max()),
        "sample_count": int(values.size),
    }


def cd_wait_statistics(
    data: dict[str, np.ndarray],
) -> dict[str, int | float]:
    return field_statistics(data, "cd_wait_count")


def adpcm_decode_statistics(
    data: dict[str, np.ndarray],
) -> dict[str, int | float]:
    return field_statistics(data, "adpcm_decode_units")


def pump_gap_statistics(
    data: dict[str, np.ndarray],
) -> dict[str, int | float]:
    return field_statistics(data, "pump_gap_ticks")


def validate(
    tsv_path: Path,
    gate_path: Path,
    config_path: Path | None,
    rows: list[dict[str, str]],
    data: dict[str, np.ndarray],
    gate: dict,
) -> None:
    frames = len(rows)
    for field in (
        "pattern_dma_ready_vcounter",
        "name_table_dma_ready_vcounter",
    ):
        if field not in data:
            raise SystemExit(f"HUD TSV lacks required schema-16 field {field}")
    if int(gate["observed_first_loop_frames"]) != frames:
        raise SystemExit(
            "gate observed_first_loop_frames does not match the HUD TSV")
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
    for gate_key, column in MAXIMUM_COLUMN.items():
        actual = int(round(float(data[column][1:].max(initial=0))))
        recorded = int(gate["maxima"][gate_key])
        if actual != recorded:
            raise SystemExit(
                f"gate {gate_key} maximum {recorded} != TSV maximum {actual}")
    if int(gate.get("evaluation_first_frame", 1)) != 1:
        raise SystemExit("HUD gate must exclude untimed frame 0")
    for field, statistics_key, expected in (
        (
            "cd_wait_count",
            "cd_wait_statistics",
            cd_wait_statistics(data),
        ),
        (
            "adpcm_decode_units",
            "adpcm_decode_statistics",
            adpcm_decode_statistics(data),
        ),
    ):
        recorded = gate.get(statistics_key)
        if recorded is None:
            raise SystemExit(f"gate JSON lacks {statistics_key}")
        for key in ("minimum", "maximum", "sample_count"):
            if int(recorded[key]) != int(expected[key]):
                raise SystemExit(
                    f"gate {field} {key} {recorded[key]} != "
                    f"TSV value {expected[key]}"
                )
        for key in ("mean", "median"):
            if not math.isclose(
                float(recorded[key]),
                float(expected[key]),
                abs_tol=1e-12,
            ):
                raise SystemExit(
                    f"gate {field} {key} {recorded[key]} != "
                    f"TSV value {expected[key]}"
                )
    g_values = data.get("pump_gap_ticks")
    if g_values is not None:
        expected = pump_gap_statistics(data)
        recorded = gate.get("pump_gap_statistics")
        if recorded is None:
            raise SystemExit("gate JSON lacks pump_gap_statistics")
        for key in ("minimum", "maximum", "sample_count"):
            if int(recorded[key]) != int(expected[key]):
                raise SystemExit(
                    "gate pump_gap_ticks "
                    f"{key} {recorded[key]} != TSV value {expected[key]}")
        for key in ("mean", "median"):
            if not math.isclose(
                float(recorded[key]), float(expected[key]), abs_tol=1e-12
            ):
                raise SystemExit(
                    "gate pump_gap_ticks "
                    f"{key} {recorded[key]} != TSV value {expected[key]}")
    b_values = data.get("apply_backpressure")
    if b_values is not None:
        expected_count = int(np.count_nonzero(b_values[1:]))
        recorded_count = gate.get("apply_backpressure_frames")
        if recorded_count is None:
            raise SystemExit("gate JSON lacks apply_backpressure_frames")
        if int(recorded_count) != expected_count:
            raise SystemExit(
                "gate apply_backpressure frame count "
                f"{recorded_count} != TSV value {expected_count}"
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
        values = data.get(column)
        if values is not None:
            expected = int(values[1:].max(initial=0))
            if gate_key not in gate:
                raise SystemExit(f"gate JSON lacks {gate_key}")
            if int(gate[gate_key]) != expected:
                raise SystemExit(
                    f"gate {column} maximum {gate[gate_key]} != "
                    f"TSV value {expected}"
                )
    if config_path is not None:
        if digest(config_path) != str(gate["profile_sha256"]):
            raise SystemExit("profile SHA does not match gate JSON")
    recording = Path(str(gate["recording"]))
    if recording.exists():
        stat = recording.stat()
        if stat.st_size != int(gate["recording_size"]):
            raise SystemExit("recording size does not match gate JSON")
        if stat.st_mtime_ns != int(gate["recording_mtime_ns"]):
            raise SystemExit("recording mtime does not match gate JSON")
    if not tsv_path.is_file() or not gate_path.is_file():
        raise SystemExit("HUD inputs disappeared while validating")


def derive_display_vblanks(
    data: dict[str, np.ndarray],
    content_fps: float,
) -> tuple[np.ndarray, tuple[int, ...] | None]:
    """Return displayed VBlanks per content frame from capture-frame starts.

    ``frame`` is published atomically with the displayed movie frame.  The distance
    between consecutive first sightings therefore measures how many captured
    VBlanks the earlier content frame remained visible.  The final movie frame
    has no next F transition and is deliberately left unknown so the terminal
    hold cannot contaminate cadence statistics.
    """
    starts = data.get("capture_first")
    if starts is None:
        raise SystemExit("HUD TSV lacks capture_first for displayed VBlank timing")
    if len(starts) != len(data["frame"]):
        raise SystemExit("capture_first length does not match HUD frame count")
    displayed = np.full(len(starts), np.nan, dtype=np.float64)
    if len(starts) > 1:
        spans = np.diff(starts.astype(np.int64))
        if np.any(spans <= 0):
            raise SystemExit("capture_first must increase between content frames")
        displayed[:-1] = spans
        # Frame 0 is boot staging, not a timed playback frame.  Its long first
        # span must be absent both visually and statistically.
        displayed[0] = np.nan
    return displayed, av_config.vblank_cadence_pattern(content_fps)


def display_vblank_targets(
    data: dict[str, np.ndarray],
    cadence_pattern: tuple[int, ...] | None,
) -> np.ndarray:
    """Return the phase-correct expected visible duration for each frame.

    A value stored at frame ``F`` measures the transition from ``F`` to
    ``F+1``. Frame ``F+1`` uses cadence element ``F % period``; frame zero and
    the terminal frame remain unmeasured in the companion display array.
    """

    targets = np.full(len(data["frame"]), np.nan, dtype=np.float64)
    if cadence_pattern is None:
        return targets
    frames = data["frame"].astype(np.int64)
    for index, frame in enumerate(frames):
        if frame > 0:
            targets[index] = cadence_pattern[frame % len(cadence_pattern)]
    return targets


def derive_pattern_ready_pressure(
    data: dict[str, np.ndarray],
) -> np.ndarray:
    """Map raw ready V-counters to first-VBlank pressure.

    Visible scanlines 0..223 map directly to pressure 0..223.  E0 is the
    zero-margin target head. A blank-phase sample no more than one complete
    blank after the preceding flip belongs to that preceding blank and clamps
    to zero: it is earlier than the active raster leading to PT VBlank 1.
    Any other later-blank sample maps to the 0x100 missed-head sentinel,
    avoiding the NTSC V-counter's ambiguous E5..EA repeat. Frames without a
    cold run have no ready event and remain NaN rather than masquerading as a
    real scanline-0 sample.
    """

    ready = np.asarray(data["pattern_dma_ready_vcounter"], np.float64)
    runs = np.asarray(data["cold_runs"], np.float64)
    delay_q4 = np.asarray(data["pass2_delay_q4"], np.float64)
    if ready.shape != runs.shape or ready.shape != delay_q4.shape:
        raise SystemExit(
            "pattern ready V-counter, cold-run, and pass2-delay arrays "
            "have different lengths"
        )
    if np.any(~np.isfinite(ready)) or np.any((ready < 0) | (ready > 0xFF)):
        raise SystemExit("pattern ready V-counter must stay in 00..FF")
    if np.any(~np.isfinite(delay_q4)) or np.any(
        (delay_q4 < 0) | (delay_q4 > 0xFF)
    ):
        raise SystemExit("pass2 delay q4 must stay in 00..FF")
    pressure = np.full(ready.shape, np.nan, dtype=np.float64)
    measured = runs > 0
    pressure[measured] = np.minimum(
        ready[measured],
        PATTERN_READY_MISSED_PRESSURE,
    )
    preceding_blank = (
        measured
        & (ready >= PATTERN_READY_DEADLINE_SCANLINE)
        & (delay_q4 <= PATTERN_READY_SAME_BLANK_Q4_MAX)
    )
    pressure[preceding_blank] = 0
    pressure[
        measured
        & ~preceding_blank
        & (ready > PATTERN_READY_DEADLINE_SCANLINE)
    ] = (
        PATTERN_READY_MISSED_PRESSURE
    )
    return pressure


def pattern_ready_pressure_summary(
    pressure: np.ndarray,
) -> dict[str, int]:
    """Summarize timed ready pressure without counting absent run frames."""

    measured = np.asarray(pressure[1:], np.float64)
    measured = measured[np.isfinite(measured)]
    if not measured.size:
        return {
            "maximum": 0,
            "minimum_margin_scanlines": PATTERN_READY_DEADLINE_SCANLINE,
            "missed_frames": 0,
            "sample_count": 0,
        }
    missed = measured > PATTERN_READY_DEADLINE_SCANLINE
    margin = np.maximum(
        PATTERN_READY_DEADLINE_SCANLINE
        - np.minimum(measured, PATTERN_READY_DEADLINE_SCANLINE),
        0,
    )
    return {
        "maximum": int(measured.max()),
        "minimum_margin_scanlines": int(margin.min()),
        "missed_frames": int(np.count_nonzero(missed)),
        "sample_count": int(measured.size),
    }


def derive_name_table_ready_pressure(
    data: dict[str, np.ndarray],
    content_fps: float,
) -> np.ndarray:
    """Map pre-wait NT readiness to cadence-final-VBlank pressure.

    ``transfer_vblanks`` identifies which fresh pattern budget has already
    opened. Readiness at least one whole raster before the cadence-final blank
    is unpressured and clamps to zero. In the active raster immediately before
    that target blank, raw scanlines 00..DF map directly to pressure.

    If PT splits into the cadence-final budget, NT cannot start at that
    VBlank's head: its earliest legal point is after PT2. A readiness sample in
    that target VBlank therefore keeps its raw E0..FF pressure instead of
    collapsing to a generic missed-head sentinel. A visible sample after that
    budget opened means the target blank was exhausted; a later-than-target
    PT budget also maps to 0x100.

    A movie with no nonzero timed sample does not use this DMA path.  When the
    path is present, a real raw scanline-0 sample remains pressure zero.
    """

    raw = np.asarray(data["name_table_dma_ready_vcounter"], np.float64)
    opened = np.asarray(data["transfer_vblanks"], np.float64)
    if raw.shape != opened.shape:
        raise SystemExit(
            "name-table ready V-counter and transfer-VBlank arrays "
            "have different lengths"
        )
    if np.any(~np.isfinite(raw)) or np.any((raw < 0) | (raw > 0xFF)):
        raise SystemExit("name-table DMA ready V-counter must stay in 00..FF")
    if np.any(~np.isfinite(opened)) or np.any(opened < 0):
        raise SystemExit("transfer VBlanks must be finite and nonnegative")
    pressure = np.full(raw.shape, np.nan, dtype=np.float64)
    path_present = bool(np.any(raw[1:] != 0)) if raw.size > 1 else False
    if not path_present:
        return pressure
    frames = np.asarray(
        data.get("frame", np.arange(len(raw), dtype=np.int64)),
        dtype=np.int64,
    )
    if frames.shape != raw.shape:
        raise SystemExit("frame and name-table ready arrays have different lengths")
    cadence_pattern = av_config.vblank_cadence_pattern(content_fps)
    if cadence_pattern is None:
        target_vblank = np.full(
            raw.shape,
            av_config.vsync_n_for_fps(content_fps),
            dtype=np.int64,
        )
    else:
        target_vblank = np.asarray([
            cadence_pattern[(max(int(frame), 1) - 1) % len(cadence_pattern)]
            for frame in frames
        ], dtype=np.int64)
    final_preblank_budget = np.maximum(0, target_vblank - 1)
    pressure[:] = 0
    final_preblank = opened == final_preblank_budget
    visible = raw < NT_READY_DEADLINE_SCANLINE
    pressure[final_preblank & visible] = raw[final_preblank & visible]
    target_budget = opened == target_vblank
    pressure[target_budget & ~visible] = raw[target_budget & ~visible]
    pressure[target_budget & visible] = NT_READY_MISSED_PRESSURE
    pressure[opened > target_vblank] = NT_READY_MISSED_PRESSURE
    return pressure


def name_table_ready_pressure_summary(
    pressure: np.ndarray,
) -> dict[str, int]:
    """Summarize timed NT readiness against its cadence-final blank head."""

    measured = np.asarray(pressure[1:], np.float64)
    measured = measured[np.isfinite(measured)]
    if not measured.size:
        return {
            "maximum": 0,
            "minimum_margin_scanlines": NT_READY_DEADLINE_SCANLINE,
            "missed_frames": 0,
            "sample_count": 0,
        }
    missed = measured > NT_READY_DEADLINE_SCANLINE
    margin = np.maximum(
        NT_READY_DEADLINE_SCANLINE
        - np.minimum(measured, NT_READY_DEADLINE_SCANLINE),
        0,
    )
    return {
        "maximum": int(measured.max()),
        "minimum_margin_scanlines": int(margin.min()),
        "missed_frames": int(np.count_nonzero(missed)),
        "sample_count": int(measured.size),
    }


def display_vblank_alert_masks(
    data: dict[str, np.ndarray],
    displayed: np.ndarray,
    expected_frames: int,
    content_fps: float,
    cadence_pattern: tuple[int, ...] | None,
) -> tuple[np.ndarray, np.ndarray, int]:
    """Return alert-eligible and edge-exempt measured-frame masks."""

    eligible = np.zeros(len(displayed), dtype=bool)
    exempt = np.zeros(len(displayed), dtype=bool)
    if cadence_pattern is None:
        return eligible, exempt, 0
    frames = data["frame"].astype(np.int64)
    measured = np.isfinite(displayed)
    edge_frames = hud_gate.cadence_alert_edge_frames(content_fps)
    eligible = measured.copy()
    if edge_frames:
        eligible &= frames >= edge_frames
        eligible &= frames < max(0, expected_frames - edge_frames)
    exempt = measured & ~eligible
    return eligible, exempt, edge_frames


def row_specs(
    data: dict[str, np.ndarray],
    gate: dict,
    display_vblank_expected: tuple[int, ...] | None,
) -> list[RowSpec]:
    limits = {key: float(value) for key, value in gate["limits"].items()}

    def timed_max(key: str, default: float = 0.0) -> float:
        values = data.get(key)
        if values is None or len(values) <= 1:
            return float(default)
        finite = values[1:][np.isfinite(values[1:])]
        return float(finite.max(initial=default))

    lead_max = max(
        0x68,
        int(math.ceil(timed_max("audio_lead_256b"))))
    display_vblanks = data["display_vblanks"]
    finite_vblanks = display_vblanks[np.isfinite(display_vblanks)]
    capacity_floor = (
        float(max(display_vblank_expected) * 2)
        if display_vblank_expected is not None
        else 1.0
    )
    display_vblank_max = float(
        finite_vblanks.max(initial=capacity_floor))
    rows = [
        RowSpec(
            "display_vblanks",
            "VBLANK",
            "display VBlanks/frame",
            max(capacity_floor, display_vblank_max),
            PASS_GUIDE,
            normal_value=(
                float(display_vblank_expected[0])
                if (
                    display_vblank_expected is not None
                    and len(display_vblank_expected) == 1
                )
                else None
            ),
            normal_key=(
                "display_vblank_target"
                if display_vblank_expected is not None else None
            ),
        ),
        RowSpec(
            "pattern_dma_ready_pressure",
            "PATTERN READY PRESSURE",
            "scanline 0=0; prior blank=0; 0x100=missed head",
            PATTERN_READY_MISSED_PRESSURE,
            (98, 184, 224),
            height=DMA_START_LINE_HEIGHT,
            point_plot=True,
            show_zero=True,
            deadline_value=PATTERN_READY_DEADLINE_SCANLINE,
            deadline_label="VBlank head",
        ),
        RowSpec(
            "name_table_dma_ready_pressure",
            "NT READY PRESSURE",
            "scanline 0=0; split E0..FF=after PT2; 0x100=escaped blank",
            NT_READY_MISSED_PRESSURE,
            (152, 139, 222),
            height=DMA_START_LINE_HEIGHT,
            point_plot=True,
            show_zero=True,
            deadline_value=NT_READY_DEADLINE_SCANLINE,
            deadline_label="target VBlank head",
        ),
        RowSpec(
            "sector_slip", "SECTOR SLIP", "cumulative",
            max(1, limits["sector_slip"]),
            PASS_GUIDE, "sector_slip", height=23, show_unit=False,
        ),
        RowSpec(
            "control_desync", "CONTROL DESYNC", "cumulative",
            max(1, limits["control_desync"]),
            PASS_GUIDE, "control_desync", height=23, show_unit=False,
        ),
        RowSpec(
            "audio_resync", "AUDIO RESYNC", "cumulative",
            max(1, limits["audio_resync"]),
            PASS_GUIDE, "audio_resync", height=23, show_unit=False,
        ),
        RowSpec("vblank_spill", "VBLANK SPILL", "VBlanks/frame",
                max(1, limits["vblank_spill"], timed_max("vblank_spill")),
                (238, 135, 73), "vblank_spill"),
        RowSpec("prgbuf_jitter_peak_kib", "PRGBUF JITTER", "sticky peak KiB",
                max(
                    1,
                    limits["prgbuf_jitter_peak_kib"],
                    timed_max("prgbuf_jitter_peak_kib"),
                    float(gate.get("jitter_headroom_kib", 0))),
                style.COL_PRG, "prgbuf_jitter_peak_kib"),
    ]
    if "pattern_dma_blank_words" in data:
        pattern_phase_max = max(
            1,
            *(
                timed_max(key)
                for key in (
                    "pattern_dma_blank_words",
                    "pattern_dma_active_words",
                    "pattern_cpu_blank_words",
                    "pattern_cpu_active_edge_words",
                )
            ),
        )
        rows.extend([
            RowSpec(
                "pattern_dma_blank_words",
                "PATTERN DMA IN BLANK",
                "pattern words/frame",
                pattern_phase_max,
                (94, 174, 224),
            ),
            RowSpec(
                "pattern_dma_active_words",
                "PATTERN DMA IN ACTIVE",
                "pattern words/frame",
                pattern_phase_max,
                WARN,
            ),
            RowSpec(
                "pattern_cpu_blank_words",
                "PATTERN CPU IN BLANK",
                "direct + repair words/frame",
                pattern_phase_max,
                (102, 193, 169),
            ),
            RowSpec(
                "pattern_cpu_active_edge_words",
                "PATTERN CPU IN ACTIVE*",
                "active + V-edge words/frame",
                pattern_phase_max,
                (238, 135, 73),
            ),
            RowSpec(
                "name_table_dma_blank_words",
                "NAME TABLE DMA IN BLANK",
                "name-table words/frame",
                max(1, timed_max("name_table_dma_blank_words")),
                (132, 160, 220),
            ),
            RowSpec(
                "name_table_dma_active_words",
                "NAME TABLE DMA IN ACTIVE",
                "name-table words/frame",
                max(1, timed_max("name_table_dma_active_words")),
                FAIL,
            ),
            RowSpec(
                "pattern_dma_commands",
                "PATTERN DMA COMMANDS",
                "commands/frame",
                max(1, timed_max("pattern_dma_commands")),
                style.COL_RUN,
            ),
        ])
    if "pump_gap_ticks" in data:
        frame_ticks = math.ceil(
            1000.0 / float(gate["content_fps"]) / 0.03072
        )
        rows.append(
            RowSpec(
                "pump_gap_ticks",
                "SUB PUMP GAP",
                "30.72 us ticks",
                max(frame_ticks, timed_max("pump_gap_ticks")),
                (176, 112, 224),
            )
        )
    if "msf_gap_recoveries" in data:
        rows.append(
            RowSpec(
                "msf_gap_recoveries",
                "MSF GAP",
                "cumulative recoveries",
                max(1, timed_max("msf_gap_recoveries")),
                (208, 142, 94),
            )
        )
    if "apply_backpressure" in data:
        rows.append(
            RowSpec(
                "apply_backpressure",
                "APPLY BACKPRESSURE",
                "control back-pressure/frame",
                1,
                WARN,
                show_zero=False,
            )
        )
    if "reader_ahead_frames" in data:
        rows.append(
            RowSpec(
                "reader_ahead_frames",
                "READER AHEAD",
                "complete frame slots",
                max(1, timed_max("reader_ahead_frames")),
                (103, 181, 220),
            )
        )
    if "reader_slot_sector" in data:
        rows.append(
            RowSpec(
                "reader_slot_sector",
                "READER SLOT",
                "sector index in slot",
                max(1, timed_max("reader_slot_sector")),
                (94, 158, 205),
            )
        )
    if "transfer_vblanks" in data:
        rows.append(
            RowSpec(
                "transfer_vblanks",
                "TRANSFER VBLANKS",
                "fresh pattern budgets opened/frame",
                max(2, timed_max("transfer_vblanks")),
                (238, 157, 82),
            )
        )
    if "transfer_end_vcounter" in data:
        rows.append(
            RowSpec(
                "transfer_end_vcounter",
                "TRANSFER END",
                "VDP V-counter",
                0xFF,
                (198, 137, 226),
                eight_bit_scale=True,
            )
        )
    rows.extend([
        RowSpec("cd_wait_count", "CD WAIT", "sectors/frame",
                max(1, timed_max("cd_wait_count")), WARN),
        RowSpec("audio_lead_256b", "AUDIO LEAD", "256-byte units", lead_max,
                (82, 153, 232)),
        RowSpec("sub_wait_scanlines", "SUB HANDOFF", "approx. scanlines", 255,
                (176, 112, 224), eight_bit_scale=True),
        RowSpec("adpcm_decode_units", "ADPCM", "0.12288 ms units", 255,
                (218, 112, 171), eight_bit_scale=True),
        RowSpec("transfer_ms", "PATTERN TRANSFER", "ms, 12-bit wrap", 125.83,
                (81, 202, 211)),
        RowSpec(
            "cold_runs",
            "COLD RUNS",
            "runs",
            max(1, timed_max("cold_runs")),
            style.COL_RUN,
            show_zero=False,
        ),
    ])
    optional = (
        ("flip_vcounter", "FLIP VCOUNTER", "VDP line, prior frame",
         (124, 193, 113)),
        ("first_share_exit_vcounter", "FIRST SHARE EXIT", "VDP line",
         (112, 178, 216)),
        ("pass2_delay_q4", "PASS2 DELAY", "4 ticks",
         (223, 182, 91)),
    )
    for key, label, unit, color in optional:
        if key in data:
            rows.append(
                RowSpec(
                    key,
                    label,
                    unit,
                    255,
                    color,
                    eight_bit_scale=True,
                    show_zero=False,
                )
            )
    return rows


def value_color(
    value: float,
    spec: RowSpec,
    gate: dict,
    *,
    normal_value: float | None = None,
) -> tuple[int, int, int]:
    if spec.deadline_value is not None:
        if value > spec.deadline_value:
            return FAIL
        if math.isclose(value, spec.deadline_value, abs_tol=0.01):
            return WARN
    normal = spec.normal_value if normal_value is None else normal_value
    if normal is not None:
        if value <= 0:
            return FAIL
        if math.isclose(value, normal, abs_tol=0.01):
            return spec.color
        return WARN
    if spec.gate_key is None:
        return spec.color
    limit = float(gate["limits"][spec.gate_key])
    if value > limit:
        return (
            WARN
            if spec.gate_key in gate.get("warning_fields", ())
            else FAIL
        )
    return spec.color


def fmt_hex(value: float) -> str:
    return f"0x{max(0, int(round(value))):02X}"


def fmt_frame(frame_index: int, frames: int) -> str:
    width = max(3, len(f"{max(frames - 1, 0):X}"))
    return f"f0x{frame_index:0{width}X}"


def draw_scale(
    draw: ImageDraw.ImageDraw,
    left: int,
    right: int,
    top: int,
    height: int,
    maximum: float,
    show_zero: bool,
) -> None:
    compact = height <= 23
    scale_font = font(10 if compact else 13)
    edge_offset = 6 if compact else 9
    y = top
    draw.line((left, y, right, y), fill=GRID, width=1)
    draw.text(
        (left - 10, y + edge_offset),
        fmt_hex(maximum),
        fill=(185, 187, 196),
        font=scale_font,
        anchor="rm",
    )
    if show_zero:
        draw.text(
            (left - 10, top + height - 1 - edge_offset),
            fmt_hex(0),
            fill=(185, 187, 196),
            font=scale_font,
            anchor="rm",
        )


def draw_rows(
    image: Image.Image,
    data: dict[str, np.ndarray],
    specs: list[RowSpec],
    gate: dict,
    *,
    left: int,
    top: int,
    ppf: int,
    axis_frames: int,
) -> int:
    draw = ImageDraw.Draw(image)
    observed_frames = len(data["frame"])
    if axis_frames < observed_frames:
        raise SystemExit("HUD frame axis is shorter than the observed prefix")
    plot_width = axis_frames * ppf
    right = left + plot_width - 1
    label_font = font(16)
    unit_font = font(13)
    y0 = top
    for row_index, spec in enumerate(specs):
        row_height = spec.height
        y1 = y0 + row_height - 1
        draw.rectangle((left, y0, right, y1), fill=PANEL, outline=GRID)
        values = data.get(spec.key, np.zeros(observed_frames))
        for frame_index, raw in enumerate(values):
            if frame_index == 0:
                continue
            value = float(raw)
            if not math.isfinite(value):
                continue
            value = max(0.0, value)
            x0 = left + frame_index * ppf
            x1 = x0 + ppf - 1
            clipped = min(value, spec.maximum)
            normal_value = None
            if spec.normal_key is not None:
                normal_values = data.get(spec.normal_key)
                if normal_values is not None and frame_index < len(normal_values):
                    candidate = float(normal_values[frame_index])
                    if math.isfinite(candidate):
                        normal_value = candidate
            bar = int(round((row_height - 1) * clipped / max(spec.maximum, 1e-9)))
            if spec.point_plot:
                point_x = x0 + ppf // 2
                point_span = max(row_height - 3, 1)
                point_y = y1 - 1 - int(round(
                    point_span * clipped / max(spec.maximum, 1e-9)
                ))
                draw.point(
                    (point_x, point_y),
                    fill=value_color(
                        value, spec, gate, normal_value=normal_value),
                )
            elif bar:
                draw.rectangle(
                    (x0, y1 - bar + 1, x1, y1),
                    fill=value_color(
                        value, spec, gate, normal_value=normal_value),
                )
            if normal_value is not None:
                normal_y = y1 - int(round(
                    (row_height - 1) * min(normal_value, spec.maximum)
                    / max(spec.maximum, 1e-9)))
                draw.line((x0, normal_y, x1, normal_y), fill=PASS_GUIDE)
            if value > spec.maximum:
                draw.line((x0, y0, x1, y0), fill=FAIL, width=2)
        draw_scale(
            draw,
            left,
            right,
            y0,
            row_height,
            spec.maximum,
            spec.show_zero,
        )
        draw.text(
            (18, y0 + (1 if row_height <= 23 else 3)),
            spec.label,
            fill=TEXT,
            font=label_font,
        )
        if spec.show_unit:
            draw.text((18, y0 + 25), spec.unit, fill=DIM, font=unit_font)

        if spec.gate_key is not None:
            limit = float(gate["limits"][spec.gate_key])
            limit_y = y1 - int(round(
                (row_height - 1) * min(limit, spec.maximum)
                / max(spec.maximum, 1e-9)))
            draw.line((left, limit_y, right, limit_y), fill=LIMIT, width=2)
            draw.text(
                (right - 4, limit_y - 2),
                f"limit {fmt_hex(limit)}",
                fill=LIMIT,
                font=font(13),
                anchor="rb",
            )
            if spec.gate_key == "prgbuf_jitter_peak_kib":
                normal = float(gate.get("jitter_headroom_kib", 0))
                normal_y = y1 - int(round(
                    (row_height - 1) * min(normal, spec.maximum)
                    / max(spec.maximum, 1e-9)))
                draw.line(
                    (left, normal_y, right, normal_y),
                    fill=NORMAL_LIMIT,
                    width=1,
                )
                draw.text(
                    (right - 4, normal_y - 2),
                    f"normal {fmt_hex(normal)}",
                    fill=NORMAL_LIMIT,
                    font=font(13),
                    anchor="rb",
                )

        if spec.normal_value is not None:
            normal = float(spec.normal_value)
            normal_y = y1 - int(round(
                (row_height - 1) * min(normal, spec.maximum)
                / max(spec.maximum, 1e-9)))
            draw.line(
                (left, normal_y, right, normal_y),
                fill=PASS_GUIDE,
                width=2,
            )
            draw.text(
                (right - 4, normal_y - 2),
                f"normal {fmt_hex(normal)}",
                fill=PASS_GUIDE,
                font=font(13),
                anchor="rb",
            )
        if spec.deadline_value is not None:
            deadline = float(spec.deadline_value)
            deadline_y = y1 - int(round(
                (row_height - 1) * min(deadline, spec.maximum)
                / max(spec.maximum, 1e-9)))
            draw.line(
                (left, deadline_y, right, deadline_y),
                fill=LIMIT,
                width=2,
            )
            label = spec.deadline_label or "deadline"
            draw.text(
                (right - 4, deadline_y - 2),
                f"{label} {fmt_hex(deadline)}",
                fill=LIMIT,
                font=font(13),
                anchor="rb",
            )
        y0 += row_height

    bottom = y0
    fps = float(gate["content_fps"])
    duration = axis_frames / fps
    for second in range(0, math.ceil(duration) + 1):
        frame_index = min(round(second * fps), axis_frames - 1)
        x = left + frame_index * ppf
        major = second % 5 == 0
        draw.line(
            (x, top, x, bottom),
            fill=MAJOR_GRID if major else (38, 40, 47),
            width=1,
        )
        if major:
            draw.text((x + 3, bottom + 9), f"{second}s", fill=DIM, font=font(18))
            draw.text(
                (x + 3, bottom + 32),
                fmt_frame(frame_index, axis_frames),
                fill=(115, 117, 126),
                font=font(15),
            )

    palette = data.get(
        "palette_segment",
        np.zeros(observed_frames),
    ).astype(np.int64)
    switches = np.flatnonzero(np.r_[False, palette[1:] != palette[:-1]])
    for frame_index in switches:
        x = left + int(frame_index) * ppf
        draw.line((x, top, x, bottom), fill=(130, 132, 145), width=2)
        draw.text(
            (x + 3, top + 3),
            f"palette_segment={palette[frame_index]:02d}",
            fill=TEXT,
            font=font(14),
        )
    return bottom


def main() -> None:
    args = parse_args()
    tsv_path = args.tsv.resolve()
    gate_path = args.gate_json.resolve()
    config_path = args.config.resolve() if args.config else None
    rows, data, _fields = load_tsv(tsv_path)
    gate = load_gate(gate_path)
    validate(tsv_path, gate_path, config_path, rows, data, gate)
    gpgx_vdp_path = args.gpgx_vdp_tsv.resolve() if args.gpgx_vdp_tsv else None
    gpgx_vdp_receipt = None
    gpgx_vdp_receipt_path = None
    if gpgx_vdp_path is not None:
        gpgx_data, gpgx_vdp_receipt, gpgx_vdp_receipt_path = (
            load_gpgx_vdp_tsv(gpgx_vdp_path, tsv_path, data)
        )
        data.update(gpgx_data)
    display_vblanks, display_vblank_pattern = derive_display_vblanks(
        data,
        float(gate["content_fps"]),
    )
    data["display_vblanks"] = display_vblanks
    display_vblank_targets_array = display_vblank_targets(
        data,
        display_vblank_pattern,
    )
    data["display_vblank_target"] = display_vblank_targets_array
    display_vblank_expected = (
        None
        if display_vblank_pattern is None
        else (
            display_vblank_pattern[0]
            if len(display_vblank_pattern) == 1
            else list(display_vblank_pattern)
        )
    )
    if gate.get("display_vblank_expected") != display_vblank_expected:
        raise SystemExit(
            "gate display_vblank_expected does not match the profile cadence"
        )
    data["pattern_dma_ready_pressure"] = derive_pattern_ready_pressure(data)
    ready_pressure = pattern_ready_pressure_summary(
        data["pattern_dma_ready_pressure"]
    )
    data["name_table_dma_ready_pressure"] = derive_name_table_ready_pressure(
        data,
        float(gate["content_fps"]),
    )
    name_table_ready_pressure = name_table_ready_pressure_summary(
        data["name_table_dma_ready_pressure"],
    )
    finite_display_vblanks = display_vblanks[np.isfinite(display_vblanks)]
    (
        display_vblank_alert_mask,
        display_vblank_exempt_mask,
        display_vblank_edge_frames,
    ) = display_vblank_alert_masks(
        data,
        display_vblanks,
        int(gate["expected_frames"]),
        float(gate["content_fps"]),
        display_vblank_pattern,
    )
    display_vblank_warning_count = (
        int(np.count_nonzero(
            display_vblank_alert_mask
            & (display_vblanks != display_vblank_targets_array)
        ))
        if display_vblank_pattern is not None
        else None
    )
    display_vblank_exempted_warning_count = (
        int(np.count_nonzero(
            display_vblank_exempt_mask
            & (display_vblanks != display_vblank_targets_array)
        ))
        if display_vblank_pattern is not None
        else None
    )
    display_vblank_total = int(np.count_nonzero(display_vblank_alert_mask))
    display_vblank_measured_total = int(len(finite_display_vblanks))
    display_vblank_warning_rate = (
        (
            100.0 * display_vblank_warning_count / display_vblank_total
            if display_vblank_total else 0.0
        )
        if display_vblank_warning_count is not None
        else None
    )
    if "display_vblank_edge_exempt_frames" in gate:
        for key, actual in (
            ("display_vblank_alert_evaluated_frames", display_vblank_total),
            ("display_vblank_edge_exempt_frames", display_vblank_edge_frames),
            (
                "display_vblank_exempted_violation_count",
                display_vblank_exempted_warning_count,
            ),
            ("display_vblank_violation_count", display_vblank_warning_count),
        ):
            if (
                key in gate
                and actual is not None
                and int(gate[key]) != int(actual)
            ):
                raise SystemExit(
                    f"gate {key} {gate[key]} != HUD TSV value {actual}"
                )

    observed_frames = len(rows)
    axis_frames = int(gate["expected_frames"])
    ppf = (
        args.pixels_per_frame
        or max(1, min(4, math.ceil(4200 / axis_frames)))
    )
    if ppf <= 0:
        raise SystemExit("pixels per frame must be positive")
    specs = row_specs(data, gate, display_vblank_pattern)
    left = 220
    timeline_top = 172
    plot_width = axis_frames * ppf
    width = left + plot_width + 45
    height = timeline_top + sum(spec.height for spec in specs) + 82
    requested_output = (
        args.output
        or Path(f"{tsv_path.stem}_hudline.png")
    )

    image = Image.new("RGBA", (width, height), BG + (255,))
    draw = ImageDraw.Draw(image)
    title = args.label or tsv_path.stem
    alert = str(gate["alert"])
    if alert == "NONE" and display_vblank_warning_count:
        alert = "WARNING"
    state = hud_gate.legacy_status_for_alert(alert)
    state_color = {
        "PASS": DIM,
        "WARNING": WARN,
        "FAIL": FAIL,
    }[state]
    maxima = gate["maxima"]
    limits = gate["limits"]
    max_text = "  ".join(
        f"{key} {int(maxima[key])}/{int(limits[key])}"
        for key in gate["gate_fields"]
    )
    confidence = data.get("confidence", np.ones(observed_frames))[1:]
    sample_count = data.get("sample_count", np.ones(observed_frames))[1:]
    cd_wait_stats = cd_wait_statistics(data)
    adpcm_decode_stats = adpcm_decode_statistics(data)
    pump_gap_stats = (
        pump_gap_statistics(data) if "pump_gap_ticks" in data else None
    )
    apply_backpressure_frames = (
        int(np.count_nonzero(data["apply_backpressure"][1:]))
        if "apply_backpressure" in data else None
    )
    reader_ahead_max_frames = (
        int(data["reader_ahead_frames"][1:].max(initial=0))
        if "reader_ahead_frames" in data else None
    )
    reader_slot_sector_max = (
        int(data["reader_slot_sector"][1:].max(initial=0))
        if "reader_slot_sector" in data else None
    )
    transfer_vblanks_max = (
        int(data["transfer_vblanks"][1:].max(initial=0))
        if "transfer_vblanks" in data else None
    )
    transfer_end_vcounter_max = (
        int(data["transfer_end_vcounter"][1:].max(initial=0))
        if "transfer_end_vcounter" in data else None
    )
    first_share_exit_vcounter_max = (
        int(data["first_share_exit_vcounter"][1:].max(initial=0))
        if "first_share_exit_vcounter" in data else None
    )
    pattern_dma_ready_vcounter_max = (
        int(data["pattern_dma_ready_vcounter"][1:].max(initial=0))
        if "pattern_dma_ready_vcounter" in data else None
    )
    pattern_dma_ready_pressure_max = int(ready_pressure["maximum"])
    pattern_dma_ready_min_margin_scanlines = int(
        ready_pressure["minimum_margin_scanlines"]
    )
    pattern_dma_ready_missed_frames = int(ready_pressure["missed_frames"])
    pattern_dma_ready_pressure_samples = int(ready_pressure["sample_count"])
    name_table_dma_ready_vcounter_max = (
        int(data["name_table_dma_ready_vcounter"][1:].max(initial=0))
        if "name_table_dma_ready_vcounter" in data else None
    )
    name_table_dma_ready_pressure_max = int(
        name_table_ready_pressure["maximum"]
    )
    name_table_dma_ready_min_margin_scanlines = int(
        name_table_ready_pressure["minimum_margin_scanlines"]
    )
    name_table_dma_ready_missed_frames = int(
        name_table_ready_pressure["missed_frames"]
    )
    name_table_dma_ready_pressure_samples = int(
        name_table_ready_pressure["sample_count"]
    )
    cadence_text = (
        f"VBlank warn {display_vblank_warning_rate:.2f}% / "
        f"{display_vblank_warning_count} / {display_vblank_total}, "
        f"edge-exempt {display_vblank_exempted_warning_count} "
        f"(first/last {display_vblank_edge_frames}), "
        if display_vblank_pattern is not None
        else "VBlank warning rule deferred, "
    )
    pump_gap_stats_text = (
        "pump gap min/mean/median/max "
        f"{int(pump_gap_stats['minimum'])}/"
        f"{float(pump_gap_stats['mean']):.3f}/"
        f"{float(pump_gap_stats['median']):g}/"
        f"{int(pump_gap_stats['maximum'])}; "
        if pump_gap_stats is not None else ""
    )
    apply_backpressure_text = (
        f"APPLY back-pressure {apply_backpressure_frames} frames; "
        if apply_backpressure_frames is not None else ""
    )
    reader_ahead_text = (
        f"reader lead max {reader_ahead_max_frames} frames + "
        f"sector {reader_slot_sector_max}; "
        if (
            reader_ahead_max_frames is not None
            and reader_slot_sector_max is not None
        ) else ""
    )
    transfer_text = (
        f"transfer VBlanks max {transfer_vblanks_max}; "
        f"end V-counter max {transfer_end_vcounter_max:02X}; "
        f"first-share exit max {first_share_exit_vcounter_max:02X}; "
        f"ready pressure max {pattern_dma_ready_pressure_max:02X}, "
        f"min first-VBlank margin "
        f"{pattern_dma_ready_min_margin_scanlines} lines, "
        f"missed {pattern_dma_ready_missed_frames}/"
        f"{pattern_dma_ready_pressure_samples}; "
        f"NT ready pressure max {name_table_dma_ready_pressure_max:02X}, "
        f"min target-VBlank margin "
        f"{name_table_dma_ready_min_margin_scanlines} lines, "
        f"past head {name_table_dma_ready_missed_frames}/"
        f"{name_table_dma_ready_pressure_samples}; "
        "raw pattern/NT ready max "
        f"{pattern_dma_ready_vcounter_max:02X}/"
        f"{name_table_dma_ready_vcounter_max:02X}; "
        if (
            transfer_vblanks_max is not None
            and transfer_end_vcounter_max is not None
            and first_share_exit_vcounter_max is not None
            and pattern_dma_ready_vcounter_max is not None
            and name_table_dma_ready_vcounter_max is not None
        ) else ""
    )
    gpgx_vdp_maxima = (
        {
            key: int(data[key][1:].max(initial=0))
            for key in (
                "pattern_dma_commands",
                "pattern_dma_blank_words",
                "pattern_dma_active_words",
                "pattern_cpu_blank_words",
                "pattern_cpu_active_words",
                "pattern_cpu_boundary_words",
                "pattern_cpu_active_edge_words",
                "name_table_dma_blank_words",
                "name_table_dma_active_words",
            )
        }
        if gpgx_vdp_path is not None else None
    )
    gpgx_vdp_text = (
        "LOGVDP max "
        "pattern DMA blank/active "
        f"{gpgx_vdp_maxima['pattern_dma_blank_words']}/"
        f"{gpgx_vdp_maxima['pattern_dma_active_words']}; "
        f"CPU blank/active+edge "
        f"{gpgx_vdp_maxima['pattern_cpu_blank_words']}/"
        f"{gpgx_vdp_maxima['pattern_cpu_active_edge_words']}; "
        f"NT blank/active "
        f"{gpgx_vdp_maxima['name_table_dma_blank_words']}/"
        f"{gpgx_vdp_maxima['name_table_dma_active_words']} words; "
        if gpgx_vdp_maxima is not None else ""
    )
    phase_note = (
        "pump_gap_ticks is the maximum Sub pump-opportunity interval; "
        "pattern-ready and NT-start pressure, and transfer-exit phases belong "
        "to this frame; "
        if pump_gap_stats is not None
        else "flip_vcounter belongs to the preceding flip; "
        "pattern-ready and NT-start pressure, and transfer-exit phases belong "
        "to this frame; "
    )
    coverage_text = (
        f"Complete DEBUG HUD timeline | {axis_frames} frames | "
        if observed_frames == axis_frames
        else (
            "Observed DEBUG HUD prefix | "
            f"{observed_frames} / {axis_frames} frames | "
        )
    )
    draw.text((24, 16), title, fill=TEXT, font=font(36))
    draw.text((width - 24, 18), state, fill=state_color, font=font(34), anchor="ra")
    draw.text(
        (24, 64),
        (
            coverage_text
            + f"{float(gate['content_fps']):g} fps | {ppf} px/frame"
        ),
        fill=DIM,
        font=font(20),
    )
    draw.text(
        (24, 96),
        (
            f"Gate maxima / limits  {max_text}  |  "
            f"Diagnostic cd_wait_count max {int(maxima['cd_wait_count'])}"
        ),
        fill=DIM,
        font=font(19),
    )
    draw.text(
        (24, 127),
        (
            "PrgBuf jitter normal interval "
            f"{int(gate.get('jitter_headroom_kib', 0))} KiB; "
            "CD wait min/mean/median/max "
            f"{int(cd_wait_stats['minimum'])}/"
            f"{float(cd_wait_stats['mean']):.3f}/"
            f"{float(cd_wait_stats['median']):g}/"
            f"{int(cd_wait_stats['maximum'])}; "
            "ADPCM decode min/mean/median/max "
            f"{int(adpcm_decode_stats['minimum'])}/"
            f"{float(adpcm_decode_stats['mean']):.3f}/"
            f"{float(adpcm_decode_stats['median']):g}/"
            f"{int(adpcm_decode_stats['maximum'])}; "
            f"{reader_ahead_text}{transfer_text}"
            f"{gpgx_vdp_text}"
            f"{pump_gap_stats_text}{apply_backpressure_text}"
            f"{cadence_text}"
            f"range {int(finite_display_vblanks.min())}-"
            f"{int(finite_display_vblanks.max())}; "
            f"OCR confidence min {confidence.min(initial=1.0):.3f}; "
            f"samples {int(sample_count.sum(initial=0))}; "
            f"profile {str(gate['profile_sha256'])[:10]}"
        ),
        fill=DIM,
        font=font(17),
    )
    bottom = draw_rows(
        image,
        data,
        specs,
        gate,
        left=left,
        top=timeline_top,
        ppf=ppf,
        axis_frames=axis_frames,
    )
    if observed_frames < axis_frames:
        missing_x = left + observed_frames * ppf
        overlay = Image.new("RGBA", image.size, (0, 0, 0, 0))
        odraw = ImageDraw.Draw(overlay)
        odraw.rectangle(
            (missing_x, timeline_top, left + plot_width - 1, bottom - 1),
            fill=INCOMPLETE_TAIL,
        )
        odraw.line(
            (missing_x, timeline_top, missing_x, bottom - 1),
            fill=FAIL,
            width=3,
        )
        odraw.text(
            (missing_x + 8, timeline_top + 7),
            (
                f"not observed from "
                f"{fmt_frame(observed_frames, axis_frames)}"
            ),
            fill=FAIL,
            font=font(16),
        )
        image.alpha_composite(overlay)
    draw = ImageDraw.Draw(image)
    draw.text(
        (left, bottom + 64),
        (
            "Frame 0 is untimed boot staging: every metric, scale and gate excludes it. "
            "VBLANK is derived from consecutive frame capture starts; edge observations remain visible, "
            "but the first/last 4 content frames at 30 fps and 2 at 15 fps do not raise its ALERT. "
            "The terminal hold is also excluded. "
            f"frame is the x-axis. {phase_note}"
            "pass2_delay_q4 belongs to frame. LOGVDP active CPU work includes writes "
            "on the two V-counter edge representations. Orange lines are gate "
            "limits or either ready-pressure E0 deadline; "
            "PrgBuf jitter also shows the yellow normal interval."
        ),
        fill=DIM,
        font=font(16),
    )

    lease = None
    actual_output = requested_output
    try:
        actual_output, lease = tmpfs_workspace.allocate_file(
            requested_output,
            kind="hudline-png",
            key=f"{tsv_path.stem}-{digest(tsv_path)[:10]}",
            required_bytes=max(width * height * 4, 128 * 1024 ** 2),
        )
        image.convert("RGB").save(actual_output, optimize=True)
    finally:
        if lease is not None:
            lease.release()

    receipt_rows = []
    receipt_row_top = timeline_top
    for spec in specs:
        receipt_rows.append({
            "key": spec.key,
            "label": spec.label,
            "unit": spec.unit,
            "maximum": spec.maximum,
            "color": list(spec.color),
            "gate_key": spec.gate_key,
            "eight_bit_scale": spec.eight_bit_scale,
            "normal_value": spec.normal_value,
            "normal_key": spec.normal_key,
            "top": receipt_row_top,
            "height": spec.height,
            "plot_style": "point" if spec.point_plot else "bar",
            "show_unit": spec.show_unit,
            "show_zero": spec.show_zero,
            "deadline_value": spec.deadline_value,
            "deadline_label": spec.deadline_label,
        })
        receipt_row_top += spec.height

    receipt = {
        "schema_version": 12,
        "kind": "hudline",
        "label": title,
        "image": str(actual_output),
        "image_sha256": digest(actual_output),
        "tsv": str(tsv_path),
        "tsv_sha256": digest(tsv_path),
        "gpgx_vdp_tsv": (
            str(gpgx_vdp_path) if gpgx_vdp_path is not None else None
        ),
        "gpgx_vdp_tsv_sha256": (
            digest(gpgx_vdp_path) if gpgx_vdp_path is not None else None
        ),
        "gpgx_vdp_receipt": (
            str(gpgx_vdp_receipt_path)
            if gpgx_vdp_receipt_path is not None else None
        ),
        "gpgx_vdp_receipt_sha256": (
            digest(gpgx_vdp_receipt_path)
            if gpgx_vdp_receipt_path is not None else None
        ),
        "gate_json": str(gate_path),
        "gate_json_sha256": digest(gate_path),
        "recording": gate["recording"],
        "recording_size": gate["recording_size"],
        "recording_mtime_ns": gate["recording_mtime_ns"],
        "profile_sha256": gate["profile_sha256"],
        "frames": axis_frames,
        "observed_frames": observed_frames,
        "expected_frames": axis_frames,
        "incomplete": observed_frames < axis_frames,
        "evaluation_first_frame": 1,
        "evaluated_timed_frames": max(0, observed_frames - 1),
        "fps": float(gate["content_fps"]),
        "pixels_per_frame": ppf,
        "plot_left": left,
        "plot_top": timeline_top,
        "plot_width": plot_width,
        "base_row_height": 46,
        "frame_x": "plot_left + frame * pixels_per_frame",
        "frame_label_format": "f0xHEX",
        "gate": str(gate["gate"]),
        "alert": alert,
        "gate_pass": bool(gate["pass"]),
        "gate_status": str(gate["status"]),
        "status": state,
        "gate_maxima": {
            key: maxima[key]
            for key in gate["gate_fields"]
        },
        "gate_limits": limits,
        "diagnostic_maxima": {
            "cd_wait_count": maxima["cd_wait_count"],
            **(
                {"pump_gap_ticks": int(pump_gap_stats["maximum"])}
                if pump_gap_stats is not None else {}
            ),
            **(
                {
                    "apply_backpressure": int(
                        data["apply_backpressure"][1:].max(initial=0)
                    )
                }
                if "apply_backpressure" in data else {}
            ),
            **(
                {"reader_ahead_frames": reader_ahead_max_frames}
                if reader_ahead_max_frames is not None else {}
            ),
            **(
                {"reader_slot_sector": reader_slot_sector_max}
                if reader_slot_sector_max is not None else {}
            ),
            **(
                {"transfer_vblanks": transfer_vblanks_max}
                if transfer_vblanks_max is not None else {}
            ),
            **(
                {"transfer_end_vcounter": transfer_end_vcounter_max}
                if transfer_end_vcounter_max is not None else {}
            ),
            **(
                {
                    "first_share_exit_vcounter":
                        first_share_exit_vcounter_max
                }
                if first_share_exit_vcounter_max is not None else {}
            ),
            **(
                {
                    "pattern_dma_ready_vcounter":
                        pattern_dma_ready_vcounter_max
                }
                if pattern_dma_ready_vcounter_max is not None else {}
            ),
            "pattern_dma_ready_pressure":
                pattern_dma_ready_pressure_max,
            "name_table_dma_ready_pressure":
                name_table_dma_ready_pressure_max,
            **(
                {
                    "name_table_dma_ready_vcounter":
                        name_table_dma_ready_vcounter_max
                }
                if name_table_dma_ready_vcounter_max is not None else {}
            ),
            **(
                {"LOGVDP": gpgx_vdp_maxima}
                if gpgx_vdp_maxima is not None else {}
            ),
        },
        "cd_wait_statistics": cd_wait_stats,
        "adpcm_decode_statistics": adpcm_decode_stats,
        "pump_gap_statistics": pump_gap_stats,
        "apply_backpressure_frames": apply_backpressure_frames,
        "reader_ahead_max_frames": reader_ahead_max_frames,
        "reader_slot_sector_max": reader_slot_sector_max,
        "transfer_vblanks_max": transfer_vblanks_max,
        "transfer_end_vcounter_max": transfer_end_vcounter_max,
        "first_share_exit_vcounter_max": first_share_exit_vcounter_max,
        "pattern_dma_ready_vcounter_max":
            pattern_dma_ready_vcounter_max,
        "pattern_dma_ready_pressure_max":
            pattern_dma_ready_pressure_max,
        "pattern_dma_ready_min_margin_scanlines":
            pattern_dma_ready_min_margin_scanlines,
        "pattern_dma_ready_missed_frames":
            pattern_dma_ready_missed_frames,
        "pattern_dma_ready_pressure_samples":
            pattern_dma_ready_pressure_samples,
        "pattern_dma_ready_deadline_scanline":
            PATTERN_READY_DEADLINE_SCANLINE,
        "pattern_dma_ready_missed_sentinel":
            PATTERN_READY_MISSED_PRESSURE,
        "name_table_dma_ready_vcounter_max":
            name_table_dma_ready_vcounter_max,
        "name_table_dma_ready_pressure_max":
            name_table_dma_ready_pressure_max,
        "name_table_dma_ready_min_margin_scanlines":
            name_table_dma_ready_min_margin_scanlines,
        "name_table_dma_ready_missed_frames":
            name_table_dma_ready_missed_frames,
        "name_table_dma_ready_pressure_samples":
            name_table_dma_ready_pressure_samples,
        "name_table_dma_ready_deadline_scanline":
            NT_READY_DEADLINE_SCANLINE,
        "name_table_dma_ready_missed_sentinel":
            NT_READY_MISSED_PRESSURE,
        "gpgx_vdp_maxima": gpgx_vdp_maxima,
        "gpgx_vdp_extraction": gpgx_vdp_receipt,
        "jitter_normal_kib": int(gate.get("jitter_headroom_kib", 0)),
        "display_vblank_expected": display_vblank_expected,
        "display_vblank_warning_count": display_vblank_warning_count,
        "display_vblank_warning_rate_percent": display_vblank_warning_rate,
        "display_vblank_evaluated_total": display_vblank_total,
        "display_vblank_measured_total": display_vblank_measured_total,
        "display_vblank_edge_exempt_frames": display_vblank_edge_frames,
        "display_vblank_exempted_warning_count": (
            display_vblank_exempted_warning_count),
        "display_vblank_warning_supported": (
            display_vblank_pattern is not None
        ),
        "display_vblank_min": int(finite_display_vblanks.min()),
        "display_vblank_max": int(finite_display_vblanks.max()),
        "display_vblank_average": float(finite_display_vblanks.mean()),
        "display_vblank_terminal_hold_excluded": True,
        "frame_zero_excluded_from_all_metrics": True,
        "ocr_confidence_min": float(confidence.min()),
        "ocr_sample_count": int(sample_count.sum()),
        "rows": receipt_rows,
    }
    receipt_path = analysis_logs.metadata_path(
        requested_output,
        kind="hudline-layout",
        sha256=receipt["image_sha256"],
    )
    receipt_path.write_text(
        json.dumps(receipt, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(actual_output)
    print(receipt_path)


if __name__ == "__main__":
    main()
