import {zipSync,strToU8} from 'fflate';

export function createCavcPackage(data) {
 const files={};
 const names=['HEADER.DAT','BODY.DAT','MOVIE.DAT','stage-sha256.tsv','playback-frames.tsv','preview.mp4','playback.wav',data.discName+'.iso',data.discName+'.cue'];
 for(const name of names) {
  if(!data.files[name]?.length)throw new Error(`Missing generated ${name}`);
  files[name]=data.files[name];
 }
 if(data.files['analysis-timeline.tsv'])files['analysis-timeline.tsv']=data.files['analysis-timeline.tsv'];
 if(data.files['encode-summary.json'])files['encode-summary.json']=data.files['encode-summary.json'];
 files['settings.json']=strToU8(JSON.stringify({input:data.manifest,runtime:data.runtime,hashes:data.hashes},null,2)+'\n');
 files['README.txt']=strToU8('Original CAVC codec in WebAssembly: MOSAIC-GM, Bayer dither, full update decisions, WordBuf/DicBuf/PrgBuf scheduling.\nISO and CUE form a bootable Sega CD disc. BIOS is supplied separately to an emulator.\npreview.mp4 reproduces the canonical sim display with reconstructed ADPCM/RF5C164 playback audio. playback.wav is the canonical PCM model before AAC export.\nHEADER.DAT and BODY.DAT are the on-disc stream; MOVIE.DAT is the offline compatibility container.\nNo source upload was performed.\n');
 return zipSync(files);
}
