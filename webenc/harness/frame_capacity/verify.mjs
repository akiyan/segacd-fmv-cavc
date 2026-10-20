// Compile a real maximum-length stream contract with both native and Wasm GNU tools.
import {readFile,mkdir,copyFile} from 'node:fs/promises';
import {execFileSync} from 'node:child_process';
import {homedir} from 'node:os';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import assert from 'node:assert/strict';
import {createServer} from 'vite';
import {chromium} from '@playwright/test';

const root=path.resolve(fileURLToPath(new URL('../../',import.meta.url)));
const repo=path.dirname(root);
const fixtures=process.argv.slice(2).map(name=>path.resolve(name));
assert(fixtures.length,'Pass one or more packed fixture directories.');
const server=await createServer({root,logLevel:'error',server:{host:'127.0.0.1',port:0}});
let browser;
try{
 await server.listen();
 browser=await chromium.launch({headless:true});
 const page=await browser.newPage();
 await page.goto(server.resolvedUrls.local[0]+'python-defaults.json');
 for(const fixture of fixtures){
  const work=path.join(fixture,'wasm-proof');await mkdir(work,{recursive:true});
  for(const name of ['paltab.bin','palidx.bin','player_constants.inc','sp_extension.inc','dbgfont.bin','security.bin','disc_region.inc'])
   await copyFile(path.join(fixture,name),path.join(work,name));
  const tool=name=>path.join(homedir(),'toolchains/mars/m68k-elf/bin/m68k-elf-'+name);
  const includes=['-I'+work,'-I'+path.join(repo,'boot')];
  const flags=['-m68000','--register-prefix-optional','--bitwise-or',...includes];
  for(const domain of ['ip','sp']){
   execFileSync(tool('as'),[...flags,'--defsym','MAIN_CODEGEN=1','--defsym','PLAYER_SPECIALIZED=1',path.join(repo,`boot/movieplay_${domain}.s`),'-o',path.join(work,domain+'.o')]);
   execFileSync(tool('ld'),['-nostdlib','--oformat','binary','-T',path.join(repo,`cfg/${domain}.ld`),'-o',path.join(work,`movieplay_${domain}.bin`),path.join(work,domain+'.o')]);
  }
  execFileSync(tool('as'),[...flags,path.join(repo,'boot/movieplay_boot.s'),'-o',path.join(work,'boot.o')]);
  execFileSync(tool('objcopy'),['-O','binary',path.join(work,'boot.o'),path.join(work,'boot.bin')]);
  const packed={};
  for(const name of ['paltab.bin','palidx.bin','player_constants.inc','sp_extension.inc'])
   packed[name]=[...await readFile(path.join(work,name))];
  const result=await page.evaluate(async input=>{
   const {compilePlayer,playerSources}=await import('/src/m68k-player.js');
   const sources=await playerSources();
   const packed=Object.fromEntries(Object.entries(input).map(([name,data])=>[name,new Uint8Array(data)]));
   const boot=await compilePlayer(sources,packed,new TextDecoder().decode(packed['sp_extension.inc']),'Japan',()=>{});
   return [...boot];
  },packed);
  const native=await readFile(path.join(work,'boot.bin'));
  assert.equal(native.length,32768);
  assert.deepEqual(Buffer.from(result),native);
  console.log(`PASS: native/Wasm boot bytes identical for ${path.basename(fixture)}`);
 }
}finally{
 await browser?.close();await server.close();
}
