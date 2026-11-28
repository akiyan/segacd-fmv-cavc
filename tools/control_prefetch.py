"""Advance timed control sectors without changing the frozen payload route."""

from dataclasses import dataclass

import numpy as np

import av_config
import cavc_routing
import stream_schedule


SECTOR = cavc_routing.SECTOR_BYTES
# The Sub poll reserves two sectors. Use the smaller APPLY ring of the
# SP-tail diagnostic build, too, for this scheduled occupancy limit.
APPLY_WATERMARK = 32 * 1024 - 2 * SECTOR


def apply_watermark():
    """Return the scheduled APPLY limit of the current resource budget."""
    return min(APPLY_WATERMARK + 2 * SECTOR,
               int(av_config.APPLY_SIZE_KB) * 1024) - 2 * SECTOR


@dataclass(frozen=True)
class PrefetchStats:
    multi_sector_before: int
    multi_sector_after: int
    short_first_sector_before: int
    short_first_sector_after: int
    changed_slots: int
    apply_peak_bytes: int


def _blocking_control_sectors(control, word, prefix, needed):
    """Count the current-slot control sectors blocking frame expansion."""
    required_here = np.maximum(0, needed - (prefix - control))
    return np.where(word, control, required_here)


def _plan(control, word, capacity, before, prefix, needed, blocking, *,
          short_slots, late_first_sector, max_ahead):
    """Optimize delivery with a bounded number of extra sectors per prefix."""
    parents = np.full((len(control), max_ahead + 1), -1, dtype=np.int8)
    scores = {0: (0, 0, 0, 0, 0)}
    for frame in range(1, len(control)):
        following = {}
        weight = 2 if short_slots[frame] else 1
        for previous, score in scores.items():
            for ahead in range(max_ahead + 1):
                if ahead and (frame == 1 or frame == len(control) - 1):
                    continue
                count = int(control[frame]) + ahead - previous
                if not 0 <= count <= capacity[frame]:
                    continue
                if word[frame] and count != control[frame]:
                    continue
                delivered = int(prefix[frame]) + ahead
                if (delivered < needed[frame]
                        or delivered * SECTOR - before[frame] > apply_watermark()):
                    continue
                delivered_before = int(prefix[frame - 1]) + previous
                required_here = count if word[frame] else max(
                    0, int(needed[frame]) - delivered_before)
                if required_here > blocking[frame]:
                    continue
                waits = int(required_here >= 2)
                # Remove multi-sector waits first, then the late first-sector
                # dependency. Break ties with fewer changes and less queue lead.
                candidate = (
                    score[0] + weight * waits,
                    score[1] + waits,
                    score[2] + int(late_first_sector[frame] and required_here == 1),
                    score[3] + int(ahead != previous),
                    score[4] + ahead,
                )
                if ahead not in following or candidate < following[ahead]:
                    following[ahead] = candidate
                    parents[frame, ahead] = previous
        if not following:
            raise AssertionError(f"control prefetch lost frozen route at frame {frame}")
        scores = following

    planned = control.copy()
    ahead = 0
    for frame in range(len(control) - 1, 0, -1):
        previous = int(parents[frame, ahead])
        if previous < 0:
            raise AssertionError(f"control prefetch has no parent at frame {frame}")
        planned[frame] += ahead - previous
        ahead = previous
    return planned


