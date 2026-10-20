#!/usr/bin/env python3
"""Run local unit suites once; expensive encode/playback qualification is separate."""

import argparse
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[2]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--harness-only', action='store_true',
                        help='Skip tools/ when that suite has already passed')
    args = parser.parse_args()
    directories = sorted({p.parent for p in (ROOT / 'harness').rglob('test_*.py')
                          if p.parent.name != 'gpgx_logvdp'})
    directories += [ROOT / 'webenc/harness/equivalence']
    if not args.harness_only:
        directories.insert(0, ROOT / 'tools')
    for directory in directories:
        print(f'RUN {directory.relative_to(ROOT)}', flush=True)
        subprocess.run([sys.executable, '-m', 'unittest', 'discover',
                        '-s', str(directory), '-p', 'test_*.py'], cwd=ROOT, check=True)
    subprocess.run([sys.executable, str(ROOT / 'harness/gpgx_logvdp/test_stream_log.py')],
                   cwd=ROOT, check=True)
    print('PASS: local unit suites and stream-log integration; no long encode or emulator launched')


if __name__ == '__main__':
    main()
