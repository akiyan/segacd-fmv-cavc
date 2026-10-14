import {chromium,expect} from '@playwright/test';
import {spawn} from 'node:child_process';
import {fileURLToPath} from 'node:url';
import path from 'node:path';
const repo=fileURLToPath(new URL('../../',import.meta.url));
const output=process.env.WEBENC_TEST_OUTPUT,input=process.env.WEBENC_INPUT;
if(!output||!input)throw new Error('Set WEBENC_TEST_OUTPUT and WEBENC_INPUT to managed fixture paths. Input must be a 320x224 square-pixel MP4.');
const lease=spawn(path.join(repo,'tools/python.sh'),['--gpu',path.join(repo,'webenc/harness/equivalence/lease.py'),output,input],{stdio:['pipe','pipe','inherit']});
await new Promise(resolve=>lease.stdout.once('data',resolve));
const browser=await chromium.launch();
try {
 const page=await browser.newPage(),errors=[];page.on('pageerror',error=>errors.push(error.message));
 await page.goto(process.env.WEBENC_URL||'http://127.0.0.1:4173');
 await page.locator('input[type=file]').first().setInputFiles(input);
 await expect(page.getByRole('button',{name:'Generate CAVC',exact:true})).toBeEnabled({timeout:20000});
 await page.getByRole('button',{name:'32:35',exact:true}).click();
 if(process.env.WEBENC_TEST_START_FRAME)await page.getByRole('spinbutton',{name:'Start frame',exact:true}).fill(process.env.WEBENC_TEST_START_FRAME);
 await page.waitForFunction(()=>document.querySelector('.source-frame video').readyState>=2&&!document.querySelector('.source-frame video').seeking);
 for(const [width,height]of[[1920,1080],[1366,768],[1024,768],[390,844]]){
  await page.setViewportSize({width,height});await page.waitForTimeout(400);
  const result=await page.evaluate(()=>{
   const r=s=>document.querySelector(s).getBoundingClientRect();
   const source=r('.source-surface'),canvas=r('.output-frame canvas'),frame=r('.output-frame');
   return {size:[innerWidth,innerHeight],sourceRatio:source.width/source.height,canvasRatio:canvas.width/canvas.height,objectFit:getComputedStyle(document.querySelector('.output-frame canvas')).objectFit,contained:canvas.width<=frame.width&&canvas.height<=frame.height,frameRatio:frame.width/frame.height,horizontalOverflow:document.documentElement.scrollWidth>innerWidth};
  });
  expect(result.canvasRatio).toBeCloseTo(64/49,3);expect(result.sourceRatio).toBeCloseTo(result.canvasRatio,3);
  expect(result.objectFit).toBe('fill');expect(result.contained).toBe(true);expect(result.frameRatio).toBeCloseTo(4/3,3);expect(result.horizontalOverflow).toBe(false);
  console.log('PASS H40 source/framing proportions',result);
  if(width===1920)await page.screenshot({path:path.join(output,'lunar-framing-aspect-corrected.png')});
 }
 expect(errors).toEqual([]);
}finally{await browser.close();lease.stdin.end();}
