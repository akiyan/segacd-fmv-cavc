//! Exact palette/tile and checkpointed IMA primitives. CD scheduling is not implemented.
use std::slice;

#[no_mangle]
pub extern "C" fn alloc(size: usize) -> *mut u8 {
    let mut data = Vec::<u8>::with_capacity(size);
    let ptr = data.as_mut_ptr();
    std::mem::forget(data);
    ptr
}
#[no_mangle]
pub unsafe extern "C" fn release(ptr: *mut u8, size: usize) {
    drop(Vec::from_raw_parts(ptr, 0, size));
}
fn rgb333(r: u8, g: u8, b: u8) -> [u8; 3] {
    [r, g, b].map(|v| ((v as u32 * 7 + 127) / 255) as u8)
}
fn key(color: [u8; 3]) -> usize {
    ((color[0] as usize) << 6) | ((color[1] as usize) << 3) | color[2] as usize
}
fn color(key: usize) -> [u8; 3] {
    [((key >> 6) & 7) as u8, ((key >> 3) & 7) as u8, (key & 7) as u8]
}
#[no_mangle]
pub unsafe extern "C" fn accumulate_histogram(rgba: *const u8, pixels: usize, histogram: *mut u32) {
    let input = slice::from_raw_parts(rgba, pixels * 4);
    let hist = slice::from_raw_parts_mut(histogram, 4 * 512);
    for pixel in input.chunks_exact(4) {
        let rgb = rgb333(pixel[0], pixel[1], pixel[2]);
        let max = *rgb.iter().max().unwrap();
        let min = *rgb.iter().min().unwrap();
        let line = if max - min <= 1 { 3 } else { rgb.iter().position(|v| *v == max).unwrap() };
        hist[line * 512 + key(rgb)] += 1;
    }
}
// Experimental trainer, separate from the established STL4/MOSAIC-GM algorithms.
#[no_mangle]
pub unsafe extern "C" fn train_palette(histogram: *const u32, palette: *mut u8) {
    let hist = slice::from_raw_parts(histogram, 4 * 512);
    let output = slice::from_raw_parts_mut(palette, 180);
    let global: Vec<u32> = (0..512).map(|k| (0..4).map(|p| hist[p * 512 + k]).sum()).collect();
    for line in 0..4 {
        let local = &hist[line * 512..(line + 1) * 512];
        let counts = if local.iter().any(|&v| v != 0) { local } else { &global };
        let mut ordered: Vec<usize> = (0..512).filter(|k| counts[*k] != 0).collect();
        ordered.sort_by_key(|&k| (std::cmp::Reverse(counts[k]), k));
        let mut centers = [[0f64; 3]; 15];
        for (n, &k) in ordered.iter().take(15).enumerate() { centers[n] = color(k).map(|v| v as f64); }
        for _ in 0..16 {
            let mut sums = [[0f64; 3]; 15];
            let mut weights = [0f64; 15];
            for &k in &ordered {
                let rgb = color(k).map(|v| v as f64);
                let best = (0..15).min_by(|&a,&b| {
                    let distance = |n:usize| (0..3).map(|c| (rgb[c]-centers[n][c]).powi(2)).sum::<f64>();
                    distance(a).partial_cmp(&distance(b)).unwrap().then(a.cmp(&b))
                }).unwrap();
                weights[best] += counts[k] as f64;
                for c in 0..3 { sums[best][c] += rgb[c] * counts[k] as f64; }
            }
            for n in 0..15 { if weights[n] != 0.0 { for c in 0..3 { centers[n][c] = sums[n][c] / weights[n]; } } }
        }
        for n in 0..15 { for c in 0..3 { output[line * 45 + n * 3 + c] = centers[n][c].round().clamp(0.0,7.0) as u8; } }
    }
}
#[no_mangle]
pub unsafe extern "C" fn palette_bytes(palette: *const u8, output: *mut u8) {
    let pal = slice::from_raw_parts(palette, 180);
    let out = slice::from_raw_parts_mut(output, 128);
    out.fill(0);
    for line in 0..4 { for entry in 0..15 {
        let base = line*45+entry*3;
        let word = (pal[base+2] as u16)<<9 | (pal[base+1] as u16)<<5 | (pal[base] as u16)<<1;
        out[(line*16+entry+1)*2..(line*16+entry+1)*2+2].copy_from_slice(&word.to_be_bytes());
    } }
}
#[no_mangle]
pub unsafe extern "C" fn quantize(rgba: *mut u8, width: usize, height: usize, palette: *const u8, tile: *mut u8, pmap: *mut u8) -> u32 {
    if width == 0 || height == 0 || width % 8 != 0 || height % 8 != 0 { return 1; }
    let pal = slice::from_raw_parts(palette, 180);
    if pal.iter().any(|&v| v > 7) { return 2; }
    let pixels = slice::from_raw_parts_mut(rgba, width*height*4);
    let tiles = slice::from_raw_parts_mut(tile, width*height/2);
    let lines = slice::from_raw_parts_mut(pmap, width*height/64);
    let mut indices = [[0u8;512];4];
    let mut errors = [[0u16;512];4];
    for line in 0..4 { for k in 0..512 {
        let rgb = color(k); let mut minimum = u16::MAX; let mut index=0;
        for entry in 0..15 {
            let base=line*45+entry*3;
            let distance=(0..3).map(|c| (rgb[c] as i16-pal[base+c] as i16).pow(2) as u16).sum();
            if distance<minimum {minimum=distance;index=entry;}
        }
        errors[line][k]=minimum; indices[line][k]=index as u8;
    } }
    for ty in 0..height/8 { for tx in 0..width/8 {
        let tile_index=ty*(width/8)+tx;
        let mut keys=[0usize;64]; let mut score=[0u32;4];
        for y in 0..8 { for x in 0..8 {
            let offset=((ty*8+y)*width+tx*8+x)*4;
            let k=key(rgb333(pixels[offset],pixels[offset+1],pixels[offset+2])); keys[y*8+x]=k;
            for line in 0..4 {score[line]+=errors[line][k] as u32;}
        } }
        let line=(0..4).min_by_key(|&n| score[n]).unwrap(); lines[tile_index]=line as u8;
        for n in 0..64 {
            let index=indices[line][keys[n]] as usize;
            if n%2==0 {tiles[tile_index*32+n/2]=(index as u8+1)<<4;} else {tiles[tile_index*32+n/2]|=index as u8+1;}
            let pixel=((ty*8+n/8)*width+tx*8+n%8)*4;
            for c in 0..3 {pixels[pixel+c]=pal[line*45+index*3+c]*36;}
            pixels[pixel+3]=255;
        }
    } }
    0
}
const STEPS:[i32;89]=[7,8,9,10,11,12,13,14,16,17,19,21,23,25,28,31,34,37,41,45,50,55,60,66,73,80,88,97,107,118,130,143,157,173,190,209,230,253,279,307,337,371,408,449,494,544,598,658,724,796,876,963,1060,1166,1282,1411,1552,1707,1878,2066,2272,2499,2749,3024,3327,3660,4026,4428,4871,5358,5894,6484,7132,7845,8630,9493,10442,11487,12635,13899,15289,16818,18500,20350,22385,24623,27086,29794,32767];
const INDEX:[i32;16]=[-1,-1,-1,-1,2,4,6,8,-1,-1,-1,-1,2,4,6,8];
#[no_mangle]
pub unsafe extern "C" fn adpcm_roundtrip(pcm: *const i16, count:usize, state:*mut i32, chunk:*mut u8, decoded:*mut i16) -> u32 {
    if count==0 || count%2!=0 {return 1;}
    let state=slice::from_raw_parts_mut(state,2);
    if !(-32768..=32767).contains(&state[0]) || !(0..=88).contains(&state[1]) {return 2;}
    let input=slice::from_raw_parts(pcm,count); let out=slice::from_raw_parts_mut(chunk,4+count/2);let decoded=slice::from_raw_parts_mut(decoded,count);
    out[..2].copy_from_slice(&(state[0] as i16).to_be_bytes());out[2]=state[1] as u8;out[3]=0;
    let mut predictor=state[0];let mut index=state[1] as usize;
    for (n,&sample) in input.iter().enumerate() {
        let step=STEPS[index];let mut diff=sample as i32-predictor;let mut code=0u8;
        if diff<0 {code=8;diff=-diff;}
        let mut magnitude=step>>3;
        if diff>=step {code|=4;diff-=step;magnitude+=step;}
        if diff>=step>>1 {code|=2;diff-=step>>1;magnitude+=step>>1;}
        if diff>=step>>2 {code|=1;magnitude+=step>>2;}
        predictor=(predictor+if code&8!=0 {-magnitude} else {magnitude}).clamp(-32768,32767);
        index=(index as i32+INDEX[code as usize]).clamp(0,88) as usize;
        if n%2==0 {out[4+n/2]=code;} else {out[4+n/2]|=code<<4;}
        let high=predictor>>8;
        // Mirror RF5C164 sign-magnitude conversion, including its reserved 0xff marker.
        decoded[n]=(if high>=0 {high.min(127)} else {-(-high).min(126)}) as i16*256;
    }
    state[0]=predictor;state[1]=index as i32;0
}

