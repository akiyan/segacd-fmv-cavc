async function hash(bytes){
 return [...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(v=>v.toString(16).padStart(2,'0')).join('');
}

export async function loadFFmpeg(progress,log){
 const base=new URL('/ffmpeg-runtime/',self.location.origin).href;
 const response=await fetch(base+'manifest.json');
 if(!response.ok)throw new Error('Cannot load the FFmpeg runtime manifest.');
 const manifest=await response.json();
 if(manifest.schema!==1||!manifest.chunks?.length)throw new Error('Unsupported FFmpeg runtime manifest.');
 const wasmBinary=new Uint8Array(manifest.size);
 let offset=0,lastReport=0;
 for(const chunk of manifest.chunks){
  const response=await fetch(base+chunk.file);
  if(!response.ok)throw new Error(`Cannot download FFmpeg runtime: HTTP ${response.status}.`);
  const reader=response.body.getReader();let received=0;
  while(true){
   const {value,done}=await reader.read();if(done)break;
   if(received+value.length>chunk.size)throw new Error('FFmpeg runtime chunk exceeds its declared size.');
   wasmBinary.set(value,offset+received);received+=value.length;
   const now=performance.now();
   if(now-lastReport>=150||offset+received===manifest.size){
    progress(0,8*(offset+received)/manifest.size,`Load FFmpeg runtime · ${((offset+received)/1024**2).toFixed(1)} / ${(manifest.size/1024**2).toFixed(1)} MiB`);lastReport=now;
   }
  }
  if(received!==chunk.size||await hash(wasmBinary.subarray(offset,offset+received))!==chunk.sha256)
   throw new Error('FFmpeg runtime checksum failed. Reload and try again.');
  offset+=received;
 }
 if(offset!==manifest.size)throw new Error('Incomplete FFmpeg runtime.');
 progress(0,null,'Initialize FFmpeg');
 const {default:createFFmpegCore}=await import(/* @vite-ignore */ base+'ffmpeg-core.js');
 // Run in the existing encoder Worker. Cancellation terminates this whole
 // worker, with no orphan FFmpeg workers or parallel codec state to retain.
 const core=await createFFmpegCore({wasmBinary});
 let ffmpegVersion='';
 core.setLogger(({message})=>{if(message.startsWith('ffmpeg version'))ffmpegVersion=message;});
 core.exec('-version');core.reset();
 log(`FFmpeg Wasm ${manifest.version} loaded. Input remains on your device.`);
 log(ffmpegVersion);
 return {core,version:manifest.version,ffmpegVersion};
}

// image2pipe emits complete PNGs consecutively. Keep only the unfinished PNG
// in JS; release each complete image into Pyodide as soon as it is written.
export function pngStream(onFrame){
 let pending=new Uint8Array(),position=8;
 return {
  write(bytes){
   const joined=new Uint8Array(pending.length+bytes.length);joined.set(pending);joined.set(bytes,pending.length);pending=joined;
   while(pending.length>=position+12){
    if(position===8&&![137,80,78,71,13,10,26,10].every((v,i)=>pending[i]===v))throw new Error('Invalid PNG stream from FFmpeg.');
    const length=new DataView(pending.buffer,pending.byteOffset+position,4).getUint32(0);
    if(length>64*1024**2)throw new Error('Invalid PNG chunk length.');
    const end=position+length+12;if(pending.length<end)break;
    const isEnd=pending[position+4]===73&&pending[position+5]===69&&pending[position+6]===78&&pending[position+7]===68;
    position=end;
    if(isEnd){onFrame(pending.slice(0,end));pending=pending.slice(end);position=8;}
   }
  },
  finish(){if(pending.length)throw new Error('FFmpeg returned an incomplete PNG frame.');},
 };
}

export function outputDevice(core,name,onWrite,minor=0){
 const device=core.FS.makedev(64,minor);
 core.FS.registerDevice(device,{
  open(stream){stream.seekable=false;},close(){},
  write(stream,buffer,offset,length){onWrite(buffer.subarray(offset,offset+length));return length;},
 });
 core.FS.mkdev(name,0o222,device);
}
