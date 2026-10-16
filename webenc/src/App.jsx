import { useEffect, useRef, useState } from "react";
import {
  FileVideo,
  CaretDown,
  CaretRight,
  Play,
  ArrowCounterClockwise,
  Stop,
  Copy,
  Info,
  DownloadSimple,
  Globe,
  XLogo,
  GithubLogo,
  YoutubeLogo,
} from "@phosphor-icons/react";
import { clamp, normalizeCrop, dragCrop, framing } from "./geometry";
import { OutputPlayer } from "./OutputPlayer";
import { selectColdCap, parseColdCap } from "./cold-cap";
import { inspectVideo } from "./metadata";
import { createPythonEncoderWorker } from "./python-worker-client";
import { createCavcPackage } from "./cavc-package";
import {EditorTimeline} from './EditorTimeline';
import {EncodeSummary} from './EncodeSummary';
import {availablePictureDimensions, selectPictureDimensions} from './picture-dimensions';
import {automaticOutputFps, outputFrameRates} from './output-fps';
import {encoderErrorNotice} from './encoder-error';
import {Licenses} from './Licenses';
import {subscribeOfflineEncoder, prepareOfflineEncoder} from './offline-runtime';

const pythonStages = ["Read source", "Train MOSAIC-GM", "Quantize", "Plan delivery", "Encode", "Pack & verify", "Reconstruct /sim", "Create playback MP4", "Build ISO & CUE", "ZIP"];

const emptySource = {name: "", url: "", width: 0, height: 0, duration: 0, inspecting: false};
const sourceFrameLimitNotice = "Max 32,767 output frames (≈22m45s at 24fps).";
const formatTime = (s) =>
  `${String(Math.floor((s || 0) / 60)).padStart(2, "0")}:${String(Math.floor((s || 0) % 60)).padStart(2, "0")}`;
const pixelAspectPresets = { auto: [1, 1], square: [1, 1], h40: [32, 35], h32: [8, 7] };
const Icon = ({ as: Component, ...props }) => (
  <Component size={20} weight="regular" aria-hidden="true" {...props} />
);
function downloadBlob(blob, name) {
  const url = URL.createObjectURL(blob),
    link = document.createElement("a");
  link.href = url;
  link.download = name;
  link.click();
  setTimeout(() => URL.revokeObjectURL(url), 10000);
}

