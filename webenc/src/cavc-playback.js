import {Output,BufferTarget,Mp4OutputFormat,CanvasSource,AudioSampleSource,AudioSample,canEncodeAudio,canEncodeVideo} from 'mediabunny';
import {registerAacEncoder} from '@mediabunny/aac-encoder';
import {preparePreviewAac} from './preview-audio';

export function playbackPcm(bytes,duration,outputRate=22050) {
 const view=new DataView(bytes.buffer,bytes.byteOffset,bytes.byteLength);
 let rate,channels,bits,start,length;
 for(let offset=12;offset+8<=bytes.length;) {
  const type=new TextDecoder().decode(bytes.subarray(offset,offset+4)),size=view.getUint32(offset+4,true);
  if(type==='fmt '){if(view.getUint16(offset+8,true)!==1)throw new Error('Expected PCM playback WAV');channels=view.getUint16(offset+10,true);rate=view.getUint32(offset+12,true);bits=view.getUint16(offset+22,true);}
  if(type==='data'){start=offset+8;length=size;break;}
  offset+=8+size+(size%2);
 }
 if(channels!==1||bits!==16||start===undefined)throw new Error('Invalid canonical mono playback WAV');
 const sourceCount=length/2,total=Math.min(Math.ceil(duration*outputRate),Math.ceil(sourceCount/rate*outputRate)),pcm=new Float32Array(total);
 for(let i=0;i<total;i++) {
  const position=i*rate/outputRate,index=Math.min(sourceCount-1,Math.floor(position)),next=Math.min(sourceCount-1,index+1),fraction=position-index;
  pcm[i]=(view.getInt16(start+index*2,true)*(1-fraction)+view.getInt16(start+next*2,true)*fraction)/32768;
 }
 return {pcm,sourceRate:rate,sourceSamples:sourceCount};
}

export async function createSimMp4(py,metadata,log,progress) {
 const {frames,width,height,fps,audio}=metadata,duration=frames/fps;
 if(!await canEncodeVideo('avc',{width:1024,height:784,bitrate:6000000,framerate:fps}))throw new Error('H.264 playback export is unavailable in this browser.');
 const aac=await preparePreviewAac(canEncodeAudio,registerAacEncoder);
 const output=new Output({format:new Mp4OutputFormat(),target:new BufferTarget()});
 const aperture=new OffscreenCanvas(320,224),actx=aperture.getContext('2d',{alpha:false});
 const canvas=new OffscreenCanvas(1024,784),ctx=canvas.getContext('2d',{alpha:false});ctx.imageSmoothingEnabled=false;
 const videoSource=new CanvasSource(canvas,{codec:'avc',bitrate:6000000}),audioSource=new AudioSampleSource(aac.options);
 output.addVideoTrack(videoSource,{frameRate:fps});output.addAudioTrack(audioSource);
 await output.start();
 const audioBytes=py.FS.readFile('/work/'+audio),{pcm,sourceRate,sourceSamples}=playbackPcm(audioBytes,duration);
 log(`Playback uses canonical sim frames and ADPCM/RF5C164 audio (${sourceSamples} samples at ${sourceRate} Hz).`);
 const audioTask=(async()=>{
  for(let start=0;start<pcm.length;start+=22050){
   const sample=new AudioSample({data:pcm.subarray(start,Math.min(start+22050,pcm.length)),format:'f32',numberOfChannels:1,sampleRate:22050,timestamp:(start-(aac.fallback?1024:0))/22050});
   try{await audioSource.add(sample);}finally{sample.close();}
  }
  audioSource.close();
 })();audioTask.catch(()=>{});
 try {
  for(let frame=0;frame<frames;frame++) {
   const bytes=py.FS.readFile('/work/preview/'+String(frame).padStart(5,'0')+'.png');
   const image=await createImageBitmap(new Blob([bytes],{type:'image/png'}));
   actx.fillStyle='#000';actx.fillRect(0,0,320,224);actx.drawImage(image,(320-width)/2,(224-height)/2);image.close();
   ctx.drawImage(aperture,0,0,1024,784);await videoSource.add(frame/fps,1/fps);
   progress(7,(frame+1)/frames*100,'Create playback MP4',frame+1,frames);
   if(frame%100===0)log(`MP4 frames ${frame}/${frames}`);
  }
  videoSource.close();await audioTask;await output.finalize();
  return {mp4:new Uint8Array(output.target.buffer),audioBytes,sourceRate};
 }catch(error){await audioTask.catch(()=>{});throw error;}
}
