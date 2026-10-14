import {chromium,expect} from '@playwright/test';
import {readFile,writeFile} from 'node:fs/promises';
import {spawn} from 'node:child_process';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const job=process.argv[2];if(!job)throw new Error('Completed browser encode required');
const repo=fileURLToPath(new URL('../../../',import.meta.url));
const manager=spawn(path.join(repo,'tools/python.sh'),['--gpu',path.join(repo,'webenc/harness/equivalence/lease.py'),job],{stdio:['pipe','pipe','inherit']});
await new Promise((resolve,reject)=>{manager.stdout.once('data',resolve);manager.once('exit',code=>{if(code)reject(new Error('Fixture lease failed'));});});
const manifest=JSON.parse(await readFile(path.join(job,'manifest.json'),'utf8'));
const [numerator,denominator=1]=String(manifest.fps).split('/').map(Number),fps=numerator/denominator;
const browser=await chromium.launch({headless:true});
try {
 const page=await browser.newPage({viewport:{width:1100,height:850}});
 await page.goto('http://127.0.0.1:4173/equivalence-runner.html');
 await page.evaluate(()=>{document.body.innerHTML='<input type="file"><video controls muted style="width:1024px;height:784px"></video>';});
 await page.locator('input').setInputFiles(path.join(job,'wasm-preview.mp4'));
 await page.evaluate(()=>{document.querySelector('video').src=URL.createObjectURL(document.querySelector('input').files[0]);});
 await page.waitForFunction(()=>document.querySelector('video').readyState>=2);
 const duration=await page.locator('video').evaluate(v=>v.duration);
 expect(Math.abs(duration-manifest.frames/fps)).toBeLessThan(0.1);
 await page.locator('video').evaluate(v=>v.play());
 await page.waitForFunction(()=>document.querySelector('video').currentTime>0.2);
 await page.locator('video').evaluate(v=>v.pause());
 const checks=[['middle',manifest.frames/fps/2],['late',manifest.frames/fps*0.98]];
 for(const [name,time]of checks) {
  await page.locator('video').evaluate((v,time)=>new Promise(resolve=>{v.addEventListener('seeked',resolve,{once:true});v.currentTime=time;}),time);
  await page.locator('video').screenshot({path:path.join(job,'browser-playback-'+name+'.png')});
 }
 const result={gate:'PASS',browserPlayback:true,duration,seekChecks:checks};
 await writeFile(path.join(job,'browser-playback-check.json'),JSON.stringify(result,null,2)+'\n');
 console.log(JSON.stringify(result));
}finally{await browser.close();manager.stdin.end();}
