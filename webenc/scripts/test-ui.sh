#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
qa_dir=/dev/shm/segacd-fmv-cavc/webenc-qa
mkdir -p "$qa_dir"
ffmpeg -hide_banner -loglevel error -f lavfi -i testsrc2=size=640x360:rate=24 -f lavfi -i sine=frequency=440:sample_rate=44100 -t 3 -c:v libx264 -pix_fmt yuv420p -c:a aac -y "$qa_dir/test-video.mp4"
node scripts/verify-ui.mjs
