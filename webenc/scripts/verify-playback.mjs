// Exercise actual confirmed stills, completed playback and the real ZIP package.
process.env.WEBENC_TEST_LIVE='1';
if(!process.env.WEBENC_INPUT){
 process.env.WEBENC_TEST_START_FRAME??='12';
 process.env.WEBENC_TEST_END_FRAME??='35';
}
await import('./verify-encode.mjs');