export function App({ encodedPreview = null } = {}) {
  const [offline, setOffline] = useState({status: 'loading', done: 0, total: 0, detail: 'Preparing offline encoder…'});
  const offlineLogId = useRef(0);
  useEffect(() => subscribeOfflineEncoder(state => {
    setOffline(state);
    if (state.entry && state.entry.id > offlineLogId.current) {
      offlineLogId.current = state.entry.id;
      setLogs(previous => [...previous.slice(-199), state.entry.text]);
    }
  }), []);
  const runtimeReady = offline.status === 'ready' || offline.status === 'development';
  const [source, setSource] = useState(emptySource);
  useEffect(() => {
    if (encodedPreview) setOutputMode("playback");
  }, [encodedPreview]);
  const [crop, setCrop] = useState({ x: 0, y: 0, w: 640, h: 360 });
  const [lock, setLock] = useState(true);
  const [sarMode, setSarMode] = useState("auto");
  const [customSar, setCustomSar] = useState({ n: "1", d: "1" });
  const [dimensions, setDimensions] = useState("320x224");
  const [fit, setFit] = useState("pad");
  const [fps, setFps] = useState("source");
  const [sourceFps, setSourceFps] = useState("24");
  const [region, setRegion] = useState(() => /^en(?:-|$)/i.test(navigator.language) ? "North America" : "Japan");
  const [startFrame, setStartFrame] = useState(0);
  const [endFrame, setEndFrame] = useState(null);
  const [outputMode, setOutputMode] = useState("framing");
  const [advanced, setAdvanced] = useState(false);
  const [coldOverride, setColdOverride] = useState(null);
  const [playing, setPlaying] = useState(false);
  const [time, setTime] = useState(0);
  const [monitorSize,setMonitorSize]=useState({width:360,height:270});
  const previewGrid=useRef(null);
  const [muted, setMuted] = useState(false);
  const [notice, setNotice] = useState("");
  const [logOpen, setLogOpen] = useState(true);
  const [job, setJob] = useState({
    status: "idle",
    kind: "python",
    stage: -1,
    progress: 0,
    overall: 0,
    elapsed: 0,
  });
  const [logs, setLogs] = useState([
    "Choose a source video to begin. Processing stays on your device.",
  ]);
  const [packageBlob, setPackageBlob] = useState(null);
  const [localPreview, setLocalPreview] = useState(null);
  const [encodeSummary,setEncodeSummary]=useState(null);
  const [liveFrame,setLiveFrame]=useState(null);
  const currentStages = pythonStages;
  const videoRef = useRef(null),
    imageRef = useRef(null),
    canvasRef = useRef(null);
  const sourceSurface = useRef(null),
    outputSurface = useRef(null),
    workerRef = useRef(null),
    fileInput = useRef(null);
  const drag = useRef(null),
    selectionSequence = useRef(0),
    started = useRef(0),
    logRef = useRef(null),
    rows = useRef([]),
    sourceUrl = useRef(null),
    jobSnapshot = useRef(null);
  const busy = job.status === "running";
  const warnBeforeLeaving = busy || job.status === "complete";
  useEffect(() => {
    if (!warnBeforeLeaving) return;
    const beforeUnload = event => {
      event.preventDefault();
      event.returnValue = "";
    };
    window.addEventListener("beforeunload", beforeUnload);
    return () => window.removeEventListener("beforeunload", beforeUnload);
  }, [warnBeforeLeaving]);
  useEffect(()=>{
    document.title=busy ? `${Math.round(job.overall)}% · SEGA-CD FMV Encoder for CAVC` : 'SEGA-CD FMV Encoder for CAVC';
  },[busy,job.overall]);
  useEffect(()=>()=>{document.title='SEGA-CD FMV Encoder for CAVC';},[]);
  useEffect(()=>{
    if(job.status!=="complete")return;
    const timer=setTimeout(()=>window.alert("Encoding complete. Download ZIP contains ISO, CUE and playback MP4."),0);
    return()=>clearTimeout(timer);
  },[job.status]);
  const controlsLocked = busy || Boolean(source.normalized);
  const stillSource = source.sample || source.normalized;
  const sarValid =
    sarMode !== "custom" ||
    (Number(customSar.n) > 0 && Number(customSar.d) > 0);
  const pixelAspect = pixelAspectPresets[sarMode] ||
    (sarValid ? [Number(customSar.n), Number(customSar.d)] : [1, 1]);
  const sar = pixelAspect[0] / pixelAspect[1];
  const [width, height] = dimensions.split("x").map(Number);
  const effectiveFps = fps === "source" ? (source.normalized ? Number(sourceFps) : automaticOutputFps(sourceFps)) : Number(fps);
  const automaticCap = selectColdCap(width, height, effectiveFps);
  const manualColdCap = coldOverride?.key === automaticCap.key;
  const coldCap = source.normalized?.environment?.CBRSIM_COLD_CAP ?? (manualColdCap ? coldOverride.value : automaticCap.value);
  const coldCapValid = parseColdCap(coldCap, effectiveFps).valid;
  useEffect(() => {
    setColdOverride(null);
  }, [width, height, effectiveFps]);
  const duration = source.duration;
  const sourceFrames = source.normalized?.frames ?? source.frameTimes?.length ?? Math.max(1,Math.ceil(duration*Number(sourceFps)-1e-7));
  const lastFrame = sourceFrames-1;
  const rangeStart = Math.min(startFrame,lastFrame);
  const rangeEnd = Math.max(rangeStart,Math.min(endFrame??lastFrame,lastFrame));
  const frameTime = frame => source.frameTimes ? source.frameTimes[frame]-source.frameTimes[0] : frame/Number(sourceFps);
  let currentFrame=Math.min(lastFrame,Math.floor(time*Number(sourceFps)+1e-6));
  if(source.frameTimes){
    let low=0,high=lastFrame;
    while(low<high){const middle=Math.ceil((low+high)/2);if(frameTime(middle)<=time+1e-6)low=middle;else high=middle-1;}
    currentFrame=low;
  }
  useEffect(()=>{
    const grid=previewGrid.current;
    const workspace=grid.closest('.workspace');
    const timeline=workspace.querySelector('.editor-timeline');
    const chrome=[...grid.querySelectorAll('.panel-heading,.crop-toolbar,.output-monitor-info')];
    const outerHeight=element=>{
      const style=getComputedStyle(element);
      return element.getBoundingClientRect().height+parseFloat(style.marginTop)+parseFloat(style.marginBottom);
    };
    const observer=new ResizeObserver(()=>{
      const availableWidth=grid.clientWidth;
      const panelExtras=Math.max(...[...grid.children].map(panel=>
        [...panel.querySelectorAll('.panel-heading,.crop-toolbar,.output-monitor-info')].reduce((sum,element)=>sum+outerHeight(element),0)));
      const idealFrameHeight=availableWidth*.45*3/4;
      // Cap the editor at its useful height; the lower dock gets spare space.
      workspace.style.setProperty('--editor-max-height',`${idealFrameHeight+panelExtras+outerHeight(timeline)+20}px`);
      const monitorHeight=Math.max(60,Math.min(idealFrameHeight,grid.clientHeight-panelExtras));
      setMonitorSize({width:monitorHeight*4/3,height:monitorHeight});
    });
    for(const element of [grid,timeline,...chrome])observer.observe(element);
    return()=>observer.disconnect();
  },[]);
  const rangeDuration = (rangeEnd===lastFrame ? duration : frameTime(rangeEnd+1))-frameTime(rangeStart);
  useEffect(()=>{
    if(!playing||source.normalized)return;
    let timer;
    const end=(rangeEnd===lastFrame)?duration:frameTime(rangeEnd+1);
    const check=()=>{
      const video=videoRef.current;
      if(video&&video.currentTime>=end){video.pause();seek(frameTime(rangeEnd));setPlaying(false);}
      else timer=requestAnimationFrame(check);
    };
    timer=requestAnimationFrame(check);return()=>cancelAnimationFrame(timer);
  },[playing,rangeEnd,duration,source.frameTimes,sourceFps,lastFrame]);
  function updateFrameRange(kind,value) {
    const frame=clamp(Math.round(Number(value)||0),0,lastFrame);
    const selected=kind==='start'?Math.min(frame,rangeEnd):Math.max(frame,rangeStart);
    if(kind==='start')setStartFrame(selected);
    else setEndFrame(selected);
    seek(frameTime(selected));
    setOutputMode('framing');
    videoRef.current?.pause();setPlaying(false);
    invalidate();
  }
  const baseName =
    source.name.replace(/\.[^.]+$/, "").replace(/[^a-zA-Z0-9_-]/g, "_") ||
    "video";
  const appendLog = (line) => setLogs((old) => [...old.slice(-199), line]);
  const invalidate = () => {
    setEncodeSummary(null);
    setPackageBlob(null);
    setLocalPreview(null);
    setLiveFrame(null);
    setJob((old) =>
      old.status === "running"
        ? old
        : { ...old, status: "idle", stage: -1, progress: 0, overall: 0 },
    );
  };
  const change = (setter, value) => {
    setter(value);
    invalidate();
  };
  const updateCrop = (value) => {
    setCrop(normalizeCrop(value, source.width, source.height));
    invalidate();
  };
  const settings = () => ({
    prototype: false,
    encoderImplemented: true,
    source: {
      name: source.name,
      width: source.width,
      height: source.height,
      duration,
      fps: Number(sourceFps),
      frameRange: {startFrame: rangeStart,endFrame: rangeEnd},
      fpsOrigin:
        source.nativeFps === Number(sourceFps) ? "detected" : "user-declared",
      pixelAspect,
      pixelAspectMode: sarMode,
      pixelAspectOrigin:
        sarMode === "auto"
          ? "square-pixel fallback; source pixel aspect is not detected"
          : "user-declared",
      crop,
    },
    video: {
      width,
      height,
      fit,
      fps: effectiveFps,
      fpsMode: fps,
      outputPixelAspect: [32, 35],
      aperture: [320, 224],
    },
    audio: {
      mode: "source",
      output: "22050 Hz mono IMA ADPCM",
    },
    encoder: {
      coldCap: /^\d+$/.test(coldCap) ? Number(coldCap) : coldCap,
      coldCapMode: manualColdCap ? "manual" : "auto",
      coldCapReference: automaticCap,
      palette: "mosaic-gm",
    },
    region,
  });

  useEffect(
    () => () => {
      workerRef.current?.terminate();
      if (sourceUrl.current) URL.revokeObjectURL(sourceUrl.current);
    },
    [],
  );
  useEffect(() => {
    if (logRef.current) logRef.current.scrollTop = logRef.current.scrollHeight;
  }, [logs]);
  useEffect(() => {
    if (!busy) return;
    const timer = setInterval(
      () =>
        setJob((old) => ({
          ...old,
          elapsed: (Date.now() - started.current) / 1000,
        })),
      250,
    );
    return () => clearInterval(timer);
  }, [busy]);
  useEffect(() => {
    let raf;
    const render = () => {
      const media = stillSource ? imageRef.current : videoRef.current;
      const canvas = canvasRef.current;
      if (
        canvas &&
        media &&
        (stillSource
          ? media.complete && media.naturalWidth
          : media.readyState >= 2)
      ) {
        const ctx = canvas.getContext("2d");
        ctx.fillStyle = "#000";
        ctx.fillRect(0, 0, 320, 224);
        ctx.imageSmoothingEnabled = true;
        const p = framing(crop, sar, width, height, fit);
        ctx.drawImage(
          media,
          p.sx,
          p.sy,
          p.sw,
          p.sh,
          (320 - width) / 2 + p.dx,
          (224 - height) / 2 + p.dy,
          p.dw,
          p.dh,
        );
      }
      raf = requestAnimationFrame(render);
    };
    render();
    return () => cancelAnimationFrame(raf);
  }, [source, crop, sar, width, height, fit]);
  useEffect(() => {
    if (!playing || !source.sample) return;
    const timer = setInterval(
      () =>
        setTime((old) => {
          if (old + 0.1 >= duration) {
            setPlaying(false);
            return 0;
          }
          return old + 0.1;
        }),
      100,
    );
    return () => clearInterval(timer);
  }, [playing, source.sample, duration]);

  function loadVideo(file, autoDimensions = true) {
    if (!file || busy) return;
    const selection = ++selectionSequence.current;
    setStartFrame(0);setEndFrame(null);
    if (/\.cavc-input\.zip$/i.test(file.name)) {
      loadNormalized(file, selection);
      return;
    }
    if (
      !file.type.startsWith("video/") &&
      !/\.(mp4|webm|mov)$/i.test(file.name)
    ) {
      setNotice("Choose an MP4, WebM, or MOV video.");
      return;
    }
    setPlaying(false);
    setStartFrame(0);setEndFrame(null);
    setNotice("");
    setOutputMode("framing");
    invalidate();
    setJob(old => ({ ...old, kind: "python" }));
    if (sourceUrl.current) URL.revokeObjectURL(sourceUrl.current);
    sourceUrl.current = URL.createObjectURL(file);
    setSource({
      file,
      autoDimensions,
      inspecting: true,
      name: file.name,
      url: sourceUrl.current,
      width: 1920,
      height: 1080,
      duration: 0,
      sample: false,
    });
    setTime(0);
    setCrop({ x: 0, y: 0, w: 1920, h: 1080 });
    setSarMode("auto");
    appendLog(`Selected local video: ${file.name}. No file upload.`);
    const selectedUrl = sourceUrl.current;
    inspectVideo(file)
      .then((metadata) => {
        if (sourceUrl.current !== selectedUrl) return;
        const rate = Number(metadata.fps.toFixed(6));
        setSource((old) => ({ ...old, inspecting: false, nativeFps: rate, frameTimes: metadata.frameTimes }));
        setSourceFps(String(rate));
        setFps("source");
        appendLog(`Detected source frame rate: ${rate} fps. Automatic output: ${automaticOutputFps(rate)} fps.`);
      })
      .catch((error) => {
        if (sourceUrl.current === selectedUrl) {
          setSource((old) => ({ ...old, inspecting: false }));
          appendLog(
            `Frame-rate detection unavailable: ${error.message}. Confirm source fps manually.`,
          );
        }
      });
  }
  async function loadNormalized(file, selection) {
    const inspector = new Worker(new URL("./normalized-inspect-worker.js", import.meta.url), { type: "module" });
    setNotice("Reading normalized frames and profile…");
    setSource(old => ({ ...old, inspecting: true }));
    try {
      const data = await new Promise((resolve, reject) => {
        inspector.onmessage = ({ data }) => data.type === "error" ? reject(new Error(data.message)) : resolve(data);
        inspector.onerror = event => reject(new Error(event.message));
        inspector.postMessage({ file });
      });
      if (selection !== selectionSequence.current) return;
      const m = data.manifest;
      invalidate();
      if (sourceUrl.current) URL.revokeObjectURL(sourceUrl.current);
      sourceUrl.current = URL.createObjectURL(new Blob([data.poster], { type: "image/png" }));
      setSource({ file, normalized: m, name: file.name, url: sourceUrl.current, width: m.width, height: m.height, duration: Number(m.duration), inspecting: false });
      setCrop({ x: 0, y: 0, w: m.width, h: m.height });
      setDimensions(`${m.width}x${m.height}`);
      setSourceFps(String(m.fps));setFps("source");
      setSarMode("custom");setCustomSar({ n: "32", d: "35" });
      setTime(0);setPlaying(false);setOutputMode("framing");
      setNotice("");
      setJob(old => ({ ...old, kind: "python", status: "idle", stage: -1, progress: 0, overall: 0 }));
      appendLog(`Normalized input: ${m.frames} frames, ${m.fps} fps. Profile settings are fixed; no video decoding or filtering.`);
    } catch (error) {
      if (selection === selectionSequence.current) {
        setSource(old => ({ ...old, inspecting: false }));
        setNotice(`Cannot read normalized input: ${error.message}`);
      }
    }
    finally { inspector.terminate(); }
  }
  function loadedMetadata() {
    const v = videoRef.current;
    if (!v.videoWidth || !Number.isFinite(v.duration) || v.duration <= 0) {
      setNotice(
        "This video has no readable duration or dimensions. Try a standard MP4.",
      );
      return;
    }
    setSource((old) => ({
      ...old,
      width: v.videoWidth,
      height: v.videoHeight,
      duration: v.duration,
    }));
    setCrop({ x: 0, y: 0, w: v.videoWidth, h: v.videoHeight });
    if (source.autoDimensions) {
      const selected = selectPictureDimensions(v.videoWidth, v.videoHeight, sar);
      setDimensions(selected);
      appendLog(`Picture dimensions automatically selected: ${selected}.`);
    }
    appendLog(
      `Video ready: ${v.videoWidth} × ${v.videoHeight}, ${formatTime(v.duration)}. Confirm source fps below.`,
    );
  }
  function seek(t) {
    const value = clamp(t, 0, duration);
    setTime(value);
    if (videoRef.current && !source.sample && videoRef.current.readyState >= 1)
      videoRef.current.currentTime = value;
  }
  async function togglePlay() {
    if (!source.sample && videoRef.current) {
      if (playing) {
        videoRef.current.pause();
        setPlaying(false);
      } else
        try {
          if(time<frameTime(rangeStart)||time>=((rangeEnd===lastFrame)?duration:frameTime(rangeEnd+1)))seek(frameTime(rangeStart));
          await videoRef.current.play();
          setPlaying(true);
        } catch {
          setNotice("Playback is not available. Try another video format.");
        }
    } else setPlaying((old) => !old);
  }
  function pointerDown(e, handle) {
    if (controlsLocked) return;
    if (busy) return;
    e.preventDefault();
    e.stopPropagation();
    const bounds = sourceSurface.current.getBoundingClientRect();
    drag.current = {
      handle,
      start: crop,
      px: e.clientX,
      py: e.clientY,
      bounds,
    };
    e.currentTarget.setPointerCapture(e.pointerId);
  }
  function pointerMove(e) {
    const d = drag.current;
    if (!d) return;
    updateCrop(
      dragCrop(
        d.start,
        d.handle,
        ((e.clientX - d.px) / d.bounds.width) * source.width,
        ((e.clientY - d.py) / d.bounds.height) * source.height,
        source.width,
        source.height,
        lock,
      ),
    );
  }
  function editCrop(key, value) {
    let next = { ...crop, [key]: Number(value) };
    if (lock && (key === "w" || key === "h")) {
      const r = crop.w / crop.h;
      if (key === "w") {
        next.w = clamp(
          Number(value),
          1,
          Math.min(source.width - crop.x, (source.height - crop.y) * r),
        );
        next.h = next.w / r;
      } else {
        next.h = clamp(
          Number(value),
          1,
          Math.min(source.height - crop.y, (source.width - crop.x) / r),
        );
        next.w = next.h * r;
      }
    }
    updateCrop(next);
  }
  function startPythonEncode() {
    if (!runtimeReady || busy || !source.file || source.inspecting || !sarValid || !coldCapValid) return;
    setEncodeSummary(null);
    started.current = Date.now();
    setNotice("");setPackageBlob(null);setLocalPreview(null);setLiveFrame(null);setPlaying(false);
    videoRef.current?.pause();
    setLogs(["Original Python codec started in WebAssembly. MOSAIC-GM, Bayer dither, original decisions and full pattern-supply planning is enabled."]);
    setJob({ status: "running", kind: "python", stage: 0, progress: 0, overall: 0, elapsed: 0 });
    const worker = createPythonEncoderWorker();workerRef.current = worker;
    const fail = message => {
      worker.terminate();workerRef.current = null;
      setJob(old => ({ ...old, status: "error" }));setNotice(encoderErrorNotice(message));appendLog(message);
    };
    const followFrame = index => {
      if(source.normalized)return;
      const timestamp=Math.min(frameTime(rangeEnd),frameTime(rangeStart)+index/effectiveFps);
      let low=rangeStart,high=rangeEnd;
      while(low<high){const middle=Math.ceil((low+high)/2);if(frameTime(middle)<=timestamp+1e-6)low=middle;else high=middle-1;}
      // Container timestamps can truncate a frame boundary by a microsecond.
      seek(Math.min(duration,frameTime(low)+1e-6));
    };
    worker.onmessage = ({ data }) => {
      if (workerRef.current !== worker) return;
      if (data.type === "error") { fail(data.message); return; }
      if (data.type === 'frame') {
        setLiveFrame(data);setOutputMode('playback');
        followFrame(data.frame);
        return;
      }
      if (data.type === 'features') {setEncodeSummary(data.summary);return;}
      if (data.type === "log") { appendLog(data.message); return; }
      if (data.type === "progress") {
        if(Number.isInteger(data.frameIndex))followFrame(data.frameIndex);
        setJob(old => ({ ...old, stage: data.stage, progress: data.progress??0,
          indeterminate:data.indeterminate,detail:data.detail||currentStages[data.stage],
          doneFrames:data.done||0,frames:data.total||0,
          overall:Math.max(old.overall,data.overall) }));return;
      }
      if (data.type === "complete") {
        try {
          setJob(old => ({ ...old, stage: 9, progress: 0 }));
          setPackageBlob(new Blob([createCavcPackage(data)], { type: "application/zip" }));
          setLocalPreview(new File([data.files["preview.mp4"]], `${baseName}_sim.mp4`, { type: "video/mp4" }));
          setOutputMode("playback");
          setJob(old => ({ ...old, status: "complete", progress: 100, overall: 100 }));
          appendLog(`CAVC stream complete: ${data.manifest.frames} frames. Canonical /sim playback, ISO and CUE packaged.`);
          worker.terminate();workerRef.current = null;
        } catch (error) { fail(error.message); }
      }
    };
    worker.onerror = event => fail(event.message || "Python encoder stopped");
    worker.postMessage({ type: "start", file: source.file, settings: settings() });
  }
  function cancelDemo() {
    workerRef.current?.terminate();
    workerRef.current = null;
    setJob((old) => ({ ...old, status: "cancelled" }));
    appendLog("Processing cancelled. Settings are editable again.");
  }

  return (
    <main className="app-shell">
      <header className="app-header">
        <div>
          <div className="title-row">
            <h1>SEGA-CD FMV Encoder for CAVC</h1>
            <span className="badge">simplified ver</span>
          </div>
        </div>
        <div className={`offline-status ${offline.status}`} role="status"
          title={offline.status === 'ready' ? 'Encoding needs no network connection. Files stay on your device.' : offline.detail}>
          <span className="status-dot" aria-hidden="true" />
          <span className="offline-detail">{offline.status === 'ready' ? 'Offline ready · Files stay on your device' : offline.detail}</span>
          {offline.status === 'loading' && <progress aria-label="Offline encoder download" max={offline.total || 1} value={offline.total ? offline.done : undefined} />}
          {offline.status === 'error' && <button type="button" onClick={prepareOfflineEncoder}>Retry download</button>}
        </div>
      </header>
      {notice && (
        <div role="alert" className="notice">
          <Icon as={Info} />
          {notice}
          <button onClick={() => setNotice("")} aria-label="Dismiss message">
            Dismiss
          </button>
        </div>
      )}
      <div className="workspace">
        <aside className="settings">
          <div className="settings-scroll">
          <section>
            <h2>Source video</h2>
            <button
              className="file-picker"
              disabled={busy}
              onClick={() => fileInput.current.click()}
              onDragOver={(e) => e.preventDefault()}
              onDrop={(e) => {
                e.preventDefault();
                loadVideo(e.dataTransfer.files[0]);
              }}
            >
              <Icon as={FileVideo} size={29} />
              <span>
                <strong>
                  {source.name || "Choose video"}
                </strong>
                <small>
                  {source.file ? `${source.width} × ${source.height} · ${formatTime(duration)}` : "MP4, WebM or MOV"}
                </small>
              </span>
              <span className="replace">{source.file ? "Replace" : "Browse"}</span>
            </button>
            <p className="hint source-frame-limit-hint">{sourceFrameLimitNotice}</p>
            <input
              ref={fileInput}
              type="file"
              accept="video/mp4,video/webm,video/quicktime,.mp4,.webm,.mov,.cavc-input.zip"
              hidden
              onChange={(e) => {
                loadVideo(e.target.files[0]);
                e.target.value = "";
              }}
            />
            <p className="hint">{source.normalized ? "Normalized RGB/PCM input. Profile controls are fixed; preview shows the first frame." : "Audio comes from the input video. Normalized .cavc-input.zip is also supported."}</p>
          </section>
          <section>
            <h2>Source pixel aspect</h2>
            <div
              className="segmented"
              role="group"
              aria-label="Source pixel aspect"
            >
              {[
                ["auto", "Auto"],
                ["square", "1:1"],
                ["h40", "32:35"],
                ["h32", "8:7"],
                ["custom", "Custom"],
              ].map(([value, label]) => (
                <button
                  key={value}
                  disabled={controlsLocked}
                  aria-pressed={sarMode === value}
                  className={sarMode === value ? "selected" : ""}
                  onClick={() => change(setSarMode, value)}
                >
                  {label}
                </button>
              ))}
            </div>
            {sarMode === "custom" ? (
              <div className="ratio-fields">
                <input
                  aria-label="Pixel aspect numerator"
                  type="number"
                  min="0.01"
                  step="any"
                  disabled={controlsLocked}
                  value={customSar.n}
                  onChange={(e) =>
                    change(setCustomSar, { ...customSar, n: e.target.value })
                  }
                />
                <span>:</span>
                <input
                  aria-label="Pixel aspect denominator"
                  type="number"
                  min="0.01"
                  step="any"
                  disabled={controlsLocked}
                  value={customSar.d}
                  onChange={(e) =>
                    change(setCustomSar, { ...customSar, d: e.target.value })
                  }
                />
                <span>width : height</span>
              </div>
            ) : (
              <p className="hint">
                {sarMode === "auto"
                  ? "Auto uses 1:1; source pixel aspect is not detected."
                  : sarMode === "h40" ? "32:35 · H40 source pixels."
                  : sarMode === "h32" ? "8:7 · H32 source pixels. Output remains H40."
                  : "Square source pixels (1:1)."}
              </p>
            )}
            {!sarValid && (
              <p role="alert" className="error-text">
                Both ratio values must be greater than zero.
              </p>
            )}
          </section>
          <section className="output-settings">
            <h2>Output video settings</h2>
            <label className="setting-row">
              <span>Picture dimensions</span>
              <select
                aria-label="Picture dimensions"
                value={dimensions}
                disabled={controlsLocked}
                onChange={(e) => change(setDimensions, e.target.value)}
              >
                {availablePictureDimensions(source.width, source.height).map(value => <option key={value}>{value}</option>)}
                {source.normalized && !availablePictureDimensions(source.width, source.height).includes(dimensions) && <option>{dimensions}</option>}
              </select>
            </label>
            <label className="setting-row">
              <span>Fit</span>
              <select
                aria-label="Fit"
                value={fit}
                disabled={controlsLocked}
                onChange={(e) => change(setFit, e.target.value)}
              >
                <option value="pad">Preserve aspect</option>
                <option value="crop">Fill picture (crop)</option>
              </select>
            </label>
            <label className="setting-row">
              <span>Frame rate (fps)</span>
              <select
                aria-label="Frame rate"
                value={fps}
                disabled={controlsLocked}
                onChange={(e) => change(setFps, e.target.value)}
              >
                <option value="source">Auto · {source.normalized ? sourceFps : automaticOutputFps(sourceFps)} fps</option>
                {outputFrameRates.map(rate => <option key={rate} value={rate}>{rate} fps</option>)}
              </select>
            </label>
            {source.file && !source.normalized && Number(sourceFps) !== effectiveFps && <p className="hint">Source {sourceFps} fps → {effectiveFps} fps. Timing and audio speed are preserved.</p>}
            <label className="setting-row">
              <span>Region</span>
              <select
                aria-label="Region"
                value={region}
                disabled={controlsLocked}
                onChange={(e) => change(setRegion, e.target.value)}
              >
                <option value="Japan">Japan (NTSC)</option>
                <option value="North America">North America (NTSC)</option>
              </select>
            </label>
            <div className="setting-row">
              <span>Output audio</span>
              <span className="fixed-value">22.05 kHz mono ADPCM</span>
            </div>
          </section>
          <button
            className="disclosure"
            aria-expanded={advanced}
            onClick={() => setAdvanced(!advanced)}
          >
            <Icon as={advanced ? CaretDown : CaretRight} size={15} />
            Advanced settings
          </button>
          <p className="hint cap-summary">
            Cold cap: {coldCap || "—"} ·{" "}
            {manualColdCap
              ? "Manual"
              : automaticCap.kind === "profile"
                ? "Auto · profile"
                : "Auto · estimate"}
          </p>
          {advanced && (
            <div className="advanced-fields">
              <label className="setting-row">
                <span>Source fps</span>
                <input
                  aria-label="Source fps"
                  type="number"
                  min="1"
                  max="120"
                  step="any"
                  disabled={controlsLocked}
                  value={sourceFps}
                  onChange={(e) => change(setSourceFps, e.target.value)}
                />
              </label>
              <p className="hint fps-hint">
                {source.nativeFps
                  ? "Detected from video; editable override."
                  : "Confirm source fps manually."}
              </p>
              <label className="setting-row">
                <span>Cold cap</span>
                <input
                  aria-label="Cold cap"
                  type="text"
                  spellCheck={false}
                  aria-invalid={!coldCapValid}
                  value={coldCap}
                  disabled={controlsLocked}
                  onChange={(e) =>
                    change(setColdOverride, {
                      key: automaticCap.key,
                      value: e.target.value,
                    })
                  }
                />
              </label>
              <div className="cold-cap-note">
                <p className="hint">
                  {manualColdCap ? "Manual override" : "Auto"} ·{" "}
                  {automaticCap.reason}
                </p>
                {manualColdCap && (
                  <button
                    disabled={controlsLocked}
                    onClick={() => change(setColdOverride, null)}
                  >
                    Use automatic cap
                  </button>
                )}
              </div>
              {!coldCapValid && (
                <p className="error-text" role="alert">
                  Enter a positive integer, or the matching cadence caps (for 24
                  fps: 2:180,3:230).
                </p>
              )}
              <p className="hint">Original MOSAIC-GM palette training and Bayer dither.</p>
            </div>
          )}
          </div>
          <button
            className="primary encode-button"
            disabled={
              !runtimeReady ||
              busy ||
              source.inspecting ||
              !source.file ||
              !sarValid ||
              !coldCapValid ||
              duration <= 0 ||
              effectiveFps <= 0
            }
            onClick={startPythonEncode}
          >
            <Icon as={busy ? Stop : Play} weight="fill" />
            {busy ? "Processing…" : !runtimeReady ? "Preparing encoder…" : source.inspecting ? "Reading video…" : "Generate CAVC"}
          </button>
          <p className="demo-disclaimer">CAVC encode, /sim playback and bootable disc.</p>
        </aside>
        <section className="previews" aria-label="Video previews">
          <div className="preview-grid" ref={previewGrid} style={{'--output-width':`${monitorSize.width}px`,'--preview-height':`${monitorSize.height}px`}}>
            <div className="preview-panel">
              <div className="panel-heading">
                <h2>
                  Source <span>{source.normalized ? "· first normalized frame" : "· adjust crop"}</span>
                </h2>
                <small>
                  {source.file ? `${source.width} × ${source.height}` : "No video selected"}
                </small>
              </div>
              <div className="source-frame" onDragOver={e=>{if(!source.file)e.preventDefault();}}
                onDrop={e=>{if(!source.file){e.preventDefault();loadVideo(e.dataTransfer.files[0]);}}}>
                {!source.file && <button className="empty-preview source-video-picker" disabled={busy}
                  aria-label="Choose source video" onClick={()=>fileInput.current.click()}>
                  <Icon as={FileVideo} size={32}/><span>Choose a source video to begin</span><small>Click to browse or drop a video here</small>
                </button>}
                <div
                  hidden={!source.file}
                  ref={sourceSurface}
                  className="source-surface"
                  style={{
                    aspectRatio: `${source.width * sar} / ${source.height}`,
                    "--source-ratio": (source.width * sar) / source.height,
                  }}
                >
                  {!source.file ? null : stillSource ? (
                    <img
                      ref={imageRef}
                      src={source.normalized ? source.url : "/sample-coast.png"}
                      alt={source.normalized ? "First normalized source frame" : "Sample coastal landscape"}
                      draggable="false"
                    />
                  ) : (
                    <video
                      ref={videoRef}
                      src={source.url}
                      preload="auto"
                      playsInline
                      muted={muted}
                      onLoadedMetadata={loadedMetadata}
                      onTimeUpdate={(e) => setTime(e.currentTarget.currentTime)}
                      onEnded={() => setPlaying(false)}
                      onError={() =>
                        setNotice(
                          "This browser cannot play the selected video. Try an H.264 MP4 or a WebM file.",
                        )
                      }
                    />
                  )}
                  <div
                    className={`crop-rect ${busy ? "locked" : ""}`}
                    data-testid="crop-rectangle"
                    role="group"
                    aria-label="Crop rectangle; use numeric fields for keyboard adjustment"
                    onPointerDown={(e) => pointerDown(e, "move")}
                    onPointerMove={pointerMove}
                    onPointerUp={() => {
                      drag.current = null;
                    }}
                    onPointerCancel={() => {
                      drag.current = null;
                    }}
                    style={{
                      left: `${(crop.x / source.width) * 100}%`,
                      top: `${(crop.y / source.height) * 100}%`,
                      width: `${(crop.w / source.width) * 100}%`,
                      height: `${(crop.h / source.height) * 100}%`,
                    }}
                  >
                    {["nw", "n", "ne", "e", "se", "s", "sw", "w"].map(
                      (handle) => (
                        <span
                          key={handle}
                          data-testid={`crop-${handle}`}
                          className={`crop-handle ${handle}`}
                          onPointerDown={(e) => pointerDown(e, handle)}
                        />
                      ),
                    )}
                    <span className="crop-size">
                      {crop.w} × {crop.h}
                    </span>
                  </div>
                </div>
                <span className="source-frame-limit">{sourceFrameLimitNotice}</span>
              </div>
              <div className="crop-toolbar">
              <div className="crop-fields">
                <span>Crop (px)</span>
                {["x", "y", "w", "h"].map((key) => (
                  <label key={key}>
                    {key.toUpperCase()}
                    <input
                      aria-label={`Crop ${key.toUpperCase()}`}
                      type="number"
                      min={key === "x" || key === "y" ? 0 : 1}
                      max={
                        key === "x" || key === "w"
                          ? source.width
                          : source.height
                      }
                      value={crop[key]}
                      disabled={controlsLocked}
                      onChange={(e) => editCrop(key, e.target.value)}
                    />
                  </label>
                ))}
              </div>
              <div className="crop-actions">
                <label className="check-label">
                  <input
                    type="checkbox"
                    checked={lock}
                    disabled={controlsLocked}
                    onChange={(e) => setLock(e.target.checked)}
                  />
                  Lock aspect
                </label>
                <button
                  disabled={controlsLocked}
                  onClick={() =>
                    updateCrop({
                      x: 0,
                      y: 0,
                      w: source.width,
                      h: source.height,
                    })
                  }
                >
                  <Icon as={ArrowCounterClockwise} size={15} />
                  Reset crop
                </button>
              </div>
              </div>
            </div>
            <div className="preview-panel">
              <div className="panel-heading">
                <h2>
                  Output{" "}
                  <span>
                    ·{" "}
                    {outputMode === "framing"
                      ? "framing preview"
                      : busy && liveFrame ? "confirmed sim frame" : "MP4 playback"}
                  </span>
                </h2>
                <div
                  className="output-mode"
                  role="group"
                  aria-label="Output preview mode"
                >
                  <button
                    aria-pressed={outputMode === "framing"}
                    onClick={() => setOutputMode("framing")}
                  >
                    Framing
                  </button>
                  <button
                    aria-pressed={outputMode === "playback"}
                    onClick={() => {
                      setOutputMode("playback");
                      if (videoRef.current) videoRef.current.pause();
                      setPlaying(false);
                    }}
                  >
                    Playback
                  </button>
                </div>
              </div>
              <div
                className="output-frame"
                ref={outputSurface}
                hidden={outputMode !== "framing"}
              >
                {!source.file && <div className="empty-preview"><span>Output preview appears after selecting a video</span></div>}
                <canvas
                  hidden={!source.file}
                  width="320"
                  height="224"
                  ref={canvasRef}
                  aria-label="Output framing preview"
                />
              </div>
              <OutputPlayer
                active={outputMode === "playback"}
                encodedPreview={localPreview || encodedPreview}
                compact liveFrame={liveFrame} processing={busy}
              />
              <div className="output-monitor-info">
                <span title="Output display box is 4:3. Encoded H40 pixels keep their 32:35 aspect.">{width} × {height} · {effectiveFps || '—'} fps · H40 32:35</span>
              </div>
            </div>
          </div>
          <EditorTimeline time={time} duration={duration} currentFrame={currentFrame} lastFrame={lastFrame}
            start={rangeStart} end={rangeEnd} rangeDuration={rangeDuration} playing={playing} muted={muted}
            disabled={controlsLocked||source.inspecting||!duration}
            onPlay={() => {setOutputMode('framing');togglePlay();}} onMute={() => setMuted(!muted)}
            onSeek={frame => {setOutputMode('framing');seek(frameTime(frame));}}
            onRange={updateFrameRange} onReset={() => {setStartFrame(0);setEndFrame(null);setOutputMode('framing');invalidate();}} />
          <div className="preview-footnote">
            <Icon as={Info} size={16} />
            <span>
              {source.normalized ? "First normalized input frame shown. Playback reproduces the encoded /sim result." : source.sample
                ? "Sample image loaded. Choose a video to test playback; the crop and framing controls work now."
                : "Video is processed locally. Playback reproduces the encoded /sim result, including tile updates and reconstructed audio."}
            </span>
          </div>
        </section>
      </div>
      <section className="progress-section" aria-label="Encoding progress">
        <div className="progress-content">
        <div className="progress-heading">
          <h2>
            {busy ? currentStages[job.stage] : job.status === "complete"
              ? "CAVC complete · Playback & ISO ready" : job.status === "cancelled"
              ? "Processing cancelled" : job.status === "error" ? "Processing interrupted" : "Encoding progress"}
          </h2>
          <div className="progress-summary">
            <span>{busy ? `${job.stage+1}/${currentStages.length}` : ''}</span>
            <strong>{Math.round(job.overall)}%</strong>
            {busy && <button className="cancel" onClick={cancelDemo}><Icon as={Stop} size={13} />Cancel</button>}
          </div>
        </div>
        <ol className="encoding-parts" aria-label="Encoding stages">
          {currentStages.map((label,index) => <li key={label}
            className={job.status === 'complete' || index < job.stage ? 'done' : index === job.stage ? (busy ? 'active' : 'stopped') : ''}
            aria-current={busy && index === job.stage ? 'step' : undefined}>
            <span>{job.status === 'complete' || index < job.stage ? '✓' : index+1}</span>{label}
          </li>)}
        </ol>
        <div
          className="progress-track"
          role="progressbar"
          aria-label="Overall encoding progress"
          aria-valuenow={Math.round(job.overall)}
          aria-valuemin="0"
          aria-valuemax="100"
        >
          <div style={{ width: `${job.overall}%` }} />
        </div>
        <div className={`stage-progress ${busy && job.indeterminate ? 'indeterminate' : ''}`} role="progressbar" aria-label="Current stage progress" aria-valuemin="0" aria-valuemax="100" aria-valuenow={busy && job.indeterminate ? undefined : Math.round(job.progress)} aria-valuetext={busy ? job.detail : job.status}>
          <div style={{width:busy && job.indeterminate ? '30%' : `${job.progress}%`}} />
        </div>
        <div className="progress-detail">
          <span>
            {busy ? `${job.detail||currentStages[job.stage]}${job.frames ? ` · ${job.doneFrames} / ${job.frames} frames` : ''}${job.indeterminate ? ' · Working…' : ` · ${Math.round(job.progress)}%`}` : job.status === "complete"
              ? "Playback MP4, ISO, CUE and CAVC stream packaged" : "Ready when you are"}
          </span>
          <span>
            Elapsed {formatTime(job.elapsed)}

          </span>
        </div>
        </div>
        <button className={`download-button progress-download ${packageBlob && !busy ? 'ready' : ''}`}
          disabled={!packageBlob || busy}
          aria-label="Download ZIP"
          aria-description="ZIP includes ISO, CUE and playback MP4."
          onClick={() => downloadBlob(packageBlob,`${baseName}_cavc.zip`)}>
          <Icon as={DownloadSimple} size={25} /><span>Download ZIP<small>ISO · CUE · MP4</small></span>
        </button>
      </section>
      <section className="bottom-section">
        <div className="logs">
          <div className="bottom-heading">
            <button
              className="disclosure"
              aria-expanded={logOpen}
              onClick={() => setLogOpen(!logOpen)}
            >
              <Icon as={logOpen ? CaretDown : CaretRight} size={15} />
              <h2>{offline.status === 'loading' && offline.fileCount ? `${offline.fileIndex}/${offline.fileCount} ` : ''}Activity log</h2>
            </button>
            <button
              className="quiet-button"
              aria-label="Copy activity log"
              onClick={async () => {
                try {
                  await navigator.clipboard.writeText(logs.join("\n"));
                  setNotice("Activity log copied.");
                } catch {
                  setNotice(
                    "Clipboard unavailable. Select and copy the log text.",
                  );
                }
              }}
            >
              <Icon as={Copy} size={15} />
              Copy
            </button>
          </div>
          {logOpen && (
            <pre
              ref={logRef}
              className="log-output"
              aria-label="Activity log"
              aria-live="polite"
            >
              {logs.join("\n")}
            </pre>
          )}
        </div>
        <EncodeSummary summary={encodeSummary} status={job.status}
          seekDisabled={Boolean(source.normalized)||busy}
          onSeek={frame => {setOutputMode('framing');videoRef.current?.pause();setPlaying(false);seek(frameTime(rangeStart)+frame/effectiveFps);}} />
      </section>
      <footer className="app-footer">
        <nav aria-label="Project and author links">
          <span className="footer-credit">by akiyan.com</span>
          <a className="footer-icon" href="https://www.akiyan.com/" aria-label="akiyan.com" title="www.akiyan.com" target="_blank" rel="noopener noreferrer"><Icon as={Globe} size={20} /></a>
          <a className="footer-icon" href="https://x.com/akiyan" aria-label="@akiyan on X" title="@akiyan on X" target="_blank" rel="noopener noreferrer"><Icon as={XLogo} size={19} /></a>
          <a className="footer-icon" href="https://github.com/akiyan/segacd-fmv-cavc" aria-label="GitHub" title="GitHub" target="_blank" rel="noopener noreferrer"><Icon as={GithubLogo} weight="fill" size={20} /></a>
          <a className="footer-icon" href="https://www.youtube.com/channel/UC6CTbKtzPPydO8lLwLzkF8w" aria-label="YouTube" title="YouTube" target="_blank" rel="noopener noreferrer"><Icon as={YoutubeLogo} weight="fill" size={20} /></a>
          <Licenses />
        </nav>
        <span className="footer-copyright">© 2026</span>
      </footer>
    </main>
  );
}
