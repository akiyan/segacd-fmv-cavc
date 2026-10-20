import assert from 'node:assert/strict';
import {preparePreviewAac} from '../src/preview-audio.js';

// This browser supports generic 48 kHz AAC, but not the actual preview format.
let registered=false;
const restrictedNative=async (codec, options={})=>{
  const rate=options.sampleRate ?? 48000;
  if(rate===48000)return true;
  return registered && codec==='aac' && options.fullCodecString==='mp4a.40.2'
    && options.sampleRate===22050 && options.numberOfChannels===1 && options.bitrate===96000;
};
const fallback=await preparePreviewAac(restrictedNative,()=>{registered=true;});
assert.equal(fallback.fallback,true);
assert(registered);

// Native AAC-LC works, although an automatically inferred HE-AAC profile fails.
let unexpectedRegistration=false;
const nativeLc=async (_codec, options)=>options.fullCodecString==='mp4a.40.2'
  && options.sampleRate===22050 && options.numberOfChannels===1 && options.bitrate===96000;
const native=await preparePreviewAac(nativeLc,()=>{unexpectedRegistration=true;});
assert.equal(native.fallback,false);
assert.equal(unexpectedRegistration,false);
assert.equal(native.options.fullCodecString,'mp4a.40.2');
await assert.rejects(preparePreviewAac(async()=>false,()=>{}),/including the Wasm fallback/);
console.log('PASS: generic AAC support cannot bypass exact preview probing; explicit AAC-LC selects native or Wasm correctly.');
