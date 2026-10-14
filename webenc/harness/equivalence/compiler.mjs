import {chromium} from '@playwright/test';
const browser=await chromium.launch({headless:true});
try {
 const page=await browser.newPage();page.on('console',m=>console.log(m.text()));
 await page.goto('http://127.0.0.1:4173/equivalence-runner.html');
 await page.evaluate(()=>{const input=document.createElement('input');input.type='file';document.body.append(input);});
 await page.locator('input').setInputFiles(process.argv[2]);
 console.log(await page.evaluate(async(region)=>{
  const {unzipSync}=await import('/node_modules/.vite/deps/fflate.js');
  const {playerSources,compileExtension,compilePlayer}=await import('/src/m68k-player.js');
  const inputs=unzipSync(new Uint8Array(await document.querySelector('input').files[0].arrayBuffer()));
  const sources=await playerSources(),extension=await compileExtension(sources,console.log);
  const equal=(a,b)=>a.length===b.length&&a.every((v,i)=>v===b[i]);
  if(!equal(extension,inputs['sp-extension.bin']))throw new Error('Sub extension differs from native GNU assembler');
  const boot=await compilePlayer(sources,inputs,new TextDecoder().decode(inputs['sp_extension.inc']),region,console.log);
  if(!equal(boot,inputs['native-boot.bin']))throw new Error('Sega CD boot image differs from native GNU assembler/linker');
  return {gate:'PASS',extensionBytes:extension.length,bootBytes:boot.length};
 },process.argv[3]||'Japan'));
}finally{await browser.close();}
