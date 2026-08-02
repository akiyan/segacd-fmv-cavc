#!/usr/bin/env python3
"""Automatic black-fade shot detection for CRAM-only movie frames.

The detector deliberately has no timeline or profile inputs.  It finds a
bright interval beside one or two black runs, fits every interval frame to one
static reference image plus a single global brightness scale, and accepts the
interval only when that scale moves monotonically in the direction implied by
the black edge.  Moving shots, hard cuts, and merely dark scenes therefore
stay on the ordinary tile-update path.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class BlackRun:
    """Inclusive frame range whose sampled image is effectively black."""

    start: int
    end: int


@dataclass(frozen=True)
class FadeShot:
    """One static shot with a fade on at least one side."""

    left_black: BlackRun | None
    start: int
    end: int
    reference: int
    peak: int
    right_black: BlackRun | None
    scales: tuple[float, ...]
    fit_rmse: tuple[float, ...]

    @property
    def anchor(self) -> int:
        """First ordinary frame on which the reference can be prepared."""

        if self.left_black is None:
            return self.start
        return self.left_black.start

    @property
    def preparation_end(self) -> int:
        """Last ordinary frame available for exact reference preparation."""

        if self.left_black is None:
            return self.start
        return self.left_black.end

    @property
    def display_end(self) -> int:
        """Last frame whose indexed image is frozen to this reference."""

        if self.right_black is None:
            return self.end
        return self.right_black.end

    @property
    def restoration(self) -> int:
        """First frame after this shot's CRAM-only state."""

        return self.display_end + 1

    @property
    def has_fade_in(self) -> bool:
        return self.left_black is not None

    @property
    def has_fade_out(self) -> bool:
        return self.right_black is not None

    @property
    def kind(self) -> str:
        if self.has_fade_in and self.has_fade_out:
            return "in_out"
        if self.has_fade_in:
            return "in"
        if self.has_fade_out:
            return "out"
        raise ValueError("a fade shot must have at least one black side")

    @property
    def entry_scale(self) -> float:
        """CRAM scale installed when the reference-preparation segment starts."""

        return 0.0 if self.has_fade_in else 1.0


@dataclass(frozen=True)
class FadeLayout:
    """Palette segments and per-frame targets for selected fade shots."""

    shots: tuple[FadeShot, ...]
    frame_segments: np.ndarray
    palette_sources: tuple[int, ...]
    entry_scales: tuple[float, ...]
    reference_frames: np.ndarray
    desired_scales: np.ndarray
    phases: np.ndarray
    anchors: tuple[int, ...]
    preparation_frames: tuple[int, ...]
    preparation_deadlines: tuple[int, ...]
    restorations: tuple[int, ...]


def connected_groups(shots) -> tuple[tuple[FadeShot, ...], ...]:
    """Group detected shots that share the intervening black run."""

    ordered = sorted(shots, key=lambda shot: (shot.start, shot.end))
    groups: list[list[FadeShot]] = []
    for shot in ordered:
        if (groups
                and groups[-1][-1].right_black is not None
                and groups[-1][-1].right_black == shot.left_black):
            groups[-1].append(shot)
        else:
            groups.append([shot])
    return tuple(tuple(group) for group in groups)


