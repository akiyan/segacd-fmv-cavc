import {useEffect,useRef,useState} from 'react';
import {FileVideo} from '@phosphor-icons/react';
export function OutputPlayer({active,encodedPreview=null,compact=false,liveFrame=null,processing=false}) {
 const [url,setUrl]=useState(null),[error,setError]=useState(''),video=useRef(null),canvas=useRef(null);
 useEffect(()=>{
  setError('');
  if(!(encodedPreview instanceof Blob)){setUrl(null);return;}
  const next=URL.createObjectURL(encodedPreview);setUrl(next);
  return()=>URL.revokeObjectURL(next);
 },[encodedPreview]);
 useEffect(()=>{if(!active)video.current?.pause();},[active]);
 useEffect(()=>{
  if(!liveFrame?.png||!canvas.current)return;
  let disposed=false;
  const url=URL.createObjectURL(new Blob([liveFrame.png],{type:'image/png'}));
  const image=new Image();
  image.onload=()=>{
   if(!disposed&&canvas.current){const ctx=canvas.current.getContext('2d');ctx.fillStyle='#000';ctx.fillRect(0,0,320,224);ctx.imageSmoothingEnabled=false;ctx.drawImage(image,(320-liveFrame.width)/2,(224-liveFrame.height)/2);}
   URL.revokeObjectURL(url);
  };
  image.onerror=()=>URL.revokeObjectURL(url);image.src=url;
  return()=>{disposed=true;URL.revokeObjectURL(url);};
 },[liveFrame]);
 return <div hidden={!active} className="output-player">
  <div className="output-video-frame">
   {url&&!processing?<video ref={video} src={url} controls playsInline preload="metadata" aria-label="Encoded MP4 playback"
    onError={()=>setError('This browser cannot play the generated H.264/AAC MP4.')} />
    :liveFrame?<div className="live-sim-frame"><canvas ref={canvas} width="320" height="224" aria-label={`Confirmed sim frame ${liveFrame.frame}`}/><span>Output frame {liveFrame.frame} / {liveFrame.total-1} · {processing?'Processing':'Stopped'}</span></div>
    :<div className="emulator-empty"><FileVideo size={36}/><strong>Encoded /sim playback</strong><span>Generate CAVC to create the playback MP4.</span></div>}
  </div>
  <div hidden={compact} className="output-player-controls"><span>{encodedPreview?.name||'No encoded playback yet'}</span></div>
  {error&&<p role="alert" className="error-text">{error}</p>}
  {!compact&&<p className="hint">Canonical CAVC display · Reconstructed ADPCM/RF5C164 audio</p>}
 </div>;
}
