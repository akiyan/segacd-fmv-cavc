#!/usr/bin/env python3
"""Tests for exact DEBUG HUD movie-start selection."""

from __future__ import annotations

import unittest
import subprocess
import sys
import textwrap
from pathlib import Path

import analyze
import read_frameno


def group(frame: int, capture: int) -> analyze.FrameGroup:
    return analyze.FrameGroup(
        loop=0,
        capture_first=capture,
        capture_last=capture,
        time_first=capture / 60,
        time_last=capture / 60,
        sample_count=1,
        confidence=1.0,
        values={"frame": frame},
    )


class MovieAnchorTest(unittest.TestCase):
    def test_frame_minus_one_sentinel_wins_over_earlier_plausible_zero(self) -> None:
        raw = [
            group(0, 0), group(1, 1), group(2, 2), group(3, 3),
            group(read_frameno.FRAME_MINUS_ONE, 4),
            group(0, 5), group(1, 6), group(2, 7), group(3, 8),
        ]

        selected = analyze.select_movie_groups(raw, anchor_run=4, max_step=4)
        anchor, used_sentinel = analyze.find_movie_anchor(
            raw, anchor_run=4, max_step=4)

        self.assertEqual(anchor, 5)
        self.assertTrue(used_sentinel)
        self.assertEqual(selected[0].capture_first, 5)
        self.assertEqual(
            [row.values["frame"] for row in selected[:4]], [0, 1, 2, 3])

    def test_legacy_recording_without_sentinel_still_anchors(self) -> None:
        raw = [group(0, 0), group(1, 1), group(2, 2), group(3, 3)]

        selected = analyze.select_movie_groups(raw, anchor_run=4, max_step=4)
        anchor, used_sentinel = analyze.find_movie_anchor(
            raw, anchor_run=4, max_step=4)

        self.assertEqual(anchor, 0)
        self.assertFalse(used_sentinel)
        self.assertEqual(
            [row.values["frame"] for row in selected], [0, 1, 2, 3])


class DecoderDiagnosticsTest(unittest.TestCase):
    def test_stderr_larger_than_a_pipe_does_not_block_frame_reads(self):
        # The decoder writes diagnostics before its first frame. The outer
        # timeout makes the former two-pipe deadlock a bounded test failure.
        script = textwrap.dedent('''
            import sys
            from fractions import Fraction
            from pathlib import Path
            from unittest.mock import patch
            sys.path.insert(0, 'harness/startup_resync')
            import analyze
            real_popen = analyze.subprocess.Popen
            fields = analyze.read_frameno.hud_fields_for_layout(analyze.read_frameno.hud_layout())
            def decoder(command, **kwargs):
                code = "import sys; sys.stderr.write('diagnostic\\\\n' * 32768); sys.stderr.flush(); sys.stdout.buffer.write(bytes(320 * 32))"
                return real_popen([sys.executable, '-c', code], **kwargs)
            probe = analyze.Probe(width=320, height=224, fps=Fraction(60), start_time=0)
            with patch.object(analyze.subprocess, 'Popen', decoder), patch.object(
                analyze.read_frameno, 'read_hud', return_value={key: (0, 1.0) for key in fields}
            ):
                samples = list(analyze.iter_samples(Path('unused'), probe, 0.9, 0))
            assert len(samples) == 1 and samples[0].capture == 0
        ''')
        result = subprocess.run([sys.executable, "-c", script],
                                cwd=Path(__file__).resolve().parents[2],
                                capture_output=True, text=True, timeout=10)
        self.assertEqual(result.returncode, 0, result.stderr)


if __name__ == "__main__":
    unittest.main()