def select_groups_with_segment_capacity(
        shots,
        existing_boundaries,
        *,
        frame_count: int,
        max_segments: int,
) -> tuple[FadeShot, ...]:
    """Keep complete fade groups that fit the fixed player palette tables.

    Every shot needs a black preparation segment at its anchor.  The end of a
    connected group needs one normal segment to restore the ordinary palette.
    An unrelated pre-existing palette boundary inside such a group would make
    the CRAM-only state ambiguous, so that group stays on the normal path.
    """

    count = int(frame_count)
    capacity = int(max_segments)
    boundaries = {int(frame) for frame in existing_boundaries}
    if count < 0 or capacity <= 0:
        raise ValueError("frame_count must be non-negative and max_segments positive")
    if count:
        boundaries.add(0)
    if any(frame < 0 or frame >= count for frame in boundaries):
        raise ValueError("existing palette boundary is outside the movie")

    candidates = []
    for group in connected_groups(shots):
        restore = group[-1].restoration
        event_frames = {shot.anchor for shot in group}
        if restore < count:
            event_frames.add(restore)
        benefit = sum(shot.end - shot.start + 1 for shot in group)
        replaced = set(range(group[0].anchor, min(restore, count)))
        candidates.append(
            (benefit, group[0].start, group, event_frames, replaced))

    selected: list[FadeShot] = []
    for _benefit, _start, group, events, replaced in sorted(
            candidates, key=lambda item: (-item[0], item[1])):
        expanded = (boundaries - replaced) | events
        if len(expanded) > capacity:
            continue
        boundaries = expanded
        selected.extend(group)
    return tuple(sorted(selected, key=lambda shot: shot.start))


def scaled_palette(
        palette,
        scale: float,
        *,
        preserve=((0, 0), (0, 14)),
) -> np.ndarray:
    """Scale one ``(4, 15, 3)`` RGB333 palette while preserving HUD colours."""

    source = np.asarray(palette, dtype=np.uint8)
    if source.shape != (4, 15, 3):
        raise ValueError("fade palette must have shape (4, 15, 3)")
    value = float(scale)
    if not np.isfinite(value) or value < 0:
        raise ValueError("fade palette scale must be finite and non-negative")
    result = np.clip(np.rint(source.astype(np.float64) * value), 0, 7).astype(np.uint8)
    for line, index in preserve:
        if not (0 <= int(line) < 4 and 0 <= int(index) < 15):
            raise ValueError("preserved fade palette entry is outside the palette")
        result[int(line), int(index)] = source[int(line), int(index)]
    return result


def build_layout(
        shots,
        original_frame_segments,
        *,
        max_segments: int,
) -> FadeLayout:
    """Select detected groups and overlay their black preparation segments."""

    original = np.asarray(original_frame_segments, dtype=np.int64)
    if original.ndim != 1:
        raise ValueError("frame segments must be one-dimensional")
    count = len(original)
    if count:
        if int(original[0]) != 0 or np.any(np.diff(original) < 0):
            raise ValueError("frame segments must be forward-only from segment zero")
        boundaries = np.flatnonzero(
            np.r_[True, original[1:] != original[:-1]])
    else:
        boundaries = np.zeros(0, np.int64)
    selected = select_groups_with_segment_capacity(
        shots,
        boundaries,
        frame_count=count,
        max_segments=max_segments,
    )

    events: dict[int, tuple[int, float]] = {
        int(frame): (int(original[int(frame)]), 1.0)
        for frame in boundaries
    }
    anchors = tuple(shot.anchor for shot in selected)
    restorations = []
    for group in connected_groups(selected):
        restore = group[-1].restoration
        for frame in tuple(events):
            if group[0].anchor <= frame < min(restore, count):
                del events[frame]
        if restore < count:
            events[restore] = (int(original[restore]), 1.0)
            restorations.append(restore)
    for shot in selected:
        events[shot.anchor] = (
            int(original[shot.reference]), shot.entry_scale)

    frame_segments = np.zeros(count, np.int32)
    palette_sources: list[int] = []
    entry_scales: list[float] = []
    ordered_events = sorted(events.items())
    for segment, (frame, (source, scale)) in enumerate(ordered_events):
        end = ordered_events[segment + 1][0] if segment + 1 < len(ordered_events) else count
        frame_segments[frame:end] = segment
        palette_sources.append(source)
        entry_scales.append(scale)
    if len(palette_sources) > int(max_segments):
        raise AssertionError("selected fade layout exceeds palette capacity")

    references = np.full(count, -1, np.int32)
    desired = np.full(count, np.nan, np.float64)
    phases = np.zeros(count, np.uint8)
    preparation_frames = set()
    preparation_deadlines = set()
    for shot in selected:
        references[shot.anchor:shot.display_end + 1] = shot.reference
        desired[shot.start:shot.end + 1] = shot.scales
        if shot.has_fade_in and shot.has_fade_out:
            phases[shot.start:shot.peak + 1] = 1
            phases[shot.peak + 1:shot.end + 1] = 2
        elif shot.has_fade_in:
            phases[shot.start:shot.end + 1] = 1
        else:
            phases[shot.start:shot.end + 1] = 2
        if shot.right_black is not None:
            desired[
                shot.right_black.start:shot.right_black.end + 1] = 0.0
            phases[
                shot.right_black.start:shot.right_black.end + 1] = 2
        preparation_deadlines.add(shot.preparation_end)
    # A shared black frame belongs to the next shot's ordinary preparation
    # segment, not to the previous shot's CRAM-only fade-out control.
    for shot in selected:
        preparation_frames.update(
            range(shot.anchor, shot.preparation_end + 1))
        desired[shot.anchor:shot.preparation_end + 1] = np.nan
        phases[shot.anchor:shot.preparation_end + 1] = 0
        references[shot.anchor:shot.preparation_end + 1] = shot.reference

    return FadeLayout(
        shots=selected,
        frame_segments=frame_segments,
        palette_sources=tuple(palette_sources),
        entry_scales=tuple(entry_scales),
        reference_frames=references,
        desired_scales=desired,
        phases=phases,
        anchors=anchors,
        preparation_frames=tuple(sorted(preparation_frames)),
        preparation_deadlines=tuple(sorted(preparation_deadlines)),
        restorations=tuple(restorations),
    )


