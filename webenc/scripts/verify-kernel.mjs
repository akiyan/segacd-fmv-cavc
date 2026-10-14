import {readFile} from 'node:fs/promises';
import assert from 'node:assert/strict';
import {createKernel} from '../src/kernel.js';
const root='/dev/shm/segacd-fmv-cavc/webenc-kernel-test';
const data=JSON.parse(await readFile(`${root}/fixture.json`));
const kernel=await createKernel(await readFile('public/wasm/webenc-kernel.wasm'));
for(const frame of data.frames){const read=async suffix=>new Uint8Array(await readFile(`${root}/${frame.stem}.${suffix}`));const result=kernel.quantize(await read('rgba'),frame.width,frame.height,await read('palette'));for(const kind of ['rgba','tile','pmap'])assert.deepEqual(result[kind],await read(`expected-${kind}`),`${frame.stem} ${kind}`);}
for(const audio of data.audio){const bytes=await readFile(`${root}/${audio.stem}.pcm`);const pcm=new Int16Array(bytes.buffer,bytes.byteOffset,bytes.length/2);const result=kernel.adpcmRoundtrip(pcm,audio.initial);assert.deepEqual(result.chunk,new Uint8Array(await readFile(`${root}/${audio.stem}.expected-chunk`)));assert.deepEqual(new Uint8Array(result.pcm.buffer),new Uint8Array(await readFile(`${root}/${audio.stem}.expected-pcm`)));assert.deepEqual(result.state,audio.final);}
const residency = kernel.createResidency(12, 17);
for (const [frame, record] of data.residency.entries()) {
  assert.deepEqual(record.keys.map(k => residency.has(new Uint8Array(k))), record.before);
  const result = residency.placeFrame(record.cells, new Uint8Array(record.keys.flat()), frame);
  assert.deepEqual(Array.from(result), record.placed.flatMap(([slot,cold]) => [slot,Number(cold)]), `residency frame ${frame}`);
}
residency.dispose();
kernel.dispose();console.log(`PASS: Wasm == Python for ${data.frames.length} quantized frames, ${data.audio.length} ADPCM chunks and ${data.residency.length} residency frames including evictions.`);
