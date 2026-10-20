#!/usr/bin/env python3
"""Compare all saved decisions, numeric traces and media bytes of two completed sims."""

import argparse
import csv
import hashlib
from pathlib import Path
import pickle
import sys

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'tools'))


def equal(left, right, where):
    if isinstance(left, np.ndarray) or isinstance(right, np.ndarray):
        a, b = np.asarray(left), np.asarray(right)
        if a.shape != b.shape or a.dtype != b.dtype:
            raise AssertionError(f'{where}: shape/dtype differ: {a.shape}/{a.dtype}, {b.shape}/{b.dtype}')
        np.testing.assert_array_equal(a, b, err_msg=where)
    elif isinstance(left, dict):
        if left.keys() != right.keys():
            raise AssertionError(f'{where}: keys differ')
        for key in left:
            equal(left[key], right[key], f'{where}.{key}')
    elif isinstance(left, (tuple, list)):
        if len(left) != len(right):
            raise AssertionError(f'{where}: lengths differ')
        for index, (a, b) in enumerate(zip(left, right)):
            equal(a, b, f'{where}[{index}]')
    elif isinstance(left, float) and np.isnan(left):
        if not np.isnan(right):
            raise AssertionError(f'{where}: NaN differs')
    elif left != right:
        raise AssertionError(f'{where}: {left!r} != {right!r}')


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('baseline', type=Path)
    parser.add_argument('candidate', type=Path)
    parser.add_argument('--tsv', type=Path, required=True)
    args = parser.parse_args()
    rows = []
    # Only local, trusted encoder outputs may be unpickled.
    with (args.baseline / 'decisions.pkl').open('rb') as f:
        left = pickle.load(f)
    with (args.candidate / 'decisions.pkl').open('rb') as f:
        right = pickle.load(f)
    equal(left, right, 'decisions')
    rows.append(['decisions.pkl', 'all fields/frames', 'IDENTICAL'])
    for name in ('stats.npz', 'buffer_remaining.npz', 'seg_palettes.npz'):
        with np.load(args.baseline / name, allow_pickle=False) as a, np.load(args.candidate / name, allow_pickle=False) as b:
            if set(a.files) != set(b.files):
                raise AssertionError(f'{name}: fields differ')
            for key in a.files:
                equal(a[key], b[key], f'{name}.{key}')
        rows.append([name, 'all numeric fields', 'IDENTICAL'])
    for name in ('miss_masks.npy', 'palettes.bin', 'audio_22k05_s16_mono.wav',
                 'audio_playback_adpcm22_rf5c.wav'):
        a, b = digest(args.baseline / name), digest(args.candidate / name)
        if a != b:
            raise AssertionError(f'{name}: bytes differ')
        rows.append([name, a, 'IDENTICAL'])
    args.tsv.parent.mkdir(parents=True, exist_ok=True)
    with args.tsv.open('w', encoding='utf-8', newline='') as stream:
        writer = csv.writer(stream, delimiter='\t', lineterminator='\n')
        writer.writerow(['artifact', 'comparison', 'result'])
        writer.writerows(rows)
    print(f'PASS: {len(left["frames"])} frames, all saved decisions/traces and audio; {args.tsv}')


if __name__ == '__main__':
    main()
