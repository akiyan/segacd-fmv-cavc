"""Tests for phase-safe adoption and the 64-by-32 rolling plane."""

from __future__ import annotations

import unittest

import numpy as np

import scroll_frames
import scroll_plan


def lunar_segment():
    start, end = 1118, 1335
    deltas = (-5,) * (end - start + 1)
    return scroll_frames.ScrollSegment(
        start=start, end=end, axis="x", deltas=deltas,
        cumulative=tuple(int(value) for value in np.cumsum(deltas)),
        support=.99, residual=2.0, gain=19.0, multiframe_support=.98)


class ScrollPlanTests(unittest.TestCase):
    def test_normal_plane_mapping_keeps_each_row_on_the_64_cell_stride(self):
        self.assertEqual(
            scroll_plan.normal_plane_cells(3, 2),
            (0, 1, 2, 64, 65, 66),
        )

    def test_position_state_matches_the_window_model(self):
        window = scroll_plan.ScrollWindow(
            anchor=0, end=1, axis=scroll_frames.AXIS_HORIZONTAL,
            deltas=(-5,), positions=(0, -5), detector_start=0,
            support=1.0, multiframe_support=1.0, adoption_gain=10.0,
            beneficial_fraction=1.0, overlap_rmse_p95=0.0,
        )
        expected = scroll_plan.frame_state(window, 1, columns=4, rows=2)
        actual = scroll_plan.position_state(
            1,
            scroll_frames.AXIS_HORIZONTAL,
            window.position_at(1),
            columns=4,
            rows=2,
        )
        self.assertEqual(actual, expected)

    def test_positive_motion_guards_the_low_edge(self):
        state = scroll_plan.position_state(
            1, scroll_frames.AXIS_HORIZONTAL, 5, delta=5,
            columns=4, rows=2)
        self.assertEqual(state.world_guard, ((0, -2), (1, -2)))

    def test_lunar_window_is_selected_without_a_time_range(self):
        segment = lunar_segment()
        measurements = {
            frame: scroll_frames.AdoptionMeasurement(
                frame=frame, fixed_changed=900, edge_tiles=28,
                residual_changed=60, scroll_changed=88,
                gain=900 / 88, overlap_rmse=5.0,
                fixed_cost=900.0, residual_cost=60.0, scroll_cost=88.0)
            for frame in range(segment.start, segment.end + 1)
        }
        windows = scroll_plan.select_windows(
            [segment], measurements, fps=24.0)
        self.assertEqual(len(windows), 1)
        window = windows[0]
        self.assertEqual((window.anchor, window.end), (1117, 1333))
        self.assertEqual(window.movements, 216)
        self.assertEqual(window.final_position, -1080)
        self.assertEqual(window.final_position % 8, 0)

    def test_forbidden_frame_splits_or_rejects_a_window(self):
        segment = lunar_segment()
        measurements = {
            frame: scroll_frames.AdoptionMeasurement(
                frame, 900, 28, 40, 68, 10.0, 4.0, 900.0, 40.0, 68.0)
            for frame in range(segment.start, segment.end + 1)
        }
        windows = scroll_plan.select_windows(
            [segment], measurements, fps=24.0,
            forbidden_frames={1300})
        self.assertTrue(all(
            not (window.anchor <= 1300 <= window.end)
            for window in windows))

    def test_horizontal_rolling_plane_matches_pixels_and_rebases(self):
        window = scroll_plan.ScrollWindow(
            anchor=0, end=8, axis="x", deltas=(-5,) * 8,
            positions=tuple(-5 * frame for frame in range(9)),
            detector_start=0, support=1.0, multiframe_support=1.0,
            adoption_gain=10.0, beneficial_fraction=1.0,
            overlap_rmse_p95=0.0)
        patterns = {
            entry: np.full((8, 8), entry, np.int16)
            for entry in range(200)
        }
        plane = scroll_plan.RollingPlane()
        for frame in range(window.anchor, window.end + 1):
            state = scroll_plan.frame_state(
                window, frame, columns=40, rows=28)
            world = (*state.world_primary, *state.world_guard)
            entries = [column % 200 for _row, column in world]
            plane.update(world, entries)
            rendered = plane.render(
                patterns, state, width=320, height=224)
            expected = np.broadcast_to(
                ((np.arange(320) - state.hscroll) // 8 % 200)[None, :],
                (224, 320),
            )
            np.testing.assert_array_equal(rendered, expected)
        final_state = scroll_plan.frame_state(
            window, window.end, columns=40, rows=28)
        rebased = plane.viewport_entries(
            final_state, columns=40, rows=28)
        self.assertEqual(rebased.shape, (28, 40))
        np.testing.assert_array_equal(
            rebased[0], np.arange(5, 45, dtype=np.int64))

    def test_vertical_ring_wrap_is_exact(self):
        window = scroll_plan.ScrollWindow(
            anchor=0, end=8, axis="y", deltas=(4,) * 8,
            positions=tuple(4 * frame for frame in range(9)),
            detector_start=0, support=1.0, multiframe_support=1.0,
            adoption_gain=5.0, beneficial_fraction=1.0,
            overlap_rmse_p95=0.0)
        patterns = {
            entry: np.full((8, 8), entry, np.int16)
            for entry in range(200)
        }
        plane = scroll_plan.RollingPlane()
        for frame in range(9):
            state = scroll_plan.frame_state(
                window, frame, columns=40, rows=28)
            world = (*state.world_primary, *state.world_guard)
            entries = [row % 200 for row, _column in world]
            plane.update(world, entries)
            rendered = plane.render(
                patterns, state, width=320, height=224)
            expected = np.broadcast_to(
                (((np.arange(224) - state.vscroll) // 8) % 200)[:, None],
                (224, 320),
            )
            np.testing.assert_array_equal(rendered, expected)


if __name__ == "__main__":
    unittest.main()
