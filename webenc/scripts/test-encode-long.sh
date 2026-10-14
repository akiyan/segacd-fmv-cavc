#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
qa_dir=/dev/shm/segacd-fmv-cavc/webenc-qa
mkdir -p "$qa_dir"
ffmpeg -hide_banner -loglevel error \
  -f lavfi -i testsrc2=size=320x180:rate=24 \
  -f lavfi -i sine=frequency=440:sample_rate=44100 \
  -t 60 -c:v libx264 -preset ultrafast -pix_fmt yuv420p -c:a aac \
  -y "$qa_dir/test-video-long.mp4"
WEBENC_INPUT="$qa_dir/test-video-long.mp4" WEBENC_TEST_TIMEOUT=240000 npm run test:encode
for artifact in encoded-preview.zip encoded-preview.mp4 encoded-timeline.tsv real-preview.png; do
  cp "$qa_dir/$artifact" "$qa_dir/long-$artifact"
done