def _black_runs(mask: np.ndarray) -> tuple[BlackRun, ...]:
    hits = np.flatnonzero(mask)
    if not len(hits):
        return ()
    runs: list[BlackRun] = []
    start = previous = int(hits[0])
    for raw_frame in hits[1:]:
        frame = int(raw_frame)
        if frame == previous + 1:
            previous = frame
            continue
        runs.append(BlackRun(start, previous))
        start = previous = frame
    runs.append(BlackRun(start, previous))
    return tuple(runs)


def _fit_static_scale(
        samples: np.ndarray,
        black: np.ndarray,
        *,
        reference_local: int | None = None,
) -> tuple[int, np.ndarray, np.ndarray]:
    """Return the best bright reference and each frame's scale/error."""

    centered = samples - black[None, ...]
    energy = np.einsum("fsc,fsc->f", centered, centered)
    if reference_local is None:
        # A complete fade reference is the brightest observed frame.  The
        # final maximum is preferred so a two-frame peak naturally leaves its
        # last frame as the unmodified reference/plateau frame.
        maximum = float(energy.max(initial=0.0))
        candidates = np.flatnonzero(
            np.isclose(energy, maximum, rtol=1e-6, atol=1e-6))
        selected_reference = int(candidates[-1]) if len(candidates) else 0
    else:
        selected_reference = int(reference_local)
        if not 0 <= selected_reference < len(samples):
            raise ValueError("fade reference is outside the sample interval")
    reference = centered[selected_reference]
    denominator = float(np.sum(reference * reference))
    if denominator <= 1e-9:
        return (
            selected_reference,
            np.zeros(len(samples)),
            np.full(len(samples), np.inf),
        )
    scales = np.einsum("fsc,sc->f", centered, reference) / denominator
    prediction = black[None, ...] + scales[:, None, None] * reference[None, ...]
    rmse = np.sqrt(np.mean((samples - prediction) ** 2, axis=(1, 2)))
    return selected_reference, scales, rmse


