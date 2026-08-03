#!/usr/bin/env python3
"""Regression tests for saved single-name-table aggregate comparisons."""

from __future__ import annotations

import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def load_comparator():
    path = ROOT / "harness/single_name_table/compare_aggregates.py"
    spec = importlib.util.spec_from_file_location(
        "single_nt_aggregate_compare", path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


comparator = load_comparator()


class SingleNameTableAggregateCompareTests(unittest.TestCase):
    def test_report_supplements_and_overrides_pipeline_log(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            log = Path(tmp) / "pipeline.log"
            report = Path(tmp) / "report.txt"
            log.write_text(
                "physical budget final: minimum cumulative spare=1 sectors\n"
                "VRAM_tiles=1535  L3(PRG-RAM)_tiles=0\n",
                encoding="utf-8",
            )
            report.write_text(
                "VRAM_tiles=1663  L3(PRG-RAM)_tiles=0\n"
                "starved_frames=2 (50.0%)\n",
                encoding="utf-8",
            )

            lines = comparator.summary_lines([log, report])

            self.assertIn("minimum cumulative spare=1", lines[
                "physical budget final:"])
            self.assertTrue(lines["VRAM_tiles="].startswith(
                "VRAM_tiles=1663"))
            self.assertEqual(lines["starved_frames="],
                             "starved_frames=2 (50.0%)")

    def test_tsv_comparison_covers_movie_and_timed_scopes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            main = Path(tmp) / "main.tsv"
            candidate = Path(tmp) / "candidate.tsv"
            main.write_text(
                "frame\tvalue\tlabel\n0\t1\ta\n1\t2\tb\n2\t3\tb\n",
                encoding="utf-8",
            )
            candidate.write_text(
                "frame\tvalue\tlabel\n0\t2\ta\n1\t3\tb\n2\t4\tc\n",
                encoding="utf-8",
            )
            output = []

            comparator.compare_tsv(
                output,
                source_name="fixture",
                main_path=main,
                candidate_path=candidate,
            )

            indexed = {
                (row["scope"], row["metric"], row["statistic"]): row
                for row in output
            }
            self.assertEqual(
                indexed[("movie", "value", "sum")]["main_value"], "6")
            self.assertEqual(
                indexed[("movie", "value", "sum")]["candidate_value"], "9")
            self.assertEqual(
                indexed[("timed", "value", "sum")]["main_value"], "5")
            self.assertEqual(
                indexed[("timed", "value", "sum")]["candidate_value"], "7")
            self.assertEqual(
                indexed[("movie", "label", "unique_values")]["comparison"],
                "changed",
            )

    def test_starved_count_and_percent_are_numeric(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            main = Path(tmp) / "main.log"
            candidate = Path(tmp) / "candidate.log"
            main.write_text("starved_frames=8 (80.0%)\n", encoding="utf-8")
            candidate.write_text(
                "starved_frames=6 (60.0%)\n", encoding="utf-8")
            output = []

            comparator.compare_sim_log(output, [main], [candidate])

            indexed = {row["metric"]: row for row in output}
            self.assertEqual(indexed[
                "starved_frames.starved_frames"]["delta"], "-2")
            self.assertEqual(indexed[
                "starved_frames.starved_percent"]["delta"], "-20")


if __name__ == "__main__":
    unittest.main()
