"""Whole-stream scheduling fixtures, including one-minute demand traces."""
import json
import sys
from pathlib import Path
import numpy as np
root = Path(__file__).resolve().parents[2]
sys.path.insert(0,str(root/'tools'))
import av_config
import cavc_routing
import shadow_updates
from stream_schedule import control_block_lengths, schedule_payload_ring, rate_deltas, ScheduleError
rng = np.random.default_rng(16475)
cases=[]
for fps in [15,24,30,29.97,20,60,23.5]:
    count=round(fps*60)
    for mode in ['mixed','overload','startup-heavy']:
        loads=rng.integers(5,45,count,dtype=np.int64)
        updates=loads+rng.integers(0,100,count,dtype=np.int64)
        runs=rng.integers(1,5,count,dtype=np.int64)
        if mode=='overload': loads[:]=250;updates[:]=300;runs[:]=30
        if mode=='startup-heavy': loads[1:40]=300;updates[1:40]=500;runs[1:40]=80
        # Abrupt scene changes and low-demand intervals through the whole trace.
        if mode=='mixed':
            for start in range(100,count,300): loads[start:start+15]=150;updates[start:start+15]=220;runs[start:start+15]=15
        cells=840;audio=av_config.audio_frame_layout(fps)[2]
        bitmap=shadow_updates.aligned_bitmap_bytes(cells)
        lists=updates*shadow_updates.LIST_ITEM_BYTES < bitmap+updates*shadow_updates.SHADOW_ENTRY_BYTES
        lengths=control_block_lengths(updates,runs,cells=cells,audio_frame_bytes=audio,update_lists=lists)
        capacity=av_config.scheduled_delivery_cap_kb(fps)*32
        record=dict(fps=fps,mode=mode,loads=loads.tolist(),updates=updates.tolist(),runs=runs.tolist(),cells=cells,audioBytes=audio,lengths=lengths.tolist(),capacity=capacity,rates=rate_deltas(count,fps).tolist())
        try:
            result=schedule_payload_ring(loads,lengths,fps=fps,ring_capacity_patterns=capacity,prebuffer_capacity_patterns=capacity,frame_sectors=cavc_routing.FRAME_SECTORS,fill=True)
            names={'feasible':'feasible','prebufferPatterns':'prebuf_pat','payloadSectors':'n_pay_sec','controlSectors':'n_ctrl_sec','sectorAllowance':'ratedelta','routedSectors':'fsec','rateLead':'rate_lead_trace','ringOccupancy':'ring_occupancy','ringBeforeConsume':'ring_occupancy_before_consume'}
            expected={}
            for js,py in names.items():
                if py not in result:continue
                value=result[py];expected[js]=value.tolist() if isinstance(value,np.ndarray) else value
            record['expected']=expected
        except ScheduleError as e:
            record['error']=str(e)
        cases.append(record)
from test_paths import KERNEL_ROOT
out=KERNEL_ROOT/'schedule.json'
out.parent.mkdir(parents=True,exist_ok=True);out.write_text(json.dumps(cases))
print(f'Python scheduling reference: {len(cases)} complete 60-second traces, {sum(len(c["loads"]) for c in cases)} frames')
