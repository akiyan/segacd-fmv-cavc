import fs from 'node:fs';
import path from 'node:path';
import {fileURLToPath} from 'node:url';
import {spawnSync} from 'node:child_process';

// Standalone slide illustration. Timing blocks are schematic, not a trace.
const scriptDir = path.dirname(fileURLToPath(import.meta.url));
let out = path.join(scriptDir, 'out');
let svgOnly = false;
const args = process.argv.slice(2);
for (let i = 0; i < args.length; i++) {
 if (args[i] === '--help' || args[i] === '-h') {
  console.log('Usage: node harness/cpu_sequence/build.mjs [--out-dir DIR] [--svg-only]');
  process.exit(0);
 } else if (args[i] === '--out-dir' && args[i + 1] && !args[i + 1].startsWith('--')) {
  out = path.resolve(args[++i]);
 } else if (args[i] === '--svg-only') {
  svgOnly = true;
 } else {
  console.error(`Unknown or incomplete argument: ${args[i]}`);
  process.exit(1);
 }
}
fs.mkdirSync(out, {recursive: true});
let s=[],c;
const esc=x=>String(x).replaceAll('&','&amp;').replaceAll('<','&lt;');
const themes=[
{bg:'#ffffff',ink:'#173047',muted:'#6b7c8d',md:'#edf1f5',cd:'#e8f3ff',cpu:'#def3e7',cpuBorder:'#6fae8e',ram:'#fff5c8',ramBorder:'#dac77d',shared:'#f1ecff',sharedBorder:'#9f87d2',pcm:'#f0dfff',blank:'#ffe1ad',line:'#38546a',task:'#ffffff',rule:'#c6d6d0'},
{bg:'#111d2a',ink:'#e7f2f8',muted:'#9cb2c0',md:'#1c2a38',cd:'#1b3445',cpu:'#203f3d',cpuBorder:'#58aa94',ram:'#3e3b29',ramBorder:'#b9a66f',shared:'#342d4c',sharedBorder:'#a38cd8',pcm:'#443351',blank:'#59452d',line:'#b1c8d8',task:'#2c514b',rule:'#496c66'},
{bg:'#fbfaf7',ink:'#243d41',muted:'#6f817f',md:'#eeeeea',cd:'#e6efec',cpu:'#ffffff',cpuBorder:'#9ab5a9',ram:'#eee8cf',ramBorder:'#c4b790',shared:'#e8e3ef',sharedBorder:'#a89ab8',pcm:'#eadfec',blank:'#f5dfb6',line:'#506a69',task:'#e2ede7',rule:'#cbdad2'}];
function rect(x,y,w,h,fill,stroke='none',r=18,sw=2){s.push(`<rect x="${x}" y="${y}" width="${w}" height="${h}" fill="${fill}" stroke="${stroke}" stroke-width="${sw}" rx="${r}"/>`);}
function text(x,y,t,size=30,fill=c.ink,weight=500,anchor='middle'){s.push(`<text x="${x}" y="${y}" font-family="Noto Sans CJK JP" font-size="${size}" font-weight="${weight}" text-anchor="${anchor}" fill="${fill}">${esc(t)}</text>`);}
function line(x1,y1,x2,y2,color=c.line,sw=3,dash=''){s.push(`<path d="M ${x1} ${y1} L ${x2} ${y2}" fill="none" stroke="${color}" stroke-width="${sw}" ${dash?`stroke-dasharray="${dash}"`:''}/>`);}
function head(x,y,dx,dy,col=c.line){const px=-dy,py=dx;s.push(`<path d="M ${x-dx*13+px*7} ${y-dy*13+py*7} L ${x} ${y} L ${x-dx*13-px*7} ${y-dy*13-py*7}" fill="none" stroke="${col}" stroke-width="3" stroke-linejoin="round"/>`);}
function arrow(x1,x2,y,col=c.line,dash=''){line(x1,y,x2,y,col,3,dash);head(x2,y,x2>x1?1:-1,0,col);}
function down(x,y1,y2,col=c.line){line(x,y1,x,y2,col,3);head(x,y2,0,1,col);}
function icon(type,x,y,size=40,color=c.ink){
 s.push(`<g transform="translate(${x},${y}) scale(${size/48})" fill="none" stroke="${color}" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round">`);
 if(type==='cpu'){
  s.push('<rect x="10" y="10" width="28" height="28" rx="3"/><rect x="17" y="17" width="14" height="14" rx="1"/>');
  for(const t of [16,24,32])s.push(`<path d="M ${t} 3 V 10 M ${t} 38 V 45 M 3 ${t} H 10 M 38 ${t} H 45"/>`);
 }else if(type==='cd'){
  s.push('<circle cx="24" cy="24" r="20"/><circle cx="24" cy="24" r="5"/><path d="M 14 10 A 17 17 0 0 1 32 9 M 11 16 A 17 17 0 0 1 14 12 M 34 38 A 17 17 0 0 1 16 39"/>');
 }else if(type==='pcm'){
  s.push('<path d="M 4 19 H 12 L 22 10 V 38 L 12 29 H 4 Z M 29 16 Q 38 24 29 32 M 35 9 Q 50 24 35 39"/>');
 }else if(type==='register'){
  s.push('<rect x="10" y="7" width="28" height="8" rx="2"/><rect x="10" y="20" width="28" height="8" rx="2"/><rect x="10" y="33" width="28" height="8" rx="2"/><path d="M 2 11 H 7 M 2 24 H 7 M 2 37 H 7 M 41 11 H 46 M 41 24 H 46 M 41 37 H 46"/>');
 }else{
  s.push('<rect x="9" y="7" width="30" height="34" rx="3"/><path d="M 17 15 H 31 M 17 24 H 31 M 17 33 H 31"/>');
  for(const t of [13,20,28,35])s.push(`<path d="M 3 ${t} H 9 M 39 ${t} H 45"/>`);
 }
 s.push('</g>');
}
function card(x,y,w,h,title,fill=c.ram,stroke=c.ramBorder){
 rect(x,y,w,h,fill,stroke,14);
 const type=title==='CD-ROM'?'cd':title==='PCM'?'pcm':title==='通信レジスタ'?'register':'memory';
 if(w<180){icon(type,x+w/2-25,y+23,50,stroke);text(x+w/2,y+111,title,29,c.ink,600);}
 else{icon(type,x+17,y+17,37,stroke);text(x+68,y+45,title,28,c.ink,600,'start');}
}
function swap(mid,y,vertical=true){
 const col=c.sharedBorder;
 if(vertical){
 s.push(`<path d="M ${mid-36} ${y-61} C ${mid-90} ${y-25}, ${mid-90} ${y+23}, ${mid-36} ${y+61}" fill="none" stroke="${col}" stroke-width="5"/>`);
 head(mid-36,y+61,.82,.57,col);
 s.push(`<path d="M ${mid+36} ${y+61} C ${mid+90} ${y+23}, ${mid+90} ${y-25}, ${mid+36} ${y-61}" fill="none" stroke="${col}" stroke-width="5"/>`);
 head(mid+36,y-61,-.82,-.57,col);
 rect(mid-46,y-18,92,37,c.bg,'none',6);text(mid,y+8,'SWAP',20,col,700);
 } else {
 s.push(`<path d="M ${mid-115} ${y-30} C ${mid-65} ${y-99}, ${mid+65} ${y-99}, ${mid+115} ${y-30}" fill="none" stroke="${col}" stroke-width="5"/>`);head(mid+115,y-30,.59,.81,col);
 s.push(`<path d="M ${mid+115} ${y+30} C ${mid+65} ${y+99}, ${mid-65} ${y+99}, ${mid-115} ${y+30}" fill="none" stroke="${col}" stroke-width="5"/>`);head(mid-115,y+30,-.59,-.81,col);
 text(mid,y+8,'SWAP',20,col,700);
 }
}
function task(x,y,w,label,mode){if(mode!==2)rect(x,y-29,w,60,c.task,'none',11);text(x+w/2,y+12,label,32,c.ink,600);}
function flow(x,tasks){for(let i=0;i<tasks.length-1;i++)down(x,tasks[i][0]+32,tasks[i+1][0]-32,c.cpuBorder);}
function cpu(x,w,mode,main=true){
 rect(x,200,w,1071,c.cpu,c.cpuBorder,20,3);
 rect(x,200,w,127,c.cpuBorder,'none',18);rect(x,290,w,37,c.cpuBorder,'none',0);
 icon('cpu',x+w/2-132,211,42,'#102b29');
 text(x+w/2+25,250,main?'Main-CPU':'Sub-CPU',32,'#102b29',700);
 text(x+w/2,308,main?'7.67 MHz':'12.5 MHz',36,'#102b29',700);
 const odds=[[385,main?'更新データを参照':'CDセクタを回収'],[465,main?'ネームテーブル準備':'転送リストを生成'],[545,main?'VBlankを待つ':'音声を復号・出力']];
 const evens=main?[[916,'次のVBlankを待つ']]:[[864,'次フレームを準備'],[974,'交換要求を待つ']];
 // The CPU panels alone own all process names and downward execution arrows.
 if(mode===3){rect(x+16,347,w-32,348,c.task,'none',12);rect(x+16,811,w-32,234,c.task,'none',12);}
 const vblankHeight = 206;
 rect(x+3,590,w-6,vblankHeight,c.blank,'none',0);
 rect(x+3,1062,w-6,vblankHeight,c.blank,'none',0);
 text(x+w/2,352,'ODD · Active 224L',18,c.muted,600);
 text(x+w/2,819,'EVEN · Active 224L',18,c.muted,600);
 text(x+17,614,'VBlank · 38L',17,c.muted,500,'start');
 text(x+17,1086,'VBlank · 38L',17,c.muted,500,'start');
 const tw=w-92;
 flow(x+w/2,odds);flow(x+w/2,evens);
 for(const [y,t] of [...odds,...evens])task(x+46,y,tw,t,mode);
 down(x+w/2,588,648,c.cpuBorder);
 text(x+w/2,683,main?'パターンテーブルDMA':'CD回収・音声出力',29,c.ink,700);
 if(main)text(x+w/2,718,'205 B/line',21,'#f5dc8e',600);
 down(x+w/2,main?959:1017,1090,c.cpuBorder);
 task(x+46,1121,tw,main?'残りのパターン転送':'バンクを交換',mode);
 if(main)text(x+w/2,1162,'205 B/line',21,'#f5dc8e',600);
 down(x+w/2,main?1175:1163,1191,c.cpuBorder);
 task(x+46,1221,tw,main?'ネームテーブル転送':'CD回収を継続',mode);
 if(main)text(x+w/2,1260,'205 B/line',21,'#f5dc8e',600);
}
function common(mode,title,sub){
 c=themes[mode-1];s=[];rect(0,0,2560,1440,c.bg,'none',0);
 rect(145,188,840,1115,c.md,'none',24);rect(1010,188,1425,1115,c.cd,'none',24);
 text(565,169,'メガドライブ本体',31,c.ink,600);text(1722,169,'メガCD',31,c.ink,600);
 text(1237,235,'Main / Sub 共有',24,c.muted,500);
 cpu(485,455,mode,true);cpu(1800,405,mode,false);
 // Resource blocks remain outside the CPUs; labels here are device names only.
 card(190,330,245,290,'Main-RAM');text(312,483,'64',44,'#f5dc8e',700);text(312,522,'KiB',24,'#f5dc8e',600);text(312,582,'DicBuf',23,c.muted);
 card(190,657,245,611,'VRAM');
 text(312,778,'64',44,'#f5dc8e',700);text(312,817,'KiB',24,'#f5dc8e',600);
 text(312,895,'パターンテーブル',23,c.muted);text(312,1140,'ネームテーブル',23,c.muted);
 card(1520,330,230,155,'CD-ROM');
 card(1520,514,230,520,'PRG-RAM');text(1635,710,'512',44,'#f5dc8e',700);text(1635,751,'KiB',24,'#f5dc8e',600);text(1635,985,'PrgBuf / APPLY',19,c.muted);
 card(2240,330,155,938,'PCM',c.pcm,c.sharedBorder);
 text(85,226,'時間',22,c.muted,500);down(85,251,1268,c.muted);
 text(170,1362,'ODD / EVEN＝60Hz表示の前半 / 後半',22,c.muted,400,'start');
 text(2395,1362,'概略配置・VBlank拡大・処理境界は未計測',21,c.muted,400,'end');
 text(170,1400,'理論値：RAMコピー＝MOVE.L連続・追加waitなし ｜ VRAM DMA＝H40 VBlank ｜ B/lineは1走査線時間あたりの換算量',19,c.muted,400,'start');
}
function shared(mode){
 if(mode===1){
 card(1070,361,340,282,'Word-RAM 0',c.shared,c.sharedBorder);text(1240,590,'128 KiB',23,c.muted);
 card(1070,725,340,282,'Word-RAM 1',c.shared,c.sharedBorder);text(1240,954,'128 KiB',23,c.muted);
 swap(1240,683);
 } else if(mode===2){
 rect(1040,360,400,660,c.shared,c.sharedBorder,22,3);icon('memory',1100,379,38,c.sharedBorder);text(1260,410,'Word-RAM',32,c.ink,700);
 rect(1062,451,168,523,c.bg,c.sharedBorder,12);rect(1250,451,168,523,c.bg,c.sharedBorder,12);
 icon('memory',1078,484,26,c.sharedBorder);icon('memory',1266,484,26,c.sharedBorder);
 text(1158,508,'Bank 0',23,c.ink,600);text(1346,508,'Bank 1',23,c.ink,600);
 text(1146,882,'128',36,'#d3baff',700);text(1334,882,'128',36,'#d3baff',700);
 text(1146,927,'KiB',23,'#d3baff',600);text(1334,927,'KiB',23,'#d3baff',600);
 swap(1240,711,false);
 } else {
 card(1065,360,350,282,'Word-RAM 0',c.shared,c.sharedBorder);text(1240,588,'128 KiB',23,c.muted);
 card(1065,727,350,282,'Word-RAM 1',c.shared,c.sharedBorder);text(1240,955,'128 KiB',23,c.muted);
 swap(1240,684);
 }
 text(1240,1050,'1M / 1M',23,c.muted,600);
 card(1070,1080,340,188,'通信レジスタ',c.shared,c.sharedBorder);
 text(1240,1185,'16 B × 2',28,'#d3baff',700);
 text(1240,1223,'CMD / READY',23,c.muted);
}
function transfers(mode){
 const left=mode===2?1040:1070,right=mode===2?1440:mode===3?1415:1410;
 // Short links stop at CPU borders; DMA data paths run below CPU task labels.
 arrow(left,940,395,c.sharedBorder);arrow(485,435,505);
 arrow(1750,1800,395);arrow(1750,1800,560);
 arrow(2205,2240,615,c.sharedBorder);
 arrow(485,435,774,c.sharedBorder);
 arrow(1750,1800,864);arrow(1520,right,864,c.sharedBorder);arrow(2205,2240,920,c.sharedBorder);
 arrow(485,435,1153,c.sharedBorder);
 arrow(485,435,1255);
 // Register traffic is separate from memory payload traffic.
 arrow(940,1070,1180,c.sharedBorder,'8 7');arrow(1410,1800,1180,c.sharedBorder,'8 7');
 // RAM-to-RAM copy estimates are examples of the documented no-wait model,
 // not measurements of the displayed control-read or update routines.
 rect(943,344,93,89,c.cd,'none',7);text(989,375,'97.7',27,'#d3baff',700);text(989,424,'B/line',18,c.muted);
 arrow(1040,940,395,c.sharedBorder);
 rect(1443,813,74,89,c.cd,'none',7);text(1480,840,'159.2',24,'#d3baff',700);text(1480,894,'B/line',17,c.muted);
 arrow(1520,1440,864,c.sharedBorder);
}
for(const i of [2]){
 const name='cpu-sequence';common(i,'','');shared(i);transfers(i);
 fs.writeFileSync(path.join(out,name+'.svg'),`<svg xmlns="http://www.w3.org/2000/svg" width="2560" height="1440" viewBox="0 0 2560 1440"><rect width="2560" height="1440" fill="${c.bg}"/><g transform="translate(0,-70)">${s.join('\n')}</g></svg>`);
}
const svgPath = path.join(out, 'cpu-sequence.svg');
console.log(svgPath);
if (!svgOnly) {
 const pngPath = path.join(out, 'cpu-sequence.png');
 const result = spawnSync('rsvg-convert', ['-o', pngPath, svgPath], {stdio: 'inherit'});
 if (result.error || result.status !== 0) {
  console.error(result.error?.message ?? `rsvg-convert failed: ${result.status ?? result.signal}`);
  console.error('SVG was generated; install rsvg-convert or use --svg-only.');
  process.exit(1);
 }
 console.log(pngPath);
}
