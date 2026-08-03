#!/usr/bin/env python3
"""Regression tests for frame-aligned GPGX LOGVDP extraction."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


extract = load_module(
    "gpgx_logvdp_extract",
    ROOT / "harness/gpgx_logvdp/extract_frame_tsv.py",
)


def dma(rate: int, capacity: int, remaining: int, pc: int) -> str:
    return (
        "[libretro ERROR] [224(224)][100(100)] "
        f"DMA type 1 ({rate} access/line)(100 cycles left)-> "
        f"{capacity} access ({remaining} remaining) ({pc:x})\n"
    )


def vram(vcounter: int, pc: int) -> str:
    return (
        f"[libretro ERROR] [{vcounter}({vcounter})][100(100)] "
        f"VRAM 0x100 write -> 0x1 ({pc:x})\n"
    )


class GpgxLogvdpFrameTsvTests(unittest.TestCase):
    def setUp(self):
        self.pattern_pc = 0x0D7E
        self.split_pattern_pc = 0x10BC
        self.nt_pc = 0x1338
        self.nt_words = 1192
        self.compact = [
            dma(102, 47, 47, self.pattern_pc),
            dma(102, self.nt_words, self.nt_words, self.nt_pc),
            dma(9, 9, 31, self.pattern_pc),
            dma(102, 22, 22, self.split_pattern_pc),
            dma(102, self.nt_words, self.nt_words, self.nt_pc),
            dma(102, self.nt_words, self.nt_words, self.nt_pc),
        ]

    def test_infers_movie_dma_call_sites(self):
        events = extract.dma_events(self.compact)
        self.assertEqual(
            extract.infer_dma_pcs(events, 3),
            (
                (self.pattern_pc, self.split_pattern_pc),
                self.nt_pc,
                self.nt_words,
                102,
            ),
        )

    def test_accepts_a_complete_first_loop_followed_by_tail_replay(self):
        events = extract.dma_events(
            self.compact + [
                dma(102, self.nt_words, self.nt_words, self.nt_pc),
                dma(102, self.nt_words, self.nt_words, self.nt_pc),
            ]
        )
        self.assertEqual(
            extract.infer_dma_pcs(events, 3),
            (
                (self.pattern_pc, self.split_pattern_pc),
                self.nt_pc,
                self.nt_words,
                102,
            ),
        )
        rows = extract.extract_dma_rows(
            events, 3, (self.pattern_pc, self.split_pattern_pc),
            self.nt_pc, self.nt_words, 102)
        self.assertEqual(len(rows), 3)

    def test_extracts_dma_and_cpu_words_on_the_same_frame_axis(self):
        events = extract.dma_events(self.compact)
        rows = extract.extract_dma_rows(
            events, 3, (self.pattern_pc, self.split_pattern_pc),
            self.nt_pc, self.nt_words, 102)
        full = [
            self.compact[0],
            *[vram(224, self.pattern_pc) for _ in range(47)],
            vram(225, 0x0D90),
            self.compact[1],
            *[vram(227, self.nt_pc) for _ in range(self.nt_words)],
            self.compact[2],
            *[vram(10, self.pattern_pc) for _ in range(9)],
            self.compact[3],
            *[vram(224, self.split_pattern_pc) for _ in range(22)],
            vram(20, 0x0D90),
            *[vram(20, 0x0DFE) for _ in range(16)],
            self.compact[4],
            *[vram(227, self.nt_pc) for _ in range(self.nt_words)],
            self.compact[5],
            *[vram(227, self.nt_pc) for _ in range(self.nt_words)],
        ]
        extract.extract_cpu_rows(
            full, rows, (self.pattern_pc, self.split_pattern_pc),
            self.nt_pc, self.nt_words)

        self.assertEqual(rows[0]["pattern_dma_blank_words"], 47)
        self.assertEqual(rows[0]["pattern_cpu_blank_words"], 1)
        self.assertEqual(rows[1]["pattern_dma_active_words"], 9)
        self.assertEqual(rows[1]["pattern_dma_blank_words"], 22)
        self.assertEqual(rows[1]["pattern_cpu_active_words"], 17)
        self.assertEqual(
            rows[1]["name_table_dma_blank_words"], self.nt_words)
        self.assertEqual(rows[1]["name_table_dma_active_words"], 0)

        hud = [
            {"frame": "0"},
            {"frame": "1"},
            {"frame": "2"},
        ]
        self.assertIsNone(extract.validate_frame_axis(rows, hud))

    def test_keeps_ambiguous_scanout_edge_words_separate(self):
        rows = extract.empty_rows(1)
        extract.extract_cpu_rows(
            [
                vram(223, 0x0D90),
                vram(261, 0x0D90),
                dma(102, self.nt_words, self.nt_words, self.nt_pc),
            ],
            rows,
            (self.pattern_pc,),
            self.nt_pc,
            self.nt_words,
        )
        self.assertEqual(rows[0]["pattern_cpu_boundary_words"], 2)
        self.assertEqual(rows[0]["pattern_cpu_active_words"], 0)
        self.assertEqual(rows[0]["pattern_cpu_blank_words"], 0)


if __name__ == "__main__":
    unittest.main()
