"""Tests for automatic axis-only scroll detection and adoption."""

from __future__ import annotations

import unittest

import numpy as np

import scroll_frames


def textured(seed=1, height=128, width=192):
    rng = np.random.default_rng(seed)
    base = rng.integers(0, 256, (height, width, 3), dtype=np.uint8)
    # Neighbour averaging keeps coherent image detail without making integer
    # shifts ambiguous on the detector's four-pixel sampling lattice.
    return ((
        base.astype(np.uint16)
        + np.roll(base, 1, axis=0).astype(np.uint16)
        + np.roll(base, 1, axis=1).astype(np.uint16)
    ) // 3).astype(np.uint8)


def translate(image, dx=0, dy=0, fill=0):
    out = np.full_like(image, fill)
    x0 = max(0, dx)
    x1 = min(image.shape[1], image.shape[1] + dx)
    y0 = max(0, dy)
    y1 = min(image.shape[0], image.shape[0] + dy)
    out[y0:y1, x0:x1] = image[y0 - dy:y1 - dy, x0 - dx:x1 - dx]
    return out


class ScrollFrameTests(unittest.TestCase):
    def test_detects_horizontal_motion_with_foreground_occlusion(self):
        previous = textured()
        current = translate(previous, dx=-5)
        current[32:64, 72:112] = 255
        result = scroll_frames.estimate_motion(
            previous, current, backend="cpu")
        self.assertTrue(result.accepted)
        self.assertEqual((result.axis, result.delta), ("x", -5))
        self.assertGreater(result.gain, 2.0)

    def test_detects_vertical_motion(self):
        previous = textured(seed=2)
        current = translate(previous, dy=4)
        result = scroll_frames.estimate_motion(
            previous, current, backend="cpu")
        self.assertTrue(result.accepted)
        self.assertEqual((result.axis, result.delta), ("y", 4))

    def test_rejects_static_fade_cut_and_local_motion(self):
        previous = textured(seed=3)
        cases = {
            "static": previous.copy(),
            "fade": np.rint(previous.astype(np.float32) * 0.55).astype(np.uint8),
            "cut": textured(seed=4),
            "local": previous.copy(),
        }
        cases["local"][24:88, 64:128] = translate(
            previous, dx=9)[24:88, 64:128]
        for name, current in cases.items():
            with self.subTest(name=name):
                result = scroll_frames.estimate_motion(
                    previous, current, backend="cpu")
                self.assertFalse(result.accepted)

    def test_temporal_grouping_bridges_hold_but_resets_at_cut(self):
        rows = []
        for frame in range(1, 14):
            accepted = frame != 6
            rows.append(scroll_frames.MotionEstimate(
                frame=frame, axis="x" if accepted else "none",
                delta=-5 if accepted else 0,
                support=.8 if accepted else 0.0,
                residual=2.0, zero_residual=2.0 if frame == 6 else 20.0,
                gain=10.0,
                runner_up_margin=.5, valid_blocks=50,
                accepted=accepted, cut=False,
            ))
        rows.append(scroll_frames.MotionEstimate(
            frame=14, axis="none", delta=0, support=0.0,
            residual=60.0, zero_residual=70.0, gain=1.1,
            runner_up_margin=0.0, valid_blocks=50,
            accepted=False, cut=True,
        ))
        segments = scroll_frames.build_segments(rows)
        self.assertEqual(len(segments), 1)
        self.assertEqual((segments[0].start, segments[0].end), (1, 13))
        self.assertEqual(segments[0].deltas[5], 0)

    def test_adoption_counts_edge_and_residual_separately(self):
        previous = textured(seed=5)
        current = translate(previous, dx=-5)
        measurement = scroll_frames.measure_adoption(
            previous, current, frame=1, axis="x", delta=-5,
            tile_rmse_threshold=4.0)
        self.assertEqual(measurement.edge_tiles, previous.shape[0] // 8)
        self.assertEqual(measurement.residual_changed, 0)
        self.assertGreater(measurement.gain, 5.0)
        segment = scroll_frames.ScrollSegment(
            start=1, end=1, axis="x", deltas=(-5,), cumulative=(-5,),
            support=1.0, residual=0.0, gain=10.0, multiframe_support=1.0)
        self.assertTrue(scroll_frames.adopt_segment(segment, [measurement]))


if __name__ == "__main__":
    unittest.main()
