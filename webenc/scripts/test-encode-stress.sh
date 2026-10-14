#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
qa_dir=/dev/shm/segacd-fmv-cavc/webenc-qa
mkdir -p "$qa_dir"
ffmpeg -hide_banner -loglevel error \
  -f lavfi -i testsrc2=size=320x180:rate=24 \
  -f lavfi -i sine=frequency=440:sample_rate=44100 \
  -t 60 -vf noise=alls=100:allf=t+u -c:v libx264 -preset ultrafast \
  -crf 28 -pix_fmt yuv420p -c:a aac -y "$qa_dir/test-video-stress.mp4"
WEBENC_INPUT="$qa_dir/test-video-stress.mp4" WEBENC_TEST_TIMEOUT=240000 \
WEBENC_TEST_FPS=30 WEBENC_TEST_DIMENSIONS=320x144 WEBENC_TEST_CAP=230 npm run test:encode
for artifact in encoded-preview.zip encoded-preview.mp4 encoded-timeline.tsv real-preview.png; do
  cp "$qa_dir/$artifact" "$qa_dir/stress-$artifact"
done
