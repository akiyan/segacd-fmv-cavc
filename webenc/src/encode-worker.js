import {
  Input,
  BlobSource,
  ALL_FORMATS,
  CanvasSink,
  AudioSampleSink,
  AudioSample,
  AudioSampleSource,
  Output,
  BufferTarget,
  Mp4OutputFormat,
  CanvasSource,
  canEncodeAudio,
  canEncodeVideo,
} from "mediabunny";
import { registerAacEncoder } from "@mediabunny/aac-encoder";
import { preparePreviewAac } from "./preview-audio";
import { createKernel } from "./kernel";
import { framing } from "./geometry";
import { createTemporalPreview } from "./temporal-preview";
import { previewDeliveryPlan, deliveryArtifacts, selectionBudgets } from "./delivery-plan";
const labels = [
  "Read source",
  "Train palette",
  "Encode audio",
  "Quantize & MP4",
  "Plan delivery",
  "Finalize MP4",
  "Package",
];
const report = (stage, progress, extra = {}) =>
  self.postMessage({
    type: "progress",
    stage,
    progress,
    overall: ((stage + progress / 100) / labels.length) * 100,
    label: labels[stage],
    ...extra,
  });
const log = (message) => self.postMessage({ type: "log", message });
function drawPicture(context, canvas, settings) {
  const { width, height, fit } = settings.video;
  const [n, d] = settings.source.pixelAspect;
  const p = framing(settings.source.crop, n / d, width, height, fit);
  context.fillStyle = "#000";
  context.fillRect(0, 0, width, height);
  context.drawImage(canvas, p.sx, p.sy, p.sw, p.sh, p.dx, p.dy, p.dw, p.dh);
}
async function run(file, settings) {
  let input, kernel, output, temporal;
  try {
    report(0, 0);
    log("Reading source locally; preparing Rust/WebAssembly preview kernel.");
    if (!self.VideoDecoder || !self.VideoEncoder)
      throw new Error(
        "This browser does not support WebCodecs video processing.",
      );
    if (
      !(await canEncodeVideo("avc", {
        width: 1024,
        height: 784,
        bitrate: 4000000,
        framerate: settings.video.fps,
      }))
    )
      throw new Error("H.264 MP4 encoding is not available in this browser.");
    input = new Input({ source: new BlobSource(file), formats: ALL_FORMATS });
    const track = await input.getPrimaryVideoTrack();
    if (!track || !(await track.canDecode()))
      throw new Error("The video track cannot be decoded. Try H.264 MP4.");
    const audio = await input.getPrimaryAudioTrack();
    if (audio && !(await audio.canDecode()))
      throw new Error("The video audio cannot be decoded. Try an AAC MP4.");
    const first = await track.getFirstTimestamp(),
      duration = await track.computeDuration(),
      fps = Number(settings.video.fps),
      frames = Math.ceil(duration * fps - 1e-7);
    if (!frames || frames > 100000)
      throw new Error("Choose a shorter video (up to 100,000 output frames).");
    kernel = await createKernel();
    const sink = new CanvasSink(track, {
      width: settings.source.width,
      height: settings.source.height,
      fit: "fill",
      poolSize: 2,
    });
    const { width, height } = settings.video;
    const budgets=selectionBudgets(frames,fps);
    const picture = new OffscreenCanvas(width, height),
      ctx = picture.getContext("2d", {
        willReadFrequently: true,
        alpha: false,
      });
    const sampleCount = Math.min(32, frames);
    const times = Array.from(
      { length: sampleCount },
      (_, i) => first + ((frames - 1) * i) / Math.max(1, sampleCount - 1) / fps,
    );
    report(0, 100, { frames });
    report(1, 0);
    log(
        `Training experimental four-line palette from ${sampleCount} frames. STL4/MOSAIC-GM remain pending.`,
    );
    let sampled = 0;
    for await (const frame of sink.canvasesAtTimestamps(times)) {
      if (!frame) throw new Error("A training frame could not be decoded.");
      drawPicture(ctx, frame.canvas, settings);
      kernel.accumulate(ctx.getImageData(0, 0, width, height).data);
      report(1, (++sampled / sampleCount) * 100, { frames });
    }
    const palette = kernel.trainPalette(),
      paletteBytes = kernel.paletteBytes(palette);
    report(2, 0);
    let decodedPcm = null,
      audioChunks = [];
    if (audio) {
      const sampleRate = 22050,
        total = Math.ceil(duration * sampleRate),
        resampled = new Float32Array(total);
      const audioSink = new AudioSampleSink(audio);
      for await (const sample of audioSink.samples()) {
        try {
          const values = new Float32Array(
            sample.numberOfFrames * sample.numberOfChannels,
          );
          sample.copyTo(values, { planeIndex: 0, format: "f32" });
          const start = sample.timestamp - first,
            begin = Math.max(0, Math.ceil(start * sampleRate)),
            end = Math.min(
              total,
              Math.floor((start + sample.duration) * sampleRate),
            );
          for (let i = begin; i < end; i++) {
            const position = (i / sampleRate - start) * sample.sampleRate,
              j = Math.min(
                sample.numberOfFrames - 1,
                Math.max(0, Math.floor(position)),
              ),
              next = Math.min(sample.numberOfFrames - 1, j + 1),
              fraction = Math.max(0, position - j);
            let sum = 0;
            for (let c = 0; c < sample.numberOfChannels; c++)
              sum +=
                values[j * sample.numberOfChannels + c] * (1 - fraction) +
                values[next * sample.numberOfChannels + c] * fraction;
            resampled[i] = sum / sample.numberOfChannels;
          }
          report(
            2,
            Math.min(
              90,
              Math.max(0, (start + sample.duration) / duration) * 90,
            ),
            { frames },
          );
        } finally {
          sample.close();
        }
      }
      decodedPcm = new Float32Array(total);
      let state = [0, 0];
      for (let offset = 0; offset < total; offset += 1024) {
        const length = Math.min(1024, total - offset),
          padded = length + (length % 2),
          pcm = new Int16Array(padded);
        for (let n = 0; n < length; n++)
          pcm[n] = Math.max(
            -32768,
            Math.min(32767, Math.round(resampled[offset + n] * 32768)),
          );
        const result = kernel.adpcmRoundtrip(pcm, state);
        state = result.state;
        audioChunks.push(result.chunk);
        for (let n = 0; n < length; n++)
          decodedPcm[offset + n] = result.pcm[n] / 32768;
        if (offset % 65536 === 0)
          report(2, 90 + (offset / total) * 10, { frames });
      }
      log(
        `Decoded video audio → 22.05 kHz mono → checkpointed IMA ADPCM → RF5C164 reconstruction (${total} samples).`,
      );
    } else log("No source audio track; preview will be silent.");
    report(2, 100, { frames });
    const aac = decodedPcm ? await preparePreviewAac(canEncodeAudio, registerAacEncoder) : null;
    const fallbackAac = aac?.fallback;
    if(aac)log(`MP4 audio: AAC-LC, 96 kbps, 22.05 kHz mono (${fallbackAac ? "Wasm fallback" : "browser encoder"}).`);
    const aperture = new OffscreenCanvas(320, 224),
      actx = aperture.getContext("2d", { alpha: false });
    const preview = new OffscreenCanvas(1024, 784),
      pctx = preview.getContext("2d", { alpha: false });
    pctx.imageSmoothingEnabled = false;
    output = new Output({
      format: new Mp4OutputFormat(),
      target: new BufferTarget(),
    });
    const videoSource = new CanvasSource(preview, {
      codec: "avc",
      bitrate: 4000000,
    });
    output.addVideoTrack(videoSource, { frameRate: fps });
    let audioSource;
    if (decodedPcm) {
      audioSource = new AudioSampleSource(aac.options);
      output.addAudioTrack(audioSource);
    }
    await output.start();
    const audioTask = (async () => {
      if (!audioSource) return;
      for (let start = 0; start < decodedPcm.length; start += 22050) {
        const sample = new AudioSample({
          data: decodedPcm.subarray(
            start,
            Math.min(start + 22050, decodedPcm.length),
          ),
          format: "f32",
          numberOfChannels: 1,
          sampleRate: 22050,
          // The FFmpeg AAC fallback emits one priming frame but assigns it
          // the first input timestamp. A negative offset lets MP4 trim that
          // frame through its edit list instead of delaying the movie audio.
          timestamp: (start - (fallbackAac ? 1024 : 0)) / 22050,
        });
        try {
          await audioSource.add(sample);
        } finally {
          sample.close();
        }
      }
      audioSource.close();
    })();
    // Always observe audio-task rejection, including a simultaneous video failure.
    audioTask.catch(() => {});
    report(3, 0, { frames });
    let index = 0,
      frame0Tile,
      frame0Pmap,
      firstPng;
    temporal = createTemporalPreview(kernel, width, height, settings.encoder.coldCap, fps);
    log(`Exact resident reuse and cold cap ${settings.encoder.coldCap} enabled; frame 0 is an untimed full load. Delivery planning follows image processing.`);
    log("Selecting updates within prior-slot pattern supply and reserved control space; geometry, fps and configured cold cap stay fixed.");
    const trace = ["frame\ttimestamp_seconds\tquantize_ms\ttile_bytes\tcold_cap\tcold_loads\treused_updates\trequested_cells\tdeferred_cells\tcold_runs\tcd_cold_budget"];
    const decisions = [];
    function* frameTimes() {
      for (let n = 0; n < frames; n++) yield first + n / fps;
    }
    for await (const frame of sink.canvasesAtTimestamps(frameTimes())) {
      if (!frame) throw new Error(`Could not decode output frame ${index}.`);
      drawPicture(ctx, frame.canvas, settings);
      const start = performance.now();
      const result = kernel.quantize(
        ctx.getImageData(0, 0, width, height).data,
        width,
        height,
        palette,
      );
      const ms = performance.now() - start;
      const displayed = temporal.apply(result, index, budgets[index]);
      decisions.push({cold:displayed.cold,updates:displayed.updates,runs:displayed.runs});
      ctx.putImageData(
        new ImageData(new Uint8ClampedArray(displayed.rgba.buffer), width, height),
        0,
        0,
      );
      actx.fillStyle = "#000";
      actx.fillRect(0, 0, 320, 224);
      actx.drawImage(picture, (320 - width) / 2, (224 - height) / 2);
      pctx.drawImage(aperture, 0, 0, 1024, 784);
      await videoSource.add(
        index / fps,
        Math.min(1 / fps, duration - index / fps),
      );
      if (index === 0) {
        frame0Tile = result.tile;
        frame0Pmap = result.pmap;
        firstPng = await preview.convertToBlob({ type: "image/png" });
      }
      trace.push(
        `${index}\t${(index / fps).toFixed(9)}\t${ms.toFixed(3)}\t${result.tile.length}\t${displayed.cap}\t${displayed.cold}\t${displayed.reused}\t${displayed.requested}\t${displayed.deferred}\t${displayed.runs}\t${index===0?'':displayed.cdColdBudget}`,
      );
      index++;
      report(3, (index / frames) * 100, { frames, doneFrames: index });
      if (index % Math.max(1, Math.round(fps)) === 0)
        log(`Processed ${index} / ${frames} frames.`);
    }
    videoSource.close();
    await audioTask;
    report(4, 0, { frames, doneFrames: index });
    log("Checking each CD-1x deadline and finite PrgBuf balance using the current Python schedule model.");
    const deliveryPlan = previewDeliveryPlan(decisions, fps, width * height / 64);
    if(!deliveryPlan.feasible)throw new Error(`Could not construct a deliverable preview: ${deliveryPlan.message}. No unverified package was produced.`);
    deliveryPlan.selectionPolicy="Conservative previous-slot pattern funding with reserved control sectors; configured cold cap unchanged";
    const delivery = deliveryArtifacts(deliveryPlan);
    log(`Delivery model: ${deliveryPlan.message}. This is a planning check; stream packing and disc generation remain pending.`);
    report(4, 100, { frames, doneFrames: index });
    report(5, 0, { frames, doneFrames: index });
    log("Finalizing the real H.264/AAC MP4 preview.");
    await output.finalize();
    report(5, 100, { frames, doneFrames: index });
    const mp4 = output.target.buffer;
    if (!mp4?.byteLength) throw new Error("No MP4 was produced.");
    const adpcmLength = audioChunks.reduce((n, chunk) => n + chunk.length, 0),
      adpcm = new Uint8Array(adpcmLength);
    let at = 0;
    for (const chunk of audioChunks) {
      adpcm.set(chunk, at);
      at += chunk.length;
    }
    report(6, 0, { frames, doneFrames: index });
    self.postMessage(
      {
        type: "complete",
        mp4,
        palette: paletteBytes,
        frame0Tile,
        frame0Pmap,
        adpcm,
        preview: firstPng,
        tsv: trace.join("\n") + "\n",
        frames,
        index,
        duration,
        audioSamples: decodedPcm?.length || 0,
        fps,
        deliveryPlan: delivery.summary,
        deliveryTsv: delivery.tsv,
      },
      [
        mp4,
        paletteBytes.buffer,
        frame0Tile.buffer,
        frame0Pmap.buffer,
        adpcm.buffer,
      ],
    );
  } catch (error) {
    if (output) await output.cancel().catch(() => {});
    self.postMessage({
      type: "error",
      message: error.message || String(error),
    });
  } finally {
    temporal?.dispose();
    kernel?.dispose();
    input?.dispose();
  }
}
self.onmessage = ({ data }) => {
  if (data.type === "start") run(data.file, data.settings);
};
