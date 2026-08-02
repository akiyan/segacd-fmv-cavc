#!/usr/bin/env python3
"""Canonical HUD upload-gate and alert result handling."""

from __future__ import annotations

from collections.abc import Collection, Mapping
import math


GATE_VALUES = ("PASS", "FAIL")
ALERT_VALUES = ("NONE", "WARNING", "FAIL")
LEGACY_STATUS_BY_ALERT = {
    "NONE": "PASS",
    "WARNING": "WARNING",
    "FAIL": "FAIL",
}
ALERT_BY_LEGACY_STATUS = {
    status: alert for alert, status in LEGACY_STATUS_BY_ALERT.items()
}

# Display-cadence observations at the movie edges include startup and terminal
# handoff behavior that is not representative of the steady timed loop. Keep
# those observations visible, but do not let them raise the cadence alert.
CADENCE_ALERT_EDGE_FRAMES = {
    15: 2,
    24: 3,
    30: 4,
}


def cadence_alert_edge_frames(content_fps: float) -> int:
    """Return content frames excluded at each edge from cadence alerts."""

    value = float(content_fps)
    for nominal_fps, edge_frames in CADENCE_ALERT_EDGE_FRAMES.items():
        if math.isclose(value, nominal_fps, rel_tol=0.0, abs_tol=0.1):
            return edge_frames
    return 0


def cadence_alert_frame_is_exempt(
    frame: int,
    expected_frames: int,
    content_fps: float,
) -> bool:
    """Whether one content frame is outside the cadence-alert steady region."""

    edge_frames = cadence_alert_edge_frames(content_fps)
    if edge_frames == 0:
        return False
    return (
        frame < edge_frames
        or frame >= max(0, expected_frames - edge_frames)
    )


def classify_alert(
    failures: Collection[object],
    warnings: Collection[object],
) -> str:
    """Return the three-state alert without changing gate eligibility."""

    if failures:
        return "FAIL"
    if warnings:
        return "WARNING"
    return "NONE"


def gate_for_alert(alert: str) -> str:
    """Map an alert to the binary upload gate."""

    if alert not in ALERT_VALUES:
        raise ValueError(f"invalid HUD alert: {alert!r}")
    return "FAIL" if alert == "FAIL" else "PASS"


def legacy_status_for_alert(alert: str) -> str:
    """Return the deprecated PASS/WARNING/FAIL compatibility value."""

    try:
        return LEGACY_STATUS_BY_ALERT[alert]
    except KeyError as exc:
        raise ValueError(f"invalid HUD alert: {alert!r}") from exc


def normalize_result(raw: Mapping[str, object]) -> dict:
    """Validate a gate result and supply canonical and compatibility fields."""

    result = dict(raw)
    schema = int(result.get("schema_version", 0))
    if schema >= 6:
        if "gate" not in result or "alert" not in result:
            raise ValueError("schema-6 HUD result requires gate and alert")
        gate = str(result["gate"])
        alert = str(result["alert"])
    else:
        status = str(
            result.get(
                "status",
                "PASS" if bool(result.get("pass", False)) else "FAIL",
            )
        )
        try:
            alert = ALERT_BY_LEGACY_STATUS[status]
        except KeyError as exc:
            raise ValueError(f"invalid legacy HUD status: {status!r}") from exc
        gate = gate_for_alert(alert)

    if gate not in GATE_VALUES:
        raise ValueError(f"invalid HUD gate: {gate!r}")
    if alert not in ALERT_VALUES:
        raise ValueError(f"invalid HUD alert: {alert!r}")
    expected_gate = gate_for_alert(alert)
    if gate != expected_gate:
        raise ValueError(
            f"HUD gate {gate!r} disagrees with alert {alert!r}"
        )

    status = legacy_status_for_alert(alert)
    if "status" in result and str(result["status"]) != status:
        raise ValueError("legacy HUD status disagrees with alert")
    passed = gate == "PASS"
    if "pass" in result and bool(result["pass"]) != passed:
        raise ValueError("legacy HUD pass boolean disagrees with gate")

    result.update({
        "gate": gate,
        "alert": alert,
        "status": status,
        "pass": passed,
    })
    return result
