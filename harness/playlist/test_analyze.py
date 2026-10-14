"""Dispatcher evidence must fail closed on missing or reordered visits."""
import unittest

import analyze


class Markers(unittest.TestCase):
    manifest = {"trace_pc_start": 0xFF0600, "trace_pc_end": 0xFF0640,
                "items": [{"id": "a"}, {"id": "b"}]}

    def marker(self, index, cycle, visit):
        words = [0x504C, 0x5354, index, cycle >> 16, cycle & 65535,
                 visit >> 16, visit & 65535, 0x454E]
        return [f"VRAM 0x{i * 2:X} write -> 0x{word:X} (FF0620)\n"
                for i, word in enumerate(words)]

    def test_wrap_with_unrelated_player_writes(self):
        lines = self.marker(0, 0, 1) + ["VRAM 0x0 write -> 0x1234 (FF1000)\n"]
        lines += self.marker(1, 0, 2) + self.marker(0, 1, 3)
        result = analyze.read_markers(lines, self.manifest)
        self.assertEqual([(v["index"], v["cycle"], v["visit"]) for v in result],
                         [(0, 0, 1), (1, 0, 2), (0, 1, 3)])

    def test_missing_reordered_or_truncated_evidence(self):
        for lines in [[], self.marker(0, 0, 1)[:-1], self.marker(1, 0, 1),
                      self.marker(0, 0, 1) + self.marker(0, 1, 3),
                      self.marker(0, 0, 1) + self.marker(1, 1, 2)]:
            with self.subTest(lines=lines), self.assertRaises(ValueError):
                analyze.read_markers(lines, self.manifest)

    def test_corrupt_marker_signature(self):
        lines = self.marker(0, 0, 1)
        lines[0] = lines[0].replace("504C", "504D")
        with self.assertRaisesRegex(ValueError, "signature"):
            analyze.read_markers(lines, self.manifest)


if __name__ == "__main__":
    unittest.main()
