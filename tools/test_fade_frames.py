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


if __name__ == "__main__":
    unittest.main()
