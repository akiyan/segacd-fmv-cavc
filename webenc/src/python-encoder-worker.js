import {unzipSync,strFromU8} from 'fflate';
import {normalizeVideo} from './cavc-normalize';
import {createSimMp4} from './cavc-playback';
import {playerSources,compileExtension,compilePlayer} from './m68k-player';
import {createCavcDisc} from './cavc-disc';
const progress=(stage,value,detail='',done=0,total=0,frameIndex=null)=>{
 if(stage===0&&detail==='Normalize source frames'&&done>0)frameIndex=done-1;
 self.postMessage({type:'progress',stage,progress:value,indeterminate:value==null,detail,done,total,frameIndex,overall:(stage+(value??0)/100)/10*100});
};
const features=encoded=>self.postMessage({type:'features',summary:JSON.parse(encoded)});
const log=message=>{
 self.postMessage({type:'log',message});
 const resolve=message.match(/resolve (\d+)\/(\d+)/),replay=message.match(/Playback frames (\d+)\/(\d+)/);
 if(resolve)progress(5,100*Number(resolve[1])/Number(resolve[2]),'Resolve packed frames',Number(resolve[1]),Number(resolve[2]));
 if(replay)progress(6,100*Number(replay[1])/Number(replay[2]),'Reconstruct canonical display',Number(replay[1]),Number(replay[2]));
 if(message.includes('Assembling original IP player'))progress(8,20,'Assemble Main CPU player');
 if(message.includes('Assembling original SP player'))progress(8,50,'Assemble Sub CPU player');
};
async function sha(bytes){return [...new Uint8Array(await crypto.subtle.digest('SHA-256',bytes))].map(v=>v.toString(16).padStart(2,'0')).join('');}
self.onmessage=async({data})=>{
 if(data.type!=='start')return;
 try {
  progress(0,null,'Load Python and codec runtime');log('Loading the original CAVC encoder in WebAssembly.');
  const runtimeUrl=new URL('/python-runtime/pyodide.mjs',self.location.origin).href;
  const {loadPyodide}=await import(/* @vite-ignore */ runtimeUrl);
  const py=await loadPyodide({indexURL:'/python-runtime/',stdout:log,stderr:log});
  await py.loadPackage(['numpy','pillow']);
  const sources=unzipSync(new Uint8Array(await(await fetch('/python-codec.zip')).arrayBuffer()));
  const runtime=JSON.parse(strFromU8(sources['manifest.json']));
  py.FS.mkdirTree('/codec/tools');py.FS.mkdirTree('/work/master');py.FS.mkdirTree('/work/raw');
  for(const [name,bytes]of Object.entries(sources))if(/^tools\/[a-zA-Z0-9_]+\.(py|txt)$/.test(name))py.FS.writeFile('/codec/'+name,bytes);
  const bootSources=await playerSources();
  log('Building the original Sub extension in WebAssembly.');
  const extension=await compileExtension(bootSources,log);
  let manifest;
  if(/\.cavc-input\.zip$/i.test(data.file.name)) {
   const inputs=unzipSync(new Uint8Array(await data.file.arrayBuffer()));
   manifest=JSON.parse(strFromU8(inputs['manifest.json']));
   if(manifest.schema!==1||!manifest.normalizationComplete)throw new Error('Unsupported normalized input schema');
   if(manifest.encoderSha256!==runtime.encoderSha256)throw new Error('Normalized input and runtime encoder fingerprints differ. Regenerate the comparison data.');
   if(await sha(inputs['sp-extension.bin'])!==await sha(extension))throw new Error('Normalized input uses a different Sub extension. Regenerate it for this player version.');
   let n=0;
   for(const [name,bytes]of Object.entries(inputs)) {
    if(!/^(master|raw)\/\d{5}\.png$/.test(name)&&!['manifest.json','input-sha256.tsv','audio_22k05_s16_mono.wav'].includes(name))continue;
    py.FS.writeFile('/work/'+name,bytes);
    if(++n%128===0){progress(0,n/Object.keys(inputs).length*100);await new Promise(r=>setTimeout(r,0));}
   }
   py.FS.writeFile('/original-audio.wav',inputs['audio_22k05_s16_mono.wav']);
   log(`Normalized ${manifest.frames} frames: ${manifest.width}×${manifest.height}, ${manifest.fps} fps.`);
  }else manifest=await normalizeVideo(py,data.file,data.settings,runtime,log,progress);
  py.FS.writeFile('/work/sp-extension.bin',extension);
  progress(0,100);progress(1,0);
  for(const [name,url]of [['numeric_compat.py','/python-numeric-compat.py'],['stages.py','/python-stages.py'],['replay.py','/python-replay.py'],['prebuffer_trace.py','/python-prebuffer-trace.py'],['progress.py','/python-progress.py'],['features.py','/python-features.py'],['timeline.py','/python-timeline.py']])py.FS.writeFile('/codec/tools/'+name,await(await fetch(url)).text());
  const numeric=new Uint8Array(await(await fetch('/python-numeric.npz')).arrayBuffer());
  if(await sha(numeric)!==runtime.numericSha256)throw new Error('Native colour constants failed their runtime checksum');
  py.FS.writeFile('/codec/numeric-constants.npz',numeric);
  py.globals.set('__webenc_progress',progress);
  py.globals.set('__webenc_features',features);
  await py.runPythonAsync(await(await fetch('/python-adapter.py')).text());
  progress(5,100);progress(6,0);log('Reconstructing the canonical /sim display and playback audio.');
  let lastFrameSent=0;
  py.globals.set('__webenc_frame',(frame,path,total,width,height)=>{
   const now=performance.now();
   if(frame!==0&&frame!==total-1&&now-lastFrameSent<150)return;
   lastFrameSent=now;
   const png=py.FS.readFile(path);
   self.postMessage({type:'frame',frame,total,width,height,png},[png.buffer]);
  });
  await py.runPythonAsync("from replay import render\nrender('/work', __webenc_frame)");
  const playback=JSON.parse(new TextDecoder().decode(py.FS.readFile('/work/playback.json')));
  const files={};
  for(const name of ['HEADER.DAT','BODY.DAT','MOVIE.DAT','paltab.bin','palidx.bin','player_constants.inc'])files[name]=py.FS.readFile('/work/packed/'+name);
  files['stage-sha256.tsv']=py.FS.readFile('/work/stage-sha256.tsv');
  files['encode-summary.json']=py.FS.readFile('/work/encode-summary.json');
  files['analysis-timeline.tsv']=py.FS.readFile('/work/analysis-timeline.tsv');
  files['playback-frames.tsv']=py.FS.readFile('/work/playback-frames.tsv');
  files['decisions.pkl']=py.FS.readFile('/work/decisions.pkl');
  await py.runPythonAsync("from sp_extension import metadata,render_include\nfrom pathlib import Path\nPath('/work/sp_extension.inc').write_text(render_include(metadata(Path('/work/sp-extension.bin').read_bytes())))");
  progress(6,100);progress(7,0);
  const encoded=await createSimMp4(py,playback,log,progress);
  files['preview.mp4']=encoded.mp4;files['playback.wav']=encoded.audioBytes;
  progress(8,0);
  const boot=await compilePlayer(bootSources,files,new TextDecoder().decode(py.FS.readFile('/work/sp_extension.inc')),data.settings?.region||'Japan',log);
  const disc=createCavcDisc(boot,files['HEADER.DAT'],files['BODY.DAT'],data.file.name.replace(/\.(cavc-input\.zip|mp4|webm|mov)$/i,''));
  files[disc.name+'.iso']=disc.iso;files[disc.name+'.cue']=new TextEncoder().encode(disc.cue);
  progress(8,100);progress(9,0);
  const hashes={},entries=Object.entries(files);let hashed=0;
  for(const [name,bytes]of entries){hashes[name]=await sha(bytes);progress(9,++hashed/entries.length*90,'Check download files');}
  self.postMessage({type:'complete',files,hashes,manifest,runtime,playback,discName:disc.name},Object.values(files).map(bytes=>bytes.buffer));
 }catch(error){self.postMessage({type:'error',message:String(error.stack||error)});}
};
