export const outputFrameRates = [15, 24, 30];

export function automaticOutputFps(sourceFps) {
  const rate = Number(sourceFps);
  if (!Number.isFinite(rate) || rate <= 0) return 24;
  return outputFrameRates.reduce((best, fps) =>
    Math.abs(fps - rate) < Math.abs(best - rate) ? fps : best, 30);
}
