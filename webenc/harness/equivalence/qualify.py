"""Qualify browser stream features, canonical replay, PCM and ISO contents."""
import argparse
import datetime
import hashlib
import json
from pathlib import Path
import pickle
import sys
import numpy as np

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'tools'))
from tmpfs_workspace import lease_managed_path

parser = argparse.ArgumentParser()
parser.add_argument('job', type=Path)
args = parser.parse_args()
job = args.job.resolve()
lease = lease_managed_path(job, required_bytes=2 * 1024**3)
try:
    manifest = json.loads((job / 'manifest.json').read_text())
    sys.path.insert(0, str(job / 'snapshot/tools'))
    from replay import render
    render(job / 'native')
    with (job / 'native/decisions.pkl').open('rb') as f:
        native = pickle.load(f)
    with (job / 'wasm-decisions.pkl').open('rb') as f:
        browser = pickle.load(f)
    count = manifest['frames']
    assert len(native['frames']) == len(browser['frames']) == count
    columns = ['frame', 'scroll_active', 'scroll_x', 'scroll_y', 'fade_type', 'cram_sha256']
    rows = ['\t'.join(columns)]
    for key in ['active', 'positions']:
        assert np.array_equal(native['scroll'][key], browser['scroll'][key]), key
    for key in ['frame_types', 'active_frame_cram']:
        assert np.array_equal(native['fade'][key], browser['fade'][key]), key
    scroll = np.asarray(browser['scroll']['active'], dtype=bool)
    positions = np.asarray(browser['scroll']['positions'])
    types = np.asarray(browser['fade']['frame_types'])
    cram = np.asarray(browser['fade']['active_frame_cram'], dtype=np.uint8)
    for frame in range(count):
        values = [frame, int(scroll[frame]), *positions[frame], types[frame],
                  hashlib.sha256(cram[frame].tobytes()).hexdigest()]
        rows.append('\t'.join(map(str, values)))
    (job / 'playback-features.tsv').write_text('\n'.join(rows) + '\n')
    with np.load(job / 'native/stats.npz', allow_pickle=True) as stats:
        audio = Path(str(stats['audio_playback_file']))
    if not audio.is_absolute():
        audio = job / 'native' / audio
    if not audio.exists():
        audio = job / 'native' / audio.name
    pcm = (job / 'wasm-playback.wav').read_bytes()
    assert audio.read_bytes() == pcm, 'Canonical reconstructed PCM WAV differs'
    hashes = json.loads((job / 'wasm-result.json').read_text())['hashes']
    iso_name = next(name for name in hashes if name.endswith('.iso'))
    iso = (job / ('wasm-' + iso_name)).read_bytes()
    assert iso[:16] == b'SEGADISCSYSTEM  '
    pvd = iso[16 * 2048:17 * 2048]
    assert pvd[:7] == b'\x01CD001\x01'
    sector = int.from_bytes(pvd[158:162], 'little')
    size = int.from_bytes(pvd[166:170], 'little')
    directory = iso[sector * 2048:sector * 2048 + size]
    entries = {}
    offset = 0
    while offset < len(directory):
        length = directory[offset]
        if not length:
            offset = (offset // 2048 + 1) * 2048
            continue
        record = directory[offset:offset + length]
        name = record[33:33 + record[32]].decode('ascii').split(';')[0]
        start = int.from_bytes(record[2:6], 'little') * 2048
        length_bytes = int.from_bytes(record[10:14], 'little')
        entries[name] = iso[start:start + length_bytes]
        offset += length
    for name in ['HEADER.DAT', 'BODY.DAT']:
        assert entries[name] == (job / ('wasm-' + name)).read_bytes(), name
    cue = (job / ('wasm-' + iso_name[:-4] + '.cue')).read_text()
    assert f'FILE "{iso_name}" BINARY' in cue and 'MODE1/2048' in cue
    assert (job / 'native/playback-frames.tsv').read_bytes() == (job / 'wasm-playback-frames.tsv').read_bytes()
    changes = np.any(cram[1:] != cram[:-1], axis=tuple(range(1, cram.ndim)))
    result = dict(gate='PASS', profile=manifest['profile'], frames=count,
                  fullProfile=not bool(manifest.get('iteration')),
                  scrollFrames=int(scroll.sum()),
                  fadeTypes={str(int(t)): int(np.count_nonzero(types == t)) for t in np.unique(types)},
                  cramChanges=int(changes.sum()),
                  canonicalRgbFramesMatch=True, reconstructedPcmMatch=True,
                  reconstructedPcmSha256=hashlib.sha256(pcm).hexdigest(),
                  isoFilesMatch=True, cueMatches=True,
                  featuresMatch=True, isoName=iso_name)
    (job / 'playback-qualification.json').write_text(json.dumps(result, indent=2) + '\n')
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    stem = stamp + '_webenc_' + Path(manifest['profile']).stem + '_playback'
    (ROOT / 'logs' / (stem + '.json')).write_text(json.dumps(result, indent=2) + '\n')
    (ROOT / 'logs' / (stem + '.tsv')).write_text('\n'.join(rows) + '\n')
    print(json.dumps(result), flush=True)
finally:
    lease.release()
