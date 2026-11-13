"""Reject stale codec/player bundles before qualifying or publishing a build."""
import argparse
import hashlib
import json
from pathlib import Path
import zipfile

ROOT = Path(__file__).resolve().parents[3]
parser = argparse.ArgumentParser()
parser.add_argument('directory', type=Path, help='public or built client directory')
parser.add_argument('--json', type=Path, required=True)
args = parser.parse_args()
codec_files = sorted((ROOT / 'tools').glob('*.py'))
fingerprint = hashlib.sha256()
with zipfile.ZipFile(args.directory / 'python-codec.zip') as archive:
    for source in codec_files:
        contents = source.read_bytes()
        assert archive.read('tools/' + source.name) == contents, source
        fingerprint.update(source.name.encode())
        fingerprint.update(contents)
    version = (ROOT / 'tools/av_version.txt').read_bytes()
    assert archive.read('tools/av_version.txt') == version
    manifest = json.loads(archive.read('manifest.json'))
    assert manifest['encoderSha256'] == fingerprint.hexdigest()
    values = dict(line.split('=', 1) for line in version.decode().splitlines()
                  if line.startswith(('date=', 'e=', 'p=')))
    assert manifest['buildVersion'] == f"{values['date']}.e{values['e']}.p{values['p']}"
with zipfile.ZipFile(args.directory / 'player-code.zip') as archive:
    player_files = [name for name in archive.namelist() if name != 'boot/dbgfont.bin']
    for name in player_files:
        assert archive.read(name) == (ROOT / name).read_bytes(), name
assert (args.directory / 'python-adapter.py').read_bytes() == (
    ROOT / 'webenc/harness/equivalence/browser.py').read_bytes()
receipt = dict(passed=True, build_version=manifest['buildVersion'],
               codec_files=len(codec_files), player_files=player_files,
               encoder_sha256=fingerprint.hexdigest(),
               archives={name: hashlib.sha256((args.directory / name).read_bytes()).hexdigest()
                         for name in ['python-codec.zip', 'player-code.zip']})
args.json.parent.mkdir(parents=True, exist_ok=True)
args.json.write_text(json.dumps(receipt, indent=2) + '\n')
print(json.dumps(receipt))
