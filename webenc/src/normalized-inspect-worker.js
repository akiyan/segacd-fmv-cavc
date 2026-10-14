import {unzipSync,strFromU8} from 'fflate';
self.onmessage=async({data})=>{
 try{
  const files=unzipSync(new Uint8Array(await data.file.arrayBuffer()),{filter:entry=>['manifest.json','raw/00001.png'].includes(entry.name)});
  const manifest=JSON.parse(strFromU8(files['manifest.json']));
  if(manifest.schema!==1 || !manifest.normalizationComplete || manifest.width%8 || manifest.height%8 || manifest.width>320 || manifest.height>224 || manifest.frames<1 || !files['raw/00001.png'])throw new Error('Invalid normalized CAVC input');
  self.postMessage({type:'complete',manifest,poster:files['raw/00001.png']},[files['raw/00001.png'].buffer]);
 }catch(error){self.postMessage({type:'error',message:error.message});}
};
