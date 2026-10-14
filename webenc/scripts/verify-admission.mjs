import {build} from 'esbuild';
import {readFile} from 'node:fs/promises';
import assert from 'node:assert/strict';
import {createKernel} from '../src/kernel.js';
const bundled=await build({stdin:{contents:"export * from './src/temporal-preview.js';export * from './src/delivery-plan.js';",resolveDir:process.cwd()},bundle:true,write:false,format:'esm',platform:'node'});
const {createTemporalPreview,selectionBudgets,previewDeliveryPlan,controlLengths}=await import(`data:text/javascript;base64,${Buffer.from(bundled.outputFiles[0].contents).toString('base64')}`);
const kernel=await createKernel(await readFile('public/wasm/webenc-kernel.wasm'));
const width=320,height=144,cells=width*height/64,cap=230,fps=30,frames=fps*60;
const constrained=createTemporalPreview(kernel,width,height,cap,fps);
const baseline=createTemporalPreview(kernel,width,height,cap,fps);
const budgets=selectionBudgets(frames,fps),records=[],original=[];
let seed=8171;
function random(){seed=(Math.imul(seed,1664525)+1013904223)>>>0;return seed;}
for(let f=0;f<frames;f++){
 const tile=new Uint8Array(cells*32),rgba=new Uint8Array(width*height*4),pmap=new Uint8Array(cells);
 for(let cell=0;cell<cells;cell++){
  for(let n=0;n<32;n++){
   const a=1+(random()>>>16)%15,b=1+(random()>>>16)%15;
   tile[cell*32+n]=(a<<4)|b;
   for(let q=0;q<2;q++){
    const index=q?b:a,x=(cell%40)*8+(n*2+q)%8,y=Math.floor(cell/40)*8+Math.floor((n*2+q)/8);
    rgba.set([(index&7)*36,(index>>3)*36,((index*3)&7)*36,255],(y*width+x)*4);
   }
  }
 }
 const input={tile,rgba,pmap};
 const a=constrained.apply(input,f,budgets[f]),b=baseline.apply(input,f);
 assert.equal(a.cap,cap,'configured cold cap must remain fixed');
 if(f>0){assert(a.cold<=cap);assert(a.cold<=budgets[f].coldBudget);}
 records.push({cold:a.cold,updates:a.updates,runs:a.runs});
 original.push({cold:b.cold,updates:b.updates,runs:b.runs});
}
const plan=previewDeliveryPlan(records,fps,cells),unrestricted=previewDeliveryPlan(original,fps,cells);
assert.equal(unrestricted.feasible,false,'sustained unconstrained loads must exceed CD delivery');
assert.equal(plan.feasible,true);
assert(plan.rateLead.every(v=>v===0));assert(plan.readyMargin.every(v=>v>=0));
assert(plan.ringBeforeConsume.every(v=>v<=plan.physicalCapacity));
const lengths=controlLengths(records.map(r=>r.updates),records.map(r=>r.runs),cells,budgets[0].audioBytes);
assert(lengths.slice(1).every((v,i)=>v<=budgets[i+1].controlByteLimit));
constrained.dispose();baseline.dispose();
// Mixed-cadence and slow streams use whole physical slots, including rate
// padding outside the useful routing count. Test full one-minute schedules.
for(const rate of [15,24,29.97,60]) {
 const count=Math.round(rate*60),b=selectionBudgets(count,rate);
 const demands=b.map((v,i)=>({cold:i===0?720:Math.min(230,v.coldBudget),updates:i===0?720:Math.min(230,v.coldBudget),runs:i===0?1:Math.min(230,v.coldBudget)}));
 const proof=previewDeliveryPlan(demands,rate,720);
 assert.equal(proof.feasible,true,`conservative ${rate} fps route`);
 assert(proof.rateLead.every(v=>v===0));
}
kernel.dispose();
console.log('PASS: complete 60-second high-demand stream fails without admission and fits with admission; same 320x144, 30fps, cold cap 230; every deadline/control/ring balance checked.');
// Resident reuse is free of pattern payload but still spends control entries.
const controlKernel=await createKernel(await readFile('public/wasm/webenc-kernel.wasm'));
const large=createTemporalPreview(controlKernel,320,224,480,15);
const tile=new Uint8Array(1120*32).fill(0x11),pmap=new Uint8Array(1120),rgba=new Uint8Array(320*224*4);
for(let i=0;i<rgba.length;i+=4)rgba.set([50,50,50,255],i);
const boot=large.apply({tile,pmap,rgba},0);
pmap.fill(1);for(let i=0;i<rgba.length;i+=4)rgba.set([200,200,200,255],i);
const budget=selectionBudgets(3,15);
const changed=large.apply({tile,pmap,rgba},1,budget[1]);
assert.equal(changed.cold,0);assert(changed.updates<1120);
assert(controlLengths([changed.updates],[changed.runs],1120,budget[1].audioBytes)[0]<=budget[1].controlByteLimit);
const completed=large.apply({tile,pmap,rgba},2,budget[2]);
assert.equal(changed.updates+completed.updates,1120);
large.dispose();controlKernel.dispose();
console.log('PASS: 320x224 / 15fps resident repoints spend control space and finish in subsequent frames.');
