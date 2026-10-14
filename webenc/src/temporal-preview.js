import { parseColdCap } from './cold-cap.js';
import registry from './generated/profile-caps.json';

export function frameColdCap(specification, fps, frame) {
  const parsed = parseColdCap(specification, fps);
  if (!parsed.valid) throw new Error('Invalid cold cap');
  const {spec} = parsed;
  if (spec['*']) return spec['*'];
  if (Object.keys(spec).length === 1) return Object.values(spec)[0];
  if (frame === 0) return Math.max(...Object.values(spec));
  return spec[(frame - 1) % 2 === 0 ? 2 : 3];
}

// Exact-only experimental selection, distinct from sim.py's quality policy.
// The underlying visible-update allocator is ported from tile_alloc.py.
export function createTemporalPreview(kernel, width, height, capSpec, fps) {
  const cells = width * height / 64;
  const residency = kernel.createResidency(cells, registry.maxColdCap);
  const shownTile = new Uint8Array(cells * 32);
  const shownMap = new Uint8Array(cells);
  const shownRgba = new Uint8Array(width * height * 4);
  const cols = width / 8;
  const cellPixels = (cell, visit) => {
    const x = cell % cols * 8, y = Math.floor(cell / cols) * 8;
    for (let row = 0; row < 8; row++)
      for (let col = 0; col < 8; col++) visit(((y + row) * width + x + col) * 4);
  };
  return {
    apply(result, frame, budget = null) {
      const cap = frameColdCap(capSpec, fps, frame);
      const selected = new Set(), groups = new Map();
      const resident = [], errors = new Map();
      const admittedColdLimit=frame===0?Infinity:Math.min(cap,budget?.coldBudget ?? cap);
      const fitsControl=(updates,cold)=> {
        if(frame===0 || !budget)return true;
        const bitmap=(Math.ceil(cells/8)+1)&~1;
        const entries=Math.min(updates*4,bitmap+updates*2);
        // Each fresh pattern may form its own four-byte run descriptor.
        return 8+budget.audioBytes+entries+cold*4<=budget.controlByteLimit;
      };
      let requested = 0;
      for (let cell = 0; cell < cells; cell++) {
        const pattern = result.tile.subarray(cell * 32, cell * 32 + 32);
        const unchanged = frame > 0 && result.pmap[cell] === shownMap[cell] &&
          pattern.every((v,n) => v === shownTile[cell * 32 + n]);
        if (unchanged) continue;
        requested++;
        let error = 0;
        cellPixels(cell, pixel => {
          for (let c = 0; c < 3; c++) error += (result.rgba[pixel+c] - shownRgba[pixel+c]) ** 2;
        });
        errors.set(cell,error);
        if (residency.has(pattern)) { resident.push(cell); continue; }
        const key = Array.from(pattern).join('.');
        const group = groups.get(key) || {cells:[], error:0, first:cell};
        group.cells.push(cell); group.error += error; groups.set(key, group);
      }
      // Rank fresh patterns by the total displayed error they would remove.
      // Frame 0 is untimed; all patterns are installed regardless of cold cap.
      const ordered = [...groups.values()].sort((a,b) => b.error-a.error || a.first-b.first);
      resident.sort((a,b)=>errors.get(b)-errors.get(a)||a-b);
      for(const cell of resident)if(fitsControl(selected.size+1,0))selected.add(cell);
      let selectedCold=0;
      for (const group of ordered) {
        if(selectedCold>=admittedColdLimit)break;
        let admitted=false;
        group.cells.sort((a,b)=>errors.get(b)-errors.get(a)||a-b);
        for(const cell of group.cells) {
          if(fitsControl(selected.size+1,selectedCold+(admitted?0:1))) {
            selected.add(cell);
            if(!admitted){selectedCold++;admitted=true;}
          }
        }
      }
      const updates = [...selected].sort((a,b) => a-b);
      const patterns = new Uint8Array(updates.length * 32);
      updates.forEach((cell,n) => patterns.set(result.tile.subarray(cell*32,cell*32+32),n*32));
      const placed = residency.placeFrame(updates, patterns, frame);
      let cold = 0;
      const coldSlots = [];
      updates.forEach((cell,n) => {
        cold += placed[n*2+1];
        if (placed[n*2+1]) coldSlots.push(placed[n*2]);
        shownTile.set(result.tile.subarray(cell*32,cell*32+32),cell*32);
        shownMap[cell] = result.pmap[cell];
        cellPixels(cell, pixel => shownRgba.set(result.rgba.subarray(pixel,pixel+4),pixel));
      });
      if (frame > 0 && cold > cap) throw new Error('Cold-cap allocator invariant failed');
      if(frame>0 && cold>admittedColdLimit)throw new Error('CD selection budget invariant failed');
      coldSlots.sort((a,b)=>a-b);
      const runs = coldSlots.filter((slot,n)=>n===0 || slot!==coldSlots[n-1]+1).length;
      return {rgba:shownRgba, cold, cap, runs, updates:updates.length,
        cdColdBudget:budget?.coldBudget ?? cap,
        reused:updates.length-cold, requested, deferred:requested-updates.length};
    },
    dispose() { residency.dispose(); },
  };
}
