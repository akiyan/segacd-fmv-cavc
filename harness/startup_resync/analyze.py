#!/usr/bin/env python3
"""Extract and aggregate the 43-cell DEBUG HUD from a native recording.

Every output field uses a descriptive snake_case name. H32 wraps the sequence
after 32 cells; H40 wraps after 40. The OCR layer unpacks Main VBlank spill from
the transfer stopwatch, APPLY back-pressure from the pump-gap word, and reader
frame/sector lead from their shared byte.

Frames are decoded sequentially through ffmpeg. High-confidence OCR samples
with the same frame value are combined before audio_resync transitions are
reported. This is a diagnostic tool only; its HUD timing must not be used to
trim a publication recording or to write a timestamp into an upload description.

Current players expose their black pre-roll state as frame=FFFF. The extractor
anchors content at the immediately following frame=0000.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import statistics
import subprocess
import sys
from collections import Counter
from dataclasses import dataclass, replace
from fractions import Fraction
from pathlib import Path
from typing import BinaryIO, Iterable

import numpy as np


ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "tools"))
import read_frameno  # noqa: E402
import av_config  # noqa: E402
import encode_config  # noqa: E402
import analysis_logs  # noqa: E402
import hud_gate  # noqa: E402


@dataclass(frozen=True)
class Probe:
    width: int
    height: int
    fps: Fraction
    start_time: float


@dataclass(frozen=True)
class Sample:
    capture: int
    time_s: float
    values: dict[str, int]
    confidence: dict[str, float]


@dataclass(frozen=True)
class FrameGroup:
    loop: int
    capture_first: int
    capture_last: int
    time_first: float
    time_last: float
    sample_count: int
    confidence: float
    values: dict[str, int]


def _fraction(value: str) -> Fraction:
    try:
        result = Fraction(value)
    except (ValueError, ZeroDivisionError) as exc:
        raise SystemExit(f"invalid frame rate from ffprobe: {value!r}") from exc
    if result <= 0:
        raise SystemExit(f"non-positive frame rate from ffprobe: {value!r}")
    return result


def probe_video(path: Path) -> Probe:
    cmd = [
        "ffprobe", "-v", "error", "-select_streams", "v:0",
        "-show_entries", "stream=width,height,r_frame_rate,avg_frame_rate,start_time",
        "-of", "json", str(path),
    ]
    try:
        result = subprocess.run(cmd, check=True, capture_output=True, text=True)
    except FileNotFoundError as exc:
        raise SystemExit("ffprobe was not found") from exc
    except subprocess.CalledProcessError as exc:
        raise SystemExit(exc.stderr.strip() or "ffprobe failed") from exc
    data = json.loads(result.stdout)
    streams = data.get("streams", [])
    if not streams:
        raise SystemExit(f"no video stream: {path}")
    stream = streams[0]
    rate = stream.get("avg_frame_rate")
    if not rate or rate == "0/0":
        rate = stream.get("r_frame_rate")
    return Probe(
        width=int(stream["width"]),
        height=int(stream["height"]),
        fps=_fraction(rate),
        start_time=float(stream.get("start_time", 0.0) or 0.0),
    )


def _read_exact(pipe: BinaryIO, size: int) -> bytes:
    chunks = bytearray()
    while len(chunks) < size:
        chunk = pipe.read(size - len(chunks))
        if not chunk:
            break
        chunks += chunk
    return bytes(chunks)


def iter_samples(
    path: Path,
    probe: Probe,
    confidence: float,
    crop_x: int,
) -> Iterable[Sample]:
    # Only the top-left HUD area is sent through the pipe.  Decoding still sees
    # every source frame, while pipe traffic stays small even for an upscaled MP4.
    available_width = probe.width - crop_x
    layout = read_frameno.hud_layout_for_width(available_width)
    fields = read_frameno.hud_fields_for_layout(layout)
    hud_width_cells, hud_height_cells = read_frameno.hud_layout_dimensions(
        layout
    )
    crop_w = min(hud_width_cells * read_frameno.CELL, available_width)
    crop_h = min(max(32, hud_height_cells * read_frameno.CELL), probe.height)
    if crop_x < 0 or crop_x >= probe.width:
        raise SystemExit(f"--crop-x must be within 0..{probe.width - 1}")
    if (
        crop_w < hud_width_cells * read_frameno.CELL
        or crop_h < hud_height_cells * read_frameno.CELL
    ):
        raise SystemExit(
            f"HUD crop is too small ({crop_w}x{crop_h}); "
            f"need at least {hud_width_cells * read_frameno.CELL}x"
            f"{hud_height_cells * read_frameno.CELL}"
        )

    vf = f"crop={crop_w}:{crop_h}:{crop_x}:0,format=gray"
    cmd = [
        "ffmpeg", "-hide_banner", "-loglevel", "error", "-i", str(path),
        "-map", "0:v:0", "-vf", vf, "-fps_mode", "passthrough",
        "-f", "rawvideo", "-pix_fmt", "gray", "-",
    ]
    try:
        process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    except FileNotFoundError as exc:
        raise SystemExit("ffmpeg was not found") from exc
    assert process.stdout is not None
    frame_size = crop_w * crop_h
    capture = 0
    while True:
        raw = _read_exact(process.stdout, frame_size)
        if not raw:
            break
        if len(raw) != frame_size:
            process.kill()
            raise SystemExit(
                f"ffmpeg returned a partial raw frame: {len(raw)} / {frame_size} bytes"
            )
        image = np.frombuffer(raw, np.uint8).reshape(crop_h, crop_w)
        hud = read_frameno.read_hud(image, layout=layout)
        field_conf = {name: float(hud[name][1]) for name in fields}
        if min(field_conf.values()) >= confidence:
            yield Sample(
                capture=capture,
                time_s=probe.start_time + capture / float(probe.fps),
                values={name: int(hud[name][0]) for name in fields},
                confidence=field_conf,
            )
        capture += 1

    stderr = process.stderr.read().decode("utf-8", "replace") if process.stderr else ""
    return_code = process.wait()
    if return_code:
        raise SystemExit(stderr.strip() or f"ffmpeg failed with exit code {return_code}")


def aggregate(samples: list[Sample], loop: int = -1) -> FrameGroup:
    if not samples:
        raise ValueError("cannot aggregate an empty sample group")
    values: dict[str, int] = {}
    for field in samples[0].values:
        counts = Counter(sample.values[field] for sample in samples)
        # Prefer the common value, then the value with the highest summed OCR
        # confidence.  The final tie-break is deterministic.
        values[field] = max(
            counts,
            key=lambda value: (
                counts[value],
                sum(
                    sample.confidence[field]
                    for sample in samples
                    if sample.values[field] == value
                ),
                -value,
            ),
        )
    return FrameGroup(
        loop=loop,
        capture_first=samples[0].capture,
        capture_last=samples[-1].capture,
        time_first=samples[0].time_s,
        time_last=samples[-1].time_s,
        sample_count=len(samples),
        confidence=float(statistics.median(
            min(sample.confidence.values()) for sample in samples
        )),
        values=values,
    )


def group_samples(samples: Iterable[Sample], max_gap: int) -> list[FrameGroup]:
    groups: list[FrameGroup] = []
    pending: list[Sample] = []
    for sample in samples:
        if pending and (
            sample.values["frame"] != pending[-1].values["frame"]
            or sample.capture - pending[-1].capture > max_gap
        ):
            groups.append(aggregate(pending))
            pending = []
        pending.append(sample)
    if pending:
        groups.append(aggregate(pending))
    return groups


def _has_anchor_run(groups: list[FrameGroup], start: int, length: int, max_step: int) -> bool:
    previous = 0
    accepted = 1
    for group in groups[start + 1:start + length * 3]:
        frame = group.values["frame"]
        if frame == previous:
            continue
        if 1 <= frame - previous <= max_step:
            accepted += 1
            previous = frame
            if accepted >= length:
                return True
        else:
            return False
    return accepted >= length


def find_movie_anchor(
    groups: list[FrameGroup], anchor_run: int, max_step: int
) -> tuple[int, bool]:
    plausible = [
        index for index, group in enumerate(groups)
        if group.values["frame"] == 0
        and _has_anchor_run(groups, index, anchor_run, max_step)
    ]
    sentinel_anchored = [
        index for index in plausible
        if index > 0
        and groups[index - 1].values["frame"] == read_frameno.FRAME_MINUS_ONE
    ]
    anchor = sentinel_anchored[0] if sentinel_anchored else (
        plausible[0] if plausible else None
    )
    if anchor is None:
        raise SystemExit(
            "could not find frame=0000 followed by "
            f"{anchor_run - 1} plausible HUD frames; "
            "check --confidence and --crop-x"
        )
    return anchor, bool(sentinel_anchored)


def select_movie_groups(
    groups: list[FrameGroup], anchor_run: int, max_step: int
) -> list[FrameGroup]:
    anchor, _sentinel = find_movie_anchor(groups, anchor_run, max_step)

    selected: list[FrameGroup] = []
    loop = 0
    previous = -1
    for group in groups[anchor:]:
        frame = group.values["frame"]
        if not selected:
            pass
        elif frame == previous:
            # A low-confidence gap can split one displayed movie frame into two
            # raw groups.  Keep the stronger aggregate rather than emitting a
            # duplicate F row.
            if group.sample_count > selected[-1].sample_count or (
                group.sample_count == selected[-1].sample_count
                and group.confidence > selected[-1].confidence
            ):
                selected[-1] = replace(group, loop=loop)
            continue
        elif 1 <= frame - previous <= max_step:
            pass
        elif frame <= max_step and previous >= max_step * 4:
            loop += 1
        else:
            # Isolated high-confidence OCR mistakes are still possible on old
            # transparent HUD captures.  Ignore a non-contiguous outlier and
            # let the next plausible group reconnect to `previous`.
            continue
        selected.append(replace(group, loop=loop))
        previous = frame
    return selected


def transition_indices(groups: list[FrameGroup]) -> list[int]:
    return [
        index for index in range(1, len(groups))
        if groups[index].values["audio_resync"] != groups[index - 1].values["audio_resync"]
    ]


def timed_first_loop(groups: list[FrameGroup]) -> list[FrameGroup]:
    """Return timed movie frames, excluding frame 0 and later loops."""
    return [
        group for group in groups
        if group.loop == 0 and group.values["frame"] != 0
    ]


def field_statistics(
    groups: list[FrameGroup],
    field: str,
) -> dict[str, int | float]:
    """Summarize one HUD field over the timed first movie loop."""
    values = [
        group.values[field]
        for group in timed_first_loop(groups)
        if field in group.values
    ]
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
    groups: list[FrameGroup],
) -> dict[str, int | float]:
    """Summarize blocking CD pumps over the timed first movie loop."""
    return field_statistics(groups, "cd_wait_count")


def adpcm_decode_statistics(
    groups: list[FrameGroup],
) -> dict[str, int | float]:
    """Summarize Sub ADPCM decode time over the timed first movie loop."""
    return field_statistics(groups, "adpcm_decode_units")


def pump_gap_statistics(
    groups: list[FrameGroup],
) -> dict[str, int | float]:
    """Summarize maximum time outside the Sub CDC pump."""
    values = [
        group.values["pump_gap_ticks"]
        for group in timed_first_loop(groups)
        if "pump_gap_ticks" in group.values
    ]
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


def apply_backpressure_frame_count(groups: list[FrameGroup]) -> int:
    """Count timed frames that report APPLY back-pressure."""
    return sum(
        bool(group.values["apply_backpressure"])
        for group in timed_first_loop(groups)
        if "apply_backpressure" in group.values
    )


def format_field_statistics(
    field: str,
    result: dict[str, int | float],
) -> str:
    """Format the canonical human-readable HUD field summary."""
    return (
        f"{field} statistics (timed first loop; frame 0 excluded): "
        f"min={int(result['minimum'])} "
        f"mean={float(result['mean']):.3f} "
        f"median={float(result['median']):g} "
        f"max={int(result['maximum'])} "
        f"n={int(result['sample_count'])}"
    )


def format_cd_wait_statistics(result: dict[str, int | float]) -> str:
    return format_field_statistics("cd_wait_count", result)


def format_adpcm_decode_statistics(
    result: dict[str, int | float],
) -> str:
    return format_field_statistics("adpcm_decode_units", result)


def _fmt(group: FrameGroup) -> str:
    v = group.values
    return (
        f"loop={group.loop} t={group.time_first:8.3f}s "
        f"cap={group.capture_first:5d}-{group.capture_last:<5d} "
        f"frame={v['frame']:04X} palette_segment={v['palette_segment']:X} "
        f"sector_slip={v['sector_slip']:X} "
        f"control_desync={v['control_desync']:X} "
        f"audio_resync={v['audio_resync']:X} "
        f"audio_lead_256b={v['audio_lead_256b']:02X} "
        f"cd_wait_count={v['cd_wait_count']:X} "
        f"sub_wait_scanlines={v['sub_wait_scanlines']:02X} "
        f"vblank_spill={v['vblank_spill']:X} "
        f"adpcm_decode_units={v['adpcm_decode_units']:02X} "
        f"transfer_ticks={v['transfer_ticks']:03X} "
        f"cold_runs={v['cold_runs']:02X} "
        f"prgbuf_jitter_peak_kib={v['prgbuf_jitter_peak_kib']:02X} "
        f"pump_gap_ticks={v['pump_gap_ticks']:03X} "
        f"apply_backpressure={v['apply_backpressure']} "
        f"msf_gap_recoveries={v['msf_gap_recoveries']:X} "
        f"reader_ahead_frames={v['reader_ahead_frames']:X} "
        f"reader_slot_sector={v['reader_slot_sector']:X} "
        f"transfer_vblanks={v['transfer_vblanks']:X} "
        f"transfer_end_vcounter={v['transfer_end_vcounter']:02X} "
        f"pattern_dma_ready_vcounter={v['pattern_dma_ready_vcounter']:02X} "
        f"name_table_dma_ready_vcounter="
        f"{v['name_table_dma_ready_vcounter']:02X} "
        f"n={group.sample_count} "
        f"conf={group.confidence:.3f}"
    )


def print_report(groups: list[FrameGroup], context: int) -> list[int]:
    transitions = transition_indices(groups)
    print(f"movie HUD groups: {len(groups)}")
    print(f"first: {_fmt(groups[0])}")
    print(f"last:  {_fmt(groups[-1])}")
    print(format_cd_wait_statistics(cd_wait_statistics(groups)))
    print(format_adpcm_decode_statistics(adpcm_decode_statistics(groups)))
    if "pump_gap_ticks" in groups[0].values:
        print(
            format_field_statistics(
                "pump_gap_ticks",
                pump_gap_statistics(groups),
            )
        )
        print(
            "apply_backpressure frames "
            f"(timed first loop): {apply_backpressure_frame_count(groups)}"
        )
    print(f"audio_resync transitions: {len(transitions)}")
    if "prgbuf_jitter_peak_kib" in groups[0].values:
        peak = max(group.values["prgbuf_jitter_peak_kib"] for group in groups)
        peak_group = next(group for group in groups if group.values["prgbuf_jitter_peak_kib"] == peak)
        updates = sum(
            groups[index].values["prgbuf_jitter_peak_kib"] > groups[index - 1].values["prgbuf_jitter_peak_kib"]
            for index in range(1, len(groups))
        )
        print(
            f"prgbuf_jitter_peak_kib high-water: {peak:02X} "
            f"({peak} KiB ceil) first at "
            f"frame={peak_group.values['frame']:04X} "
            f"({peak_group.values['frame']}), updates={updates}"
        )
    if "reader_ahead_frames" in groups[0].values:
        lead_group = max(
            groups,
            key=lambda group: (
                group.values["reader_ahead_frames"],
                group.values["reader_slot_sector"],
            ),
        )
        print(
            "reader lead: "
            f"{lead_group.values['reader_ahead_frames']} complete frame slots "
            f"+ sector {lead_group.values['reader_slot_sector']} at "
            f"frame={lead_group.values['frame']:04X}"
        )
    for number, index in enumerate(transitions, 1):
        previous = groups[index - 1]
        current = groups[index]
        following = groups[index + 1] if index + 1 < len(groups) else None
        after_lead = (
            f"{following.values['audio_lead_256b']:02X}"
            if following else "--")
        print(
            f"\n[{number}] audio_resync "
            f"{previous.values['audio_resync']:X}->"
            f"{current.values['audio_resync']:X} "
            f"at frame={current.values['frame']:04X} "
            f"({current.values['frame']}) "
            f"t={current.time_first:.3f}s; "
            "audio_lead_256b before/current/after="
            f"{previous.values['audio_lead_256b']:02X}/"
            f"{current.values['audio_lead_256b']:02X}/{after_lead}"
        )
        for row in groups[max(0, index - context):min(len(groups), index + context + 1)]:
            marker = ">" if row is current else " "
            print(f" {marker} {_fmt(row)}")
    return transitions


def write_tsv(path: Path, groups: list[FrameGroup], transitions: list[int]) -> None:
    transition_set = set(transitions)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    columns = [
        "loop", "capture_first", "capture_last", "time_first_s", "time_last_s",
        "sample_count", "confidence", "frame", "frame_hex",
        "palette_segment", "sector_slip", "control_desync", "audio_resync",
        "audio_lead_256b", "audio_lead_hex", "cd_wait_count",
        "sub_wait_scanlines", "vblank_spill", "adpcm_decode_units",
        "transfer_ticks", "transfer_ms", "cold_runs",
        "prgbuf_jitter_peak_kib", "reader_ahead_frames",
        "reader_slot_sector", "transfer_vblanks", "transfer_end_vcounter",
        "pattern_dma_ready_vcounter", "name_table_dma_ready_vcounter",
        "pump_gap_ticks", "pump_gap_ms", "apply_backpressure",
        "msf_gap_recoveries", "transport_retry_recoveries",
        "flip_vcounter", "first_share_exit_vcounter", "pass2_delay_q4",
        "audio_resync_transition", "prev_frame",
        "prev_audio_lead_256b", "next_frame", "next_audio_lead_256b",
    ]
    with temporary.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(
            handle,
            fieldnames=columns,
            delimiter="\t",
            lineterminator="\n",
        )
        writer.writeheader()
        for index, group in enumerate(groups):
            values = group.values
            changed = index in transition_set
            previous = groups[index - 1] if changed else None
            following = groups[index + 1] if changed and index + 1 < len(groups) else None
            writer.writerow({
                "loop": group.loop,
                "capture_first": group.capture_first,
                "capture_last": group.capture_last,
                "time_first_s": f"{group.time_first:.6f}",
                "time_last_s": f"{group.time_last:.6f}",
                "sample_count": group.sample_count,
                "confidence": f"{group.confidence:.3f}",
                "frame": values["frame"],
                "frame_hex": f"{values['frame']:04X}",
                "palette_segment": values["palette_segment"],
                "sector_slip": values["sector_slip"],
                "control_desync": values["control_desync"],
                "audio_resync": values["audio_resync"],
                "audio_lead_256b": values["audio_lead_256b"],
                "audio_lead_hex": f"{values['audio_lead_256b']:02X}",
                "cd_wait_count": values["cd_wait_count"],
                "sub_wait_scanlines": values["sub_wait_scanlines"],
                "vblank_spill": values["vblank_spill"],
                "adpcm_decode_units": values["adpcm_decode_units"],
                "transfer_ticks": values["transfer_ticks"],
                "transfer_ms": (
                    f"{values['transfer_ticks'] * 0.03072:.5f}"),
                "cold_runs": values["cold_runs"],
                "prgbuf_jitter_peak_kib": values[
                    "prgbuf_jitter_peak_kib"],
                "reader_ahead_frames": values["reader_ahead_frames"],
                "reader_slot_sector": values["reader_slot_sector"],
                "transfer_vblanks": values["transfer_vblanks"],
                "transfer_end_vcounter": (
                    f"{values['transfer_end_vcounter']:02X}"),
                "pattern_dma_ready_vcounter": (
                    f"{values['pattern_dma_ready_vcounter']:02X}"),
                "name_table_dma_ready_vcounter": (
                    f"{values['name_table_dma_ready_vcounter']:02X}"),
                "pump_gap_ticks": values["pump_gap_ticks"],
                "pump_gap_ms": (
                    f"{values['pump_gap_ticks'] * 0.03072:.5f}"),
                "apply_backpressure": values["apply_backpressure"],
                "msf_gap_recoveries": values["msf_gap_recoveries"],
                "transport_retry_recoveries": (
                    values["sector_slip"] - values["msf_gap_recoveries"]
                ) & 0xF,
                "flip_vcounter": f"{values['flip_vcounter']:02X}",
                "first_share_exit_vcounter": (
                    f"{values['first_share_exit_vcounter']:02X}"),
                "pass2_delay_q4": values["pass2_delay_q4"],
                "audio_resync_transition": (
                    f"{previous.values['audio_resync']:X}->"
                    f"{values['audio_resync']:X}" if previous else ""
                ),
                "prev_frame": previous.values["frame"] if previous else "",
                "prev_audio_lead_256b": (
                    previous.values["audio_lead_256b"] if previous else ""),
                "next_frame": following.values["frame"] if following else "",
                "next_audio_lead_256b": (
                    following.values["audio_lead_256b"] if following else ""),
            })
    temporary.replace(path)
    print(f"TSV: {path}")


def upload_gate_limits(content_fps: float) -> tuple[dict[str, int], str]:
    """Return cadence-aware HUD limits for the exact encoded content rate."""
    fps = float(content_fps)
    if fps <= 0:
        raise ValueError(f"content fps must be positive, got {content_fps!r}")
    fixed_n = av_config.fixed_vblank_interval(fps)
    if fixed_n is not None:
        cadence = f"fixed_n{fixed_n}"
        # Pattern work may consume the N-1 intervening VBlanks; the Nth is the
        # fixed display-flip deadline.
        m_limit = fixed_n - 1
    else:
        cadence = "delivery_paced"
        # The Main path may use the complete number of display fields
        # available to one content frame; exceeding it proves an additional
        # spill.
        m_limit = math.ceil(av_config.NTSC_VSYNC / fps)
    return {
        "sector_slip": 0,
        "control_desync": 0,
        "audio_resync": 0,
        "vblank_spill": m_limit,
        # This is ceil-KiB. Leave one complete KiB below the physical ring end
        # so an accepted value proves head and tail never became equal at
        # full. Values beyond jitter headroom remain visible for review.
        "prgbuf_jitter_peak_kib": (
            av_config.RING_SIZE_KB
            - av_config.prg_buf_cap_kb(fps)
            - 1
        ),
    }, cadence


def display_vblank_cadence(
    groups: list[FrameGroup],
    content_fps: float,
    expected_frames: int,
) -> dict:
    """Measure display cadence while keeping edge observations diagnostic."""
    first_loop = [group for group in groups if group.loop == 0]
    expected = av_config.fixed_vblank_interval(float(content_fps))
    histogram: Counter[int] = Counter()
    observations: list[dict[str, int]] = []
    for current, following in zip(first_loop, first_loop[1:]):
        frame = current.values["frame"]
        next_frame = following.values["frame"]
        # Frame 0 is untimed boot staging. The last movie frame has no
        # following transition and is excluded naturally by zip().
        if frame == 0 or next_frame != frame + 1:
            continue
        actual = following.capture_first - current.capture_first
        histogram[actual] += 1
        observations.append({
            "frame": frame,
            "next_frame": next_frame,
            "capture_first": current.capture_first,
            "next_capture_first": following.capture_first,
            "display_vblanks": actual,
        })
    measured_violations = (
        [
            observation for observation in observations
            if observation["display_vblanks"] != expected
        ]
        if expected is not None else []
    )
    edge_frames = (
        hud_gate.cadence_alert_edge_frames(content_fps)
        if expected is not None else 0
    )
    alert_observations = (
        [
            observation for observation in observations
            if not hud_gate.cadence_alert_frame_is_exempt(
                observation["frame"],
                expected_frames,
                content_fps,
            )
        ]
        if expected is not None else []
    )
    exempted_violations = [
        observation for observation in measured_violations
        if hud_gate.cadence_alert_frame_is_exempt(
            observation["frame"],
            expected_frames,
            content_fps,
        )
    ]
    violations = [
        observation for observation in measured_violations
        if not hud_gate.cadence_alert_frame_is_exempt(
            observation["frame"],
            expected_frames,
            content_fps,
        )
    ]
    return {
        "expected": expected,
        "evaluated_frames": len(observations),
        "alert_evaluated_frames": len(alert_observations),
        "edge_exempt_frames": edge_frames,
        "histogram": {
            str(display_vblanks): count
            for display_vblanks, count in sorted(histogram.items())
        },
        "violation_count": len(violations),
        "violations": violations,
        "exempted_violation_count": len(exempted_violations),
        "exempted_violations": exempted_violations,
    }


def evaluate_upload_gate(
    groups: list[FrameGroup],
    expected_frames: int,
    recording: Path,
    content_fps: float = 30.0,
    profile: encode_config.EncodeProfile | None = None,
) -> dict:
    """Classify a complete first loop with a binary gate and tri-state alert."""
    first_loop = [group for group in groups if group.loop == 0]
    # Frame 0 is assembled during untimed boot staging.  Keep it in the
    # sequence-completeness proof, but never let its placeholder/startup HUD
    # values affect a timed playback metric or gate.
    timed_loop = timed_first_loop(groups)
    gate_fields = (
        "sector_slip", "control_desync", "audio_resync",
        "vblank_spill", "prgbuf_jitter_peak_kib",
    )
    measured_fields = (*gate_fields, "cd_wait_count")
    failures: list[str] = []
    warnings: list[str] = []
    missing = [
        field for field in gate_fields
        if field not in first_loop[0].values
    ]
    maxima = {
        field: max(
            (group.values.get(field, 0) for group in timed_loop),
            default=0,
        )
        for field in measured_fields
    }
    if missing:
        failures.append(f"HUD fields missing: {','.join(missing)}")

    frames = [group.values["frame"] for group in first_loop]
    wanted = list(range(expected_frames))
    if frames != wanted:
        first_bad = next(
            (index for index, (actual, expected) in enumerate(zip(frames, wanted))
             if actual != expected),
            min(len(frames), len(wanted)),
        )
        actual = frames[first_bad] if first_bad < len(frames) else None
        expected = wanted[first_bad] if first_bad < len(wanted) else None
        failures.append(
            f"first loop is incomplete: got {len(frames)} frames, expected "
            f"{expected_frames}; first mismatch index={first_bad} "
            f"actual={actual} expected={expected}"
        )

    limits, cadence = upload_gate_limits(content_fps)
    for field, limit in limits.items():
        if maxima[field] > limit:
            message = (
                f"{field} peak {maxima[field]:02X} exceeds "
                f"{'cadence warning' if field == 'vblank_spill' else 'upload'} "
                f"limit {limit:02X}"
            )
            (warnings if field == "vblank_spill" else failures).append(message)
    fixed_n = av_config.fixed_vblank_interval(float(content_fps))
    transfer_vblank_max = (
        max(
            (group.values.get("transfer_vblanks", 0) for group in timed_loop),
            default=0,
        )
        if first_loop and "transfer_vblanks" in first_loop[0].values else None
    )
    if (
        fixed_n is not None
        and transfer_vblank_max is not None
        and transfer_vblank_max > fixed_n
    ):
        warnings.append(
            f"transfer_vblanks peak {transfer_vblank_max:X} exceeds fixed-N "
            "transfer "
            f"window count {fixed_n:X}"
        )
    display_cadence = display_vblank_cadence(
        groups,
        content_fps,
        expected_frames,
    )
    if display_cadence["violation_count"]:
        examples = ", ".join(
            f"frame={row['frame']:04d}:{row['display_vblanks']}"
            for row in display_cadence["violations"][:8]
        )
        remaining = display_cadence["violation_count"] - 8
        suffix = f", +{remaining} more" if remaining > 0 else ""
        warnings.append(
            f"{cadence} display cadence missed "
            f"{display_cadence['violation_count']} deadline(s) outside the "
            f"{display_cadence['edge_exempt_frames']}-frame edge exception: "
            f"{examples}{suffix}"
        )

    stat = recording.stat()
    alert = hud_gate.classify_alert(failures, warnings)
    gate = hud_gate.gate_for_alert(alert)
    status = hud_gate.legacy_status_for_alert(alert)
    result = {
        "schema_version": 15,
        "gate": gate,
        "alert": alert,
        "pass": gate == "PASS",
        "status": status,
        "recording": str(recording.resolve()),
        "recording_size": stat.st_size,
        "recording_mtime_ns": stat.st_mtime_ns,
        "expected_frames": expected_frames,
        "observed_first_loop_frames": len(first_loop),
        "evaluation_first_frame": 1,
        "evaluated_timed_frames": len(timed_loop),
        "content_fps": float(content_fps),
        "cadence": cadence,
        "display_vblank_expected": display_cadence["expected"],
        "display_vblank_evaluated_frames": (
            display_cadence["evaluated_frames"]),
        "display_vblank_alert_evaluated_frames": (
            display_cadence["alert_evaluated_frames"]),
        "display_vblank_edge_exempt_frames": (
            display_cadence["edge_exempt_frames"]),
        "display_vblank_histogram": display_cadence["histogram"],
        "display_vblank_violation_count": (
            display_cadence["violation_count"]),
        "display_vblank_violations": display_cadence["violations"],
        "display_vblank_exempted_violation_count": (
            display_cadence["exempted_violation_count"]),
        "display_vblank_exempted_violations": (
            display_cadence["exempted_violations"]),
        "gate_fields": list(gate_fields),
        "warning_fields": ["vblank_spill"],
        "diagnostic_fields": [
            "cd_wait_count", "adpcm_decode_units", "pump_gap_ticks",
            "apply_backpressure", "msf_gap_recoveries",
            "reader_ahead_frames", "reader_slot_sector", "cold_runs",
            "transfer_ticks", "transfer_vblanks", "transfer_end_vcounter",
            "pattern_dma_ready_vcounter",
            "name_table_dma_ready_vcounter",
            "sub_wait_scanlines", "flip_vcounter",
            "first_share_exit_vcounter", "pass2_delay_q4",
        ],
        "maxima": maxima,
        "cd_wait_statistics": cd_wait_statistics(groups),
        "adpcm_decode_statistics": adpcm_decode_statistics(groups),
        "limits": limits,
        "prg_buf_cap_kib": av_config.prg_buf_cap_kb(content_fps),
        "jitter_headroom_kib": (
            av_config.ring_jitter_headroom_kb(content_fps)),
        "delivery_limit_kib": (
            av_config.scheduled_delivery_cap_kb(content_fps)),
        "backpressure_kib": av_config.BACKPRESSURE_KB,
        "physical_ring_kib": av_config.RING_SIZE_KB,
        "requires_explicit_upload_approval": False,
        "warnings": warnings,
        "failures": failures,
    }
    if "pump_gap_ticks" in first_loop[0].values:
        result["pump_gap_statistics"] = pump_gap_statistics(groups)
        result["apply_backpressure_frames"] = apply_backpressure_frame_count(
            groups)
    if "reader_ahead_frames" in first_loop[0].values:
        result["reader_ahead_max_frames"] = max(
            (group.values["reader_ahead_frames"] for group in timed_loop),
            default=0,
        )
        result["reader_slot_sector_max"] = max(
            (group.values["reader_slot_sector"] for group in timed_loop),
            default=0,
        )
    if "transfer_vblanks" in first_loop[0].values:
        result["transfer_vblanks_max"] = max(
            (group.values["transfer_vblanks"] for group in timed_loop),
            default=0,
        )
        result["transfer_end_vcounter_max"] = max(
            (group.values["transfer_end_vcounter"] for group in timed_loop),
            default=0,
        )
    if "first_share_exit_vcounter" in first_loop[0].values:
        result["first_share_exit_vcounter_max"] = max(
            (group.values["first_share_exit_vcounter"] for group in timed_loop),
            default=0,
        )
    for field in (
        "pattern_dma_ready_vcounter",
        "name_table_dma_ready_vcounter",
    ):
        if field in first_loop[0].values:
            result[f"{field}_max"] = max(
                (group.values[field] for group in timed_loop),
                default=0,
            )
    if profile is not None:
        result["profile"] = str(profile.path.resolve())
        result["profile_sha256"] = profile.sha256
    return result


def write_gate_json(path: Path, result: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n")
    gate = result["gate"]
    alert = result["alert"]
    maxima = result["maxima"]
    print(
        f"HUD record gate: {gate}  alert={alert}  "
        + " ".join(
            f"{field}={maxima[field]:X}"
            for field in result["gate_fields"]
        )
        + f"  cd_wait_count diagnostic max={maxima['cd_wait_count']:X}"
        + f"  frames={result['observed_first_loop_frames']}/"
        f"{result['expected_frames']}  cadence={result['cadence']} "
        f"fps={result['content_fps']:g}"
    )
    print(f"HUD gate JSON: {path.resolve()}")
    expected_vblanks = result["display_vblank_expected"]
    cadence_rule = (
        f"expected={expected_vblanks}"
        if expected_vblanks is not None else "variable delivery-paced"
    )
    print(
        "  display VBlanks/frame "
        f"{cadence_rule} histogram={result['display_vblank_histogram']} "
        f"alert violations={result['display_vblank_violation_count']}/"
        f"{result['display_vblank_alert_evaluated_frames']} "
        f"edge-exempt violations="
        f"{result['display_vblank_exempted_violation_count']} "
        f"(first/last {result['display_vblank_edge_exempt_frames']} frames; "
        f"measured={result['display_vblank_evaluated_frames']})"
    )
    if "reader_ahead_max_frames" in result:
        print(
            "  reader lead max="
            f"{result['reader_ahead_max_frames']} complete frame slots + "
            f"sector {result['reader_slot_sector_max']}"
        )
    if "transfer_vblanks_max" in result:
        print(
            "  transfer diagnostics: opened VBlank budgets max="
            f"{result['transfer_vblanks_max']}, end V-counter max="
            f"{result['transfer_end_vcounter_max']:02X}, first-share exit max="
            f"{result.get('first_share_exit_vcounter_max', 0):02X}, "
            "pattern/NT ready V-counter max="
            f"{result.get('pattern_dma_ready_vcounter_max', 0):02X}/"
            f"{result.get('name_table_dma_ready_vcounter_max', 0):02X}"
        )
    if "pump_gap_statistics" in result:
        print(
            "  "
            + format_field_statistics(
                "pump_gap_ticks", result["pump_gap_statistics"]
            )
        )
        print(
            "  apply_backpressure frames "
            f"(timed first loop): {result['apply_backpressure_frames']}"
        )
    for failure in result["failures"]:
        print(f"  gate failure: {failure}")
    for warning in result["warnings"]:
        print(f"  gate warning: {warning}")
    print(f"HUD gate JSON: {path}")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Aggregate the DEBUG HUD and report audio_resync transitions.")
    )
    parser.add_argument("recording", type=Path, help="native FFV1 MKV or MP4 recording")
    parser.add_argument(
        "profile", nargs="?", type=Path,
        help="encode profile; required positionally with --gate-json",
    )
    parser.add_argument(
        "--tsv",
        type=Path,
        help="write all aggregated movie frames as tab-separated values",
    )
    parser.add_argument(
        "--gate-json", type=Path,
        help="write the mandatory PASS/FAIL gate and NONE/WARNING/FAIL alert",
    )
    parser.add_argument(
        "--expected-frames", type=int,
        help="complete first-loop frame count required by --gate-json",
    )
    parser.add_argument(
        "--confidence", type=float, default=0.90,
        help="minimum confidence for every HUD field (default: 0.90)",
    )
    parser.add_argument(
        "--crop-x", type=int, default=0,
        help="left edge of the native HUD crop (default: 0; legacy centered H32 may use 32)",
    )
    parser.add_argument(
        "--max-gap", type=int, default=3,
        help="maximum capture-frame gap inside one frame group (default: 3)",
    )
    parser.add_argument(
        "--max-frame-step", type=int, default=4,
        help="largest accepted frame increment after a missed OCR group",
    )
    parser.add_argument(
        "--anchor-run", type=int, default=4,
        help="plausible groups required to accept a frame-0000 anchor",
    )
    parser.add_argument(
        "--context", type=int, default=2,
        help="frames printed on each side of an audio_resync transition",
    )
    args = parser.parse_args()
    if not args.recording.is_file():
        parser.error(f"recording not found: {args.recording}")
    if not 0.0 <= args.confidence <= 1.0:
        parser.error("--confidence must be within 0..1")
    for name in ("max_gap", "max_frame_step", "anchor_run"):
        if getattr(args, name) < 1:
            parser.error(f"--{name.replace('_', '-')} must be at least 1")
    if args.context < 0:
        parser.error("--context must not be negative")
    if args.gate_json and not args.expected_frames:
        parser.error("--gate-json requires --expected-frames")
    if args.gate_json and args.profile is None:
        parser.error("--gate-json requires the encode profile as the second positional argument")
    if args.profile is not None and not args.profile.is_file():
        parser.error(f"profile not found: {args.profile}")
    if args.expected_frames is not None and args.expected_frames < 1:
        parser.error("--expected-frames must be at least 1")
    if args.tsv is not None and args.tsv.suffix.lower() != ".tsv":
        parser.error("--tsv output must use the .tsv extension")
    return args


def main() -> int:
    args = parse_args()
    profile = (
        encode_config.load_profile(args.profile)
        if args.profile is not None else None
    )
    probe = probe_video(args.recording)
    print(
        f"input: {args.recording} ({probe.width}x{probe.height}, "
        f"{float(probe.fps):.6f} capture fps)"
    )
    raw_groups = group_samples(
        iter_samples(args.recording, probe, args.confidence, args.crop_x),
        args.max_gap,
    )
    anchor, sentinel_anchor = find_movie_anchor(
        raw_groups, args.anchor_run, args.max_frame_step)
    groups = select_movie_groups(raw_groups, args.anchor_run, args.max_frame_step)
    anchor_method = (
        "frame=FFFF player-only sentinel" if sentinel_anchor
        else "plausible frame=0000 sequence"
    )
    print(
        f"movie start anchor: {anchor_method}; "
        f"frame=0000 capture={raw_groups[anchor].capture_first}")
    transitions = print_report(groups, args.context)
    hud_tsv = args.tsv
    if hud_tsv is None and profile is not None:
        hud_tsv = analysis_logs.unique_tsv_path(profile, kind="hud")
    if hud_tsv is not None:
        write_tsv(hud_tsv, groups, transitions)
        print(f"HUD TSV: {hud_tsv.resolve()}")
    gate_path = args.gate_json
    if (
        gate_path is None
        and profile is not None
        and args.expected_frames is not None
    ):
        if hud_tsv is None:
            raise AssertionError("profile HUD analysis did not allocate a TSV")
        gate_path = hud_tsv.with_name(f"{hud_tsv.stem}_gate.json")
    if gate_path is not None:
        content_fps = float(Fraction(str(profile.data["source"]["fps"])))
        result = evaluate_upload_gate(
            groups, args.expected_frames, args.recording, content_fps, profile)
        result["ocr_start_anchor"] = {
            "method": "frame_minus_one" if sentinel_anchor else "plausible_sequence",
            "frame0_capture_first": raw_groups[anchor].capture_first,
            "frame0_time_first_s": raw_groups[anchor].time_first,
            "frame0_time_last_s": raw_groups[anchor].time_last,
        }
        if sentinel_anchor:
            sentinel = raw_groups[anchor - 1]
            result["ocr_start_anchor"].update({
                "frame_minus_one_raw16": read_frameno.FRAME_MINUS_ONE,
                "frame_minus_one_capture_first": sentinel.capture_first,
                "frame_minus_one_capture_last": sentinel.capture_last,
                "frame_minus_one_time_first_s": sentinel.time_first,
                "frame_minus_one_time_last_s": sentinel.time_last,
            })
        write_gate_json(gate_path, result)
        if result["gate"] == "FAIL":
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
