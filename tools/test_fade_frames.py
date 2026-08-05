from __future__ import annotations

import unittest

import numpy as np

import fade_frames


def spatial_image(seed: int, samples: int = 24) -> np.ndarray:
    rng = np.random.default_rng(seed)
    return rng.uniform(30, 235, (samples, 3))


def fade_frame(base: np.ndarray, scale: float, black: float = 6.0) -> np.ndarray:
    return black + scale * (base - black)


def detect_fade_shots(probes, dark, **kwargs):
    return fade_frames.detect_fade_shots(
        probes, dark, spatial_shape=(4, 6), **kwargs)


class FadeFrameTests(unittest.TestCase):
    def test_detects_fade_in_without_a_later_black_run(self) -> None:
        black = np.full((24, 3), 6.0)
        image = spatial_image(10)
        probes = np.stack([
            black,
            fade_frame(image, 0.34),
            fade_frame(image, 0.65),
            image,
            image,
            spatial_image(11),
            spatial_image(12),
        ])
        dark = np.asarray([1.0, *([0.0] * 6)])

        shots = detect_fade_shots(probes, dark)

        self.assertEqual(len(shots), 1)
        shot = shots[0]
        self.assertEqual(shot.kind, "in")
        self.assertEqual(
            (shot.anchor, shot.start, shot.end, shot.reference, shot.peak),
            (0, 1, 4, 4, 4),
        )
        self.assertIsNone(shot.right_black)
        self.assertAlmostEqual(shot.scales[0], 0.34, places=6)
        self.assertAlmostEqual(shot.scales[-1], 1.0, places=6)

    def test_detects_fade_out_without_an_earlier_black_run(self) -> None:
        black = np.full((24, 3), 6.0)
        image = spatial_image(20)
        probes = np.stack([
            image,
            image,
            fade_frame(image, 0.66),
            fade_frame(image, 0.33),
            black,
            black,
            spatial_image(21),
        ])
        dark = np.asarray([*([0.0] * 4), 1.0, 1.0, 0.0])

        shots = detect_fade_shots(probes, dark)

        self.assertEqual(len(shots), 1)
        shot = shots[0]
        self.assertEqual(shot.kind, "out")
        self.assertEqual(
            (shot.anchor, shot.start, shot.end, shot.reference, shot.peak),
            (0, 0, 3, 0, 0),
        )
        self.assertIsNone(shot.left_black)
        self.assertAlmostEqual(shot.scales[0], 1.0, places=6)
        self.assertAlmostEqual(shot.scales[-1], 0.33, places=6)

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

        shots = detect_fade_shots(probes, dark)

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
        self.assertEqual(detect_fade_shots(probes, dark), ())

    def test_rejects_a_static_hard_cut_without_brightness_ramps(self) -> None:
        black = np.full((24, 3), 6.0)
        image = spatial_image(1)
        probes = np.stack([black, image, image, image, black])
        dark = np.asarray([1.0, 0.0, 0.0, 0.0, 1.0])
        self.assertEqual(detect_fade_shots(probes, dark), ())

    def test_rejects_a_temporary_black_frame_between_hard_cuts(self) -> None:
        black = np.full((24, 3), 6.0)
        first = spatial_image(30)
        second = spatial_image(31)
        probes = np.stack([
            first, first, first,
            black,
            second, second, second,
        ])
        dark = np.asarray([0.0, 0.0, 0.0, 1.0, 0.0, 0.0, 0.0])
        self.assertEqual(detect_fade_shots(probes, dark), ())

    def test_rejects_a_mildly_changing_dark_scene(self) -> None:
        black = np.full((24, 3), 6.0)
        image = spatial_image(32) * 0.12 + 8.0
        probes = np.stack([
            black,
            fade_frame(image, 0.90),
            image,
            fade_frame(image, 0.95),
            spatial_image(33) * 0.12 + 8.0,
        ])
        dark = np.asarray([1.0, 0.6, 0.5, 0.55, 0.5])
        self.assertEqual(detect_fade_shots(probes, dark), ())

    def test_rejects_a_brightness_ramp_with_spatial_motion(self) -> None:
        black = np.full((24, 3), 6.0)
        image = spatial_image(34).reshape(4, 6, 3)
        probes = np.stack([
            black,
            fade_frame(np.roll(image, 1, axis=1), 0.40).reshape(24, 3),
            fade_frame(np.roll(image, 1, axis=0), 0.70).reshape(24, 3),
            image.reshape(24, 3),
        ])
        dark = np.asarray([1.0, 0.0, 0.0, 0.0])
        self.assertEqual(
            detect_fade_shots(probes, dark, maximum_rmse=255.0), ())

    def test_validates_shapes(self) -> None:
        with self.assertRaisesRegex(ValueError, "shape"):
            detect_fade_shots(np.zeros((3, 4)), np.zeros(3))
        with self.assertRaisesRegex(ValueError, "equal frame counts"):
            detect_fade_shots(np.zeros((3, 4, 3)), np.zeros(2))
        with self.assertRaisesRegex(ValueError, "spatial shape"):
            fade_frames.detect_fade_shots(
                np.zeros((3, 24, 3)), np.zeros(3), spatial_shape=(5, 5))

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
        shots = detect_fade_shots(probes, dark)
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
        shots = detect_fade_shots(probes, dark)
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
        shots = detect_fade_shots(probes, dark)
        self.assertEqual(len(shots), 1)
        layout = fade_frames.build_layout(
            shots, np.zeros(len(probes), np.int32), max_segments=2)
        self.assertEqual(layout.anchors, (0,))
        self.assertEqual(layout.preparation_frames, (0, 1))
        np.testing.assert_array_equal(
            layout.reference_frames[:2],
            np.full(2, shots[0].reference, np.int32),
        )

    def test_layout_connects_one_sided_fades_to_ordinary_frames(self) -> None:
        black = np.full((24, 3), 6.0)
        first = spatial_image(40)
        second = spatial_image(41)
        probes = np.stack([
            black,
            fade_frame(first, 0.35),
            fade_frame(first, 0.65),
            first,
            second,
            fade_frame(second, 0.65),
            fade_frame(second, 0.35),
            black,
        ])
        dark = np.asarray([1.0, *([0.0] * 6), 1.0])
        shots = detect_fade_shots(probes, dark)
        self.assertEqual([shot.kind for shot in shots], ["in", "out"])

        layout = fade_frames.build_layout(
            shots, np.zeros(len(probes), np.int32), max_segments=4)

        self.assertEqual(layout.anchors, (0, 4))
        self.assertEqual(layout.preparation_frames, (0, 4))
        self.assertEqual(layout.preparation_deadlines, (0, 4))
        self.assertEqual(layout.restorations, (4,))
        self.assertEqual(layout.entry_scales, (0.0, 1.0))
        self.assertEqual(layout.frame_segments.tolist(), [
            0, 0, 0, 0,
            1, 1, 1, 1,
        ])
        self.assertTrue(np.isnan(layout.desired_scales[0]))
        self.assertEqual(layout.phases[1:4].tolist(), [1, 1, 1])
        self.assertTrue(np.isnan(layout.desired_scales[4]))
        self.assertEqual(layout.phases[5:].tolist(), [2, 2, 2])


