// Exercise the browser packer on frozen decisions, without rerunning training.
// This is a pack/validation regression, not independent encoder equivalence.
import {chromium} from '@playwright/test';
import {readFile,writeFile} from 'node:fs/promises';
import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
const job=process.argv[2];if(!job)throw new Error('Managed regression job directory required');
const root=fileURLToPath(new URL('../../../',import.meta.url));
const lease=spawn(path.join(root,'tools/python.sh'),[path.join(root,'webenc/harness/equivalence/lease.py'),job],{stdio:['pipe','pipe','inherit']});
await new Promise(resolve=>lease.stdout.once('data',resolve));
const browser=await chromium.launch();
try{
 const page=await browser.newPage();page.on('console',message=>console.log(message.text()));
 await page.goto(process.env.WEBENC_URL||'http://127.0.0.1:4175');
 await page.evaluate(()=>{const input=document.createElement('input');input.type='file';input.multiple=true;input.id='repack-input';document.body.append(input);});
 await page.locator('#repack-input').setInputFiles(['decisions.pkl','audio_22k05_s16_mono.wav','sp-extension.bin'].map(name=>path.join(job,name)));
 const result=await page.evaluate(async()=>{
  const {loadPyodide}=await import('/python-runtime/pyodide.mjs');
  const py=await loadPyodide({indexURL:'/python-runtime/'});await py.loadPackage(['numpy','pillow']);
  py.FS.writeFile('/codec.zip',new Uint8Array(await(await fetch('/python-codec.zip')).arrayBuffer()));
  py.FS.mkdirTree('/work/packed');py.FS.mkdirTree('/codec/tools');
  for(const file of document.querySelector('#repack-input').files)py.FS.writeFile('/work/'+file.name,new Uint8Array(await file.arrayBuffer()));
  py.FS.writeFile('/codec/tools/pack_validation.py',await(await fetch('/python-pack-validation.py')).text());
  await py.runPythonAsync(`import os,sys,zipfile,types
zipfile.ZipFile('/codec.zip').extractall('/codec')
sys.path.insert(0,'/codec/tools')
os.environ.update(CBRSIM_FPS='30',CBRSIM_W='320',CBRSIM_H='224',CBRSIM_COLD_CAP='210',CBRSIM_GPU='0',CBRSIM_WORKERS='1')
sys.modules['tmpfs_workspace']=types.ModuleType('tmpfs_workspace')
import pack_stream
from pack_validation import install
install(pack_stream)
sys.argv=['pack_stream','--dec-log','/work/decisions.pkl','--audio','/work/audio_22k05_s16_mono.wav','--sp-extension','/work/sp-extension.bin','--output','/work/packed/MOVIE.DAT','--verify']
pack_stream.main()`);
  const files={};
  for(const name of ['HEADER.DAT','BODY.DAT','MOVIE.DAT']){
   const bytes=py.FS.readFile('/work/packed/'+name);let text='';
   for(let offset=0;offset<bytes.length;offset+=8192)text+=String.fromCharCode(...bytes.subarray(offset,offset+8192));
   files[name]=btoa(text);
  }
  return files;
 });
 const rows=['artifact\tnative_bytes\twasm_bytes\tbyte_equal'];
 for(const [name,encoded]of Object.entries(result)){
  const bytes=Buffer.from(encoded,'base64'),reference=await readFile(path.join(job,'packed',name));
  const same=bytes.equals(reference);rows.push(`${name}\t${reference.length}\t${bytes.length}\t${same}`);
  if(!same)throw new Error(`Browser repack differs from native: ${name}`);
 }
 const receipt=rows.join('\n')+'\n';await writeFile(path.join(root,'logs/webenc_scroll_pack_browser_repack.tsv'),receipt);
 console.log('PASS: full browser pack verification; HEADER/BODY/MOVIE byte-identical to corrected native pack.');
}finally{await browser.close();lease.stdin.end();}
