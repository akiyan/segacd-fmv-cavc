"""Bound long-movie PCM drift without increasing any stream header."""

import sys
import unittest
from fractions import Fraction
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
import av_config


class AudioClockTests(unittest.TestCase):
    def test_short_movies_retain_fixed_frequency(self):
        for fps in (15, 24, 30):
            samples = av_config.audio_frame_layout(fps)[1]
            self.assertEqual(av_config.long_movie_audio_fd_plan(
                samples, fps, 16384), (0, 0, 0))

    def test_65535_frames_cannot_exhaust_pcm_reserve_at_physical_clock(self):
        frames = 65535
        for fps in (15, 24, 30):
            samples = av_config.audio_frame_layout(fps)[1]
            low, step, modulus = av_config.long_movie_audio_fd_plan(samples, fps, frames)
            cadence = av_config.vblank_cadence_pattern(fps)
            phase = 0
            delta_vblanks = 0
            elapsed_vblanks = 0
            for frame in range(frames):
                phase += step
                extra = phase >= modulus
                if extra:
                    phase -= modulus
                interval = cadence[frame % len(cadence)]
                delta_vblanks += (low + extra) * interval
                elapsed_vblanks += interval
            physical_vsync = Fraction(53_693_175, 3420 * 262)
            physical_consumed = (Fraction(12_500_000, 384 * 2048)
                                 * delta_vblanks / physical_vsync)
            # A final short interval at 24fps differs from the long-term
            # average by half a VBlank. Separate that normal phase swing from
            # accumulated frequency error. Core qualification uses its trace;
            # its end-of-frame Blip update is not a truncated-line clock.
            ideal_consumed = Fraction(samples * len(cadence), sum(cadence)) * elapsed_vblanks
            supplied = frames * samples
            with self.subTest(fps=fps):
                self.assertLess(abs(ideal_consumed - physical_consumed), 16)
                self.assertLess(abs(supplied - physical_consumed), samples)
