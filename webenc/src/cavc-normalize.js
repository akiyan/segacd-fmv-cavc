import {Input,BlobSource,ALL_FORMATS} from 'mediabunny';
import {videoFrameTimes,frameInterval} from './frame-range';
import {loadFFmpeg,pngStream,outputDevice} from './ffmpeg-runtime';
import {videoFilter,pcmWave} from './normalization-plan';

export async function normalizeVideo(py,file,settings,runtime,log,progress) {
 const input=new Input({source:new BlobSource(file),formats:ALL_FORMATS});
 let core,mounted=false;
 try {
  const track=await input.getPrimaryVideoTrack();
  if(!track)throw new Error('No video track found. Choose MP4, WebM or MOV.');
  const audio=await input.getPrimaryAudioTrack();
  const trackFirst=await track.getFirstTimestamp(),trackDuration=await track.computeDuration();
  const interval=frameInterval(await videoFrameTimes(track),trackFirst+trackDuration,settings.source.frameRange);
  const first=interval.start,duration=interval.end-first;
  const {width,height,fps}=settings.video;
  const plannedFrames=Math.ceil(duration*fps-1e-7);
  if(plannedFrames<1||plannedFrames>32767)throw new Error('The CAVC stream supports up to 32767 output frames.');
  const loaded=await loadFFmpeg(progress,log);core=loaded.core;
  const version=loaded.version;
  // WORKERFS reads the selected Blob without copying the complete input into
  // FFmpeg's heap. The main-thread fallback is for small diagnostic fixtures.
  core.FS.mkdir('/input');
  const inputName='/input/source';
  if(typeof FileReaderSync==='function'){
   core.FS.mount(core.FS.filesystems.WORKERFS,{blobs:[{name:'source',data:file}]},'/input');mounted=true;
  }else core.FS.writeFile(inputName,new Uint8Array(await file.arrayBuffer()));
  let recent=[];
  core.setLogger(({message})=>{recent.push(message);recent=recent.slice(-12);if(!/^frame=/.test(message))log(`FFmpeg: ${message}`);});
  const run=args=>{recent=[];core.reset();const code=core.exec(...args);if(code!==0)throw new Error(`FFmpeg preprocessing failed (${code}): ${recent.join('\n')}`);};
  const filter=videoFilter(settings);
  let frames=0,lastReport=0;
  const stream=pngStream(bytes=>{
   const name=String(++frames).padStart(5,'0')+'.png';
   py.FS.writeFile('/work/master/'+name,bytes);py.FS.writeFile('/work/raw/'+name,bytes);
   const now=performance.now();
   if(frames===1||frames===plannedFrames||now-lastReport>=150){
    progress(0,8+72*Math.min(1,frames/plannedFrames),'Normalize source frames',frames,plannedFrames);lastReport=now;
   }
  });
  outputDevice(core,'/dev/cavc-frames',bytes=>stream.write(bytes));
  const videoArgs=['-hide_banner','-loglevel','info','-nostats','-cpuflags','0','-threads','1','-filter_threads','1',
   '-ss',String(first),'-t',String(duration),'-i',inputName,'-map','0:v:0','-an',
   '-vf',filter,'-vsync','0','-frames:v',String(plannedFrames),'-c:v','png','-pix_fmt','rgb24','-threads','1','-f','image2pipe','/dev/cavc-frames'];
  log(`FFmpeg normalizing up to ${plannedFrames} frames to ${width}×${height}, ${fps} fps (Lanczos).`);
  log(`Source frames ${interval.startFrame}–${interval.endFrame} (inclusive), ${first.toFixed(6)}–${interval.end.toFixed(6)} seconds. Audio uses the same interval.`);
  run(videoArgs);stream.finish();
  if(!frames)throw new Error('FFmpeg produced no frames for the selected range.');
  progress(0,80,'Normalize source frames',frames,frames);
  const total=Math.round(frames/fps*22050);
  let pcm=new Uint8Array(total*2),audioArgs=null;
  if(audio){
   // Downmix/resample from the audio head, then trim. This preserves resampler
   // history and makes a trimmed PCM interval match the same full conversion.
   const af=`aformat=sample_fmts=s16:sample_rates=22050:channel_layouts=mono,atrim=start=${first}:end=${interval.end},asetpts=PTS-STARTPTS,apad=whole_len=${total},atrim=end_sample=${total}`;
   let written=0;lastReport=0;
   outputDevice(core,'/dev/cavc-audio',bytes=>{
    const length=Math.min(bytes.length,pcm.length-written);if(length>0)pcm.set(bytes.subarray(0,length),written);
    written+=bytes.length;const now=performance.now();
    if(now-lastReport>=150){progress(0,80+20*Math.min(1,written/(total*2)),`Normalize source audio · ${Math.min(total,written/2)} / ${total} samples`);lastReport=now;}
   },1);
   audioArgs=['-hide_banner','-loglevel','info','-nostats','-cpuflags','0','-threads','1','-i',inputName,'-map','0:a:0','-vn',
    '-af',af,'-ac','1','-ar','22050','-c:a','pcm_s16le','-f','s16le','/dev/cavc-audio'];
   run(audioArgs);
   if(written!==pcm.length)throw new Error(`FFmpeg audio length mismatch: ${written/2} / ${total} samples.`);
  }else log('Source has no audio track; creating silent 22.05 kHz mono PCM.');
  const audioBytes=pcmWave(pcm,total);py.FS.writeFile('/work/audio_22k05_s16_mono.wav',audioBytes);py.FS.writeFile('/original-audio.wav',audioBytes);
  const defaults=await(await fetch('/python-defaults.json')).json();
  const sections={source:{path:file.name,fps:String(fps),duration:String(frames/fps),sar:'32:35'},
   video:{width,height,fit:'pad',master_denoise:false,output_dither:'bayer'},
   encoder:{cold_cap:String(settings.encoder.coldCap)},palette:{algorithm:'mosaic-gm'},output:{emit_decisions:true}};
  const profileSha256=[...new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(JSON.stringify(sections))))].map(v=>v.toString(16).padStart(2,'0')).join('');
  const environment={...defaults,CBRSIM_SRC:file.name,CBRSIM_FPS:String(fps),CBRSIM_DURATION:String(frames/fps),CBRSIM_W:String(width),CBRSIM_H:String(height),
   CBRSIM_GEOMETRY_FIT:'pad',CBRSIM_SOURCE_SAR:'32:35',CBRSIM_MASTER_DENOISE:'0',CBRSIM_MASTER_VF:'setsar=1',CBRSIM_RAW_VF:'setsar=1',CBRSIM_OUTPUT_DITHER:'bayer',CBRSIM_PAL_ALGO:'mosaic-gm',
   CBRSIM_COLD_CAP:String(settings.encoder.coldCap),CBRSIM_EMIT_DEC:'1'};
  const manifest={schema:1,normalizationComplete:true,profile:'browser-input.toml',profileSha256,profileSections:sections,encoderSha256:runtime.encoderSha256,
   frames,width,height,fps:String(fps),duration:String(frames/fps),audioSamples:total,environment,normalizer:`FFmpeg Wasm ${version} / Lanczos RGB + 22050 Hz mono s16 PCM`,normalization:{engine:'ffmpeg.wasm',coreVersion:version,ffmpegVersion:loaded.ffmpegVersion,videoFilter:filter,videoArgs,audioArgs},sourceName:file.name,inputSettings:settings,sourceFrameRange:interval};
  py.FS.writeFile('/work/manifest.json',JSON.stringify(manifest));progress(0,100);
  return manifest;
 } finally {
  if(mounted)core.FS.unmount('/input');
  input.dispose();
 }
}
