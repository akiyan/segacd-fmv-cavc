"""Compare every browser-normalized RGB pixel and PCM sample with native FFmpeg."""
from pathlib import Path
import hashlib
import json
import subprocess
import sys
import wave
import numpy as np
from PIL import Image

root=Path(__file__).resolve().parents[3]
sys.path.insert(0,str(root/'tools'))
from video_geometry import raw_filter

target,source=map(Path,sys.argv[1:])
manifest=json.loads((target/'manifest.json').read_text())
normalization=manifest['normalization']
settings=manifest['inputSettings']
crop=settings['source']['crop']
geometry=raw_filter(manifest['width'],manifest['height'],crop['w'],crop['h'],
    src_sar_num=settings['source']['pixelAspect'][0],src_sar_den=settings['source']['pixelAspect'][1],fit=settings['video']['fit'])
filters=[]
if crop['x'] or crop['y'] or crop['w']!=settings['source']['width'] or crop['h']!=settings['source']['height']:
    filters=[f"crop={crop['w']}:{crop['h']}:{crop['x']}:{crop['y']}:exact=1"]
# setsar=1 precedes the user's crop, just as in the browser.
canonical=','.join(['setsar=1',*filters,*geometry.split(',')[1:],f"fps={settings['video']['fps']}"])
assert canonical==normalization['videoFilter'],(canonical,normalization['videoFilter'])
args=normalization['videoArgs'].copy()
args[args.index('/input/source')]=str(source)
args[args.index('png')]='rawvideo'
args[args.index('image2pipe')]='rawvideo'
args[-1]='-'
native=subprocess.check_output(['ffmpeg','-y',*args],stderr=subprocess.DEVNULL)
browser=b''.join(Image.open(image).convert('RGB').tobytes() for image in sorted((target/'master').glob('*.png')))
assert len(native)==len(browser),(len(native),len(browser))
with wave.open(str(target/'audio.wav')) as wav:
    assert (wav.getnchannels(),wav.getframerate(),wav.getsampwidth())==(1,22050,2)
    pcm=wav.readframes(wav.getnframes())
if normalization['audioArgs']:
    args=normalization['audioArgs'].copy()
    args[args.index('/input/source')]=str(source);args[-1]='-'
    native_pcm=subprocess.check_output(['ffmpeg','-y',*args],stderr=subprocess.DEVNULL)
else:
    native_pcm=bytes(manifest['audioSamples']*2)
assert len(pcm)==len(native_pcm),(len(pcm),len(native_pcm))
rgb_diff=np.abs(np.frombuffer(browser,dtype=np.uint8).astype(np.int16)-np.frombuffer(native,dtype=np.uint8))
pcm_diff=np.abs(np.frombuffer(pcm,dtype='<i2').astype(np.int32)-np.frombuffer(native_pcm,dtype='<i2'))
result={'case':target.name,'frames':manifest['frames'],'videoBytes':len(browser),'videoByteEqual':browser==native,'videoMaxError':int(rgb_diff.max(initial=0)),
        'videoDifferentSamples':int(np.count_nonzero(rgb_diff)),'audioByteEqual':pcm==native_pcm,'audioMaxError':int(pcm_diff.max(initial=0)),
        'browserCoreVersion':normalization['coreVersion'],'browserFFmpegVersion':normalization.get('ffmpegVersion'),'nativeVersion':subprocess.check_output(['ffmpeg','-version'],text=True).splitlines()[0],
        'nativeCpuFlags':'0','scope':'Every normalized RGB pixel and PCM sample; native reference disables CPU-specific optimized routines.'}
rows='artifact\tbrowser_sha256\tnative_sha256\tbyte_equal\tmax_sample_error\n'
for name,a,b,diff in [('rgb',browser,native,rgb_diff),('pcm',pcm,native_pcm,pcm_diff)]:
    rows+=f'{name}\t{hashlib.sha256(a).hexdigest()}\t{hashlib.sha256(b).hexdigest()}\t{a==b}\t{diff.max(initial=0)}\n'
(target/'comparison.json').write_text(json.dumps(result,indent=2)+'\n')
(target/'comparison.tsv').write_text(rows)
logs=root/'logs';logs.mkdir(exist_ok=True)
(logs/f'webenc_ffmpeg_scalar_preprocessing_{target.name}.json').write_text(json.dumps(result,indent=2)+'\n')
(logs/f'webenc_ffmpeg_scalar_preprocessing_{target.name}.tsv').write_text(rows)
print(json.dumps(result),flush=True)
if not result['videoByteEqual'] or not result['audioByteEqual']:
    raise SystemExit('Native/Wasm preprocessing bytes differ; inspect the version-specific diagnostics.')
