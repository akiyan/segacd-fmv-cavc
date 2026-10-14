// Deliberately simulated progress. No source data is sent to this worker.
const stages = [
  "Read source",
  "Choose colors",
  "Quantize",
  "Plan delivery",
  "Encode",
  "Verify & ZIP",
];
let timer;
self.onmessage = ({ data }) => {
  clearInterval(timer);
  if (data.type !== "start") return;
  let stage = 0,
    progress = 0;
  const frames = Math.max(1, Math.round(data.duration * data.fps));
  timer = setInterval(() => {
    progress += stage === 4 ? 2 : 10;
    self.postMessage({
      type: "progress",
      stage,
      progress: Math.min(progress, 100),
      overall: ((stage + Math.min(progress, 100) / 100) / stages.length) * 100,
      frames,
      doneFrames: Math.floor((frames * Math.min(progress, 100)) / 100),
      label: stages[stage],
    });
    if (progress >= 100) {
      stage++;
      progress = 0;
      if (stage === stages.length) {
        clearInterval(timer);
        self.postMessage({ type: "complete" });
      }
    }
  }, 100);
};
