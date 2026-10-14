"""Export canonical analysis rows without loading the analysis video UI."""
import ast
import csv
import json
from pathlib import Path
from types import SimpleNamespace
import numpy as np
import analysis_style as style
import r2v_model
import stream_schedule


def export(directory, decisions):
    directory = Path(directory)
    tools = Path(style.__file__).parent
    source = (tools / 'render_analysis.py').read_text()
    tree = ast.parse(source)
    functions = {node.name: node for node in tree.body if isinstance(node, ast.FunctionDef)}
    z = np.load(directory / 'stats.npz', allow_pickle=True)
    columns = tuple(str(z['cols']).split())
    stats = z['stats']
    frames = len(stats)
    layout_tree = ast.parse((tools / 'layout_preview.py').read_text())
    timed = next(node for node in layout_tree.body if isinstance(node, ast.FunctionDef) and node.name == 'timed_metric_value')
    timed_context = {}
    exec(compile(ast.Module(body=[timed], type_ignores=[]), '<canonical-timed-metric>', 'exec'), timed_context)
    context = dict(np=np, Path=Path, SIM=str(directory), z=z, S=stats,
        STAT_COLUMNS=columns, idx={name:index for index,name in enumerate(columns)},
        NF=frames, C=int(z['cells']), FPS=float(z['fps']), BUDGET=int(z['budget_tiles']),
        ACTIVE_TILES=int(z['active_tiles']), COLD_CAP=int(z['max_cold']),
        FRAME_SEG=np.asarray(decisions['frame_seg']),
        SCROLL_ACTIVE=np.asarray(decisions.get('scroll',{}).get('active',np.zeros(frames,np.bool_))),
        SCROLL_POSITIONS=np.asarray(decisions.get('scroll',{}).get('positions',np.zeros((frames,2),np.int64))),
        style=style, r2v_model=r2v_model, stream_schedule=stream_schedule,
        L=SimpleNamespace(timed_metric_value=timed_context['timed_metric_value']))
    # Execute the original trace validation/category/R2V/Band calculations.
    exec(source[source.index('BUF = np.load'):source.index('MISS_MASKS = np.load')], context)
    exec(source[source.index('col = lambda k:'):source.index('# ---- palettes.bin')], context)
    exec(source[source.index('BODY_USEFUL_BYTES ='):source.index('EFF = FB')], context)
    # Strip video-UI-only fields from frame_data; retain every field consumed
    # by the original analysis_tsv_row, without rewriting their calculations.
    required = {node.slice.value for node in ast.walk(functions['analysis_tsv_row'])
        if isinstance(node,ast.Subscript) and isinstance(node.value,ast.Name)
        and node.value.id=='data' and isinstance(node.slice,ast.Constant)}
    data = functions['frame_data']
    returned = next(node for node in ast.walk(data) if isinstance(node,ast.Return))
    returned.value.keywords = [keyword for keyword in returned.value.keywords if keyword.arg in required]
    definitions = [data,functions['_tsv_number'],functions['analysis_tsv_row']]
    exec(compile(ast.Module(body=definitions,type_ignores=[]), '<canonical-analysis-rows>', 'exec'), context)
    rows = [context['analysis_tsv_row'](frame) for frame in range(frames)]
    tsv = directory / 'analysis-timeline.tsv'
    with tsv.open('w',encoding='utf-8',newline='') as file:
        writer = csv.DictWriter(file,fieldnames=list(rows[0]),delimiter='\t',lineterminator='\n')
        writer.writeheader(); writer.writerows(rows)
    names = ['frame','palette_segment','cold_cap_tiles','status_req','status_cold','status_pre',
        *['legend_'+name.lower() for name in style.LEGEND_ORDER if name!='Wrd'],
        'legend_wr0','legend_wr1','status_prg','status_wr0','status_wr1','status_run','status_r2v',
        'body_raw_payload_bytes','body_prg_payload_bytes','body_control_bytes','body_physical_bytes']
    series = {name:[int(row[name]) for row in rows] for name in names}
    color = lambda rgb:'#'+''.join(f'{value:02x}' for value in rgb)
    colors = {name:color(rgb) for name,rgb in style.CATEGORY_COLORS.items()}
    colors.update(RUN=color(style.COL_RUN),R2V=color(style.COL_DMA),Control=color(style.COL_OVH),Limit=color(style.COL_LIMIT))
    timed_max = lambda name:max(1,max(series[name][1:],default=0))
    supply_max = sum(max(1,max(series['status_'+name.lower()])) for name in style.METER_SUPPLY_SOURCE_ORDER)
    return dict(schema=1,frames=frames,fps=context['FPS'],series=series,colors=colors,
        reqOrder=list(style.REQ_TIMELINE_CATS),legendOrder=[name for name in style.LEGEND_ORDER if name!='Scrl' or bool(context['SCROLL_ACTIVE'].any())],
        scales=dict(Req=context['C'],Supply=supply_max,RUN=timed_max('status_run'),R2V=timed_max('status_r2v'),DIC=timed_max('legend_dic'),Band=100),
        supplyCapacities=context['SUPPLY_CAPACITIES'],coldCap=context['COLD_CAP'])
