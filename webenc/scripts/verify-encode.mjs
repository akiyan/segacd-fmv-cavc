import {chromium,expect} from '@playwright/test';
import {readFile,writeFile,mkdir} from 'node:fs/promises';
import {unzipSync} from 'fflate';
import path from 'node:path';
import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';
const output=process.env.WEBENC_TEST_OUTPUT||'/dev/shm/segacd-fmv-cavc/webenc-qa';await mkdir(output,{recursive:true});
const repo=fileURLToPath(new URL('../../',import.meta.url));
const manager=spawn(path.join(repo,'tools/python.sh'),['--gpu',path.join(repo,'webenc/harness/equivalence/lease.py'),output,...(process.env.WEBENC_INPUT?[process.env.WEBENC_INPUT]:[])],{stdio:['pipe','pipe','inherit']});
await new Promise((resolve,reject)=>{manager.stdout.once('data',resolve);manager.once('exit',code=>{if(code)reject(new Error('Fixture lease failed'));});});
const browser=await chromium.launch({headless:true});
try {
 const page=await browser.newPage({viewport:{width:1440,height:1100},acceptDownloads:true}),errors=[],alerts=[];
 page.on('dialog',async dialog=>{alerts.push({type:dialog.type(),message:dialog.message()});await dialog.dismiss();});
 page.on('pageerror',e=>errors.push(e.message));await page.goto(process.env.WEBENC_URL||'http://127.0.0.1:4173');
 const generate=page.getByRole('button',{name:'Generate CAVC',exact:true});
 if(!process.env.WEBENC_INPUT){await page.getByRole('complementary').locator('input[type=file]').setInputFiles(path.join(repo,'webenc/public/sample-test.mp4'));await expect(generate).toBeEnabled({timeout:15000});await page.getByLabel('Picture dimensions').selectOption('320x224');}
 if(process.env.WEBENC_INPUT)await page.getByRole('complementary').locator('input[type=file]').setInputFiles(process.env.WEBENC_INPUT);
 await expect(generate).toBeEnabled({timeout:15000});
 if(process.env.WEBENC_TEST_FPS)await page.getByLabel('Frame rate',{exact:true}).selectOption(process.env.WEBENC_TEST_FPS);
 if(process.env.WEBENC_TEST_DIMENSIONS)await page.getByLabel('Picture dimensions').selectOption(process.env.WEBENC_TEST_DIMENSIONS);
 if(process.env.WEBENC_TEST_SAR_PRESET)await page.getByRole('button',{name:process.env.WEBENC_TEST_SAR_PRESET,exact:true}).click();
 if(process.env.WEBENC_TEST_SAR){const [n,d]=process.env.WEBENC_TEST_SAR.split(':');await page.getByRole('button',{name:'Custom',exact:true}).click();await page.getByLabel('Pixel aspect numerator').fill(n);await page.getByLabel('Pixel aspect denominator').fill(d);}
 if(process.env.WEBENC_TEST_CAP){await page.getByRole('button',{name:'Advanced settings'}).click();await page.getByLabel('Cold cap',{exact:true}).fill(process.env.WEBENC_TEST_CAP);}
 if(process.env.WEBENC_TEST_END_FRAME)await page.getByRole('spinbutton',{name:'End frame',exact:true}).fill(process.env.WEBENC_TEST_END_FRAME);
 if(process.env.WEBENC_TEST_START_FRAME)await page.getByRole('spinbutton',{name:'Start frame',exact:true}).fill(process.env.WEBENC_TEST_START_FRAME);
 if(process.env.WEBENC_TEST_PROGRESS)await page.evaluate(()=>{
  window.progressSnapshots=[];
  new MutationObserver(()=>{
   const label=document.querySelector('.progress-detail')?.textContent||'';
   if(window.progressSnapshots.at(-1)!==label)window.progressSnapshots.push(label);
  }).observe(document.querySelector('.progress-section'),{subtree:true,childList:true,characterData:true,attributes:true});
 });
 if(process.env.WEBENC_TEST_LIVE)await page.evaluate(()=>{
  window.liveChecks={frames:[],samples:[],sourceSeeks:[],featureFrames:[]};
  const OriginalWorker=window.Worker;
  window.Worker=class extends OriginalWorker {
   constructor(...args){super(...args);this.addEventListener('message',({data})=>{
    if(data.type==='progress'&&data.detail==='Read palette frame features')window.liveChecks.featureFrames.push({frame:data.frameIndex,done:data.done,total:data.total});
    if(data.type==='frame'){window.liveChecks.frames.push({frame:data.frame,total:data.total,png:Array.from(data.png)});}
    if(data.type==='frame'||(data.type==='progress'&&Number.isInteger(data.frameIndex)))setTimeout(()=>{
     const output=document.querySelector('.live-sim-frame canvas'),source=document.querySelector('.source-frame video');
     if(source)window.liveChecks.sourceSeeks.push({frame:data.frame??data.frameIndex,time:source.currentTime,detail:data.detail||'Confirmed replay'});
     if(output)window.liveChecks.samples.push({label:output.getAttribute('aria-label'),controls:!!document.querySelector('.output-video-frame video[controls]'),busy:/^\d+% ·/.test(document.title),playback:document.querySelector('[aria-label="Output preview mode"] button[aria-pressed=true]')?.textContent});
    },0);
   });}
  };
 });
 await generate.click();
 await page.waitForFunction(()=>/^\d+% · SEGA-CD FMV Encoder for CAVC$/.test(document.title));
 if(process.env.WEBENC_TEST_LIVE){await page.locator('.live-sim-frame canvas').waitFor({state:'visible',timeout:180000});await page.screenshot({path:path.join(output,'live-sim-frame.png')});}
 const monitor=setInterval(async()=>{try{console.log((await page.locator('.log-output').textContent()).split('\n').slice(-2).join('\n'));}catch{}},15000);
 try{await page.waitForFunction(()=>document.querySelector('.notice')||document.querySelector('.download-button:not(:disabled)'),null,{timeout:Number(process.env.WEBENC_TEST_TIMEOUT||600000)});}finally{clearInterval(monitor);}
 await expect.poll(()=>alerts.length).toBe(1);expect(alerts[0]).toEqual({type:'alert',message:'Encoding complete. Download ZIP contains ISO, CUE and playback MP4.'});
 const notices=await page.locator('.notice').allTextContents();if(notices.length)throw new Error(notices.join('\n'));
 expect(await page.title()).toBe('SEGA-CD FMV Encoder for CAVC');
 if(process.env.WEBENC_TEST_PROGRESS){
  const snapshots=await page.evaluate(()=>window.progressSnapshots),text=snapshots.join('\n');
  for(const label of ['Read palette frame features','MOSAIC-GM global candidate','Quantize frames','Predict future video demand','Forecast VRAM prefetch','Encode frame decisions','Reconstruct canonical display','Create playback MP4'])expect(text).toContain(label);
  expect(text).toContain('Working…');
  await writeFile(path.join(output,'gui-progress.json'),JSON.stringify(snapshots,null,2)+'\n');
  console.log('PASS: actual palette, quantization, demand, prefetch, decisions, replay and MP4 progress reaches GUI');
 }
 const video=page.getByLabel('Encoded MP4 playback');await expect(video).toBeVisible();await video.evaluate(v=>v.play());
 await page.waitForFunction(()=>document.querySelector('.output-video-frame video')?.currentTime>0.2);
 if(process.env.WEBENC_TEST_LIVE){
  const observed=await page.evaluate(()=>window.liveChecks);
  expect(observed.frames.length).toBeGreaterThan(0);
  expect(observed.samples.some(sample=>sample.busy&&sample.playback==='Playback'&&!sample.controls)).toBe(true);
  expect(observed.sourceSeeks.length).toBeGreaterThan(0);
  const features=observed.featureFrames.filter(event=>Number.isInteger(event.frame));
  expect(features.length).toBeGreaterThan(0);expect(features[0].frame).toBe(0);
  expect(features.at(-1).frame).toBe(features.at(-1).total-1);
  expect(observed.sourceSeeks.some(event=>event.detail==='Read palette frame features')).toBe(true);
  await writeFile(path.join(output,'live-frame-check.json'),JSON.stringify(observed,null,2));
 }
 const pending=page.waitForEvent('download');await page.getByRole('button',{name:'Download ZIP',exact:true}).click();
 const download=await pending,zip=path.join(output,'encoded-cavc.zip');await download.saveAs(zip);const files=unzipSync(await readFile(zip));
 for(const name of ['preview.mp4','playback.wav','HEADER.DAT','BODY.DAT','MOVIE.DAT','settings.json','stage-sha256.tsv','encode-summary.json','analysis-timeline.tsv'])expect(files[name]?.length).toBeGreaterThan(0);
 if(process.env.WEBENC_TEST_SAR_PRESET)expect(JSON.parse(new TextDecoder().decode(files['settings.json'])).input.inputSettings.source.pixelAspect).toEqual(process.env.WEBENC_TEST_SAR_PRESET.split(':').map(Number));
 const summary=JSON.parse(new TextDecoder().decode(files['encode-summary.json']));
 expect(summary.timeline.frames).toBe(summary.frames);
 expect(Object.keys(summary.timeline.scales)).toEqual(['Req','Supply','RUN','R2V','DIC','Band']);
 await expect(page.getByRole('button',{name:'Overview',exact:true})).toHaveCount(0);
 await expect(page.getByRole('button',{name:'Palettes',exact:true})).toHaveCount(0);
 expect(summary.status).toBe('verified');expect(summary.packedStreamVerified).toBe(true);expect(summary.frames).toBe(JSON.parse(new TextDecoder().decode(files['settings.json'])).input.frames);
 expect(summary.paletteSets.length).toBeGreaterThan(0);for(const set of summary.paletteSets){expect(set.colors.length).toBe(4);for(const colors of set.colors)expect(colors.length).toBe(15);}
 await expect(page.getByLabel('Encoder decisions')).toContainText('Stream verified');
 const isoName=Object.keys(files).find(n=>n.endsWith('.iso')),cueName=Object.keys(files).find(n=>n.endsWith('.cue'));expect(isoName).toBeTruthy();expect(cueName).toBeTruthy();expect(new TextDecoder().decode(files[cueName])).toContain(`FILE "${isoName}" BINARY`);
 const iso=files[isoName],view=new DataView(iso.buffer,iso.byteOffset,iso.byteLength);expect(new TextDecoder().decode(iso.subarray(0,16))).toBe('SEGADISCSYSTEM  ');expect(new TextDecoder().decode(iso.subarray(32769,32774))).toBe('CD001');
 const root=view.getUint32(32926,true)*2048,found={};
 for(let offset=root;iso[offset];offset+=iso[offset]){const name=new TextDecoder().decode(iso.subarray(offset+33,offset+33+iso[offset+32])),extent=view.getUint32(offset+2,true)*2048,length=view.getUint32(offset+10,true);found[name]=iso.subarray(extent,extent+length);}
 for(const name of ['HEADER.DAT','BODY.DAT'])expect(Buffer.from(found[name+';1']).equals(Buffer.from(files[name]))).toBe(true);
 expect(Buffer.concat([Buffer.from(files['HEADER.DAT']),Buffer.from(files['BODY.DAT'])]).equals(Buffer.from(files['MOVIE.DAT']))).toBe(true);
 for(const name of ['preview.mp4','playback.wav',isoName,cueName,'settings.json','stage-sha256.tsv'])await writeFile(path.join(output,name),files[name]);
 await page.screenshot({path:path.join(output,'cavc-complete.png'),fullPage:true});await writeFile(path.join(output,'webapp-log.txt'),await page.locator('.log-output').textContent());expect(errors).toEqual([]);
 console.log(JSON.stringify({gate:'PASS',zip,isoName,frames:JSON.parse(new TextDecoder().decode(files['settings.json'])).input.frames}));
}finally{await browser.close();manager.stdin.end();}
