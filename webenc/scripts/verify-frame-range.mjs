import {fileURLToPath} from 'node:url';
import {chromium,expect} from '@playwright/test';
const browser=await chromium.launch({headless:true});
try {
 for(const [locale,region] of [['en-GB','North America'],['ja-JP','Japan']]) {
  const page=await browser.newPage({locale,viewport:{width:1440,height:1100}});
  await page.goto(process.env.WEBENC_URL||'http://127.0.0.1:4173');
  await expect(page.getByRole('button',{name:'Generate CAVC',exact:true})).toBeDisabled();
  await page.locator('input[type=file]').first().setInputFiles(fileURLToPath(new URL('../public/sample-test.mp4',import.meta.url)));
  await expect(page.getByRole('button',{name:'Generate CAVC',exact:true})).toBeEnabled();
  await page.getByLabel('Picture dimensions').selectOption('320x224');
  await expect(page.getByRole('button',{name:'Generate CAVC',exact:true})).toBeEnabled({timeout:20000});
  await expect(page.getByLabel('Picture dimensions')).toHaveValue('320x224');
  await expect(page.getByLabel('Region',{exact:true})).toHaveValue(region);
  await expect(page.getByRole('spinbutton',{name:'Start frame',exact:true})).toHaveValue('0');
  await expect(page.getByRole('spinbutton',{name:'End frame',exact:true})).toHaveValue('71');
  await page.getByRole('spinbutton',{name:'End frame',exact:true}).fill('35');
  await page.getByRole('spinbutton',{name:'Start frame',exact:true}).fill('12');
  await expect(page.getByRole('slider',{name:'Range start frame',exact:true})).toHaveValue('12');
  await expect(page.getByRole('slider',{name:'Range end frame',exact:true})).toHaveValue('35');
  await page.getByRole('slider',{name:'Range start frame',exact:true}).focus();await page.keyboard.press('ArrowRight');
  await expect(page.getByRole('spinbutton',{name:'Start frame',exact:true})).toHaveValue('13');
  const slider=await page.getByRole('slider',{name:'Range end frame',exact:true}).boundingBox();
  await page.mouse.move(slider.x+9+(slider.width-18)*35/71,slider.y+16);await page.mouse.down();await page.mouse.move(slider.x+9+(slider.width-18)*48/71,slider.y+16,{steps:8});await page.mouse.up();
  expect(Number(await page.getByRole('spinbutton',{name:'End frame',exact:true}).inputValue())).toBeGreaterThan(40);
  await page.getByRole('button',{name:'Full video',exact:true}).click();
  await expect(page.getByRole('spinbutton',{name:'Start frame',exact:true})).toHaveValue('0');
  await expect(page.getByRole('spinbutton',{name:'End frame',exact:true})).toHaveValue('71');
  await page.setViewportSize({width:390,height:844});
  expect(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth)).toBe(true);
  await page.close();
 }
 const page=await browser.newPage();await page.goto((process.env.WEBENC_URL||'http://127.0.0.1:4173')+'/equivalence-runner.html');
 const result=await page.evaluate(async()=>{
  const {normalizeVideo}=await import('/src/cavc-normalize.js');
  const {inspectVideo}=await import('/src/metadata.js');
  const file=new File([await(await fetch('/sample-test.mp4')).blob()],'sample.mp4',{type:'video/mp4'});
  const meta=await inspectVideo(file);
  const settings={source:{width:640,height:360,pixelAspect:[1,1],crop:{x:0,y:0,w:640,h:360}},video:{width:320,height:224,fps:24,fit:'pad'},encoder:{coldCap:'2:180,3:230'}};
  const run=async range=>{const files={};const py={FS:{writeFile:(p,b)=>files[p]=b}};const m=await normalizeVideo(py,file,{...settings,source:{...settings.source,frameRange:range}},{encoderSha256:'test'},()=>{},()=>{});return {m,files};};
  const full=await run({startFrame:0,endFrame:71}),cut=await run({startFrame:12,endFrame:35});
  const equal=(a,b)=>a.length===b.length&&a.every((v,i)=>v===b[i]);
  if(!equal(full.files['/work/master/00013.png'],cut.files['/work/master/00001.png']))throw new Error('First trimmed video frame differs');
  if(!equal(full.files['/work/master/00036.png'],cut.files['/work/master/00024.png']))throw new Error('Last trimmed video frame differs');
  const a=new DataView(full.files['/original-audio.wav'].buffer),b=new DataView(cut.files['/original-audio.wav'].buffer);
  let maxError=0,maxIndex=0,errorCount=0;for(let i=0;i<22050;i++){const error=Math.abs(a.getInt16(44+(i+11025)*2,true)-b.getInt16(44+i*2,true));if(error>1)errorCount++;if(error>maxError){maxError=error;maxIndex=i;}}
  if(maxError>1)throw new Error(JSON.stringify({maxError,maxIndex,errorCount,range:cut.m.sourceFrameRange,full:full.m.sourceFrameRange,expected:a.getInt16(44+(maxIndex+11025)*2,true),actual:b.getInt16(44+maxIndex*2,true)}));
  return {frames:cut.m.frames,range:cut.m.sourceFrameRange,audioMaxSampleError:maxError,sourceFrames:meta.frameTimes.length};
 });
 expect(result.frames).toBe(24);expect(result.sourceFrames).toBe(72);expect(result.range.start).toBeCloseTo(.5,6);expect(result.range.end).toBeCloseTo(1.5,6);
 console.log('PASS: language defaults, numeric bounds, keyboard/mouse range slider, mobile layout, exact selected RGB frames and synchronized PCM',result);
}finally{await browser.close();}
