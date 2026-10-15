"""Reproduce and repack the full source at the reported browser quality point."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import pickle
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(ROOT/'tools'), str(Path(__file__).parent)]
from tmpfs_workspace import activate_directory, mark_directory_complete, lease_managed_path


def verify_pack(target,source_hash):
    os.environ.update(CBRSIM_FPS='30',CBRSIM_W='320',CBRSIM_H='224',CBRSIM_COLD_CAP='210',CBRSIM_GPU='0',CBRSIM_WORKERS='1')
    toolchain=Path.home()/'toolchains/mars/m68k-elf/bin/m68k-elf-'
    subprocess.run([str(toolchain)+'as','-m68000','--register-prefix-optional','--bitwise-or','-I'+str(ROOT/'boot'),str(ROOT/'boot/movieplay_sp_ext.s'),'-o',str(target/'sp-extension.o')],check=True)
    subprocess.run([str(toolchain)+'ld','-nostdlib','--oformat','binary','-T',str(ROOT/'cfg/sp_ext.ld'),'-o',str(target/'sp-extension.bin'),str(target/'sp-extension.o')],check=True)
    with (target/'decisions.pkl').open('rb') as file:decisions=pickle.load(file)
    import pack_stream
    sys.argv=['pack_stream','--dec-log',str(target/'decisions.pkl'),'--audio',str(target/'audio_22k05_s16_mono.wav'),
              '--output',str(target/'packed/MOVIE.DAT'),'--sp-extension',str(target/'sp-extension.bin'),'--verify']
    original_error=None
    try:pack_stream.main()
    except SystemExit as error:
        original_error=str(error)
        if 'selected shadow list is not faster' not in original_error:raise
        print(f'ORIGINAL_PACK_REPRODUCED={original_error}',flush=True)
    from pack_validation import install as install_pack_validation
    install_pack_validation(pack_stream)
    pack_stream.main()
    receipt={'frames':len(decisions['frames']),'width':320,'height':224,'fps':30,'coldCap':210,'sourceSha256':source_hash,
             'originalPackError':original_error,'correctedPackVerified':True,
             'files':{name:hashlib.sha256((target/'packed'/name).read_bytes()).hexdigest() for name in ['HEADER.DAT','BODY.DAT','MOVIE.DAT']}}
    (target/'repro-result.json').write_text(json.dumps(receipt,indent=2)+'\n')
    (ROOT/'logs/webenc_scroll_pack_full_repro.json').write_text(json.dumps(receipt,indent=2)+'\n')
    return receipt

parser=argparse.ArgumentParser()
parser.add_argument('source',type=Path)
parser.add_argument('--pack-only',type=Path)
args=parser.parse_args()
source=args.source.resolve()
source_hash=hashlib.sha256(source.read_bytes()).hexdigest()
code_hash=hashlib.sha256(b''.join(p.name.encode()+p.read_bytes() for p in sorted((ROOT/'tools').glob('*.py')))).hexdigest()
identity=hashlib.sha256((source_hash+code_hash+'320x224-30-pad-sar32:35-cold210').encode()).hexdigest()
if args.pack_only:
    lease=lease_managed_path(args.pack_only,required_bytes=256*1024**2)
    if lease is None:raise SystemExit('Pack-only input must be a managed existing fixture directory')
    try:
        receipt=verify_pack(args.pack_only,source_hash)
        mark_directory_complete(lease,reuse_token=identity,details=receipt)
        print(json.dumps(receipt),flush=True)
    finally:lease.release()
    raise SystemExit(0)
lease=activate_directory(kind='webenc-scroll-pack',key=f'{source.stem}-{identity[:12]}',required_bytes=4*1024**3,reuse_token=identity)
target=lease.entry/'data'
try:
    if lease.reused:
        print(target,flush=True);raise SystemExit(0)
    print(f'REPRO_DIRECTORY={target}',flush=True)
    from video_geometry import probe_source,raw_filter
    sw,sh,_,_=probe_source(str(source))
    vf=raw_filter(320,224,sw,sh,src_sar_num=32,src_sar_den=35,fit='pad')
    master=target/'master';master.mkdir()
    subprocess.run(['ffmpeg','-y','-v','error','-cpuflags','0','-threads','1','-filter_threads','1',
                    '-i',str(source),'-vf',vf+',fps=30','-pix_fmt','rgb24',str(master/'%05d.png')],check=True)
    (target/'raw').symlink_to(master,target_is_directory=True)
    frames=len(list(master.glob('*.png')));duration=frames/30
    subprocess.run(['ffmpeg','-y','-v','error','-cpuflags','0','-i',str(source),'-vn',
                    '-af',f'aformat=sample_fmts=s16:sample_rates=22050:channel_layouts=mono,atrim=end={duration},apad=whole_len={round(duration*22050)},atrim=end_sample={round(duration*22050)}',
                    '-ac','1','-ar','22050','-c:a','pcm_s16le',str(target/'audio_22k05_s16_mono.wav')],check=True)
    for key in list(os.environ):
        if key.startswith('CBRSIM_'):del os.environ[key]
    from encode_config import PROFILE_ENV_DEFAULTS,EncodeProfile
    env={**PROFILE_ENV_DEFAULTS,'CBRSIM_SRC':str(source),'CBRSIM_OUT':str(target),'CBRSIM_REUSE':'1',
         'CBRSIM_FPS':'30','CBRSIM_DURATION':str(duration),'CBRSIM_W':'320','CBRSIM_H':'224',
         'CBRSIM_GEOMETRY_FIT':'pad','CBRSIM_SOURCE_SAR':'32:35','CBRSIM_MASTER_DENOISE':'0',
         'CBRSIM_MASTER_VF':'setsar=1','CBRSIM_RAW_VF':'setsar=1','CBRSIM_PAL_ALGO':'mosaic-gm',
         'CBRSIM_OUTPUT_DITHER':'bayer','CBRSIM_COLD_CAP':'210','CBRSIM_EMIT_DEC':'1',
         'CBRSIM_GPU':'0','CBRSIM_WORKERS':'1'}
    os.environ.update(env)
    import sim
    from prebuffer_trace import install as install_trace
    install_trace(sim)
    sections={'source':{'path':str(source),'fps':'30','duration':str(duration),'sar':'32:35'},
              'video':{'width':320,'height':224,'fit':'pad','master_denoise':False,'output_dither':'bayer'},
              'encoder':{'cold_cap':'210'},'palette':{'algorithm':'mosaic-gm'},'output':{'emit_decisions':True}}
    sim.CONFIG_PROFILE=EncodeProfile(target/'browser-input.toml',sections,hashlib.sha256(json.dumps(sections).encode()).hexdigest())
    from stages import install as install_stages
    install_stages(sim,target,cache=True,identity=identity[:16])
    anchors=set()
    while True:
        try:sim.main(demoted_fade_anchors=frozenset(anchors));break
        except sim.FadeDeadlineInfeasible as error:
            if error.anchor in anchors:raise
            anchors.add(error.anchor)
    receipt=verify_pack(target,source_hash)
    mark_directory_complete(lease,reuse_token=identity,details=receipt)
    print(json.dumps(receipt),flush=True)
finally:lease.release()
