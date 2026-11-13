"""Build a native compiler reference from an existing packed stream, without encoding."""
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
parser.add_argument('stream', type=Path)
parser.add_argument('output', type=Path)
parser.add_argument('--region', choices=['jp', 'us'], default='jp')
args = parser.parse_args()
work = args.output.resolve()
work.mkdir(parents=True, exist_ok=True)
lease = lease_managed_path(work, required_bytes=64 * 1024**2)
try:
    with zipfile.ZipFile(ROOT / 'webenc/public/player-code.zip') as archive:
        archive.extractall(work)
    build = work / 'build'
    build.mkdir(exist_ok=True)
    for name in ['paltab.bin', 'palidx.bin', 'player_constants.inc']:
        shutil.copyfile(args.stream / name, build / name)
    prefix = str(Path.home() / 'toolchains/mars/m68k-elf/bin/m68k-elf-')
    assembler = [prefix + 'as', '-m68000', '--register-prefix-optional', '--bitwise-or',
                 '-I' + str(build), '-I' + str(work / 'boot')]
    def assemble(name, source, flags=()):
        obj = build / (name + '.o')
        subprocess.run([*assembler, *flags, str(source), '-o', str(obj)], check=True)
        return obj
    obj = assemble('extension', work / 'boot/movieplay_sp_ext.s')
    extension_file = build / 'sp-extension.bin'
    subprocess.run([prefix + 'ld', '-nostdlib', '--oformat', 'binary', '-T',
                    str(work / 'cfg/sp_ext.ld'), '-o', str(extension_file), str(obj)], check=True)
    extension = extension_file.read_bytes()
    (build / 'sp_extension.inc').write_text(render_include(metadata(extension)))
    for source, target in [(f'region_{args.region}.inc', 'disc_region.inc'),
                           (f'sec_{args.region}.bin', 'security.bin'),
                           ('dbgfont.bin', 'dbgfont.bin')]:
        shutil.copyfile(work / 'boot' / source, build / target)
    for kind in ['ip', 'sp']:
        obj = assemble('movieplay_' + kind, work / f'boot/movieplay_{kind}.s',
                       ['--defsym', 'MAIN_CODEGEN=1', '--defsym', 'PLAYER_SPECIALIZED=1'])
        subprocess.run([prefix + 'ld', '-nostdlib', '--oformat', 'binary', '-T',
                        str(work / f'cfg/{kind}.ld'), '-o',
                        str(build / f'movieplay_{kind}.bin'), str(obj)], check=True)
    obj = assemble('boot', work / 'boot/movieplay_boot.s')
    boot = build / 'native-boot.bin'
    subprocess.run([prefix + 'objcopy', '-O', 'binary', str(obj), str(boot)], check=True)
    assert boot.stat().st_size == 32768
    fixture = work / 'compiler-input.zip'
    with zipfile.ZipFile(fixture, 'w') as archive:
        for name in ['paltab.bin', 'palidx.bin', 'player_constants.inc',
                     'sp_extension.inc', 'sp-extension.bin', 'native-boot.bin']:
            archive.write(build / name, name)
    print(fixture)
finally:
    if lease:
        lease.release()
