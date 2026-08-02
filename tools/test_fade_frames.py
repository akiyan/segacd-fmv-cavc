from __future__ import annotations

import unittest

import numpy as np

import fade_frames


def spatial_image(seed: int, samples: int = 24) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.uniform(30, 235, (samples, 3))


def fade_frame(base: np.ndarray, scale: float, black: float = 6.0) -> np.ndarray:
    return black + scale * (base - black)


class FadeFrameTests(unittest.TestCase):
    def test_detects_repeated_static_black_fades_without_a_range(self) -> None:
        black = np.full((24, 3), 6.0)
        first = spatial_image(1)
        second = spatial_image(2)
        probes = np.stack([
            black,
            fade_frame(first, 0.60), first, first, fade_frame(first, 0.44),
            black,
            fade_frame(second, 0.62), second, second, fade_frame(second, 0.45),
            black,
        ])
        dark = np.asarray([1.0, *([0.0] * 4), 1.0, *([0.0] * 4), 1.0])

        shots = fade_frames.detect_fade_shots(probes, dark)

        self.assertEqual(len(shots), 2)
        self.assertEqual(
            (shots[0].anchor, shots[0].start, shots[0].end,
             shots[0].reference, shots[0].right_black.start),
            (0, 1, 4, 3, 5),
        )
        self.assertEqual(
            (shots[1].anchor, shots[1].start, shots[1].end,
             shots[1].reference, shots[1].right_black.start),
            (5, 6, 9, 8, 10),
        )
        self.assertAlmostEqual(shots[0].scales[0], 0.60, places=6)
        self.assertAlmostEqual(shots[0].scales[-1], 0.44, places=6)

    def test_rejects_motion_between_black_frames(self) -> None:
        black = np.full((24, 3), 6.0)
        probes = np.stack([
            black,
            fade_frame(spatial_image(1), 0.6),
            spatial_image(2),
            spatial_image(3),
            fade_frame(spatial_image(4), 0.5),
            black,
        ])
        dark = np.asarray([1.0, 0.0, 0.0, 0.0, 0.0, 1.0])
        self.assertEqual(fade_frames.detect_fade_shots(probes, dark), ())

    def test_rejects_a_static_hard_cut_without_brightness_ramps(self) -> None:
        black = np.full((24, 3), 6.0)
        image = spatial_image(1)
        probes = np.stack([black, image, image, image, black])
        dark = np.asarray([1.0, 0.0, 0.0, 0.0, 1.0])
        self.assertEqual(fade_frames.detect_fade_shots(probes, dark), ())

    def test_validates_shapes(self) -> None:
        with self.assertRaisesRegex(ValueError, "shape"):
            fade_frames.detect_fade_shots(np.zeros((3, 4)), np.zeros(3))
        with self.assertRaisesRegex(ValueError, "equal frame counts"):
            fade_frames.detect_fade_shots(np.zeros((3, 4, 3)), np.zeros(2))

    def test_segment_capacity_keeps_a_connected_group_atomic(self) -> None:
        black = np.full((24, 3), 6.0)
        first = spatial_image(1)
        second = spatial_image(2)
        probes = np.stack([
            black,
            fade_frame(first, 0.6), first, first, fade_frame(first, 0.4),
            black,
            fade_frame(second, 0.6), second, second, fade_frame(second, 0.4),
            black,
            spatial_image(3),
        ])
        dark = np.asarray([1.0, *([0.0] * 4), 1.0, *([0.0] * 4), 1.0, 0.0])
        shots = fade_frames.detect_fade_shots(probes, dark)
        self.assertEqual(len(shots), 2)
        # Existing segment 0 plus anchors 0/5 and restoration 11 need three
        # total segments.  A capacity of two skips the whole connected group.
        self.assertEqual(
            fade_frames.select_groups_with_segment_capacity(
                shots, [0], frame_count=len(probes), max_segments=2),
            (),
        )
        self.assertEqual(
            fade_frames.select_groups_with_segment_capacity(
                shots, [0], frame_count=len(probes), max_segments=3),
            shots,
        )

    def test_scaled_palette_keeps_debug_endpoints(self) -> None:
        palette = np.arange(4 * 15 * 3, dtype=np.uint8).reshape(4, 15, 3) % 8
        dark = fade_frames.scaled_palette(palette, 0.0)
        np.testing.assert_array_equal(dark[0, 0], palette[0, 0])
        np.testing.assert_array_equal(dark[0, 14], palette[0, 14])
        mask = np.ones((4, 15), bool)
        mask[0, (0, 14)] = False
        self.assertFalse(dark[mask].any())

    def test_layout_prepares_each_image_on_the_shared_black_frame(self) -> None:
        black = np.full((24, 3), 6.0)
        first = spatial_image(1)
        second = spatial_image(2)
        probes = np.stack([
            black,
            fade_frame(first, 0.6), first, first, fade_frame(first, 0.4),
            black,
            fade_frame(second, 0.6), second, second, fade_frame(second, 0.4),
            black,
            spatial_image(3),
        ])
        dark = np.asarray([1.0, *([0.0] * 4), 1.0, *([0.0] * 4), 1.0, 0.0])
        shots = fade_frames.detect_fade_shots(probes, dark)
        layout = fade_frames.build_layout(
            shots, np.zeros(len(probes), np.int32), max_segments=3)

        self.assertEqual(layout.anchors, (0, 5))
        self.assertEqual(layout.preparation_frames, (0, 5))
        self.assertEqual(layout.restorations, (11,))
        self.assertEqual(layout.entry_scales, (0.0, 0.0, 1.0))
        self.assertEqual(layout.frame_segments.tolist(), [
            0, 0, 0, 0, 0,
            1, 1, 1, 1, 1, 1,
            2,
        ])
        self.assertEqual(layout.reference_frames[0], shots[0].reference)
        self.assertEqual(layout.reference_frames[5], shots[1].reference)
        self.assertTrue(np.isnan(layout.desired_scales[5]))
        self.assertEqual(layout.desired_scales[10], 0.0)
        self.assertEqual(layout.phases[10], 2)

    def test_layout_uses_every_frame_in_a_multi_frame_black_run(self) -> None:
        black = np.full((24, 3), 6.0)
        image = spatial_image(4)
        probes = np.stack([
            black,
            black,
            fade_frame(image, 0.5),
            image,
            fade_frame(image, 0.5),
            black,
        ])
        dark = np.asarray([1.0, 1.0, 0.0, 0.0, 0.0, 1.0])
        shots = fade_frames.detect_fade_shots(probes, dark)
        self.assertEqual(len(shots), 1)
        layout = fade_frames.build_layout(
            shots, np.zeros(len(probes), np.int32), max_segments=2)
        self.assertEqual(layout.anchors, (0,))
        self.assertEqual(layout.preparation_frames, (0, 1))
        np.testing.assert_array_equal(
            layout.reference_frames[:2],
            np.full(2, shots[0].reference, np.int32),
        )


if __name__ == "__main__":
    unittest.main()
