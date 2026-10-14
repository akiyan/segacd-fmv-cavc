import {build} from 'esbuild';
import {readFile} from 'node:fs/promises';
import assert from 'node:assert/strict';
const bundle=await build({entryPoints:['src/delivery-plan.js'],bundle:true,write:false,format:'esm',platform:'node'});
const {rateDeltas,controlLengths,planPayload}=await import(`data:text/javascript;base64,${Buffer.from(bundle.outputFiles[0].contents).toString('base64')}`);
const cases=JSON.parse(await readFile('/dev/shm/segacd-fmv-cavc/webenc-kernel-test/schedule.json'));
let accepted=0,rejected=0;
for(const c of cases){
 assert.deepEqual(rateDeltas(c.loads.length,c.fps),c.rates,`CD cadence ${c.fps}`);
 assert.deepEqual(controlLengths(c.updates,c.runs,c.cells,c.audioBytes),c.lengths,'Control lengths');
 const result=planPayload(c.loads,c.lengths,c.fps,c.capacity);
 if(c.error){assert.equal(result.feasible,false,`${c.fps} ${c.mode}: reference rejects this schedule`);rejected++;}
 else {
  for(const [field,value] of Object.entries(c.expected))assert.deepEqual(result[field],value,`${c.fps} ${c.mode}: ${field}`);
  if(result.feasible){accepted++;assert(result.rateLead.every(v=>v===0));assert(result.ringBeforeConsume.every(v=>v<=c.capacity));}
  else rejected++;
 }
}
assert(accepted>0 && rejected>0);
console.log(`PASS: ${cases.length} complete 1-minute scheduling cases (${accepted} feasible, ${rejected} rejected), exact Python deadlines/control/ring traces.`);