def _detect_rising_side(
        samples: np.ndarray,
        black: np.ndarray,
        *,
        min_frames: int,
        maximum_frames: int,
        min_scale_change: float,
        monotonic_tolerance: float,
        maximum_scale: float,
        maximum_rmse: float,
        maximum_relative_rmse: float,
) -> tuple[np.ndarray, np.ndarray] | None:
    """Return the longest static black-to-reference prefix, if one exists."""

    best = None
    limit = min(len(samples), int(maximum_frames))
    for length in range(int(min_frames), limit + 1):
        interval = samples[:length]
        _reference, scales, rmse = _fit_static_scale(
            interval, black, reference_local=length - 1)
        reference_scale = float(scales[-1])
        if reference_scale <= 0:
            continue
        relative_scales = scales / reference_scale
        relative_error = rmse / np.maximum(
            interval.mean(axis=(1, 2)), 16.0)
        rising = np.diff(relative_scales)
        if (
            float(relative_scales.min(initial=1.0)) < -monotonic_tolerance
            or float(relative_scales.max(initial=0.0)) > maximum_scale
            or float(relative_scales[0]) > 1.0 - min_scale_change
            or (len(rising) and float(rising.min()) < -monotonic_tolerance)
            or float(rmse.max(initial=0.0)) > maximum_rmse
            or float(relative_error.max(initial=0.0)) > maximum_relative_rmse
        ):
            continue
        best = relative_scales.copy(), rmse.copy()
    return best


def _drop_overlapping_one_sided(
        shots: list[FadeShot],
) -> list[FadeShot]:
    """Reject ambiguous one-sided fits that claim any common source frame."""

    conflicted = set()
    ordered = sorted(enumerate(shots), key=lambda item: item[1].start)
    for position, (index, shot) in enumerate(ordered):
        for other_index, other in ordered[position + 1:]:
            if other.start > shot.end:
                break
            conflicted.add(index)
            conflicted.add(other_index)
    return [shot for index, shot in enumerate(shots) if index not in conflicted]


