"""Normalize a profile's source once, then freeze inputs and encoder sources."""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import wave
import zipfile

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'tools'))
from encode_config import load_profile, apply_profile_env
from tmpfs_workspace import activate_directory, mark_directory_complete
from PIL import Image
import numpy as np

def sha(path):
    h=hashlib.sha256()
    with path.open('rb') as f:
        for chunk in iter(lambda:f.read(1024*1024),b''):h.update(chunk)
    return h.hexdigest()

parser=argparse.ArgumentParser()
parser.add_argument('profile',type=Path)
args=parser.parse_args()
profile=load_profile(args.profile)
env={};apply_profile_env(profile,env)
source=ROOT / profile.data['source']['path']
files=sorted((ROOT/'tools').glob('*.py'))
code_hash=hashlib.sha256(b''.join(p.name.encode()+p.read_bytes() for p in files)).hexdigest()
identity=hashlib.sha256((sha(source)+profile.sha256+code_hash).encode()).hexdigest()
lease=activate_directory(kind='webenc-equivalence',key=f'{profile.path.stem}-{identity[:12]}',required_bytes=4*1024**3,reuse_token=identity)
job=lease.entry/'data'
try:
    if lease.reused:
        print(job,flush=True);sys.exit(0)
    inputs=job/'inputs';inputs.mkdir()
    for name in ['master','raw']:(inputs/name).mkdir()
    w,h=int(env['CBRSIM_W']),int(env['CBRSIM_H'])
    # Explicit profile filters define the normalized codec input. They are
    # applied offline only; neither browser decoder nor Canvas participates.
    from video_geometry import probe_source,source_filter,raw_filter,parse_ratio
    sw,sh,sn,sd=probe_source(str(source))
    if env.get('CBRSIM_SOURCE_SAR'):sn,sd=parse_ratio(env['CBRSIM_SOURCE_SAR'])
    master=env.get('CBRSIM_MASTER_VF') or source_filter(w,h,sw,sh,src_sar_num=sn,src_sar_den=sd,fit=env['CBRSIM_GEOMETRY_FIT'],denoise=env['CBRSIM_MASTER_DENOISE']=='1',resize_filter=env['CBRSIM_RESIZE_FILTER'])
    raw=env.get('CBRSIM_RAW_VF') or raw_filter(w,h,sw,sh,src_sar_num=sn,src_sar_den=sd,fit=env['CBRSIM_GEOMETRY_FIT'],resize_filter=env['CBRSIM_RESIZE_FILTER'])
    for name,vf in [('master',master),('raw',raw)]:
        print(f'Normalize {name}: {vf}',flush=True)
        subprocess.run(['ffmpeg','-y','-hide_banner','-loglevel','error','-threads','1','-filter_threads','1','-ss','0','-t',env['CBRSIM_DURATION'],'-i',str(source),'-vf',f'{vf},fps={env["CBRSIM_FPS"]}','-pix_fmt','rgb24',str(inputs/name/'%05d.png')],check=True)
    audio=inputs/'audio_22k05_s16_mono.wav'
    subprocess.run(['ffmpeg','-y','-hide_banner','-loglevel','error','-threads','1','-ss','0','-t',env['CBRSIM_DURATION'],'-i',str(source),'-vn',*(['-af',env['CBRSIM_AUDIO_AF']] if env.get('CBRSIM_AUDIO_AF') else []),'-ac','1','-ar','22050','-acodec','pcm_s16le',str(audio)],check=True)
    entries=[];count=None
    for name in ['master','raw']:
        frames=sorted((inputs/name).glob('*.png'))
        if count is None:count=len(frames)
        assert len(frames)==count and count>0
        for i,path in enumerate(frames):
            pixels=np.asarray(Image.open(path).convert('RGB'),dtype=np.uint8)
            assert pixels.shape==(h,w,3)
            entries.append(f'{name}\t{i}\t{pixels.nbytes}\t{hashlib.sha256(pixels.tobytes()).hexdigest()}\t{sha(path)}')
    with wave.open(str(audio),'rb') as wav:
        assert (wav.getframerate(),wav.getnchannels(),wav.getsampwidth())==(22050,1,2)
        pcm=wav.readframes(wav.getnframes())
    (inputs/'audio.s16le').write_bytes(pcm)
    entries.append(f'pcm\t0\t{len(pcm)}\t{hashlib.sha256(pcm).hexdigest()}\t{sha(audio)}')
    (inputs/'input-sha256.tsv').write_text('kind\tframe\tbytes\tdecoded_sha256\tcontainer_sha256\n'+'\n'.join(entries)+'\n')
    snapshot=job/'snapshot';(snapshot/'tools').mkdir(parents=True)
    for path in files:shutil.copyfile(path,snapshot/'tools'/path.name)
    shutil.copyfile(ROOT/'tools/av_version.txt',snapshot/'tools/av_version.txt')
    shutil.copytree(ROOT/'boot',snapshot/'boot',ignore=shutil.ignore_patterns('sec_*.bin'))
    shutil.copytree(ROOT/'cfg',snapshot/'cfg')
    (snapshot/'profiles').mkdir();shutil.copyfile(profile.path,snapshot/'profiles'/profile.path.name)
    toolchain=Path.home()/'toolchains/mars/m68k-elf/bin/m68k-elf-'
    subprocess.run([str(toolchain)+'as','-m68000','--register-prefix-optional','--bitwise-or','-I'+str(snapshot/'boot'),str(snapshot/'boot/movieplay_sp_ext.s'),'-o',str(job/'extension.o')],check=True)
    subprocess.run([str(toolchain)+'ld','-nostdlib','--oformat','binary','-T',str(snapshot/'cfg/sp_ext.ld'),'-o',str(inputs/'sp-extension.bin'),str(job/'extension.o')],check=True)
    manifest={'schema':1,'profile':profile.path.name,'profileSha256':profile.sha256,'sourceSha256':sha(source),'encoderSha256':code_hash,'width':w,'height':h,'fps':env['CBRSIM_FPS'],'frames':count,'duration':env['CBRSIM_DURATION'],'audioRate':22050,'audioSamples':len(pcm)//2,'environment':env,'inputFormat':'RGB24 encoded losslessly as PNG; mono s16le PCM','masterFilterApplied':master,'rawFilterApplied':raw,'audioFilterApplied':env.get('CBRSIM_AUDIO_AF',''),'normalizationComplete':True,'profileSections':{name:profile.section(name) for name in ['source','video','encoder','palette','output']}}
    (inputs/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    (job/'manifest.json').write_text(json.dumps(manifest,indent=2)+'\n')
    (job/'identity.json').write_text(json.dumps({'identity':identity,'job':str(job)})+'\n')
    # The archive contains data only. Python source is bundled independently.
    archive=job/'normalized.cavc-input.zip'
    with zipfile.ZipFile(archive,'w',compression=zipfile.ZIP_STORED) as z:
        for path in sorted(inputs.rglob('*')):
            if path.is_file():z.write(path,path.relative_to(inputs).as_posix())
    mark_directory_complete(lease,reuse_token=identity,details={'frames':count,'archiveSha256':sha(archive)})
    print(f'Normalized {count} frames, {len(pcm)//2} audio samples; input archive {archive.stat().st_size} bytes',flush=True)
    print(job,flush=True)
finally:lease.release()
