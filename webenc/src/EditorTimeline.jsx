import {Play,Pause,SpeakerHigh,SpeakerSlash,CaretDown} from '@phosphor-icons/react';

const clock=seconds=>{
 const centiseconds=Math.max(0,Math.floor(seconds*100));
 return `${String(Math.floor(centiseconds/6000)).padStart(2,'0')}:${String(Math.floor(centiseconds/100)%60).padStart(2,'0')}.${String(centiseconds%100).padStart(2,'0')}`;
};

export function EditorTimeline({time,duration,currentFrame,lastFrame,start,end,rangeDuration,
 playing,muted,disabled,onPlay,onMute,onSeek,onRange,onReset}) {
 const maximum=Math.max(1,lastFrame),position=currentFrame/maximum*100;
 return <section className="editor-timeline" aria-label="Source playback and frame range">
  <div className="timeline-transport">
   <button className="icon-button" aria-label={playing?'Pause preview':'Play preview'} disabled={disabled} onClick={onPlay}>
    {playing?<Pause size={20} weight="fill"/>:<Play size={20} weight="fill"/>}
   </button>
   <span className="time-code">{clock(time)} / {clock(duration)}</span>
  </div>
  <div className="timeline-rail" onPointerDown={event=>{
   if(disabled||event.target.tagName==='INPUT')return;
   const rect=event.currentTarget.getBoundingClientRect();
   onSeek(Math.max(0,Math.min(lastFrame,Math.round((event.clientX-rect.left-9)/(rect.width-18)*lastFrame))));
  }}>
   <div className="timeline-track"/>
   <div className="timeline-selection" style={{left:`calc(9px + (100% - 18px) * ${start/maximum})`,right:`calc(9px + (100% - 18px) * ${1-end/maximum})`}}/>
   <input aria-label="Range start frame" className="timeline-bound" type="range" min="0" max={lastFrame} step="1" value={start} disabled={disabled} onChange={e=>onRange('start',e.target.value)}/>
   <input aria-label="Range end frame" className="timeline-bound" type="range" min="0" max={lastFrame} step="1" value={end} disabled={disabled} onChange={e=>onRange('end',e.target.value)}/>
   <input aria-label="Preview position" aria-valuetext={`Source frame ${currentFrame}`} className="timeline-scrubber" type="range" min="0" max={lastFrame} step="1" value={currentFrame} disabled={disabled} onChange={e=>onSeek(Number(e.target.value))}/>
   <span className="timeline-playhead" style={{left:`calc(9px + (100% - 18px) * ${position/100})`}}><CaretDown size={14} weight="fill"/></span>
  </div>
  <button className="icon-button timeline-mute" aria-label={muted?'Unmute preview':'Mute preview'} onClick={onMute}><span>{muted?<SpeakerSlash size={20}/>:<SpeakerHigh size={20}/>}</span></button>
  <div className="timeline-footer">
   <span className="timeline-position">Source · frame {currentFrame} / {lastFrame}</span>
   <div className="timeline-fields" title="Source frames start at 0. Both endpoints are included; audio uses the same range.">
    <label>Start<input aria-label="Start frame" type="number" min="0" max={end} step="1" value={start} disabled={disabled} onChange={e=>onRange('start',e.target.value)}/></label>
    <label>End<input aria-label="End frame" type="number" min={start} max={lastFrame} step="1" value={end} disabled={disabled} onChange={e=>onRange('end',e.target.value)}/></label>
   </div>
   <span className="timeline-summary">{end-start+1} frames · {rangeDuration.toFixed(2)} s</span>
   <button className="timeline-reset" disabled={disabled} onClick={onReset}>Full video</button>
  </div>
 </section>;
}
