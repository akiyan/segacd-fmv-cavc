import { Input, BlobSource, ALL_FORMATS } from "mediabunny";
import {videoFrameTimes} from './frame-range';
export async function inspectVideo(file) {
  const input = new Input({
    source: new BlobSource(file),
    formats: ALL_FORMATS,
  });
  try {
    const track = await input.getPrimaryVideoTrack();
    if (!track) throw new Error("No video track found");
    const stats = await track.computePacketStats();
    return {
      fps: stats.averagePacketRate,
      duration: await track.computeDuration(),
      frameTimes: await videoFrameTimes(track),
    };
  } finally {
    input.dispose();
  }
}
