import {build} from 'esbuild';
import {readFile} from 'node:fs/promises';
import assert from 'node:assert/strict';
import {createKernel} from '../src/kernel.js';
const bundled = await build({entryPoints:['src/temporal-preview.js'],bundle:true,write:false,format:'esm',platform:'node'});
const {createTemporalPreview,frameColdCap} = await import(`data:text/javascript;base64,${Buffer.from(bundled.outputFiles[0].contents).toString('base64')}`);
const kernel = await createKernel(await readFile('public/wasm/webenc-kernel.wasm'));
const temporal = createTemporalPreview(kernel,32,8,1,30);
function frame(values) {
 const tile=new Uint8Array(128),pmap=new Uint8Array(4),rgba=new Uint8Array(32*8*4);
 values.forEach((v,c)=>{
  tile.fill(v*17,c*32,c*32+32);
  for(let y=0;y<8;y++)for(let x=0;x<8;x++)rgba.set([v*20,v*20,v*20,255],(y*32+c*8+x)*4);
 });
 return {tile,pmap,rgba};
}
let r=temporal.apply(frame([1,2,3,4]),0);
assert.equal(r.cold,4,'frame 0 must not be capped');
r=temporal.apply(frame([5,6,7,9]),1);
assert.equal(r.cold,1);assert.equal(r.updates,1);
assert.equal(r.rgba[(0*32+24)*4],180,'largest display error must update first');
r=temporal.apply(frame([9,9,9,9]),2);
assert.equal(r.cold,0);assert.equal(r.updates,3,'resident patterns must be free to repoint');
assert(r.rgba.filter((_,i)=>i%4===0).every(v=>v===180));
// A repeated fresh pattern costs one load even when every cell changes.
r=temporal.apply(frame([10,10,10,10]),3);assert.equal(r.cold,1);assert.equal(r.updates,4);
r=temporal.apply(frame([10,10,10,10]),4);assert.equal(r.cold,0);assert.equal(r.updates,0);
assert.deepEqual(Array.from({length:7},(_,f)=>frameColdCap('2:180,3:230',24,f)),[230,180,230,180,230,180,230]);
temporal.dispose();kernel.dispose();
console.log('PASS: untimed frame 0, exact reuse, unique cold counting, cap enforcement, priority and 24fps cadence.');