def apply_to_schedule(schedule, *, fps):
    """Advance control in the packer's already-verified simulation schedule."""
    control = np.asarray(schedule["n_ctrl_sec"], dtype=np.int64)
    payload = np.asarray(schedule["n_pay_sec"], dtype=np.int64)
    word = np.asarray(schedule.get("word_stage_sectors", np.zeros_like(control)))
    physical = np.asarray(schedule["fsec"], dtype=np.int64)
    lengths = np.asarray(schedule["blk_len"], dtype=np.int64).copy()
    lengths[0] = 0
    end = np.cumsum(lengths)
    before = end - lengths
    needed = (end + SECTOR - 1) // SECTOR
    prefix = np.cumsum(control)
    blocking = _blocking_control_sectors(control, word, prefix, needed)
    baseline_waits = int(np.count_nonzero(blocking[2:] >= 2))
    baseline_peak = int(np.max(prefix * SECTOR - before))

    short_slots = np.zeros_like(control, dtype=bool)
    late_first_sector = short_slots.copy()
    if av_config.vblank_cadence_pattern(fps) == (2, 3):
        short_slots[1::2] = True
        rate_steps, rate_mod = av_config.cd_sector_rate_steps(fps)
        # In the short interval, a floor-sized slot starts with the lower
        # CD-1x accumulator remainder, so its first sector arrives later.
        late_first_sector = short_slots & (physical == rate_steps[0] // rate_mod) & (word == 0)
        late_first_sector[:2] = False
    baseline_first = int(np.count_nonzero(late_first_sector & (blocking == 1)))
    if (not baseline_waits and not baseline_first) or baseline_peak > apply_watermark():
        return schedule, PrefetchStats(
            baseline_waits, baseline_waits, baseline_first, baseline_first, 0, baseline_peak,
        )

    capacity = np.minimum(
        np.minimum(physical, cavc_routing.FRAME_SECTORS) - payload,
        cavc_routing.MAX_CTRL_SECTORS,
    )
    planned = control
    if baseline_waits:
        planned = _plan(control, word, capacity, before, prefix, needed, blocking,
                        short_slots=short_slots, late_first_sector=np.zeros_like(short_slots),
                        max_ahead=1)

    first_pass_blocking = _blocking_control_sectors(planned, word, np.cumsum(planned), needed)
    short_first_before = int(np.count_nonzero(late_first_sector & (first_pass_blocking == 1)))
    short_first_after = short_first_before
    max_ahead = 1
    if short_first_before:
        # Keep each frame's blocking limit from the first pass. The two-sector
        # bound is measured from the frozen route and includes its existing lead.
        candidate = _plan(control, word, capacity, before, prefix, needed, first_pass_blocking,
                          short_slots=short_slots, late_first_sector=late_first_sector,
                          max_ahead=2)
        candidate_blocking = _blocking_control_sectors(candidate, word, np.cumsum(candidate), needed)
        remaining = int(np.count_nonzero(late_first_sector & (candidate_blocking == 1)))
        if remaining < short_first_before:
            planned = candidate
            short_first_after = remaining
            max_ahead = 2

    changed_slots = int(np.count_nonzero(planned != control))
    if not changed_slots:
        return schedule, PrefetchStats(
            baseline_waits, baseline_waits, short_first_before, short_first_after, 0, baseline_peak,
        )

    # Verify the materialized route by recomputing the physical CD clock and
    # the control byte prefixes. Word-prefix sectors retain their exact slots.
    fsec, _, rate_lead = stream_schedule.rate_match_sectors(payload, planned, fps=fps)
    if not np.array_equal(fsec, physical) or np.any(rate_lead):
        raise AssertionError("control prefetch changed physical CD slot timing")
    for pay, count, stage in zip(payload, planned, word, strict=True):
        cavc_routing.encode_route(pay, count, stage)
    planned_prefix = np.cumsum(planned)
    credit = planned_prefix - prefix
    if (np.any(planned[:2] != control[:2]) or credit[-1] != 0
            or np.any((credit < 0) | (credit > max_ahead))
            or np.any(planned[word != 0] != control[word != 0])):
        raise AssertionError("control prefetch changed a protected route boundary")
    delivered_bytes = planned_prefix * SECTOR
    margin = delivered_bytes - end
    apply_peak = int(np.max(delivered_bytes - before))
    if np.any(margin < 0) or apply_peak > apply_watermark():
        raise AssertionError("control prefetch violates a deadline or APPLY capacity")
    planned_blocking = _blocking_control_sectors(planned, word, planned_prefix, needed)
    if np.any(planned_blocking > first_pass_blocking) or np.any(planned_blocking > blocking):
        raise AssertionError("control prefetch delayed a control block")

    # Useful Prg/Word bytes may end in different slots, so keep their proven
    # per-slot counts instead of treating them as one continuous payload.
    useful_control = np.diff(np.minimum(delivered_bytes, end[-1]), prepend=0)
    useful_payload = np.asarray(schedule["body_useful_payload_bytes"], dtype=np.int64)
    rate_pad = (physical - payload - planned) * SECTOR
    stream_pad = (payload + planned) * SECTOR - useful_control - useful_payload
    if np.any(rate_pad < 0) or np.any(stream_pad < 0):
        raise AssertionError("control prefetch produced invalid BODY padding")
    updated = dict(
        schedule,
        n_ctrl_sec=planned,
        ctrl_min=int(margin.min()),
        body_useful_control_bytes=useful_control,
        body_pad_bytes=rate_pad + stream_pad,
        body_rate_pad_bytes=rate_pad,
        body_stream_pad_bytes=stream_pad,
    )
    return updated, PrefetchStats(
        baseline_waits, int(np.count_nonzero(planned_blocking[2:] >= 2)),
        short_first_before, short_first_after,
        changed_slots, apply_peak,
    )