class BlackSampleEvidenceTests(unittest.TestCase):
    def test_faint_title_card_is_not_swallowed_by_a_black_run(self) -> None:
        # A title card: near-zero frame mean, 98%+ dark pixels, but two tile
        # samples carry bright text. It must become content beside the black
        # runs, and its own brightness ramp then forms a complete fade shot.
        base = np.zeros((24, 3))
        title = base.copy()
        title[3] = 150.0
        title[11] = 120.0
        probes = np.stack([
            base, base,
            fade_frame(title, 0.4, black=0.0),
            fade_frame(title, 0.7, black=0.0),
            title, title, title,
            fade_frame(title, 0.7, black=0.0),
            fade_frame(title, 0.4, black=0.0),
            base, base,
        ])
        dark = np.asarray([1.0, 1.0, *([0.985] * 7), 1.0, 1.0])
        shots = detect_fade_shots(probes, dark)
        self.assertEqual([shot.kind for shot in shots], ["in_out"])
        shot = shots[0]
        self.assertEqual(shot.left_black.end, 1)
        self.assertEqual(shot.right_black.start, 9)
        self.assertEqual(shot.start, 2)
        self.assertEqual(shot.end, 8)
        self.assertIn(shot.reference, range(4, 7))

    def test_residual_glow_still_counts_as_black(self) -> None:
        # A fade tail's dim glow (well under black_sample_max) must keep its
        # black-run membership so real fades keep their preparation windows.
        glow = np.zeros((24, 3))
        glow[5] = 30.0
        first = spatial_image(21)
        probes = np.stack([
            glow, glow, glow,
            fade_frame(first, 0.35),
            fade_frame(first, 0.65),
            first,
        ])
        dark = np.asarray([1.0, 1.0, 1.0, 0.0, 0.0, 0.0])
        shots = detect_fade_shots(probes, dark)
        self.assertEqual([shot.kind for shot in shots], ["in"])
        self.assertEqual(shots[0].left_black.end, 2)


