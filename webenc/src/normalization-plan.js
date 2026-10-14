// Match tools/video_geometry.py's no-denoise Lanczos geometry, after the
// explicit source crop. Keep source PAR separate from output H40 PAR.
const even=value=>Math.max(2,value-(value&1));
export function videoFilter(settings){
 const {width,height,fps,fit}=settings.video;
 const {crop,pixelAspect, width:sourceWidth,height:sourceHeight}=settings.source;
 const sar=pixelAspect[0]/pixelAspect[1],dar=width*32/35/height;
 const sourceAspect=crop.w*sar/crop.h;
 const filters=['setsar=1'];
 if(crop.x||crop.y||crop.w!==sourceWidth||crop.h!==sourceHeight)
  filters.push(`crop=${crop.w}:${crop.h}:${crop.x}:${crop.y}:exact=1`);
 let currentWidth=crop.w,currentHeight=crop.h,targetWidth=width,targetHeight=height;
 if(fit==='crop'){
  let w=even(crop.w),h=even(crop.h),x=0,y=0;
  if(sourceAspect>dar+1e-9){w=Math.min(even(Math.floor(crop.h*dar/sar)),crop.w);h=crop.h;x=Math.floor((crop.w-w)/2);}
  else if(sourceAspect<dar-1e-9){w=crop.w;h=Math.min(even(Math.floor(crop.w*sar/dar)),crop.h);y=Math.floor((crop.h-h)/2);}
  filters.push(`crop=${w}:${h}:${x}:${y}`);currentWidth=w;currentHeight=h;
 }else if(sourceAspect>dar){targetHeight=even(Math.floor(width*32/35/sourceAspect));}
 else {targetWidth=even(Math.floor(height*sourceAspect/(32/35)));}
 if(currentWidth!==targetWidth||currentHeight!==targetHeight)filters.push(`scale=${targetWidth}:${targetHeight}:flags=lanczos`);
 if(fit!=='crop')filters.push(`pad=${width}:${height}:(ow-iw)/2:(oh-ih)/2:color=black`);
 filters.push(`fps=${fps}`);
 return filters.join(',');
}

export function pcmWave(pcm,totalSamples){
 const bytes=new Uint8Array(44+totalSamples*2),view=new DataView(bytes.buffer);
 const text=(offset,value)=>[...value].forEach((c,i)=>bytes[offset+i]=c.charCodeAt(0));
 text(0,'RIFF');view.setUint32(4,bytes.length-8,true);text(8,'WAVE');text(12,'fmt ');
 view.setUint32(16,16,true);view.setUint16(20,1,true);view.setUint16(22,1,true);
 view.setUint32(24,22050,true);view.setUint32(28,44100,true);view.setUint16(32,2,true);view.setUint16(34,16,true);
 text(36,'data');view.setUint32(40,totalSamples*2,true);
 bytes.set(pcm.subarray(0,totalSamples*2),44);return bytes;
}
