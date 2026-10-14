import {mkdir,readFile,writeFile,copyFile} from 'node:fs/promises';
import {execFileSync} from 'node:child_process';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {zipSync} from 'fflate';
const root=fileURLToPath(new URL('../',import.meta.url)),repo=path.resolve(root,'..');
const build=path.join(root,'.toolchain/binutils-build'),dest=path.join(root,'public/m68k-runtime');
await mkdir(dest,{recursive:true});
for(const [directory,name]of [['gas','as-new'],['ld','ld-new'],['binutils','objcopy']]) {
 await copyFile(path.join(build,directory,name),path.join(dest,name+'.mjs'));
 await copyFile(path.join(build,directory,name+'.wasm'),path.join(dest,name+'.wasm'));
}
const entries={};
for(const name of ['movieplay_ip.s','movieplay_sp.s','movieplay_sp_ext.s','movieplay_boot.s','region_jp.inc','region_us.inc','sec_jp.bin','sec_us.bin'])entries['boot/'+name]=await readFile(path.join(repo,'boot',name));
for(const name of ['ip.ld','sp.ld','sp_ext.ld'])entries['cfg/'+name]=await readFile(path.join(repo,'cfg',name));
const font=path.join(root,'.toolchain/dbgfont.bin');
execFileSync(path.join(repo,'tools/python.sh'),[path.join(repo,'tools/gen_debugfont.py'),'--output',font],{stdio:'inherit'});
entries['boot/dbgfont.bin']=await readFile(font);
await writeFile(path.join(root,'public/player-code.zip'),zipSync(entries,{level:6}));
await copyFile(path.join(root,'.toolchain/binutils-src/COPYING3'),path.join(dest,'COPYING3'));
await copyFile(path.join(root,'.toolchain/binutils-2.40.tar.xz'),path.join(dest,'binutils-2.40.tar.xz'));
await copyFile(path.join(root,'scripts/build-m68k-runtime.sh'),path.join(dest,'build-m68k-runtime.sh'));
console.log('Prepared GNU Binutils 2.40 / m68k WebAssembly and original player sources; no BIOS.');
