"""Exercise the exact pack guard, including required lists with no speed gain."""
import ast
import inspect
from pathlib import Path
import sys
import types
import unittest

import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'tools'))
sys.path.insert(0, str(Path(__file__).parent))
import pack_stream
import shadow_updates
import stream_schedule
from pack_validation import install


class ScrollListValidation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = inspect.getsource(pack_stream.main)
        cls.pack = types.ModuleType('isolated_pack')
        cls.pack.__dict__.update(pack_stream.__dict__)
        install(cls.pack)
        cls.corrected = inspect.getsource(cls.pack.main)

    def guard(self, source, kinds, cells, selected):
        costs = [shadow_updates.frame_cost(c, 2048 if k == 3 else 896)
                 for k, c in zip(kinds, cells)]
        scope = dict(np=np, shadow_updates=shadow_updates,
                     frame_types=np.asarray(kinds), update_lists=np.asarray(selected),
                     recomputed_list=np.array([c.list_cycles for c in costs]),
                     recomputed_legacy=np.array([c.legacy_cycles for c in costs]))
        body = ast.parse(source).body[0].body
        index = next(i for i, node in enumerate(body)
                     if isinstance(node, ast.If)
                     and 'selected shadow list is not faster' in ast.unparse(node))
        nodes = body[index-1:index+1] if isinstance(body[index-1], ast.Assign) else body[index:index+1]
        module = ast.fix_missing_locations(ast.Module(body=nodes, type_ignores=[]))
        exec(compile(module, '<actual-pack-guard>', 'exec'), scope)

    def test_dense_scroll_reproduces_failure_and_is_accepted(self):
        cells = [[], list(range(896)), []]
        kinds = [0, 3, 0]
        plan = stream_schedule.select_shadow_update_lists(
            cells, np.zeros(3, np.int64), np.zeros(3, np.int64), cells=896,
            fps=30, ring_capacity_patterns=128, prebuffer_capacity_patterns=64,
            frame_sectors=3, audio_frame_bytes=16, frame_types=kinds)
        self.assertTrue(plan['selected'][1])
        self.assertLessEqual(plan['costs'][1].saved_cycles, 0)
        with self.assertRaisesRegex(SystemExit, 'not faster at frame 1'):
            self.guard(self.original, kinds, cells, plan['selected'])
        self.guard(self.corrected, kinds, cells, plan['selected'])

    def test_scroll_without_changed_cells_still_requires_its_position_item(self):
        kinds, cells, flags = [0, 3], [[], []], [False, True]
        with self.assertRaisesRegex(SystemExit, 'not faster at frame 1'):
            self.guard(self.original, kinds, cells, flags)
        self.guard(self.corrected, kinds, cells, flags)
        raw = shadow_updates.encode_count(0, True, shadow_updates.FRAME_SCROLL)
        self.assertEqual(shadow_updates.decode_count(raw), (0, True))

    def test_slower_optional_normal_list_remains_rejected(self):
        for source in (self.original, self.corrected):
            with self.assertRaisesRegex(SystemExit, 'not faster at frame 1'):
                self.guard(source, [0, 0], [[], list(range(896))], [False, True])

    def test_fast_optional_normal_list_remains_accepted(self):
        for source in (self.original, self.corrected):
            self.guard(source, [0, 0], [[], [30]], [False, True])



if __name__ == '__main__':
    unittest.main()
