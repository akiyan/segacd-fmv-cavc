export function createPythonEncoderWorker(){
 return new Worker(new URL('./python-encoder-worker.js',import.meta.url),{type:'module'});
}
