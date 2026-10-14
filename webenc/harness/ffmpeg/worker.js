import {normalizeVideo} from '../../src/cavc-normalize';
self.onmessage=async({data:{file,settings}})=>{
 try{
  const files={};
  const py={FS:{writeFile:(name,bytes)=>{if(name.includes('/master/')||name==='/original-audio.wav')files[name]=bytes;}}};
  const progress=(...values)=>self.postMessage({type:'progress',values});
  const manifest=await normalizeVideo(py,file,settings,{encoderSha256:'normalization-fixture'},()=>{},progress);
  self.postMessage({type:'complete',manifest,files},Object.values(files).map(bytes=>bytes.buffer));
 }catch(error){self.postMessage({type:'error',message:String(error.stack||error)});}
};
