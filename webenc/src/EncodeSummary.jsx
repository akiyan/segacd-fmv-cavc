import {CodecTimeline} from './CodecTimeline';
const seconds=(frame,summary)=>(frame/summary.fps).toFixed(2)+' s';
const label=(event,kind)=>kind==='scroll'?(event.axis==='x'?'Horizontal scroll':'Vertical scroll'):`Palette fade ${event.kind}`;
function Palette({set}) {
 return <div className="palette-colors" aria-label={`Palette set ${set.index+1}: ${set.uniqueLines} unique color lines`}>
  {set.colors.map((colors,bank)=><div className="palette-line" key={bank}><span>B{bank}</span>{[[0,0,0],...colors].map((rgb,index)=><span className="palette-swatch" key={index} title={`Bank ${bank}, color ${index}: RGB333 ${rgb.join(', ')} · display RGB ${rgb.map(value=>value*36).join(', ')}`} style={{backgroundColor:`rgb(${rgb.map(value=>value*36).join(',')})`}} />)}</div>)}
 </div>;
}
function EventTrack({kind,summary,onSeek,disabled}) {
 const events=summary?.[kind];
 return <div className="encode-event-track">
  <span>{kind==='scroll'?'HW scroll':'Palette fade'}</span>
  <div className="encode-event-rail">
   {events==null?<span className="event-empty">Pending</span>:events.length===0?<span className="event-empty">None</span>:events.map((event,index)=><button key={index} disabled={disabled} className={`encode-event ${kind} ${event.axis||event.kind}`} style={{left:`${event.start/summary.frames*100}%`,width:`${Math.max(.5,(event.end-event.start)/summary.frames*100)}%`}}
    title={`${label(event,kind)} · ${seconds(event.start,summary)}–${seconds(event.end,summary)} · frames ${event.start}–${event.end-1}`}
    aria-label={`${label(event,kind)} at output frame ${event.start}`} onClick={()=>onSeek(event.start)} />)}
  </div>
  <span>{events==null?'—':events.length}</span>
 </div>;
}

export function EncodeSummary({summary,status,onSeek,seekDisabled}) {
 const sets=summary?.paletteSets||[];
 const events=[...(summary?.scroll||[]).map(event=>({...event,type:'scroll'})),
  ...(summary?.fades||[]).map(event=>({...event,type:'fades'}))].sort((a,b)=>a.start-b.start||a.end-b.end);
 return <div className="download-package encode-summary">
  <div className="encode-summary-heading"><h2>Encode summary</h2></div>
  <div className="encode-summary-body" aria-label="Encoder decisions">
   <CodecTimeline timeline={summary?.timeline} onSeek={onSeek} disabled={seekDisabled}/>
   {!summary?<p className="summary-empty">Selected palettes and effects will appear as encoding progresses.</p>:<>
    <div className="summary-metrics"><span>{sets.length} palette sets · {Math.max(0,...sets.map(set=>set.uniqueLines))} unique lines / 4 banks</span><span>{summary.status==='verified'?'Stream verified':status==='cancelled'||status==='error'?'Partial':'Planned'}</span></div>
    <div className="palette-set-list" aria-label="Palette sets">
     {sets.map(set=><article key={set.index} className="palette-set-card">
      <div className="palette-set-heading"><strong>Set {set.index+1}</strong><span>{set.uniqueLines} lines</span></div>
      <Palette set={set}/>
      <p className="palette-set-spans" title={set.spans.map(span=>`${seconds(span.start,summary)}–${seconds(span.end,summary)}`).join(' / ')}>{set.spans.map(span=>`${seconds(span.start,summary)}–${seconds(span.end,summary)}`).join(' / ')}</p>
     </article>)}
     {!sets.length&&<p>Palettes pending</p>}
    </div>
    <div className="summary-effect-overview" aria-label="Effect timeline">
     <EventTrack kind="scroll" summary={summary} onSeek={onSeek} disabled={seekDisabled}/>
     <EventTrack kind="fades" summary={summary} onSeek={onSeek} disabled={seekDisabled}/>
     <div className="summary-axis"><span>Output 0 s</span><span>{seconds(summary.frames,summary)}</span></div>
    </div>
    <div className="encode-event-list">
     <h3>Events</h3>
     <p>Output frames start at 0. Click an event to inspect its source.</p>
     {events.map((event,index)=><button key={`${event.type}-${event.start}-${index}`} disabled={seekDisabled} onClick={()=>onSeek(event.start)}>
      <span>{label(event,event.type)}</span><span>{seconds(event.start,summary)}–{seconds(event.end,summary)}</span>
      <span>f{event.start}–{event.end-1}{event.controls?` · ${event.controls} CRAM writes`:''}</span>
     </button>)}
     {!events.length&&<p>{summary.scroll==null||summary.fades==null?'Events pending':'No scroll or fade events'}</p>}
    </div>
   </>}
  </div>
 </div>;
}
