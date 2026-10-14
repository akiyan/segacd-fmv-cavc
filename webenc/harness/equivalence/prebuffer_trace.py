"""Account for unused sector padding in an entirely boot-prefetched Prg stream.

No decisions, schedule, buffers or packed fields change. The trace contains real
patterns only; a boot preload may round their tail up to a complete sector.
"""
import inspect
import linecache


def install(sim):
    source=inspect.getsource(sim.main)
    marker='    word_flag_cursors = ['
    if source.count(marker)!=1:raise RuntimeError('Prg funding-trace boundary changed')
    correction='''    # An all-boot Prg tail can include unused whole-sector alignment padding.
    if prg_flag_cursor > len(prg_raw_flags):
        remaining = len(prg_raw_flags) - int(transfer_tiles_log[0])
        rounded = ((remaining + 63) // 64) * 64
        if (ring_enabled or remaining < 0
                or int(physical_schedule["prebuf_pat"]) != rounded
                or int(np.sum(body_payload_bytes)) != 0):
            raise AssertionError("Prg trace overrun is not unused boot-sector padding")
        print(f"Unused boot prebuffer sector padding: {prg_flag_cursor - len(prg_raw_flags)} patterns", flush=True)
        prg_flag_cursor = len(prg_raw_flags)
'''
    source=source.replace(marker,correction+marker)
    filename='<cavc-boot-padding-trace>'
    linecache.cache[filename]=(len(source),None,source.splitlines(True),filename)
    exec(compile(source,filename,'exec'),sim.__dict__)