// Visible-update subset of tools/tile_alloc.py. Prefetch/pins are not enabled.
pub struct Residency {
    keys: std::collections::HashMap<[u8; 32], usize>,
    slots: Vec<Option<[u8; 32]>>,
    refs: Vec<i32>,
    last: Vec<i32>,
    current: Vec<i32>,
    previous: Vec<i32>,
    free: Vec<usize>,
    hand: usize,
}
#[no_mangle]
pub extern "C" fn residency_create(cells: usize, pool: usize) -> *mut Residency {
    if cells == 0 || pool <= cells { return std::ptr::null_mut(); }
    Box::into_raw(Box::new(Residency {
        keys: std::collections::HashMap::new(), slots: vec![None;pool],
        refs:vec![0;pool], last:vec![-1;pool], current:vec![-1;cells],
        previous:vec![-1;cells], free:(0..pool).rev().collect(), hand:0,
    }))
}
#[no_mangle]
pub unsafe extern "C" fn residency_has(state:*const Residency, key:*const u8) -> u32 {
    let k: [u8;32] = slice::from_raw_parts(key,32).try_into().unwrap();
    (*state).keys.contains_key(&k) as u32
}
#[no_mangle]
pub unsafe extern "C" fn residency_place_frame(state:*mut Residency, cells:*const u32, keys:*const u8, count:usize, frame:i32, output:*mut u32) -> u32 {
    let s=&mut *state;
    if count == 0 { s.previous.clone_from(&s.current); return 0; }
    let cs=slice::from_raw_parts(cells,count);
    let ks=slice::from_raw_parts(keys,count*32);
    let out=slice::from_raw_parts_mut(output,count*2);
    if cs.iter().any(|&c| c as usize >= s.current.len()) { return 1; }
    let pool=s.slots.len();
    let mut prev=vec![false;pool];
    for &slot in &s.previous { if slot>=0 {prev[slot as usize]=true;} }
    let mut protected=vec![false;pool];
    for k in ks.chunks_exact(32) {
        let key:[u8;32]=k.try_into().unwrap();
        if let Some(&slot)=s.keys.get(&key) {protected[slot]=true;}
    }
    for (n,&c) in cs.iter().enumerate() {
        let key:[u8;32]=ks[n*32..n*32+32].try_into().unwrap();
        let cold=!s.keys.contains_key(&key);
        let slot=if let Some(&slot)=s.keys.get(&key) {slot} else {
            let mut chosen=s.free.pop();
            if chosen.is_none() {
                for _ in 0..pool {
                    let slot=s.hand; s.hand=(s.hand+1)%pool;
                    if s.refs[slot]==0 && !prev[slot] && !protected[slot] {chosen=Some(slot);break;}
                }
            }
            if chosen.is_none() {
                for _ in 0..pool {
                    let slot=s.hand; s.hand=(s.hand+1)%pool;
                    if s.refs[slot]==0 {chosen=Some(slot);break;}
                }
            }
            let slot=chosen.unwrap_or_else(|| (0..pool).min_by_key(|&i| s.last[i]).unwrap());
            if let Some(old)=s.slots[slot] {s.keys.remove(&old);}
            s.keys.insert(key,slot); s.slots[slot]=Some(key); slot
        };
        let old=s.current[c as usize];
        if old>=0 {s.refs[old as usize]-=1;}
        s.refs[slot]+=1; s.last[slot]=frame; s.current[c as usize]=slot as i32;
        out[n*2]=slot as u32; out[n*2+1]=cold as u32;
    }
    s.previous.clone_from(&s.current);
    0
}
#[no_mangle]
pub unsafe extern "C" fn residency_destroy(state:*mut Residency) {drop(Box::from_raw(state));}
