import {readFile,writeFile,mkdir,copyFile,readdir} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {zipSync,strToU8} from 'fflate';
import {execFileSync} from 'node:child_process';
const root=fileURLToPath(new URL('../',import.meta.url)),repo=path.resolve(root,'..');
const pkg=path.join(root,'node_modules/pyodide');
const lock=JSON.parse(await readFile(path.join(pkg,'pyodide-lock.json')));
const version=JSON.parse(await readFile(path.join(pkg,'package.json'))).version;
const dest=path.join(root,'public/python-runtime');await mkdir(dest,{recursive:true});
for(const name of ['pyodide.mjs','pyodide.asm.mjs','pyodide.asm.wasm','python_stdlib.zip','pyodide-lock.json'])
 await copyFile(path.join(pkg,name),path.join(dest,name));
for(const name of ['numpy','pillow']){
 const info=lock.packages[name],target=path.join(dest,info.file_name);
 let bytes;try{bytes=await readFile(target);}catch{}
 if(!bytes || createHash('sha256').update(bytes).digest('hex')!==info.sha256){
  const response=await fetch(`https://cdn.jsdelivr.net/pyodide/v${version}/full/${info.file_name}`);
  if(!response.ok)throw new Error(`Cannot fetch ${name}: ${response.status}`);
  bytes=new Uint8Array(await response.arrayBuffer());
  if(createHash('sha256').update(bytes).digest('hex')!==info.sha256)throw new Error(`Checksum mismatch: ${name}`);
  await writeFile(target,bytes);
 }
}
// Freeze only the 512 hardware colours and their comparison constants.
// This never reads source media, quantized frames or native encode decisions.
const numericFile=path.join(root,'public/python-numeric.npz');
execFileSync(path.join(repo,'tools/python.sh'),['--gpu',path.join(root,'harness/equivalence/numeric.py'),
 '--tools',path.join(repo,'tools'),'--output',numericFile],{stdio:'inherit'});
const numericSha256=createHash('sha256').update(await readFile(numericFile)).digest('hex');
const entries={},fingerprint=createHash('sha256');
for(const name of (await readdir(path.join(repo,'tools'))).filter(n=>n.endsWith('.py')).sort()){
 const bytes=await readFile(path.join(repo,'tools',name));entries[`tools/${name}`]=bytes;fingerprint.update(name);fingerprint.update(bytes);
}
entries['tools/av_version.txt']=await readFile(path.join(repo,'tools/av_version.txt'));
entries['manifest.json']=strToU8(JSON.stringify({schema:1,encoderSha256:fingerprint.digest('hex'),runtime:version,python:lock.info.python,numpy:lock.packages.numpy.version,numericSha256}));
await writeFile(path.join(root,'public/python-codec.zip'),zipSync(entries,{level:6}));
console.log(`Prepared self-hosted Python/Wasm ${version}, NumPy ${lock.packages.numpy.version}, Pillow ${lock.packages.pillow.version}; no media or BIOS included.`);

await copyFile(path.join(root,"harness/equivalence/browser.py"),path.join(root,"public/python-adapter.py"));

await copyFile(path.join(root,"harness/equivalence/stages.py"),path.join(root,"public/python-stages.py"));

await copyFile(path.join(root,"harness/equivalence/numeric_compat.py"),path.join(root,"public/python-numeric-compat.py"));
await copyFile(path.join(root,'harness/equivalence/replay.py'),path.join(root,'public/python-replay.py'));
await copyFile(path.join(root,'harness/equivalence/prebuffer_trace.py'),path.join(root,'public/python-prebuffer-trace.py'));
await copyFile(path.join(root,'harness/equivalence/progress.py'),path.join(root,'public/python-progress.py'));
await copyFile(path.join(root,'harness/equivalence/features.py'),path.join(root,'public/python-features.py'));
execFileSync(path.join(repo,'tools/python.sh'),['--gpu','-c',
 `import sys,json;sys.path.insert(0,${JSON.stringify(path.join(repo,'tools'))});from encode_config import PROFILE_ENV_DEFAULTS;from pathlib import Path;Path(${JSON.stringify(path.join(root,'public/python-defaults.json'))}).write_text(json.dumps(PROFILE_ENV_DEFAULTS))`],{stdio:'inherit'});

await copyFile(path.join(root,'harness/equivalence/timeline.py'),path.join(root,'public/python-timeline.py'));
await copyFile(path.join(root,'harness/equivalence/pack_validation.py'),path.join(root,'public/python-pack-validation.py'));