class OverlayShotTargetTests(unittest.TestCase):
    def _detected_layout(self):
        first = spatial_image(11)
        second = spatial_image(12)
        black = fade_frame(first, 0.0)
        probes = np.stack([
            black,
            fade_frame(first, 0.35),
            fade_frame(first, 0.65),
            first,
            black,
            second,
            fade_frame(second, 0.65),
            fade_frame(second, 0.35),
            black,
        ])
        dark = np.asarray([1.0, *([0.0] * 3), 1.0, *([0.0] * 3), 1.0])
        shots = detect_fade_shots(probes, dark)
        layout = fade_frames.build_layout(
            shots, np.zeros(len(probes), np.int32), max_segments=6)
        return shots, layout, len(probes)

    def test_overlay_matches_the_layout_for_the_same_shots(self) -> None:
        shots, layout, count = self._detected_layout()
        (references, desired, phases,
         preparation_frames,
         preparation_deadlines) = fade_frames.overlay_shot_targets(
            layout.shots, count)
        np.testing.assert_array_equal(references, layout.reference_frames)
        np.testing.assert_array_equal(phases, layout.phases)
        np.testing.assert_array_equal(
            np.isnan(desired), np.isnan(layout.desired_scales))
        finite = ~np.isnan(desired)
        np.testing.assert_allclose(
            desired[finite], layout.desired_scales[finite])
        self.assertEqual(preparation_frames, layout.preparation_frames)
        self.assertEqual(preparation_deadlines, layout.preparation_deadlines)

    def test_overlay_of_a_subset_drops_only_that_shot(self) -> None:
        shots, layout, count = self._detected_layout()
        self.assertGreaterEqual(len(layout.shots), 2)
        kept = tuple(
            shot for shot in layout.shots if shot.kind != "out")
        (references, _desired, phases,
         preparation_frames,
         _deadlines) = fade_frames.overlay_shot_targets(kept, count)
        dropped = [
            shot for shot in layout.shots if shot.kind == "out"]
        self.assertTrue(dropped)
        for shot in dropped:
            for frame in range(shot.start, shot.end + 1):
                self.assertEqual(int(references[frame]), -1)
                self.assertEqual(int(phases[frame]), 0)
                self.assertNotIn(frame, preparation_frames)
        for shot in kept:
            self.assertEqual(
                int(references[shot.preparation_end]), shot.reference)

    def test_overlay_of_no_shots_is_empty(self) -> None:
        references, desired, phases, frames, deadlines = (
            fade_frames.overlay_shot_targets((), 5))
        self.assertTrue(np.all(references == -1))
        self.assertTrue(np.all(np.isnan(desired)))
        self.assertTrue(np.all(phases == 0))
        self.assertEqual(frames, ())
        self.assertEqual(deadlines, ())


if __name__ == "__main__":
    unittest.main()
