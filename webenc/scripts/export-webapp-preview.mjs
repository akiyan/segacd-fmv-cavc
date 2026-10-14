import {execFileSync} from 'node:child_process';
import {fileURLToPath} from 'node:url';
const [input,output]=process.argv.slice(2);
if(!input||!output)throw new Error('Usage: export-webapp-preview.mjs INPUT.mp4 OUTPUT_DIRECTORY');
execFileSync(process.execPath,[fileURLToPath(new URL('./verify-encode.mjs',import.meta.url))],{
 stdio:'inherit',env:{...process.env,WEBENC_INPUT:input,WEBENC_TEST_OUTPUT:output,
 WEBENC_URL:process.env.WEBENC_URL||'https://level-ubuntu.taildb3e9c.ts.net:8443/',
 WEBENC_TEST_DIMENSIONS:'288x200',WEBENC_TEST_FPS:'30',WEBENC_TEST_SAR:'32:35',WEBENC_TEST_CAP:'210'}
});
