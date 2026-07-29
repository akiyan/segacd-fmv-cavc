#!/usr/bin/env python3
"""Regression tests for the analysis waveform and spectrum data model."""
from __future__ import annotations

import unittest

import numpy as np

import analysis_audio
import layout_preview as layout


class AnalysisAudioTests(unittest.TestCase):
    def test_audio_panels_split_the_right_column_with_a_gap(self) -> None:
        self.assertEqual(
            layout.WAVE_FRAME,
            (layout.SRC_FRAME[0], 1014, layout.SRC_FRAME[0] + 284, 1064),
        )
        self.assertEqual(layout.SPEC_FRAME[0] - layout.WAVE_FRAME[2], 10)
        self.assertEqual(layout.SPEC_FRAME[2], layout.SRC_FRAME[2])
        self.assertEqual(layout.wave_window_label(30), "1 frame (33ms)")
        self.assertEqual(layout.wave_window_label(15), "1 frame (67ms)")

    def test_one_frame_windows_partition_samples_without_gaps(self) -> None:
        bounds = [
            analysis_audio.frame_sample_bounds(
                frame, fps=30, sample_rate=22_050,
                total_samples=100_000)
            for frame in range(4)
        ]
        self.assertEqual(bounds[0], (0, 735))
        self.assertTrue(all(
            bounds[index][1] == bounds[index + 1][0]
            for index in range(len(bounds) - 1)))

    def test_signed_pcm_is_preserved(self) -> None:
        samples, full_scale = analysis_audio.decode_pcm_mono(
            np.asarray([-32768, -7, 0, 9, 32767], "<i2").tobytes(),
            sample_width=2,
            channels=1,
        )
        self.assertEqual(full_scale, 32768)
        np.testing.assert_array_equal(
            samples, [-32768, -7, 0, 9, 32767])

    def test_waveform_columns_keep_signed_minimum_and_maximum(self) -> None:
        samples = np.asarray([-8, -4, 3, 9, -2, 7, -6, 1], np.int32)
        minima, maxima = analysis_audio.waveform_extrema(
            samples, start=0, stop=8, columns=4)
        np.testing.assert_array_equal(minima, [-8, 3, -2, -6])
        np.testing.assert_array_equal(maxima, [-4, 9, 7, 1])

    def test_spectrum_peaks_in_the_band_containing_a_sine(self) -> None:
        sample_rate = 22_050
        frequency = 1_000
        time = np.arange(4096) / sample_rate
        samples = np.rint(
            np.sin(2 * np.pi * frequency * time) * 30_000).astype(np.int32)
        levels = analysis_audio.spectrum_levels(
            samples,
            sample_rate=sample_rate,
            center_sample=2048,
            full_scale=32768,
        )
        edges = np.geomspace(40.0, 11_025.0, 25)
        expected = int(np.searchsorted(edges, frequency, side="right") - 1)
        self.assertEqual(int(np.argmax(levels)), expected)
        self.assertGreater(float(levels[expected]), 0.9)


if __name__ == "__main__":
    unittest.main()
