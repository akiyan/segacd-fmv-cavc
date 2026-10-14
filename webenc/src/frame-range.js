import {EncodedPacketSink} from 'mediabunny';

// Frame numbers refer to presentation order, including variable-rate sources.
export async function videoFrameTimes(track) {
 const times=[];
 for await(const packet of new EncodedPacketSink(track).packets(undefined,undefined,{metadataOnly:true}))times.push(packet.timestamp);
 times.sort((a,b)=>a-b);
 if(!times.length)throw new Error('No video frames found');
 return times;
}

export function frameInterval(times,trackEnd,range) {
 const startFrame=range?.startFrame??0,endFrame=range?.endFrame??times.length-1;
 if(!Number.isInteger(startFrame)||!Number.isInteger(endFrame)||startFrame<0||endFrame<startFrame||endFrame>=times.length)
  throw new Error('Choose a valid source frame range');
 const start=times[startFrame],end=times[endFrame+1]??trackEnd;
 if(!(end>start))throw new Error('The selected frame range has no duration');
 return {start,end,startFrame,endFrame,sourceFrames:times.length};
}
