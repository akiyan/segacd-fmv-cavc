import {chromium,expect} from '@playwright/test';
import path from 'node:path';
import {readFile} from 'node:fs/promises';
import {unzipSync} from 'fflate';
const job=process.argv[2];
if(!job)throw new Error('Normalized job directory required');
const manifest=JSON.parse(await readFile(path.join(job,'manifest.json'),'utf8'));
const browser=await chromium.launch({headless:true});
try {
 const page=await browser.newPage({viewport:{width:1440,height:1024}});
 const errors=[];page.on('pageerror',error=>errors.push(error.message));
 await page.goto(process.env.WEBENC_URL||'http://127.0.0.1:4173');
 await expect(page.getByRole('button',{name:'Generate CAVC'})).toBeEnabled({timeout:15000});
 await page.getByRole('complementary').locator('input[type=file]').setInputFiles(path.join(job,'normalized.cavc-input.zip'));
 const generate=page.getByRole('button',{name:'Generate CAVC'});
 await expect(generate).toBeEnabled({timeout:30000});
 await expect(page.getByLabel('Picture dimensions')).toHaveValue(`${manifest.width}x${manifest.height}`);
 await expect(page.getByLabel('Picture dimensions')).toBeDisabled();
 await expect(page.getByRole('spinbutton',{name:'Crop W',exact:true})).toBeDisabled();
 await expect(page.getByRole('button',{name:/Replace/})).toBeEnabled();
 await page.waitForFunction(()=>document.querySelector('.source-surface img')?.naturalWidth>0);
 await page.screenshot({path:path.join(job,'normalized-ui.png'),fullPage:true});
 await generate.click();
 await expect(page.getByRole('button',{name:'Cancel',exact:true})).toBeVisible();
 await expect(page.getByLabel('Activity log',{exact:true})).toContainText(/original Python codec/i,{timeout:10000});
 if(process.argv.includes('--complete')) {
  const monitor=setInterval(async()=>{try {console.log((await page.getByLabel('Activity log',{exact:true}).textContent()).slice(-1200));}catch{}},10000);
  const download=page.getByRole('button',{name:'Download ZIP',exact:true});
  const timeout=Number(process.env.WEBENC_TEST_TIMEOUT||3600000);
  try {await Promise.race([
   expect(download).toBeEnabled({timeout}),
   page.locator('.notice').waitFor({state:'visible',timeout}).then(async()=>{throw new Error(await page.locator('.notice').textContent());})
  ]);}
  catch(error) {console.log(await page.getByLabel('Activity log',{exact:true}).textContent());console.log(await page.locator('.notice').allTextContents());throw error;}
  finally {clearInterval(monitor);}
  const pending=page.waitForEvent('download');await download.click();
  const artifact=await pending;const file=path.join(job,'ui-cavc-stream.zip');await artifact.saveAs(file);
  const files=unzipSync(await readFile(file));
  for(const name of ['HEADER.DAT','BODY.DAT','MOVIE.DAT','settings.json','stage-sha256.tsv','playback-frames.tsv','preview.mp4','playback.wav'])expect(files[name]?.length).toBeGreaterThan(0);
  expect(Buffer.concat([Buffer.from(files['HEADER.DAT']),Buffer.from(files['BODY.DAT'])]).equals(Buffer.from(files['MOVIE.DAT']))).toBe(true);
  expect(errors).toEqual([]);
  console.log('Normalized SPA: complete original-code encode and actual CAVC ZIP download PASS');
  process.exitCode=0;
 } else {
 await page.getByRole('button',{name:'Cancel',exact:true}).click();
 await expect(generate).toBeEnabled();
 await expect(page.getByLabel('Picture dimensions')).toBeDisabled();
 await expect(page.getByRole('button',{name:/Replace/})).toBeEnabled();
 expect(errors).toEqual([]);
 console.log('Normalized SPA: import, fixed profile, first-frame preview, worker start and cancel PASS');
 }
} finally {await browser.close();}
