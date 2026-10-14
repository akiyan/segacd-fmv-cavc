import {chromium,expect} from '@playwright/test';
import {spawn,execFileSync} from 'node:child_process';
import {mkdir,writeFile,readFile} from 'node:fs/promises';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
const root=fileURLToPath(new URL('../../../',import.meta.url));
const output=process.env.WEBENC_TEST_OUTPUT;
if(!output)throw new Error('Set WEBENC_TEST_OUTPUT to a managed tmpfs directory.');
const lease=spawn(path.join(root,'tools/python.sh'),['--gpu',path.join(root,'webenc/harness/equivalence/lease.py'),output],{stdio:['pipe','pipe','inherit']});
await new Promise(resolve=>lease.stdout.once('data',resolve));
const browser=await chromium.launch();
try{
 const page=await browser.newPage();
 await page.goto(process.env.WEBENC_URL||'http://127.0.0.1:4175');
 const directory=path.join(output,'ffmpeg-normalization');await mkdir(directory,{recursive:true});
 execFileSync('ffmpeg',['-v','error','-y','-i',path.join(output,'source-60fps.mp4'),'-map','0:v:0','-an','-c:v','copy',path.join(output,'ffmpeg-silent.mp4')]);
 execFileSync('ffmpeg',['-v','error','-y','-i',path.join(output,'source-60fps.mp4'),'-f','lavfi','-i','aevalsrc=0.1*sin(2*PI*440*t)|0.1*sin(2*PI*660*t):s=48000:d=2','-map','0:v:0','-map','1:a:0','-c:v','copy','-c:a','aac','-shortest',path.join(output,'ffmpeg-stereo.mp4')]);
 const cases=[
  {name:'60-to-30',source:'source-60fps.mp4',start:0,end:47,sar:[32,35],width:320,height:224,fit:'pad'},
  {name:'59.94-to-30',source:'source-59.94fps.mp4',start:0,end:47,sar:[32,35],width:320,height:224,fit:'pad'},
  {name:'trimmed',source:'source-60fps.mp4',start:12,end:59,sar:[32,35],width:320,height:224,fit:'pad'},
  {name:'square-pad',source:'source-60fps.mp4',start:0,end:47,sar:[1,1],width:320,height:224,fit:'pad'},
  {name:'square-crop',source:'source-60fps.mp4',start:0,end:47,sar:[1,1],width:320,height:224,fit:'crop'},
  {name:'custom-crop',source:'source-60fps.mp4',start:0,end:47,sar:[8,7],width:320,height:144,fit:'pad',crop:{x:13,y:17,w:281,h:183}},
  {name:'silent',source:'ffmpeg-silent.mp4',start:0,end:47,sar:[32,35],width:320,height:224,fit:'pad'},
  {name:'stereo',source:'ffmpeg-stereo.mp4',start:0,end:47,sar:[32,35],width:320,height:224,fit:'pad'},
 ];
 if(process.env.WEBENC_TEST_LONG){
  const file=path.join(output,'ffmpeg-minute.mp4');
  execFileSync('ffmpeg',['-v','error','-y','-f','lavfi','-i','testsrc2=size=640x360:rate=24:duration=60','-f','lavfi','-i','sine=frequency=440:sample_rate=48000:duration=60','-c:v','libx264','-preset','ultrafast','-pix_fmt','yuv420p','-c:a','aac','-shortest',file]);
  cases.push({name:'minute',source:'ffmpeg-minute.mp4',start:0,end:1439,sar:[1,1],width:320,height:224,fit:'pad'});
 }
 for(const item of cases){
  if(process.env.WEBENC_CASES&&!process.env.WEBENC_CASES.split(',').includes(item.name))continue;
  const source=path.join(output,item.source),bytes=await readFile(source);
  const sourceWidth=item.name==='minute'?640:320,sourceHeight=item.name==='minute'?360:224;
  const settings={source:{width:sourceWidth,height:sourceHeight,pixelAspect:item.sar,crop:item.crop||{x:0,y:0,w:sourceWidth,h:sourceHeight},frameRange:{startFrame:item.start,endFrame:item.end}},video:{width:item.width,height:item.height,fps:item.name==='minute'?24:30,fit:item.fit},encoder:{coldCap:item.name==='minute'?'2:180,3:230':'210'}};
  const result=await page.evaluate(async({bytes,name,settings})=>{
   const worker=new Worker('/harness/ffmpeg/worker.js',{type:'module'});
   const progress=[];
   try{return await new Promise((resolve,reject)=>{
    worker.onmessage=async({data})=>{
     if(data.type==='progress'){progress.push(data.values);return;}
     if(data.type==='error'){reject(new Error(data.message));return;}
     const files=await Promise.all(Object.entries(data.files).map(async([name,value])=>[name,await new Promise((resolve,reject)=>{
      const reader=new FileReader();reader.onload=()=>resolve(reader.result.split(',')[1]);reader.onerror=()=>reject(reader.error);reader.readAsDataURL(new Blob([value]));
     })]));
     resolve({manifest:data.manifest,progress,files:Object.fromEntries(files)});
    };
    worker.onerror=e=>reject(new Error(e.message));
    worker.postMessage({file:new File([Uint8Array.from(atob(bytes),c=>c.charCodeAt(0))],name,{type:'video/mp4'}),settings});
   });}finally{worker.terminate();}
  },{bytes:bytes.toString('base64'),name:item.source,settings});
  const target=path.join(directory,item.name);await mkdir(path.join(target,'master'),{recursive:true});
  for(const [name,bytes]of Object.entries(result.files))await writeFile(path.join(target,name.includes('/master/')?'master/'+path.basename(name):'audio.wav'),Buffer.from(bytes,'base64'));
  await writeFile(path.join(target,'manifest.json'),JSON.stringify(result.manifest,null,2)+'\n');
  await writeFile(path.join(target,'progress.json'),JSON.stringify(result.progress)+'\n');
  const frameEvents=result.progress.filter(values=>values[2]==='Normalize source frames');
  expect(frameEvents[0][3]).toBe(1);expect(frameEvents.at(-1)[3]).toBe(result.manifest.frames);
  expect(result.manifest.normalization.engine).toBe('ffmpeg.wasm');
  execFileSync(path.join(root,'tools/python.sh'),[path.join(root,'webenc/harness/ffmpeg/compare.py'),target,source],{stdio:'inherit'});
 }
 if(process.env.WEBENC_TEST_CANCEL){
  let alerts=0;page.on('dialog',async dialog=>{if(dialog.type()==='alert')alerts++;await dialog.dismiss();});
  await page.locator('input[type=file]').first().setInputFiles(path.join(output,'ffmpeg-minute.mp4'));
  const generate=page.getByRole('button',{name:'Generate CAVC',exact:true});await expect(generate).toBeEnabled();
  await generate.click();
  await page.waitForFunction(()=>document.querySelector('.progress-detail')?.textContent.includes('Normalize source frames'),null,{timeout:120000});
  await page.getByRole('button',{name:'Cancel',exact:true}).click();
  await expect(generate).toBeEnabled();
  await expect(page.getByRole('button',{name:'Download ZIP',exact:true})).toBeDisabled();
  expect(await page.title()).toBe('SEGA-CD FMV Encoder for CAVC');
  await page.waitForTimeout(300);expect(alerts).toBe(0);
  console.log('PASS: cancellation during real FFmpeg frame extraction restores controls and keeps output unavailable.');
 }
}finally{await browser.close();lease.stdin.end();}
