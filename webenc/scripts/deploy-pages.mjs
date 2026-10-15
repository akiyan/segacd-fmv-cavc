#!/usr/bin/env node
// cf manages Pages; the documented assets API fills its missing upload command.
import {cp,mkdir,readFile,readdir,rm,writeFile,stat} from 'node:fs/promises';
import {execFileSync} from 'node:child_process';
import {homedir} from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {hashFile} from '@cloudflare/deploy-helpers';
import mime from 'mime';

const root=fileURLToPath(new URL('../',import.meta.url));
const config=JSON.parse(await readFile(path.join(root,'cloudflare-pages.json'),'utf8'));
const destination=path.join(root,'dist/pages');
await rm(destination,{recursive:true,force:true});await mkdir(destination,{recursive:true});
const excluded=new Set(['sample-test.mp4','sample-coast.png','equivalence-runner.html']);
for(const name of await readdir(path.join(root,'dist/client'))){
 if(!excluded.has(name))await cp(path.join(root,'dist/client',name),path.join(destination,name),{recursive:true});
}
await writeFile(path.join(destination,'_headers'),`/*
  Cross-Origin-Opener-Policy: same-origin
  Cross-Origin-Embedder-Policy: require-corp
  X-Content-Type-Options: nosniff
  Speculation-Rules: "/offline-speculation.json"
/assets/*
  Cache-Control: public, max-age=31536000, immutable
/offline-worker.js
  Cache-Control: no-cache
/offline-manifest.json
  Cache-Control: no-cache
`);
const files=[];
async function collect(directory){
 for(const entry of await readdir(directory,{withFileTypes:true})){
  const file=path.join(directory,entry.name);
  if(entry.isDirectory()){await collect(file);continue;}
  if(entry.name==='_headers')continue;
  const size=(await stat(file)).size;
  if(size>25*1024**2)throw new Error(`Pages asset exceeds 25 MiB: ${path.relative(destination,file)}`);
  files.push({file,size,key:hashFile(file),name:'/'+path.relative(destination,file).split(path.sep).join('/'),type:mime.getType(file)||'application/octet-stream'});
 }
}
await collect(destination);
if(files.length>20000)throw new Error('Pages asset count exceeds 20000.');
const manifest=Object.fromEntries(files.map(file=>[file.name,file.key]));
await writeFile(path.join(root,'dist/pages-manifest.json'),JSON.stringify(manifest,null,2)+'\n');
console.log(`Pages build: ${files.length} assets, ${(files.reduce((sum,file)=>sum+file.size,0)/1024**2).toFixed(1)} MiB; largest ${(Math.max(...files.map(file=>file.size))/1024**2).toFixed(1)} MiB.`);
if(process.argv.includes('--dry-run'))process.exit(0);

function cf(args,environment={}){
 return JSON.parse(execFileSync('cf',args,{cwd:root,encoding:'utf8',env:{...process.env,...environment},maxBuffer:16*1024**2}));
}
const zones=cf(['zones','list','--name',config.zone]);
if(zones.length!==1)throw new Error(`Expected one accessible zone for ${config.zone}.`);
const accountId=zones[0].account.id;
const environment={CLOUDFLARE_ACCOUNT_ID:accountId};
const projects=cf(['pages','list'],environment);
if(!projects.some(project=>project.name===config.project))cf(['pages','create','--name',config.project,'--production-branch',config.branch],environment);
// Read the existing cf default OAuth session privately. Tokens never enter
// command arguments, logs, build output or deployment receipts.
const token=process.env.CLOUDFLARE_API_TOKEN||JSON.parse(await readFile(path.join(process.env.XDG_CONFIG_HOME||path.join(homedir(),'.config'),'cloudflare/config/default.json'),'utf8')).oauth_token;
if(!token)throw new Error('Run cf auth login before deploying.');
async function api(endpoint,auth,body){
 const response=await fetch('https://api.cloudflare.com/client/v4'+endpoint,{method:body===undefined?'GET':'POST',headers:{Authorization:`Bearer ${auth}`,...(body===undefined?{}:{'Content-Type':'application/json'})},body:body===undefined?undefined:JSON.stringify(body),signal:AbortSignal.timeout(120000)});
 const data=await response.json();
 if(!response.ok||data.success===false)throw new Error(`Cloudflare API ${endpoint}: ${JSON.stringify(data.errors||response.status)}`);
 return data.result;
}
const {jwt}=await api(`/accounts/${accountId}/pages/projects/${config.project}/upload-token`,token);
const missing=new Set(await api('/pages/assets/check-missing',jwt,{hashes:files.map(file=>file.key)}));
let uploaded=0,batch=[],size=0;
async function upload(){
 if(!batch.length)return;
 const payload=await Promise.all(batch.map(async file=>({key:file.key,value:(await readFile(file.file)).toString('base64'),metadata:{contentType:file.type},base64:true})));
 for(let attempt=0;;attempt++){
  try{await api('/pages/assets/upload',jwt,payload);break;}
  catch(error){if(attempt>=2)throw error;await new Promise(resolve=>setTimeout(resolve,1000*2**attempt));}
 }
 uploaded+=batch.length;console.log(`Uploaded ${uploaded}/${missing.size} missing assets.`);batch=[];size=0;
}
for(const file of files.filter(file=>missing.has(file.key))){
 if(size+file.size>20*1024**2)await upload();
 batch.push(file);size+=file.size;
}
await upload();
await api('/pages/assets/upsert-hashes',jwt,{hashes:files.map(file=>file.key)});
const commit=execFileSync('git',['rev-parse','HEAD'],{cwd:root,encoding:'utf8'}).trim();
const deployment=cf(['pages','deployments','create',config.project,'--branch',config.branch,'--commit-hash',commit,'--commit-dirty','true','--commit-message','ブラウザ版エンコーダーを公開','--manifest',JSON.stringify(manifest),'--file',path.join(destination,'_headers')],environment);
const receipt={project:config.project,accountId,domain:config.domain,deploymentId:deployment.id,url:deployment.url,stage:deployment.latest_stage,assets:files.length};
await writeFile(path.join(root,'dist/pages-deployment.json'),JSON.stringify(receipt,null,2)+'\n');
console.log(JSON.stringify(receipt,null,2));
