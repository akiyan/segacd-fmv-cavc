# Offline encoding check

Build with `npm run build`, serve with `npm run preview -- --port 4175`, and run:

```sh
node harness/offline/verify.mjs /absolute/path/to/a/short-test.mp4
```

The browser starts with empty storage. The harness interrupts one FFmpeg asset,
checks that Generate stays disabled, retries with partial-cache reuse, and waits
for every runtime asset to be saved. It then disables networking, reloads the
page offline, selects the local MP4 and performs two real CAVC encodes with fresh
Workers, including playback MP4, reconstructed audio and ISO/CUE ZIP download.
It checks that offline HTTP responses are served by the service worker, that no
request fails and that the Licenses modal works offline with project MIT terms.
The persistent receipt is `logs/webenc_offline_verification.json`.
Use `WEBENC_URL` to target a deployed build. Input media is leased through the
project's managed tmpfs workflow; no generated media is kept in this directory.
