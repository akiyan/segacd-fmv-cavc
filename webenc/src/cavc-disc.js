const SECTOR=2048;
function text(bytes,offset,value,length=value.length) {
 bytes.fill(32,offset,offset+length);
 for(let i=0;i<Math.min(value.length,length);i++)bytes[offset+i]=value.charCodeAt(i);
}
function both16(view,offset,value){view.setUint16(offset,value,true);view.setUint16(offset+2,value,false);}
function both32(view,offset,value){view.setUint32(offset,value,true);view.setUint32(offset+4,value,false);}
function record(extent,length,name,directory=false) {
 const id=typeof name==='number'?new Uint8Array([name]):new TextEncoder().encode(name);
 const bytes=new Uint8Array(33+id.length+(id.length%2===0?1:0)),view=new DataView(bytes.buffer);
 bytes[0]=bytes.length;both32(view,2,extent);both32(view,10,length);
 bytes.set([126,1,1,0,0,0,0],18);bytes[25]=directory?2:0;both16(view,28,1);bytes[32]=id.length;bytes.set(id,33);
 return bytes;
}

export function createCavcDisc(boot,header,body,name='movie') {
 if(boot.length!==32768||header.length%SECTOR||body.length%SECTOR)throw new Error('Invalid Sega CD system area or stream sector alignment');
 const note=new TextEncoder().encode('CAVC browser encode\nHEADER.DAT + BODY.DAT\n');
 const entries=[{name:'README.TXT;1',bytes:note},{name:'HEADER.DAT;1',bytes:header},{name:'BODY.DAT;1',bytes:body}];
 let next=21;
 for(const entry of entries){entry.extent=next;next+=Math.ceil(entry.bytes.length/SECTOR);}
 const total=next+150,iso=new Uint8Array(total*SECTOR);iso.set(boot);
 const pvd=new Uint8Array(SECTOR),view=new DataView(pvd.buffer);
 pvd[0]=1;text(pvd,1,'CD001');pvd[6]=1;text(pvd,8,'SEGA CD',32);text(pvd,40,'SCFMV_DLT',32);
 both32(view,80,total);both16(view,120,1);both16(view,124,1);both16(view,128,SECTOR);both32(view,132,10);
 view.setUint32(140,18,true);view.setUint32(148,19,false);pvd.set(record(20,SECTOR,0,true),156);
 text(pvd,190,'',128);text(pvd,318,'AKIYAN',128);text(pvd,446,'CAVC BROWSER ENCODER',128);text(pvd,574,'SEGA CD CAVC',128);
 for(const offset of [813,830]){text(pvd,offset,'2026010100000000');pvd[offset+16]=0;}
 for(const offset of [847,864]){text(pvd,offset,'0000000000000000');pvd[offset+16]=0;}
 pvd[881]=1;iso.set(pvd,16*SECTOR);
 const terminator=new Uint8Array(SECTOR);terminator[0]=255;text(terminator,1,'CD001');terminator[6]=1;iso.set(terminator,17*SECTOR);
 for(const [sector,little]of [[18,true],[19,false]]){
  const table=new Uint8Array(10),v=new DataView(table.buffer);table[0]=1;v.setUint32(2,20,little);v.setUint16(6,1,little);iso.set(table,sector*SECTOR);
 }
 let offset=20*SECTOR;
 for(const entry of [record(20,SECTOR,0,true),record(20,SECTOR,1,true),...entries.map(e=>record(e.extent,e.bytes.length,e.name))]){iso.set(entry,offset);offset+=entry.length;}
 for(const entry of entries)iso.set(entry.bytes,entry.extent*SECTOR);
 const safe=name.replace(/[^a-zA-Z0-9_-]/g,'_')||'movie';
 const cue=`FILE "${safe}.iso" BINARY\n  TRACK 01 MODE1/2048\n    INDEX 01 00:00:00\n`;
 return {iso,cue,name:safe,entries:entries.map(({name,extent,bytes})=>({name,extent,bytes:bytes.length}))};
}
