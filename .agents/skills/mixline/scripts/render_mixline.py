#!/usr/bin/env python3
"""Stack matching codec and HUD timelines on one verified frame axis."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


SCRIPT = Path(__file__).resolve()
REPO = SCRIPT.parents[4]
TOOLS = REPO / "tools"
sys.path.insert(0, str(TOOLS))
import analysis_logs  # noqa: E402
import analysis_style  # noqa: E402
import tmpfs_workspace  # noqa: E402
import hud_gate  # noqa: E402


BG = (12, 12, 14)
TEXT = (230, 230, 234)
DIM = (158, 160, 169)
WARN = (246, 190, 72)
FAIL = (244, 87, 87)
SEPARATOR = (62, 64, 72)
SECTION_BG = (18, 18, 22)
HEADER_HEIGHT = 220
SECTION_HEADER_HEIGHT = 38
LOGVDPLINE_KEYS = (
    "pattern_dma_blank_words",
    "pattern_dma_active_words",
    "pattern_cpu_blank_words",
    "pattern_cpu_active_edge_words",
    "name_table_dma_blank_words",
    "name_table_dma_active_words",
    "pattern_dma_commands",
)
SECTION_LABELS = {
    "timeline": "/timeline",
    "logvdpline": "/logvdpline",
    "hudline": "/hudline",
}


def font(size: int) -> ImageFont.FreeTypeFont:
    return ImageFont.truetype(
        "/usr/share/fonts/truetype/dejavu/DejaVuSansMono.ttf", size)


def fmt_frame(frame_index: int, frames: int) -> str:
    width = max(3, len(f"{max(frames - 1, 0):X}"))
    return f"f0x{frame_index:0{width}X}"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("timeline", type=Path)
    parser.add_argument("hudline", type=Path)
    parser.add_argument("--timeline-layout", type=Path)
    parser.add_argument("--hudline-layout", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--gap", type=int, default=0)
    return parser.parse_args()


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_receipt(path: Path, kind: str) -> dict:
    if not path.is_file():
        raise SystemExit(f"{kind} layout receipt does not exist: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if data.get("kind") != kind:
        raise SystemExit(
            f"expected {kind} layout receipt, got {data.get('kind')!r}")
    return data


def validate_axis(timeline: dict, hudline: dict) -> None:
    for key in (
        "frames", "pixels_per_frame", "plot_left", "plot_width", "frame_x",
    ):
        if timeline.get(key) != hudline.get(key):
            raise SystemExit(
                f"frame-axis mismatch for {key}: "
                f"{timeline.get(key)!r} != {hudline.get(key)!r}")
    # TSV time deltas can preserve sub-microsecond decimal rounding that the
    # HUD's integer cadence does not. This tolerance is far below one frame
    # over a whole movie and does not permit a different playback cadence.
    if abs(float(timeline["fps"]) - float(hudline["fps"])) > 1e-6:
        raise SystemExit(
            f"frame-axis mismatch for fps: "
            f"{timeline['fps']} != {hudline['fps']}")


def validate_image(path: Path, receipt: dict, kind: str) -> None:
    recorded = receipt.get("image_sha256")
    if recorded and digest(path) != recorded:
        raise SystemExit(f"{kind} image hash does not match its layout receipt")


def hudline_row_geometry(receipt: dict, image_height: int) -> list[dict]:
    rows = receipt.get("rows") or ()
    if not rows:
        raise SystemExit("hudline receipt lacks row geometry")
    cursor = int(receipt["plot_top"])
    geometry = []
    for row in rows:
        height = int(row["height"])
        if height <= 0:
            raise SystemExit(f"invalid hudline row height for {row.get('key')}")
        top_value = row.get("top")
        top = cursor if top_value is None else int(top_value)
        if top < cursor:
            raise SystemExit("hudline rows overlap or are out of order")
        bottom = top + height
        if bottom > image_height:
            raise SystemExit("hudline row geometry exceeds the source image")
        geometry.append({
            "key": str(row["key"]),
            "top": top,
            "bottom": bottom,
            "height": height,
        })
        cursor = bottom
    return geometry


def split_hudline_ranges(
    receipt: dict,
    image_height: int,
) -> tuple[tuple[int, int] | None, list[tuple[int, int]]]:
    """Separate the optional LOGVDP rows from the ordinary HUDline body."""
    geometry = hudline_row_geometry(receipt, image_height)
    positions = {row["key"]: index for index, row in enumerate(geometry)}
    present = [key in positions for key in LOGVDPLINE_KEYS]
    plot_top = int(receipt["plot_top"])
    if not any(present):
        return None, [(plot_top, image_height)]
    if not all(present):
        missing = [
            key for key, exists in zip(LOGVDPLINE_KEYS, present, strict=True)
            if not exists
        ]
        raise SystemExit(
            f"hudline has an incomplete LOGVDP row block: {missing}"
        )

    indices = [positions[key] for key in LOGVDPLINE_KEYS]
    if indices != list(range(indices[0], indices[0] + len(indices))):
        raise SystemExit("hudline LOGVDP rows are not one contiguous block")
    log_top = geometry[indices[0]]["top"]
    log_bottom = geometry[indices[-1]]["bottom"]
    hud_ranges = [
        (top, bottom)
        for top, bottom in (
            (plot_top, log_top),
            (log_bottom, image_height),
        )
        if bottom > top
    ]
    if not hud_ranges:
        raise SystemExit("hudline contains no ordinary rows outside LOGVDP")
    return (log_top, log_bottom), hud_ranges


def crop_vertical_segments(
    image: Image.Image,
    segments: list[tuple[int, int]],
) -> Image.Image:
    if not segments:
        raise SystemExit("cannot compose an empty source segment list")
    height = 0
    for top, bottom in segments:
        if not 0 <= top < bottom <= image.height:
            raise SystemExit(f"invalid source segment {top}:{bottom}")
        height += bottom - top
    result = Image.new("RGB", (image.width, height), BG)
    cursor = 0
    for top, bottom in segments:
        piece = image.crop((0, top, image.width, bottom))
        result.paste(piece, (0, cursor))
        cursor += piece.height
    return result


def main() -> None:
    args = parse_args()
    if args.gap < 0:
        raise SystemExit("gap must not be negative")
    timeline_path = args.timeline.resolve()
    hudline_path = args.hudline.resolve()
    timeline_layout_path = (
        args.timeline_layout.resolve()
        if args.timeline_layout
        else analysis_logs.metadata_path(
            timeline_path,
            kind="timeline-layout",
            sha256=digest(timeline_path),
        )
    )
    hudline_layout_path = (
        args.hudline_layout.resolve()
        if args.hudline_layout
        else analysis_logs.metadata_path(
            hudline_path,
            kind="hudline-layout",
            sha256=digest(hudline_path),
        )
    )
    timeline = load_receipt(timeline_layout_path, "timeline")
    hudline = load_receipt(hudline_layout_path, "hudline")
    validate_axis(timeline, hudline)
    validate_image(timeline_path, timeline, "timeline")
    validate_image(hudline_path, hudline, "hudline")

    with Image.open(timeline_path) as source:
        timeline_image = source.convert("RGB")
    with Image.open(hudline_path) as source:
        hudline_image = source.convert("RGB")
    if timeline_image.width != hudline_image.width:
        raise SystemExit(
            f"image width mismatch: "
            f"{timeline_image.width} != {hudline_image.width}")
    expected_width = (
        int(timeline["plot_left"]) + int(timeline["plot_width"]) + 45
    )
    if timeline_image.width != expected_width:
        raise SystemExit(
            f"image width {timeline_image.width} does not match frame layout "
            f"{expected_width}")

    timeline_plot_top = int(timeline["plot_top"])
    hudline_plot_top = int(hudline["plot_top"])
    if not 0 < timeline_plot_top < timeline_image.height:
        raise SystemExit("invalid timeline plot_top")
    if not 0 < hudline_plot_top < hudline_image.height:
        raise SystemExit("invalid hudline plot_top")
    timeline_rows = timeline.get("rows") or ()
    if not timeline_rows:
        raise SystemExit("timeline receipt lacks row geometry")
    timeline_plot_bottom = max(
        int(row["top"]) + int(row["height"])
        for row in timeline_rows
    )
    if not timeline_plot_top < timeline_plot_bottom <= timeline_image.height:
        raise SystemExit("invalid timeline row geometry")
    # The HUD panel owns the one shared horizontal scale and footer. Crop the
    # codec panel at its final data row so its duplicate scale and explanation
    # disappear. When present, extract the exact LOGVDP row block into a middle
    # panel; concatenate the remaining HUD source ranges without changing any
    # row pixels.
    upper = timeline_image.crop(
        (0, timeline_plot_top, timeline_image.width, timeline_plot_bottom))
    logvdpline_range, hudline_ranges = split_hudline_ranges(
        hudline,
        hudline_image.height,
    )
    hudline_body = crop_vertical_segments(hudline_image, hudline_ranges)
    sections = [{
        "kind": "timeline",
        "image": upper,
        "source": "timeline",
        "source_segments": [(timeline_plot_top, timeline_plot_bottom)],
    }]
    if logvdpline_range is not None:
        sections.append({
            "kind": "logvdpline",
            "image": crop_vertical_segments(
                hudline_image, [logvdpline_range]),
            "source": "hudline",
            "source_segments": [logvdpline_range],
        })
    sections.append({
        "kind": "hudline",
        "image": hudline_body,
        "source": "hudline",
        "source_segments": hudline_ranges,
    })

    width = timeline_image.width
    height = (
        HEADER_HEIGHT
        + sum(
            SECTION_HEADER_HEIGHT + section["image"].height
            for section in sections
        )
        + args.gap * max(0, len(sections) - 1)
    )
    combined = Image.new("RGB", (width, height), BG)
    draw = ImageDraw.Draw(combined)
    title = timeline.get("label") or timeline_path.stem
    alert = str(
        hudline.get(
            "alert",
            "FAIL" if not hudline["gate_pass"] else (
                "WARNING"
                if hudline.get("status") in {"WARNING", "WARN"}
                else "NONE"
            ),
        )
    )
    gate = str(
        hudline.get("gate", hud_gate.gate_for_alert(alert))
    )
    if gate != hud_gate.gate_for_alert(alert):
        raise SystemExit("hudline gate and alert disagree")
    state = hud_gate.legacy_status_for_alert(alert)
    state_color = {
        "PASS": DIM,
        "WARNING": WARN,
        "FAIL": FAIL,
    }.get(state, FAIL)
    draw.text((24, 16), title, fill=TEXT, font=font(36))
    draw.text(
        (width - 24, 18), state, fill=state_color, font=font(34), anchor="ra")
    draw.text(
        (24, 64),
        (
            f"Shared frame axis | {timeline['frames']} frames | "
            f"{float(hudline['fps']):g} fps | "
            f"{timeline['pixels_per_frame']} px/frame | "
            f"x = {timeline['plot_left']} + frame * "
            f"{timeline['pixels_per_frame']}"
            + (
                f" | HUD observed "
                f"{int(hudline.get('observed_frames', hudline['frames']))}/"
                f"{int(hudline['frames'])}"
                if int(hudline.get("observed_frames", hudline["frames"]))
                != int(hudline["frames"])
                else ""
            )
        ),
        fill=DIM,
        font=font(20),
    )
    evaluation_end_raw = timeline.get("evaluation_end_frame")
    evaluation_end = (
        int(timeline["frames"])
        if evaluation_end_raw is None
        else int(evaluation_end_raw)
    )
    profile = (
        timeline.get("config_sha256")
        or hudline.get("profile_sha256")
        or ""
    )
    draw.text(
        (24, 96),
        (
            f"Codec /timeline | cold cap {timeline.get('cold_cap_tiles', '?')} "
            f"| EVAL {fmt_frame(0, int(timeline['frames']))}-"
            f"{fmt_frame(evaluation_end - 1, int(timeline['frames']))} "
            f"| profile {profile[:10]}"
        ),
        fill=DIM,
        font=font(19),
    )
    maxima = hudline["gate_maxima"]
    limits = hudline["gate_limits"]
    gate_text = "  ".join(
        f"{key} {int(maxima[key])}/{int(limits[key])}"
        for key in limits
    )
    cd_wait_max = int(
        hudline.get("diagnostic_maxima", {}).get("cd_wait_count", 0)
    )
    pump_gap_max = hudline.get(
        "diagnostic_maxima",
        {},
    ).get("pump_gap_ticks")
    pump_gap_text = (
        f"pump gap diagnostic max {int(pump_gap_max)} ticks | "
        if pump_gap_max is not None else ""
    )
    apply_backpressure_frames = hudline.get("apply_backpressure_frames")
    apply_backpressure_text = (
        "APPLY back-pressure "
        f"{int(apply_backpressure_frames)} frames | "
        if apply_backpressure_frames is not None else ""
    )
    ready_pressure_text = (
        "ready pressure max "
        f"0x{int(hudline['pattern_dma_ready_pressure_max']):02X}, "
        "min margin "
        f"{int(hudline['pattern_dma_ready_min_margin_scanlines'])} lines, "
        "missed "
        f"{int(hudline['pattern_dma_ready_missed_frames'])}/"
        f"{int(hudline['pattern_dma_ready_pressure_samples'])} | "
        if all(
            key in hudline
            for key in (
                "pattern_dma_ready_pressure_max",
                "pattern_dma_ready_min_margin_scanlines",
                "pattern_dma_ready_missed_frames",
                "pattern_dma_ready_pressure_samples",
            )
        )
        else ""
    )
    vblank_text = ""
    if hudline.get("display_vblank_warning_supported"):
        vblank_text = (
            f" | VB warn "
            f"{float(hudline['display_vblank_warning_rate_percent']):.2f}%/"
            f"{int(hudline['display_vblank_warning_count'])}/"
            f"{int(hudline['display_vblank_evaluated_total'])}"
            f" active; edge-exempt "
            f"{int(hudline.get('display_vblank_exempted_warning_count', 0))}"
        )
    draw.text(
        (24, 127),
        (
            f"Playback /hudline | gate maxima / limits  {gate_text} | "
            f"cd_wait_count diagnostic max {cd_wait_max} | "
            f"{pump_gap_text}"
            f"{apply_backpressure_text}"
            f"{ready_pressure_text}"
            "PrgBuf jitter normal "
            f"{int(hudline['jitter_normal_kib'])} KiB | "
            f"OCR {float(hudline.get('ocr_confidence_min', 0.0)):.3f}"
            f"{vblank_text}"
        ),
        fill=state_color,
        font=font(19),
    )
    legend_totals = timeline.get("legend_totals") or {}
    legend_order = timeline.get("legend_totals_order") or list(legend_totals)
    if legend_totals:
        legend_font = font(19)
        x = 24
        y = 160
        scope = str(timeline.get("legend_totals_scope", "EVAL totals"))
        draw.text((x, y), scope, fill=DIM, font=legend_font)
        x += int(draw.textlength(scope, font=legend_font)) + 26
        for name in legend_order:
            color = analysis_style.CATEGORY_COLORS.get(name, DIM)
            draw.rectangle((x, y + 3, x + 21, y + 23), fill=color)
            text = f"{name} {int(legend_totals[name]):,}"
            draw.text((x + 29, y), text, fill=TEXT, font=legend_font)
            x += 29 + int(draw.textlength(text, font=legend_font)) + 34
    draw.line(
        (0, HEADER_HEIGHT - 1, width - 1, HEADER_HEIGHT - 1),
        fill=SEPARATOR,
        width=2,
    )

    panel_receipts = []
    cursor = HEADER_HEIGHT
    for index, section in enumerate(sections):
        if index:
            cursor += args.gap
        label_top = cursor
        label_bottom = label_top + SECTION_HEADER_HEIGHT
        draw.rectangle(
            (0, label_top, width - 1, label_bottom - 1),
            fill=SECTION_BG,
        )
        draw.line(
            (0, label_top, width - 1, label_top),
            fill=SEPARATOR,
            width=2,
        )
        draw.line(
            (0, label_bottom - 1, width - 1, label_bottom - 1),
            fill=SEPARATOR,
            width=2,
        )
        draw.text(
            (18, label_top + SECTION_HEADER_HEIGHT // 2),
            SECTION_LABELS[section["kind"]],
            fill=TEXT,
            font=font(19),
            anchor="lm",
        )
        cursor = label_bottom
        panel_top = cursor
        panel_image = section["image"]
        combined.paste(panel_image, (0, panel_top))
        cursor += panel_image.height
        source_segments = [
            {
                "top": int(top),
                "bottom": int(bottom),
                "height": int(bottom - top),
            }
            for top, bottom in section["source_segments"]
        ]
        panel_receipts.append({
            "kind": section["kind"],
            "label": SECTION_LABELS[section["kind"]],
            "label_top": label_top,
            "label_height": SECTION_HEADER_HEIGHT,
            "top": panel_top,
            "height": panel_image.height,
            "source": section["source"],
            "source_segments": source_segments,
        })

    requested_output = (
        args.output
        or Path(f"{timeline_path.stem}_mixline.png")
    )
    lease = None
    actual_output = requested_output
    try:
        actual_output, lease = tmpfs_workspace.allocate_file(
            requested_output,
            kind="mixline-png",
            key=f"{timeline_path.stem}-{hudline_path.stem}",
            required_bytes=max(width * height * 3, 128 * 1024 ** 2),
        )
        combined.save(actual_output, optimize=True)
    finally:
        if lease is not None:
            lease.release()

    receipt = {
        "schema_version": 3,
        "kind": "mixline",
        "image": str(actual_output),
        "image_sha256": digest(actual_output),
        "timeline_image": str(timeline_path),
        "timeline_image_sha256": digest(timeline_path),
        "timeline_layout": str(timeline_layout_path),
        "timeline_layout_sha256": digest(timeline_layout_path),
        "hudline_image": str(hudline_path),
        "hudline_image_sha256": digest(hudline_path),
        "hudline_layout": str(hudline_layout_path),
        "hudline_layout_sha256": digest(hudline_layout_path),
        "frames": int(timeline["frames"]),
        "hud_observed_frames": int(
            hudline.get("observed_frames", hudline["frames"])
        ),
        "fps": float(timeline["fps"]),
        "status": state,
        "gate": gate,
        "alert": alert,
        "gate_pass": bool(hudline["gate_pass"]),
        "gate_status": str(hudline.get("gate_status", state)),
        "pixels_per_frame": int(timeline["pixels_per_frame"]),
        "plot_left": int(timeline["plot_left"]),
        "plot_width": int(timeline["plot_width"]),
        "frame_x": timeline["frame_x"],
        "gap": args.gap,
        "header_height": HEADER_HEIGHT,
        "section_header_height": SECTION_HEADER_HEIGHT,
        "logvdpline_present": logvdpline_range is not None,
        "panels": [
            {
                "kind": "header",
                "top": 0,
                "height": HEADER_HEIGHT,
            },
            *panel_receipts,
        ],
    }
    receipt_path = analysis_logs.metadata_path(
        requested_output,
        kind="mixline-layout",
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
