"""Browser platform adapter. Encoder/palette/packer implementations are unchanged."""
import json
import os
from pathlib import Path
import sys
import types

manifest=json.loads(Path('/work/manifest.json').read_text())
for key in list(os.environ):
    if key.startswith('CBRSIM_'):del os.environ[key]
env=manifest['environment'].copy();env.pop('CBRSIM_CONFIG',None)
env.update(CBRSIM_OUT='/work',CBRSIM_REUSE='1',CBRSIM_GPU='0',CBRSIM_WORKERS='1')
# Shared PNG inputs already contain the profile's offline crop/resize/filter.
# Explicit no-op filters avoid probing the absent source through FFmpeg before
# the original encoder reaches its normalized-input reuse branch.
if not manifest.get('normalizationComplete'):
    raise ValueError('Browser adapter requires completed normalized inputs')
env.update(CBRSIM_MASTER_VF='setsar=1',CBRSIM_RAW_VF='setsar=1')
os.environ.update(env)
sys.path.insert(0,'/codec/tools')
sys.argv=['normalized-cavc']
# Linux resource locking and disposable-workspace bookkeeping do not operate
# inside a dedicated browser worker. No encoder decisions depend on these.
class Token:
    def release(self):pass
resources=types.ModuleType('resource_tokens')
resources.requested_cpu_workers=lambda **kwargs:1
resources.acquire_tokens=lambda *args,**kwargs:Token()
resources.ResourceBusyError=RuntimeError
sys.modules['resource_tokens']=resources
workspace=types.ModuleType('tmpfs_workspace')
sys.modules['tmpfs_workspace']=workspace

import sim
from prebuffer_trace import install as install_prebuffer_trace
install_prebuffer_trace(sim)
from encode_config import EncodeProfile
sim.CONFIG_PROFILE=EncodeProfile(Path('/profiles')/manifest['profile'],manifest['profileSections'],manifest['profileSha256'])
from numeric_compat import install as install_numeric
install_numeric(sim,'/codec/numeric-constants.npz')
emit_progress=None
if Path('/codec/tools/progress.py').exists():
    from progress import install as install_progress
    emit_progress=install_progress(sim,globals().get('__webenc_progress'),globals().get('__webenc_features'))
from stages import install
install(sim,Path('/work'),cache=False)
anchors=set()
while True:
    try:sim.main(demoted_fade_anchors=frozenset(anchors));break
    except sim.FadeDeadlineInfeasible as error:
        if error.anchor in anchors:raise
        anchors.add(error.anchor)
        import gc;gc.enable()
        print(f'Fade planning retry at frame {error.anchor}',flush=True)
Path('/work/demoted-fade-anchors.json').write_text(json.dumps(sorted(anchors))+'\n')
import pack_stream
if emit_progress:emit_progress(5,None,'Resolve and verify packed stream',force=True)
sys.argv=['pack_stream','--dec-log','/work/decisions.pkl','--audio','/original-audio.wav','--output','/work/packed/MOVIE.DAT','--sp-extension','/work/sp-extension.bin','--verify']
pack_stream.main()
if Path('/codec/tools/features.py').exists():
    if emit_progress:emit_progress(5,None,'Create analysis timeline',force=True)
    from features import from_decisions
    summary=from_decisions('/work')
    if globals().get('__webenc_features') is not None:__webenc_features(json.dumps(summary,separators=(',',':')))
print('Original Python codec execution under WebAssembly complete.',flush=True)
