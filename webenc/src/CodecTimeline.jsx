import {useEffect,useRef,useState} from 'react';

const rows=[['Req',80,'cells'],['Supply',24,'patterns'],['RUN',18,''],['R2V',18,'words'],['DIC',18,''],['Band',24,'%']];
const height=rows.reduce((sum,row)=>sum+row[1],0);
const time=value=>`${Math.floor(value/60)}:${String(Math.floor(value%60)).padStart(2,'0')}`;

export function CodecTimeline({timeline,onSeek,disabled}) {
 const canvas=useRef(null),viewport=useRef(null);
 const [width,setWidth]=useState(300),[detail,setDetail]=useState(false),[hover,setHover]=useState(null);
 useEffect(()=>{if(!viewport.current)return;const observer=new ResizeObserver(([entry])=>setWidth(Math.max(1,Math.floor(entry.contentRect.width))));observer.observe(viewport.current);return()=>observer.disconnect();},[Boolean(timeline)]);
 useEffect(()=>setHover(null),[timeline]);
 const plotWidth=detail?Math.max(width,timeline?.frames*2||width):width;
 useEffect(()=>{
  if(!timeline||!canvas.current)return;
  const ctx=canvas.current.getContext('2d'),dpr=devicePixelRatio||1;
  ctx.setTransform(dpr,0,0,dpr,0,0);ctx.clearRect(0,0,plotWidth,height+22);
  const {frames,series,scales,colors}=timeline;
  const count=Math.min(frames,plotWidth);
  // Fit averages only the drawing columns; hover and Detail use exact frames.
  for(let column=0;column<count;column++){
   const begin=Math.floor(column*frames/count),end=Math.max(begin+1,Math.floor((column+1)*frames/count));
   const value=name=>{let sum=0;for(let frame=begin;frame<end;frame++)sum+=series[name]?.[frame]||0;return sum/(end-begin);};
   const x=column*plotWidth/count,w=plotWidth/count+.2;
   let top=0;
   for(const [name,h]of rows){
    ctx.fillStyle='#171b22';ctx.fillRect(x,top,w,h);
    let segments;
    if(name==='Req')segments=timeline.reqOrder.map(category=>[value('legend_'+category.toLowerCase()),colors[category]]);
    else if(name==='Supply')segments=[[value('status_wr0')+value('status_wr1'),colors.Wrd],[value('status_prg'),colors.Prg]];
    else if(name==='RUN')segments=[[value('status_run'),colors.RUN]];
    else if(name==='R2V')segments=[[value('status_r2v'),colors.R2V]];
    else if(name==='DIC')segments=[[value('legend_dic'),colors.Dic]];
    else {
     segments=[['body_raw_payload_bytes',colors.Raw],['body_prg_payload_bytes',colors.Prg],['body_control_bytes',colors.Control]].map(([key,color])=>{
      let fraction=0;for(let frame=begin;frame<end;frame++)fraction+=(series[key][frame]||0)/Math.max(1,series.body_physical_bytes[frame]);
      return [fraction/(end-begin)*100,color];
     });
    }
    let bottom=top+h-1;
    for(const [amount,color]of segments){const size=Math.min(bottom-top,Math.max(0,amount/scales[name]*(h-1)));ctx.fillStyle=color;ctx.fillRect(x,bottom-size,w,size);bottom-=size;}
    top+=h;
   }
  }
  ctx.strokeStyle='#354250';let top=0;
  for(const [,h]of rows){top+=h;ctx.beginPath();ctx.moveTo(0,top-.5);ctx.lineTo(plotWidth,top-.5);ctx.stroke();}
  ctx.strokeStyle=colors.Limit;ctx.setLineDash([3,3]);
  const cap=80-1-Math.min(scales.Req,timeline.coldCap)/scales.Req*79;
  ctx.beginPath();ctx.moveTo(0,cap);ctx.lineTo(plotWidth,cap);ctx.stroke();
  ctx.strokeStyle='#bac4d955';
  for(let frame=1;frame<frames;frame++)if(series.palette_segment[frame]!==series.palette_segment[frame-1]){const x=frame/frames*plotWidth;ctx.beginPath();ctx.moveTo(x,0);ctx.lineTo(x,height);ctx.stroke();}
  ctx.setLineDash([]);ctx.fillStyle='#99a7b8';ctx.font='9px sans-serif';
  const duration=frames/timeline.fps;
  const ticks=detail?[...Array.from({length:Math.max(1,Math.floor((duration-2)/5)+1)},(_,index)=>index*5),duration]:Array.from({length:5},(_,index)=>index/4*duration);
  for(let tick=0;tick<ticks.length;tick++){const seconds=ticks[tick],fraction=seconds/duration;ctx.textAlign=tick===0?'left':tick===ticks.length-1?'right':'center';ctx.fillText(time(seconds),fraction*plotWidth,height+14);}
 },[timeline,plotWidth]);
 const frameAt=event=>Math.min(timeline.frames-1,Math.max(0,Math.floor((event.clientX-canvas.current.getBoundingClientRect().left)/plotWidth*timeline.frames)));
 const selected=hover==null?null:timeline?.series;
 return <section className="codec-timeline" aria-label="Codec timeline">
  <div className="codec-timeline-heading"><h3>Timeline</h3>{timeline&&<><span>{timeline.frames} frames · {timeline.fps} fps</span><button aria-pressed={detail} onClick={()=>setDetail(!detail)} title="Inspect every frame at two pixels per frame">Detail</button></>}</div>
  {!timeline?<p className="hint">Timeline appears after delivery and stream verification.</p>:<>
   <div className="codec-timeline-legend">{timeline.legendOrder.map(name=><span key={name}><i style={{background:timeline.colors[name]}}/>{name}</span>)}</div>
   <div className="codec-timeline-plot">
    <div className="codec-timeline-labels">{rows.map(([name,h,unit])=><div key={name} style={{height:h}}><strong title={unit?`${name}: ${unit}`:name}>{name}</strong><small title={`0–${timeline.scales[name]} ${unit}`}>0–{timeline.scales[name]}{unit==='%'?' %':''}</small></div>)}</div>
    <div className="codec-timeline-viewport" ref={viewport}>
     <div style={{position:'relative',width:plotWidth}}>
      <canvas ref={canvas} width={plotWidth*(devicePixelRatio||1)} height={(height+22)*(devicePixelRatio||1)} style={{width:plotWidth,height:height+22}}
       role="img" aria-label="Whole-movie codec timeline: Req, physical Supply, RUN, R2V, DIC and Band"
       onPointerMove={event=>setHover(frameAt(event))} onPointerLeave={()=>setHover(null)} onClick={event=>{if(!disabled)onSeek(frameAt(event));}}/>
      {hover!=null&&<div className="codec-timeline-cursor" style={{left:hover/timeline.frames*plotWidth,height}}/>}
     </div>
    </div>
   </div>
   <p className="codec-timeline-detail">{selected?`f0x${hover.toString(16).toUpperCase()} · ${(hover/timeline.fps).toFixed(2)} s · Req ${selected.status_req[hover]} · Prg ${selected.status_prg[hover]} / Wrd ${selected.status_wr0[hover]+selected.status_wr1[hover]} patterns · RUN ${selected.status_run[hover]} · R2V ${selected.status_r2v[hover]} words`:`Cold cap ${timeline.coldCap} (yellow) · ${detail?'Exact frames':'Fit averages drawing columns'} · Hover for values${disabled?'':'; click to inspect Source'}.`}</p>
  </>}
 </section>;
}
