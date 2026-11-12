"""Independent log fixture for DMA command starts versus continued transfers."""
import tempfile
import unittest
from pathlib import Path

from check_trace import active_dma_starts


class ActiveStartsTest(unittest.TestCase):
    def test_blank_crossing_and_repair_are_not_new_active_commands(self):
        trace = """[224(224)][0(0)] DMA type 1 (102 access/line)(100 cycles left)-> 100 access (20 remaining) (ff1234)
[260(254)][0(0)] DMA type 1 (102 access/line)(100 cycles left)-> 3 access (8 remaining) (ff2222)
[0(0)][0(0)] DMA type 1 (9 access/line)(100 cycles left)-> 9 access (5 remaining) (ff2222)
[1(1)][0(0)] VRAM 0x0020 write -> 0x0000 (ff2222)
[7(7)][0(0)] DMA type 1 (9 access/line)(100 cycles left)-> 4 access (10 remaining) (ff2222)
[8(8)][0(0)] DMA type 1 (9 access/line)(100 cycles left)-> 9 access (6 remaining) (ff2222)
[224(224)][0(0)] DMA type 1 (102 access/line)(100 cycles left)-> 100 access (20 remaining) (ff1234)
"""
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "compact.log"
            path.write_text(trace)
            self.assertEqual(active_dma_starts(path, 0x1234, [20, 20]),
                             [dict(frame=1, line=7, words=10)])
            path.write_text(trace.replace("(5 remaining)", "(4 remaining)"))
            with self.assertRaisesRegex(ValueError, "discontinuous DMA"):
                active_dma_starts(path, 0x1234, [20, 20])


if __name__ == "__main__":
    unittest.main()
