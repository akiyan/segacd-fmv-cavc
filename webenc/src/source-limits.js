export const MAX_OUTPUT_FRAMES = 16384;

const secondsAt24fps = Math.round(MAX_OUTPUT_FRAMES / 24);
export const sourceFrameLimitNotice = `Max ${MAX_OUTPUT_FRAMES.toLocaleString('en-US')} output frames (≈${Math.floor(secondsAt24fps / 60)}m${String(secondsAt24fps % 60).padStart(2, '0')}s at 24fps).`;

export function validateOutputFrameCount(frames) {
  if (!Number.isSafeInteger(frames) || frames < 1 || frames > MAX_OUTPUT_FRAMES) {
    throw new Error(`The CAVC stream supports up to ${MAX_OUTPUT_FRAMES.toLocaleString('en-US')} output frames.`);
  }
}
