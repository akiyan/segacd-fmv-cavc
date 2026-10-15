"""Run the frozen original codec on the normalized full-profile inputs."""
import argparse
import json
import hashlib
import os
from pathlib import Path
import shutil
import sys
import tomllib

ROOT=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(ROOT/'tools'))
from tmpfs_workspace import lease_managed_path
parser=argparse.ArgumentParser();parser.add_argument('job',type=Path);args=parser.parse_args()
job=args.job.resolve();lease=lease_managed_path(job,required_bytes=4*1024**3)
try:
    manifest=json.loads((job/'manifest.json').read_text())
    target=job/'native';target.mkdir(exist_ok=True)
    for name in ['master','raw']:
        if not (target/name).exists():shutil.copytree(job/'inputs'/name,target/name)
    shutil.copyfile(job/'inputs/audio_22k05_s16_mono.wav',target/'audio_22k05_s16_mono.wav')
    for key in list(os.environ):
        if key.startswith('CBRSIM_'):del os.environ[key]
    env=manifest['environment'].copy();env.pop('CBRSIM_CONFIG',None)
    env.update(CBRSIM_OUT=str(target),CBRSIM_REUSE='1',CBRSIM_GPU='0',CBRSIM_WORKERS='1')
    os.environ.update(env)
    snapshot=job/'snapshot';sys.path.insert(0,str(snapshot/'tools'))
    sys.argv=['webenc-equivalence']
    # Configuration is already applied; keep profile authentication unchanged.
    import sim
    from prebuffer_trace import install as install_prebuffer_trace
    install_prebuffer_trace(sim)
    from encode_config import EncodeProfile
    profile_path=snapshot/'profiles'/manifest['profile']
    sim.CONFIG_PROFILE=EncodeProfile(profile_path,tomllib.loads(profile_path.read_text()),manifest['profileSha256'])
    from stages import install
    signature=hashlib.sha256(json.dumps(manifest,sort_keys=True).encode())
    for name in ['master','raw']:
        for image in sorted((job/'inputs'/name).glob('*.png')):signature.update(image.read_bytes())
    install(sim,target,cache=True,identity=signature.hexdigest()[:16])
    anchors=set()
    while True:
        try:sim.main(demoted_fade_anchors=frozenset(anchors));break
        except sim.FadeDeadlineInfeasible as e:
            if e.anchor in anchors:raise
            anchors.add(e.anchor)
    (target/'demoted-fade-anchors.json').write_text(json.dumps(sorted(anchors))+'\n')
    # Reload the source PCM for packing; do not use the reconstructed WAV.
    import pack_stream
    from pack_validation import install as install_pack_validation
    install_pack_validation(pack_stream)
    sys.argv=['pack_stream','--dec-log',str(target/'decisions.pkl'),'--audio',str(job/'inputs/audio_22k05_s16_mono.wav'),'--output',str(target/'packed/MOVIE.DAT'),'--sp-extension',str(job/'inputs/sp-extension.bin'),'--verify']
    pack_stream.main()
    print(f'Native original-code reference complete: {target}',flush=True)
finally:
    if lease:lease.release()
