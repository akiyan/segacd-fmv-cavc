import {Input,BlobSource,ALL_FORMATS,CanvasSink,AudioSampleSink} from 'mediabunny';
import {framing} from './geometry';
import {videoFrameTimes,frameInterval} from './frame-range';

function wave(pcm,rate=22050) {
 const bytes=new Uint8Array(44+pcm.length*2),view=new DataView(bytes.buffer);
 const text=(offset,value)=>[...value].forEach((c,i)=>bytes[offset+i]=c.charCodeAt(0));
 text(0,'RIFF');view.setUint32(4,bytes.length-8,true);text(8,'WAVE');text(12,'fmt ');
 view.setUint32(16,16,true);view.setUint16(20,1,true);view.setUint16(22,1,true);
 view.setUint32(24,rate,true);view.setUint32(28,rate*2,true);view.setUint16(32,2,true);view.setUint16(34,16,true);
 text(36,'data');view.setUint32(40,pcm.length*2,true);
 for(let i=0;i<pcm.length;i++)view.setInt16(44+i*2,Math.max(-32768,Math.min(32767,Math.round(pcm[i]*32768))),true);
 return bytes;
}

export async function normalizeVideo(py,file,settings,runtime,log,progress) {
 const input=new Input({source:new BlobSource(file),formats:ALL_FORMATS});
 try {
  const track=await input.getPrimaryVideoTrack();
  if(!track||!await track.canDecode())throw new Error('Cannot decode this video. Choose H.264 MP4 or supported WebM.');
  const audio=await input.getPrimaryAudioTrack();
  if(audio&&!await audio.canDecode())throw new Error('Cannot decode the video audio. Choose AAC-LC MP4.');
  const trackFirst=await track.getFirstTimestamp(),trackDuration=await track.computeDuration();
  const interval=frameInterval(await videoFrameTimes(track),trackFirst+trackDuration,settings.source.frameRange);
  const first=interval.start,duration=interval.end-first;
  const {width,height,fps,fit}=settings.video;
  const frames=Math.ceil(duration*fps-1e-7);
  if(frames<1||frames>32767)throw new Error('The CAVC stream supports up to 32767 output frames.');
  const canvas=new OffscreenCanvas(width,height),ctx=canvas.getContext('2d',{alpha:false});
  const sink=new CanvasSink(track,{width:settings.source.width,height:settings.source.height,fit:'fill',poolSize:2});
  const [n,d]=settings.source.pixelAspect,p=framing(settings.source.crop,n/d,width,height,fit);
  function* times(){for(let i=0;i<frames;i++)yield first+i/fps;}
  let index=0;
  log(`Normalizing ${frames} frames to ${width}×${height}, ${fps} fps. CAVC decisions follow in the original Python codec.`);
  log(`Source frames ${interval.startFrame}–${interval.endFrame} (inclusive), ${first.toFixed(6)}–${interval.end.toFixed(6)} seconds. Audio uses the same interval.`);
  for await(const frame of sink.canvasesAtTimestamps(times())) {
   if(!frame)throw new Error(`Cannot decode frame ${index}`);
   ctx.fillStyle='#000';ctx.fillRect(0,0,width,height);
   ctx.drawImage(frame.canvas,p.sx,p.sy,p.sw,p.sh,p.dx,p.dy,p.dw,p.dh);
   const bytes=new Uint8Array(await (await canvas.convertToBlob({type:'image/png'})).arrayBuffer());
   const name=String(index+1).padStart(5,'0')+'.png';
   py.FS.writeFile('/work/master/'+name,bytes);py.FS.writeFile('/work/raw/'+name,bytes);
   progress(0,++index/frames*80,'Normalize source frames',index,frames);
   if(index%100===0)log(`Normalized video ${index}/${frames}`);
  }
  const rate=22050,total=Math.round(frames/fps*rate),pcm=new Float32Array(total);
  if(audio) {
   // Decode from the audio head to preserve codec history and the packet that
   // overlaps the selected start; copy only samples inside the chosen range.
   for await(const sample of new AudioSampleSink(audio).samples(undefined,interval.end)) {
    try {
     if(sample.timestamp+sample.duration<=first)continue;
     const values=new Float32Array(sample.numberOfFrames*sample.numberOfChannels);
     sample.copyTo(values,{planeIndex:0,format:'f32'});
     // Ignore sub-sample floating-point noise at packet boundaries. Otherwise
     // subtracting a trim offset can leave a one-sample hole between packets.
     const start=sample.timestamp-first,begin=Math.max(0,Math.ceil(start*rate-1e-7));
     const end=Math.min(total,Math.ceil(duration*rate-1e-7),Math.ceil((start+sample.duration)*rate-1e-7));
     for(let i=begin;i<end;i++) {
      const position=Math.max(0,(i/rate-start)*sample.sampleRate),j=Math.min(sample.numberOfFrames-1,Math.floor(position));
      const next=Math.min(sample.numberOfFrames-1,j+1),fraction=Math.min(1,position-j);
      let value=0;
      for(let c=0;c<sample.numberOfChannels;c++)value+=values[j*sample.numberOfChannels+c]*(1-fraction)+values[next*sample.numberOfChannels+c]*fraction;
      pcm[i]=value/sample.numberOfChannels;
     }
     progress(0,80+20*Math.min(1,(start+sample.duration)/(frames/fps)),'Normalize source audio');
    }finally{sample.close();}
   }
  }
  const audioBytes=wave(pcm);py.FS.writeFile('/work/audio_22k05_s16_mono.wav',audioBytes);py.FS.writeFile('/original-audio.wav',audioBytes);
  const defaults=await(await fetch('/python-defaults.json')).json();
  const sections={source:{path:file.name,fps:String(fps),duration:String(frames/fps),sar:'32:35'},
   video:{width,height,fit:'pad',master_denoise:false,output_dither:'bayer'},
   encoder:{cold_cap:String(settings.encoder.coldCap)},palette:{algorithm:'mosaic-gm'},output:{emit_decisions:true}};
  const profileSha256=[...new Uint8Array(await crypto.subtle.digest('SHA-256',new TextEncoder().encode(JSON.stringify(sections))))].map(v=>v.toString(16).padStart(2,'0')).join('');
  const environment={...defaults,CBRSIM_SRC:file.name,CBRSIM_FPS:String(fps),CBRSIM_DURATION:String(frames/fps),CBRSIM_W:String(width),CBRSIM_H:String(height),
   CBRSIM_GEOMETRY_FIT:'pad',CBRSIM_SOURCE_SAR:'32:35',CBRSIM_MASTER_DENOISE:'0',CBRSIM_MASTER_VF:'setsar=1',CBRSIM_RAW_VF:'setsar=1',CBRSIM_OUTPUT_DITHER:'bayer',CBRSIM_PAL_ALGO:'mosaic-gm',
   CBRSIM_COLD_CAP:String(settings.encoder.coldCap),CBRSIM_EMIT_DEC:'1'};
  const manifest={schema:1,normalizationComplete:true,profile:'browser-input.toml',profileSha256,profileSections:sections,encoderSha256:runtime.encoderSha256,
   frames,width,height,fps:String(fps),duration:String(frames/fps),audioSamples:total,environment,normalizer:'WebCodecs/Canvas RGB + 22050 Hz mono PCM',sourceName:file.name,inputSettings:settings,sourceFrameRange:interval};
  py.FS.writeFile('/work/manifest.json',JSON.stringify(manifest));progress(0,100);
  return manifest;
 } finally {input.dispose();}
}
