import {readFile, writeFile, mkdir, copyFile, rm} from 'node:fs/promises';
import {createHash} from 'node:crypto';
import {fileURLToPath} from 'node:url';
import path from 'node:path';

const root=fileURLToPath(new URL('../',import.meta.url));
const source=path.join(root,'node_modules/@ffmpeg/core');
const version=JSON.parse(await readFile(path.join(source,'package.json'))).version;
const target=path.join(root,'public/ffmpeg-runtime');
await rm(target,{recursive:true,force:true});await mkdir(target,{recursive:true});
await copyFile(path.join(source,'dist/esm/ffmpeg-core.js'),path.join(target,'ffmpeg-core.js'));
// Pages limits individual assets to 25 MiB. Reassemble verified chunks only
// when Generate needs FFmpeg; no large runtime is downloaded on startup.
const bytes=await readFile(path.join(source,'dist/esm/ffmpeg-core.wasm'));
const chunks=[];
for(let offset=0,index=0;offset<bytes.length;offset+=8*1024**2,index++){
 const chunk=bytes.subarray(offset,Math.min(bytes.length,offset+8*1024**2));
 const file=`ffmpeg-core-${index}.wasm.part`;
 await writeFile(path.join(target,file),chunk);
 chunks.push({file,size:chunk.length,sha256:createHash('sha256').update(chunk).digest('hex')});
}
await writeFile(path.join(target,'manifest.json'),JSON.stringify({schema:1,package:'@ffmpeg/core',version,size:bytes.length,chunks},null,2)+'\n');
const sourceRevision='71aa99d37c02a7b4c435275ca9ef50e612f6efa1';
const cache=path.join(root,'.toolchain/ffmpeg-sources');await mkdir(cache,{recursive:true});
const sources=[
 {file:'ffmpeg.wasm-source.tar.gz',url:`https://codeload.github.com/ffmpegwasm/ffmpeg.wasm/tar.gz/${sourceRevision}`},
 {file:'ffmpeg-5.1.4-source.tar.gz',url:'https://codeload.github.com/FFmpeg/FFmpeg/tar.gz/refs/tags/n5.1.4'},
 {file:'COPYING.GPLv2',url:'https://raw.githubusercontent.com/FFmpeg/FFmpeg/n5.1.4/COPYING.GPLv2'},
 {file:'COPYING.GPLv3',url:'https://raw.githubusercontent.com/FFmpeg/FFmpeg/n5.1.4/COPYING.GPLv3'},
];
for(const source of sources){
 const file=path.join(cache,createHash('sha256').update(source.url).digest('hex').slice(0,12)+'-'+source.file);
 let bytes;try{bytes=await readFile(file);}catch{
  const response=await fetch(source.url);if(!response.ok)throw new Error(`Cannot prepare FFmpeg sources: ${response.status}`);
  bytes=new Uint8Array(await response.arrayBuffer());await writeFile(file,bytes);
 }
 if(bytes.length>25*1024**2)throw new Error(`FFmpeg source asset exceeds Pages limit: ${source.file}`);
 source.sha256=createHash('sha256').update(bytes).digest('hex');
 await writeFile(path.join(target,source.file),bytes);
}
await writeFile(path.join(target,'sources.json'),JSON.stringify({coreVersion:version,sourceRevision,sources,
 buildRecipe:`https://github.com/ffmpegwasm/ffmpeg.wasm/blob/${sourceRevision}/Dockerfile`,
 dependencySources:'The build recipe identifies each bundled library repository and its source branch/tag.'},null,2)+'\n');
await writeFile(path.join(target,'LICENSE.txt'),`@ffmpeg/core ${version}\nGPL-2.0-or-later; see COPYING.GPLv2 and COPYING.GPLv3.\nFFmpeg and bundled libraries retain their respective licenses.\nFFmpeg source and Wasm bindings/build scripts are available alongside this file.\nSee sources.json and the pinned upstream Dockerfile for bundled dependency sources.\n`);
console.log(`Prepared self-hosted FFmpeg ${version}: ${chunks.length} verified Wasm chunks.`);
