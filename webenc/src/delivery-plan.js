import config from './generated/schedule-config.json';

const ceil = (n,d) => Math.ceil(n/d);
function nominal(fps) {
  const n=Math.round(fps);return Math.abs(fps-n)<=.1?n:fps;
}
export function cadence(fps) {
  if (!(fps>0)) throw new Error('Invalid frame rate');
  const n=Math.max(1,Math.round(config.vsync/fps));
  if(n<=config.maxInterval && Math.abs(config.vsync/fps-n)<=config.intervalTolerance)return [n];
  return nominal(fps)===24?[2,3]:null;
}
export function rateDeltas(count,fps) {
  const steps=cadence(fps),numerators=steps?steps.map(n=>1001*n):[75];
  const modulus=steps?800:Math.round(fps),out=Array(count).fill(0);
  if(modulus<=0)throw new Error('Invalid delivery-paced frame rate');
  let accumulator=0;
  for(let i=1;i<count;i++) {
    accumulator+=numerators[(i-1)%numerators.length];
    out[i]=Math.floor(accumulator/modulus);accumulator%=modulus;
  }
  return out;
}
export function audioLayout(fps) {
  const pattern=cadence(fps);
  const playbackFps=pattern?config.vsync*pattern.length/pattern.reduce((a,b)=>a+b):fps;
  let samples=Math.ceil(22050/playbackFps);samples+=samples%2;
  return {samples,bytes:4+samples/2,playbackFps};
}
// Conservative construction: reserve one control sector in each slot and
// fund frame i's patterns only from the preceding physical slot. The exact
// planner still validates the resulting continuous stream independently.
export function selectionBudgets(count,fps) {
  const rate=rateDeltas(count,fps),audio=audioLayout(fps);
  const controlSectors=Math.ceil((8+audio.bytes)/config.sectorBytes);
  if(rate.slice(1).some(n=>n<controlSectors) || controlSectors>config.maxControlSectors)
    throw new Error('This frame rate has no supported conservative CD delivery slot. Choose 15, 24 or 30 fps.');
  const capKb=config.deliveryCapKb-Math.ceil(config.jitterReferenceKb*config.jitterReferenceFps/nominal(fps));
  if(capKb<=0)throw new Error('No scheduled PrgBuf capacity at this frame rate');
  const prebuffer=Math.floor(capKb*32/64)*64;
  return Array.from({length:count},(_,frame)=>({
    // Rate padding is outside the route's useful-sector capacity.
    coldBudget:frame===0?Infinity:frame===1?prebuffer:Math.max(0,Math.min(rate[frame-1],config.frameSectors)-controlSectors)*64,
    controlByteLimit:controlSectors*config.sectorBytes,
    audioBytes:audio.bytes,
  }));
}
export function controlLengths(updates,runs,cells,audioBytes) {
  const bitmap=(ceil(cells,8)+1)&~1;
  return updates.map((n,i)=>{
    const entries=Math.min(bitmap+n*config.shadowEntryBytes,n*config.listItemBytes);
    const body=4+entries+audioBytes;
    return 4+body+(body%2)+runs[i]*4;
  });
}
export function controlSectors(lengths) {
  let delivered=0,required=0;
  return lengths.map((length,i)=>{
    if(!i)return 0;
    const count=Math.max(0,ceil(required+length-delivered,config.sectorBytes));
    delivered+=count*config.sectorBytes;required+=length;return count;
  });
}
export function planPayload(loads,lengths,fps,physicalCapacity,prebufferCapacity=physicalCapacity) {
  const fail=(message,details={})=>({feasible:false,message,...details});
  const n=loads.length;
  if(!n || lengths.length!==n || loads.some(v=>!Number.isSafeInteger(v)||v<0) || lengths.some(v=>!Number.isSafeInteger(v)||v<0))throw new Error('Invalid schedule inputs');
  if(!(prebufferCapacity>0 && prebufferCapacity<=physicalCapacity))throw new Error('Invalid schedule capacity');
  const nc=controlSectors(lengths),cap=nc.map(v=>Math.max(config.frameSectors-v,0));
  const ratedelta=rateDeltas(n,fps),consumed=Array(n).fill(0),before=Array(n).fill(0);
  for(let i=1;i<n;i++){before[i]=consumed[i-1];consumed[i]=before[i]+loads[i];}
  const totalSectors=ceil(consumed[n-1],64);
  const prebuffer=Math.min(Math.floor(prebufferCapacity/64),totalSectors);
  const need=Array(n).fill(0),origin=Array(n).fill(0),delivered=Array(n).fill(0);
  need[n-1]=totalSectors;origin[n-1]=n-1;
  for(let i=n-2;i>=0;i--){
    const immediate=ceil(consumed[i+1],64),future=need[i+1]-cap[i+1];
    if(immediate>=future && immediate>0){need[i]=immediate;origin[i]=i+1;}
    else if(future>0){need[i]=future;origin[i]=origin[i+1];}
  }
  if(prebuffer<need[0])return fail('Prebuffer cannot arm the selected loads',{failureFrame:0,originFrame:origin[0]});
  let lead=0,prev=prebuffer;delivered[0]=prebuffer;
  for(let i=1;i<n;i++){
    const due=ratedelta[i]-lead,soft=Math.max(0,due-nc[i]);
    const hi=Math.min(prev+cap[i],totalSectors,Math.floor((before[i]+physicalCapacity)/64));
    const lo=Math.max(prev,need[i]);
    if(lo>hi)return fail('Selected loads exceed the delivery or ring limit',{failureFrame:i,originFrame:origin[i]});
    const current=Math.max(lo,Math.min(prev+soft,hi));delivered[i]=current;
    const actual=current-prev+nc[i];lead+=Math.max(actual,due)-ratedelta[i];prev=current;
  }
  const pay=delivered.map((v,i)=>i?v-delivered[i-1]:v-prebuffer);
  const occupancy=delivered.map((v,i)=>v*64-consumed[i]);
  const peakBefore=delivered.map((v,i)=>v*64-before[i]);
  const sectors=Array(n).fill(0),leadTrace=Array(n).fill(0),ready=Array(n).fill(0),controlMargin=Array(n).fill(0);
  lead=0;let controlBytes=0,controlRequired=0;
  for(let i=1;i<n;i++){
    ready[i]=delivered[i-1]*64-consumed[i];
    controlBytes+=nc[i]*config.sectorBytes;controlRequired+=lengths[i];controlMargin[i]=controlBytes-controlRequired;
    sectors[i]=Math.max(pay[i]+nc[i],ratedelta[i]-lead);lead+=sectors[i]-ratedelta[i];leadTrace[i]=lead;
  }
  const feasible=pay.every((v,i)=>v>=0 && v+nc[i]<=config.frameSectors && nc[i]<=config.maxControlSectors) &&
    occupancy.every(v=>v>=0) && ready.every(v=>v>=0) && controlMargin.every(v=>v>=0) && leadTrace.every(v=>v===0) && peakBefore.every(v=>v<=physicalCapacity);
  return {feasible,message:feasible?'Selected loads fit this model':'Selected loads require revised decisions',
    prebufferPatterns:prebuffer*64,payloadSectors:pay,controlSectors:nc,sectorAllowance:ratedelta,
    routedSectors:sectors,rateLead:leadTrace,ringOccupancy:occupancy,ringBeforeConsume:peakBefore,
    readyMargin:ready,controlMargin,physicalCapacity,prebufferCapacity};
}
export function previewDeliveryPlan(records,fps,cells) {
  const capKb=config.deliveryCapKb-Math.ceil(config.jitterReferenceKb*config.jitterReferenceFps/nominal(fps));
  if(capKb<=0)return {feasible:false,message:'No scheduled PrgBuf capacity at this frame rate'};
  const audio=audioLayout(fps),lengths=controlLengths(records.map(r=>r.updates),records.map(r=>r.runs),cells,audio.bytes);
  const result=planPayload(records.map(r=>r.cold),lengths,fps,capKb*32);
  return {...result,physicalFeasible:result.feasible,feasible:result.feasible && records.length<=config.maxFrames,
    model:'Normal controls; exact reuse; all timed patterns from PrgBuf; no boot-preload credits',
    qualification:'Planning model only; no HEADER/BODY or ISO has been built',
    audioControlSamples:audio.samples,audioControlBytes:audio.bytes,blockLengths:lengths,
    routingFrameLimit:config.maxFrames,routeCapacityOk:records.length<=config.maxFrames};
}
export function deliveryArtifacts(plan) {
  const fields = [
    ['sectorAllowance','sector_allowance'],['routedSectors','routed_sectors'],
    ['controlSectors','control_sectors'],['payloadSectors','payload_sectors'],
    ['rateLead','rate_lead_sectors'],['ringOccupancy','ring_patterns'],
    ['ringBeforeConsume','ring_before_consume_patterns'],['readyMargin','ready_margin_patterns'],
    ['controlMargin','control_margin_bytes'],['blockLengths','control_block_bytes'],
  ];
  const count=plan.blockLengths?.length || 0;
  const lines=['frame\t'+fields.map(([,label])=>label).join('\t')];
  for(let frame=0;frame<count;frame++)
    lines.push([frame,...fields.map(([name])=>plan[name]?.[frame] ?? '')].join('\t'));
  const summary=Object.fromEntries(Object.entries(plan).filter(([,v])=>!Array.isArray(v)));
  summary.frames=count;
  if(plan.rateLead) {
    summary.rateLeadPeak=plan.rateLead.reduce((a,b)=>Math.max(a,b),0);
    summary.ringPeak=plan.ringBeforeConsume.reduce((a,b)=>Math.max(a,b),0);
    summary.readyMinimum=plan.readyMargin.length>1?plan.readyMargin.slice(1).reduce((a,b)=>Math.min(a,b),Infinity):0;
  }
  return {summary,tsv:lines.join('\n')+'\n'};
}
