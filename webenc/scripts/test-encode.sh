#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")/.."
qa_dir="$(node --input-type=module -e "import {qaRoot} from './scripts/test-paths.mjs'; console.log(qaRoot)")"
export WEBENC_TEST_OUTPUT="$qa_dir"
mkdir -p "$qa_dir"
kind="${1:-long}"
case "$kind" in
  long) filters=() ;;
  stress) filters=(-vf noise=alls=100:allf=t+u); export WEBENC_TEST_FPS=30 WEBENC_TEST_DIMENSIONS=320x144 WEBENC_TEST_CAP=230 ;;
  *) echo 'Usage: test-encode.sh long|stress' >&2; exit 2 ;;
esac
ffmpeg -hide_banner -loglevel error \
  -f lavfi -i testsrc2=size=320x180:rate=24 \
  -f lavfi -i sine=frequency=440:sample_rate=44100 \
  -t "${WEBENC_TEST_SECONDS:-60}" "${filters[@]}" -c:v libx264 -preset ultrafast \
  -pix_fmt yuv420p -c:a aac -y "$qa_dir/test-video-$kind.mp4"
WEBENC_INPUT="$qa_dir/test-video-$kind.mp4" WEBENC_TEST_TIMEOUT=600000 npm run test:encode
for artifact in encoded-cavc.zip preview.mp4 settings.json cavc-complete.png; do
  cp "$qa_dir/$artifact" "$qa_dir/$kind-$artifact"
done
