"""Check MP4 dimensions, cadence and audio against the canonical sim PCM model."""
import json
import os
from pathlib import Path
import subprocess
import wave
import numpy as np
from test_paths import QA_ROOT as root
settings=json.loads((root/'settings.json').read_text())['input']
video=root/'preview.mp4'
info=json.loads(subprocess.check_output(['ffprobe','-v','error','-show_streams','-show_format','-of','json',str(video)]))
v=next(s for s in info['streams'] if s['codec_type']=='video');a=next(s for s in info['streams'] if s['codec_type']=='audio')
assert (v['width'],v['height'])==(1024,784)
assert int(v['nb_frames'])==int(settings['frames'])
assert int(a['sample_rate'])==22050 and a['channels']==1
with wave.open(str(root/'playback.wav'),'rb') as wav:
 assert wav.getnchannels()==1 and wav.getsampwidth()==2
 rate=wav.getframerate();reference=np.frombuffer(wav.readframes(wav.getnframes()),dtype='<i2').astype(np.float64)/32768
samples=np.frombuffer(subprocess.check_output(['ffmpeg','-v','error','-i',str(video),'-vn','-ac','1','-ar','22050','-f','f32le','pipe:1']),dtype='<f4').astype(np.float64)
count=min(len(samples),int(float(settings['duration'])*22050))
expected=np.interp(np.arange(count)*rate/22050,np.arange(len(reference)),reference)
# FFT alignment around zero catches an untrimmed AAC priming frame.
length=min(count,22050*10);x=expected[:length];y=samples[:length]
if np.std(x)>1e-5:
 size=1<<(2*length-1).bit_length()
 cross=np.fft.irfft(np.fft.rfft(y,size)*np.conj(np.fft.rfft(x,size)),size)
 lags=np.arange(-2048,2049);lag=int(lags[np.argmax(cross[lags%size])])
 start=max(0,-lag);end=min(length,length-lag)
 correlation=float(np.corrcoef(x[start:end],y[start+lag:end+lag])[0,1])
 assert abs(lag)<=8,f'AAC playback shifted by {lag} samples'
 assert correlation>=0.90,f'Canonical PCM correlation is {correlation}'
else:lag=0;correlation=1.0
subprocess.run(['ffmpeg','-v','error','-i',str(video),'-f','null','-'],check=True)
print(json.dumps({'gate':'PASS','frames':settings['frames'],'canonicalAudioRate':rate,'aacLagSamples':lag,'audioCorrelation':correlation}))
