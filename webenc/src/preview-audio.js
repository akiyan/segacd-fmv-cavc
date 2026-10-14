export const previewAacOptions = Object.freeze({
  fullCodecString: "mp4a.40.2", // AAC-LC; do not infer HE-AAC from 22.05 kHz.
  bitrate: 96000,
  numberOfChannels: 1,
  sampleRate: 22050,
});

export async function preparePreviewAac(canEncodeAudio, registerFallback) {
  // A generic probe uses 48 kHz stereo and does not prove this config works.
  const fallback = !(await canEncodeAudio("aac", previewAacOptions));
  if (fallback) {
    registerFallback();
    if (!(await canEncodeAudio("aac", previewAacOptions)))
      throw new Error("AAC-LC preview encoding is unavailable, including the Wasm fallback.");
  }
  return { options: { codec: "aac", ...previewAacOptions }, fallback };
}
