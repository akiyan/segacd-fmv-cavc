import {unzipSync} from 'fflate';

const factories=new Map();
export async function runM68k(name,args,files,outputs,log=()=>{}) {
 let factory=factories.get(name);
 if(!factory) {
  const url=new URL(`/m68k-runtime/${name}.mjs`,self.location.origin).href;
  factory=(await import(/* @vite-ignore */ url)).default;factories.set(name,factory);
 }
 const module=await factory({noInitialRun:true,print:log,printErr:log});
 for(const [name,bytes]of Object.entries(files)) {
  module.FS.mkdirTree(name.slice(0,name.lastIndexOf('/'))||'/');module.FS.writeFile(name,bytes);
 }
 let status;
 try {status=module.callMain(args);}catch(error){if(error.name==='ExitStatus')status=error.status;else throw error;}
 if(status)throw new Error(`m68k ${name} exited ${status}`);
 return Object.fromEntries(outputs.map(name=>[name,module.FS.readFile(name)]));
}

export async function playerSources() {
 const archive=unzipSync(new Uint8Array(await(await fetch('/player-code.zip')).arrayBuffer()));
 return Object.fromEntries(Object.entries(archive).map(([name,bytes])=>['/'+name,bytes]));
}
export async function compileExtension(sources,log) {
 const files={...sources};
 Object.assign(files,await runM68k('as-new',['-m68000','--register-prefix-optional','--bitwise-or','-I/boot','/boot/movieplay_sp_ext.s','-o','/extension.o'],files,['/extension.o'],log));
 const result=await runM68k('ld-new',['-nostdlib','--oformat','binary','-T','/cfg/sp_ext.ld','-o','/extension.bin','/extension.o'],files,['/extension.bin'],log);
 return result['/extension.bin'];
}
export async function compilePlayer(sources,packed,extensionInclude,region,log) {
 const security=region==='North America'?'us':'jp';
 const files={...sources,'/build/disc_region.inc':sources[`/boot/region_${security}.inc`],'/build/security.bin':sources[`/boot/sec_${security}.bin`],
  '/build/dbgfont.bin':sources['/boot/dbgfont.bin'],'/build/sp_extension.inc':new TextEncoder().encode(extensionInclude)};
 for(const name of ['paltab.bin','palidx.bin','player_constants.inc'])files['/build/'+name]=packed[name];
 for(const kind of ['ip','sp']) {
  log(`Assembling original ${kind.toUpperCase()} player for the generated stream.`);
  Object.assign(files,await runM68k('as-new',['-m68000','--register-prefix-optional','--bitwise-or','--defsym','MAIN_CODEGEN=1','--defsym','PLAYER_SPECIALIZED=1','-I/build','-I/boot',`/boot/movieplay_${kind}.s`,'-o',`/build/movieplay_${kind}.o`],files,[`/build/movieplay_${kind}.o`],log));
  Object.assign(files,await runM68k('ld-new',['-nostdlib','--oformat','binary','-T',`/cfg/${kind}.ld`,'-o',`/build/movieplay_${kind}.bin`,`/build/movieplay_${kind}.o`],files,[`/build/movieplay_${kind}.bin`],log));
 }
 if(files['/build/movieplay_ip.bin'].length>18944||files['/build/movieplay_sp.bin'].length>5120)throw new Error('Player exceeds its checked memory reservation.');
 Object.assign(files,await runM68k('as-new',['-m68000','--register-prefix-optional','--bitwise-or','-I/build','-I/boot','/boot/movieplay_boot.s','-o','/build/boot.o'],files,['/build/boot.o'],log));
 const result=await runM68k('objcopy',['-O','binary','/build/boot.o','/build/boot.bin'],files,['/build/boot.bin'],log);
 if(result['/build/boot.bin'].length!==32768)throw new Error('Sega CD system area must be exactly 32768 bytes.');
 return result['/build/boot.bin'];
}
