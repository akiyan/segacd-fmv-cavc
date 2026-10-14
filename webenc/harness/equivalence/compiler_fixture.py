"""Compile a native boot reference for the independently encoded stream."""
import argparse
from pathlib import Path
import shutil
import subprocess
import sys
import zipfile

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'tools'))
from sp_extension import metadata, render_include
from tmpfs_workspace import lease_managed_path

parser = argparse.ArgumentParser()
parser.add_argument('job', type=Path)
parser.add_argument('--region', choices=['jp', 'us'], default='jp')
args = parser.parse_args()
job = args.job.resolve()
lease = lease_managed_path(job, required_bytes=64 * 1024**2)
try:
    work = job / ('compiler-proof-' + args.region)
    work.mkdir(exist_ok=True)
    # Use exactly the independently bundled, unmodified player source tree.
    with zipfile.ZipFile(ROOT / 'webenc/public/player-code.zip') as archive:
        archive.extractall(work)
    build = work / 'build'
    build.mkdir(exist_ok=True)
    for name in ['paltab.bin', 'palidx.bin', 'player_constants.inc']:
        shutil.copyfile(job / 'native/packed' / name, build / name)
    extension = (job / 'inputs/sp-extension.bin').read_bytes()
    (build / 'sp_extension.inc').write_text(render_include(metadata(extension)))
    shutil.copyfile(work / 'boot' / ('region_' + args.region + '.inc'), build / 'disc_region.inc')
    shutil.copyfile(work / 'boot' / ('sec_' + args.region + '.bin'), build / 'security.bin')
    shutil.copyfile(work / 'boot/dbgfont.bin', build / 'dbgfont.bin')
    prefix = str(Path.home() / 'toolchains/mars/m68k-elf/bin/m68k-elf-')
    assembler = [prefix + 'as', '-m68000', '--register-prefix-optional', '--bitwise-or',
                 '-I' + str(build), '-I' + str(work / 'boot')]
    for kind in ['ip', 'sp']:
        obj = build / ('movieplay_' + kind + '.o')
        subprocess.run(assembler + ['--defsym', 'MAIN_CODEGEN=1', '--defsym', 'PLAYER_SPECIALIZED=1',
                       str(work / 'boot' / ('movieplay_' + kind + '.s')), '-o', str(obj)], check=True)
        subprocess.run([prefix + 'ld', '-nostdlib', '--oformat', 'binary', '-T',
                        str(work / 'cfg' / (kind + '.ld')), '-o',
                        str(build / ('movieplay_' + kind + '.bin')), str(obj)], check=True)
    subprocess.run(assembler + [str(work / 'boot/movieplay_boot.s'), '-o', str(build / 'boot.o')], check=True)
    subprocess.run([prefix + 'objcopy', '-O', 'binary', str(build / 'boot.o'), str(build / 'boot.bin')], check=True)
    boot = (build / 'boot.bin').read_bytes()
    assert len(boot) == 32768
    browser_iso = next(job.glob('wasm-*.iso')).read_bytes()
    if args.region == 'jp':
        assert boot == browser_iso[:32768], 'Browser ISO boot differs from native player compilation'
    fixture = work / 'compiler-input.zip'
    with zipfile.ZipFile(fixture, 'w') as archive:
        for name in ['paltab.bin', 'palidx.bin', 'player_constants.inc', 'sp_extension.inc']:
            archive.write(build / name, name)
        archive.writestr('sp-extension.bin', extension)
        archive.writestr('native-boot.bin', boot)
    print(fixture, flush=True)
finally:
    lease.release()
