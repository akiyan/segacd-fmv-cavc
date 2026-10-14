import {chromium} from '@playwright/test';
import {readFile,writeFile} from 'node:fs/promises';
import path from 'node:path';
import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';
const job=process.argv[2];
if(!job)throw new Error('Job directory required');
const repo=fileURLToPath(new URL('../../../',import.meta.url));
const manager=spawn(path.join(repo,'tools/python.sh'),['--gpu',path.join(repo,'webenc/harness/equivalence/lease.py'),job],{stdio:['pipe','pipe','inherit']});
await new Promise((resolve,reject)=>{manager.stdout.once('data',resolve);manager.once('exit',code=>{if(code)reject(new Error('Fixture lease failed'));});});
let browser;
try {
browser=await chromium.launch({headless:true});
const page=await browser.newPage();
page.on('console',m=>console.log(m.text()));
page.on('pageerror',e=>console.log('PAGE ERROR',e.message));
page.on('requestfailed',r=>console.log('REQUEST FAILED',r.url(),r.failure()));
page.on('response',r=>{if(r.status()>=400)console.log('HTTP ERROR',r.status(),r.url());});
page.on('worker',w=>console.log('WORKER URL',w.url()));
await page.goto('http://127.0.0.1:4173/equivalence-runner.html');
await page.evaluate(()=>{
 const input=document.createElement('input');input.type='file';input.id='normalized-comparison';document.body.append(input);
});
await page.locator('#normalized-comparison').setInputFiles(path.join(job,'normalized.cavc-input.zip'));
const result=await page.evaluate(async()=>{
 const {createPythonEncoderWorker}=await import('/src/python-worker-client.js');
 const worker=createPythonEncoderWorker();
 return await new Promise((resolve,reject)=>{
  worker.onmessage=({data})=>{
   if(data.type==='log')console.log(data.message);
   if(data.type==='error'){worker.terminate();reject(new Error(data.message));}
   if(data.type==='complete'){
    // Binary transfer back through the test protocol is small (the stream,
    // not the large decoded input). Store base64 to preserve exact bytes.
    const files={};for(const [name,bytes]of Object.entries(data.files)){
     let str='';for(let i=0;i<bytes.length;i+=8192)str+=String.fromCharCode(...bytes.subarray(i,i+8192));
     files[name]=btoa(str);
    }
    worker.terminate();resolve({files,hashes:data.hashes,runtime:data.runtime});
   }
  };
  worker.onerror=e=>{console.log('WORKER ERROR',e.message,e.filename,e.lineno);reject(new Error(e.message||'Worker script failed'));};
  worker.postMessage({type:'start',file:document.getElementById('normalized-comparison').files[0]});
 });
});
for(const [name,encoded]of Object.entries(result.files))await writeFile(path.join(job,'wasm-'+name),Buffer.from(encoded,'base64'));
await writeFile(path.join(job,'wasm-result.json'),JSON.stringify({hashes:result.hashes,runtime:result.runtime},null,2)+'\n');
console.log('WASM byte outputs:',JSON.stringify(result.hashes));
} finally {
 await browser?.close();manager.stdin.end();
}