def detect_fade_shots(
        probes,
        dark_fraction,
        *,
        black_fraction_min: float = 0.98,
        black_mean_max: float = 16.0,
        min_frames: int = 3,
        min_scale_change: float = 0.20,
        monotonic_tolerance: float = 0.06,
        maximum_scale: float = 1.08,
        maximum_rmse: float = 10.0,
        maximum_relative_rmse: float = 0.18,
        maximum_one_sided_frames: int = 240,
) -> tuple[FadeShot, ...]:
    """Detect static one- or two-sided fades without source frame ranges.

    ``probes`` is ``(frames, samples, 3)`` RGB888 data.  One sample per source
    tile is enough; using a small spatial grid preserves motion and hard-cut
    evidence while keeping the whole-movie detector cheap.  ``dark_fraction``
    is the per-frame fraction of source pixels below the encoder's black
    luminance threshold.
    """

    samples = np.asarray(probes, dtype=np.float64)
    dark = np.asarray(dark_fraction, dtype=np.float64)
    if samples.ndim != 3 or samples.shape[2] != 3:
        raise ValueError("fade probes must have shape (frames, samples, 3)")
    if dark.shape != (len(samples),):
        raise ValueError("fade probes and dark fractions must have equal frame counts")
    if not np.isfinite(samples).all() or not np.isfinite(dark).all():
        raise ValueError("fade probes and dark fractions must be finite")
    if min_frames < 1:
        raise ValueError("min_frames must be positive")
    if maximum_one_sided_frames < min_frames:
        raise ValueError(
            "maximum_one_sided_frames must be at least min_frames")

    frame_mean = samples.mean(axis=(1, 2))
    black_mask = (
        (dark >= float(black_fraction_min))
        & (frame_mean <= float(black_mean_max))
    )
    runs = _black_runs(black_mask)
    complete: list[FadeShot] = []
    for left, right in zip(runs, runs[1:]):
        start = left.end + 1
        end = right.start - 1
        if end - start + 1 < int(min_frames):
            continue
        interval = samples[start:end + 1]
        black = np.mean(
            np.concatenate(
                (samples[left.start:left.end + 1],
                 samples[right.start:right.end + 1]),
                axis=0,
            ),
            axis=0,
        )
        reference_local, scales, rmse = _fit_static_scale(interval, black)
        peak_local = int(np.argmax(scales))
        peak_scale = float(scales[peak_local])
        if peak_scale <= 0:
            continue
        relative_scales = scales / peak_scale
        relative_error = rmse / np.maximum(interval.mean(axis=(1, 2)), 16.0)
        rising = np.diff(relative_scales[:peak_local + 1])
        falling = np.diff(relative_scales[peak_local:])
        if (
            float(relative_scales.min(initial=1.0)) < -monotonic_tolerance
            or float(relative_scales.max(initial=0.0)) > maximum_scale
            or float(relative_scales[0]) > 1.0 - min_scale_change
            or float(relative_scales[-1]) > 1.0 - min_scale_change
            or (len(rising) and float(rising.min()) < -monotonic_tolerance)
            or (len(falling) and float(falling.max()) > monotonic_tolerance)
            or float(rmse.max(initial=0.0)) > maximum_rmse
            or float(relative_error.max(initial=0.0)) > maximum_relative_rmse
        ):
            continue
        complete.append(FadeShot(
            left_black=left,
            start=start,
            end=end,
            reference=start + reference_local,
            peak=start + peak_local,
            right_black=right,
            scales=tuple(float(value) for value in relative_scales),
            fit_rmse=tuple(float(value) for value in rmse),
        ))

    # A complete fit owns only the two black-run sides that bound it.  The
    # opposite side of a shared black run can still be a different one-sided
    # fade, such as a fade-out followed by a new shot fading in from black.
    complete_left = {shot.left_black for shot in complete}
    complete_right = {shot.right_black for shot in complete}
    one_sided: list[FadeShot] = []
    for run_index, black_run in enumerate(runs):
        black = samples[black_run.start:black_run.end + 1].mean(axis=0)
        previous_end = (
            runs[run_index - 1].end + 1 if run_index else 0)
        next_start = (
            runs[run_index + 1].start
            if run_index + 1 < len(runs) else len(samples))

        if black_run not in complete_left:
            start = black_run.end + 1
            rising = _detect_rising_side(
                samples[start:next_start],
                black,
                min_frames=min_frames,
                maximum_frames=maximum_one_sided_frames,
                min_scale_change=min_scale_change,
                monotonic_tolerance=monotonic_tolerance,
                maximum_scale=maximum_scale,
                maximum_rmse=maximum_rmse,
                maximum_relative_rmse=maximum_relative_rmse,
            )
            if rising is not None:
                scales, rmse = rising
                end = start + len(scales) - 1
                one_sided.append(FadeShot(
                    left_black=black_run,
                    start=start,
                    end=end,
                    reference=end,
                    peak=end,
                    right_black=None,
                    scales=tuple(float(value) for value in scales),
                    fit_rmse=tuple(float(value) for value in rmse),
                ))

        if black_run not in complete_right:
            end = black_run.start - 1
            rising = _detect_rising_side(
                samples[previous_end:black_run.start][::-1],
                black,
                min_frames=min_frames,
                maximum_frames=maximum_one_sided_frames,
                min_scale_change=min_scale_change,
                monotonic_tolerance=monotonic_tolerance,
                maximum_scale=maximum_scale,
                maximum_rmse=maximum_rmse,
                maximum_relative_rmse=maximum_relative_rmse,
            )
            if rising is not None:
                reverse_scales, reverse_rmse = rising
                start = end - len(reverse_scales) + 1
                one_sided.append(FadeShot(
                    left_black=None,
                    start=start,
                    end=end,
                    reference=start,
                    peak=start,
                    right_black=black_run,
                    scales=tuple(
                        float(value) for value in reverse_scales[::-1]),
                    fit_rmse=tuple(
                        float(value) for value in reverse_rmse[::-1]),
                ))

    unambiguous = _drop_overlapping_one_sided(one_sided)
    return tuple(sorted(
        (*complete, *unambiguous), key=lambda shot: (shot.start, shot.end)))
