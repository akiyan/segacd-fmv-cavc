import {chromium, expect} from '@playwright/test';
import {spawn, execFileSync} from 'node:child_process';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const repo=fileURLToPath(new URL('../../',import.meta.url));
const output=process.env.WEBENC_TEST_OUTPUT;
if(!output)throw new Error('Set WEBENC_TEST_OUTPUT to a managed fixture directory.');
const lease=spawn(path.join(repo,'tools/python.sh'),['--gpu',path.join(repo,'webenc/harness/equivalence/lease.py'),output],{stdio:['pipe','pipe','inherit']});
await new Promise(resolve=>lease.stdout.once('data',resolve));
const browser=await chromium.launch();
try {
 const page=await browser.newPage({viewport:{width:1366,height:768}}),requests=[],errors=[];
 page.on('request',request=>requests.push(request.url()));page.on('pageerror',error=>errors.push(error.message));
 await page.goto(process.env.WEBENC_URL||'http://127.0.0.1:4173');
 const generate=page.getByRole('button',{name:'Generate CAVC',exact:true});
 await expect(generate).toBeDisabled();await expect(page.getByText('Choose a source video to begin',{exact:true})).toBeVisible();
 await expect(page.getByLabel('Picture dimensions')).toHaveValue('320x224');
 expect(requests.some(url=>url.includes('sample-test.mp4'))).toBe(false);
 expect(requests.some(url=>url.includes('/ffmpeg-runtime/'))).toBe(false);
 await expect(page.getByRole('button',{name:'Download ZIP',exact:true})).toContainText('ISO · CUE · MP4');
 for(const rate of ['60','60000/1001']) {
  const file=path.join(output,`source-${rate==='60'?'60':'59.94'}fps.mp4`);
  execFileSync('ffmpeg',['-v','error','-y','-f','lavfi','-i',`testsrc2=size=320x224:rate=${rate}`,'-f','lavfi','-i','sine=frequency=440:sample_rate=22050','-frames:v','120','-c:v','libx264','-preset','fast','-pix_fmt','yuv420p','-c:a','aac','-shortest',file]);
  await page.locator('input[type=file]').first().setInputFiles(file);await expect(generate).toBeEnabled({timeout:20000});
  await expect(page.getByLabel('Frame rate',{exact:true})).toHaveValue('source');
  await expect(page.getByLabel('Frame rate',{exact:true}).locator('option:checked')).toHaveText('Auto · 30 fps');
  expect(await page.getByLabel('Frame rate',{exact:true}).locator('option').allTextContents()).toEqual(['Auto · 30 fps','15 fps','24 fps','30 fps']);
  await page.getByRole('button',{name:'32:35',exact:true}).click();await expect(page.getByRole('button',{name:'32:35',exact:true})).toHaveAttribute('aria-pressed','true');
  await page.getByRole('button',{name:'8:7',exact:true}).click();await expect(page.getByRole('button',{name:'8:7',exact:true})).toHaveAttribute('aria-pressed','true');
  const result=await page.evaluate(async name=>{
   const {normalizeVideo}=await import('/src/cavc-normalize.js');
   // The picker resets its value, so read the same selected media Blob URL.
   const video=document.querySelector('.source-frame video');
   const input=new File([await(await fetch(video.src)).blob()],name,{type:'video/mp4'});
   const {inspectVideo}=await import('/src/metadata.js');const metadata=await inspectVideo(input);
   const settings={source:{width:320,height:224,pixelAspect:[32,35],crop:{x:0,y:0,w:320,h:224},frameRange:{startFrame:0,endFrame:119}},video:{width:320,height:224,fps:30,fit:'pad'},encoder:{coldCap:'210'}};
   const run=async fps=>{const files={};const manifest=await normalizeVideo({FS:{writeFile:(name,bytes)=>files[name]=bytes}},input,{...settings,video:{...settings.video,fps}},{encoderSha256:'test'},()=>{},()=>{});return {files,manifest};};
   const converted=await run(30);
   if(Math.abs(metadata.fps-60)<.01){const full=await run(60);for(let i=0;i<converted.manifest.frames;i++){const a=converted.files['/work/master/'+String(i+1).padStart(5,'0')+'.png'],b=full.files['/work/master/'+String(i*2+1).padStart(5,'0')+'.png'];if(a.length!==b.length||!a.every((value,index)=>value===b[index]))throw new Error(`Output frame ${i} was not source frame ${i*2}`);}}
   return {sourceFps:metadata.fps,sourceFrames:metadata.frameTimes.length,outputFrames:converted.manifest.frames,outputFps:converted.manifest.fps,duration:Number(converted.manifest.duration),sourceDuration:metadata.duration,audioSamples:converted.manifest.audioSamples};
  },path.basename(file));
  expect(result.outputFps).toBe('30');expect(result.sourceFrames).toBe(120);expect(Math.abs(result.duration-result.sourceDuration)).toBeLessThan(1/30+.001);expect(result.audioSamples).toBe(Math.round(result.duration*22050));
  console.log('PASS timestamp sampling, source duration and audio rate',result);
 }
 for(const [width,height]of[[1366,768],[1024,768],[390,844]]){await page.setViewportSize({width,height});await page.waitForTimeout(200);expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);if(width>850)expect(await page.evaluate(()=>document.documentElement.scrollHeight<=innerHeight)).toBe(true);}
 expect(errors).toEqual([]);
 console.log('PASS empty startup, source aspect presets, supported output rates and ZIP labels');
}finally{await browser.close();lease.stdin.end();}
