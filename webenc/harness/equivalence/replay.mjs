import {chromium} from '@playwright/test';
import {readFile,writeFile} from 'node:fs/promises';
import path from 'node:path';
const job=process.argv[2];if(!job)throw new Error('Completed independent Wasm job required');
const browser=await chromium.launch({headless:true});
try {
 const page=await browser.newPage();await page.goto('http://127.0.0.1:4173/equivalence-runner.html');
 await page.evaluate(()=>{const input=document.createElement('input');input.type='file';document.body.append(input);});
 await page.locator('input').setInputFiles(path.join(job,'wasm-decisions.pkl'));
 const result=await page.evaluate(async()=>{
  const {loadPyodide}=await import('/python-runtime/pyodide.mjs');
  const {unzipSync}=await import('/node_modules/.vite/deps/fflate.js');
  const py=await loadPyodide({indexURL:'/python-runtime/'});await py.loadPackage(['numpy','pillow']);
  const sources=unzipSync(new Uint8Array(await(await fetch('/python-codec.zip')).arrayBuffer()));
  py.FS.mkdirTree('/codec/tools');py.FS.mkdirTree('/work');
  for(const [name,bytes]of Object.entries(sources))if(/^tools\/[a-zA-Z0-9_]+\.(py|txt)$/.test(name))py.FS.writeFile('/codec/'+name,bytes);
  py.FS.writeFile('/codec/tools/replay.py',await(await fetch('/python-replay.py')).text());
  py.FS.writeFile('/work/decisions.pkl',new Uint8Array(await document.querySelector('input').files[0].arrayBuffer()));
  await py.runPythonAsync("import sys\nsys.path.insert(0,'/codec/tools')\nimport numpy as np\nnp.savez('/work/stats.npz',audio_playback_file='playback.wav')\nfrom replay import render\nrender('/work')");
  return new TextDecoder().decode(py.FS.readFile('/work/playback-frames.tsv'));
 });
 await writeFile(path.join(job,'wasm-playback-frames.tsv'),result);
 const reference=await readFile(path.join(job,'native/playback-frames.tsv'),'utf8');
 if(reference!==result)throw new Error('Browser RGB replay differs from the canonical native /sim renderer');
 console.log(`PASS: every RGB pixel of ${result.trim().split('\n').length-1} browser replay frames matches canonical /sim`);
}finally{await browser.close();}
