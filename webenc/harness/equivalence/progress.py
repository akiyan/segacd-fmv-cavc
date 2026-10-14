"""Browser-only observation of original codec work; no decision changes."""
import ast
import functools
import inspect
import textwrap
import time


def install(sim, callback, feature_callback=None):
    if callback is None:
        return
    state=dict(stage=1,percent=None,label='Prepare palette inputs',sent=0,
               features=0,total=0,base=25,span=25,scope='MOSAIC-GM',evaluations=0)

    def emit(stage,percent,label,done=0,total=0,force=False,frame_index=None):
        changed=stage!=state['stage'] or label!=state['label']
        state.update(stage=stage,percent=percent,label=label)
        now=time.monotonic()
        if force or changed or now-state['sent']>=.15 or (total and done==total):
            state['sent']=now
            callback(stage,percent,label,int(done),int(total),frame_index)

    def phase(stage,label):
        emit(stage,None,label,force=True)

    def report(name,context):
        if feature_callback is not None and name in ('Palette','Quantize'):
            from features import from_context
            import json
            feature_callback(json.dumps(from_context(context,float(sim.FPS)),separators=(',',':')))

    def scope(base,span,label):
        state.update(base=base,span=span,scope=label,evaluations=0)
        emit(1,base,label,force=True)

    def core(lines,index,total):
        percent=state['base']+state['span']*((lines-1+index/total)/3)
        emit(1,percent,f"{state['scope']} · {lines+1} palette lines · core candidate {index+1}/{total}")

    def frames(stage,index,total,label,frame_index=None):
        emit(stage,100*index/max(1,total),label,index,total,
             frame_index=min(index,total-1) if frame_index is None else frame_index)

    def rewrite(owner,name,transform):
        function=getattr(owner,name)
        tree=ast.parse(textwrap.dedent(inspect.getsource(function)))
        transform(tree)
        ast.fix_missing_locations(tree)
        source=ast.unparse(tree)+'\n'
        filename=f'<webenc-progress-{name}>'
        import linecache
        linecache.cache[filename]=(len(source),None,source.splitlines(True),filename)
        namespace=function.__globals__
        namespace.update(_webenc_emit=emit,_webenc_phase=phase,
                         _webenc_scope=scope,_webenc_core=core,_webenc_frames=frames,_webenc_report=report)
        exec(compile(source,filename,'exec'),namespace)
        setattr(owner,name,namespace[name])

    original_features=sim._frame_features
    @functools.wraps(original_features)
    def features(*args,**kwargs):
        result=original_features(*args,**kwargs)
        state['features']+=1
        emit(1,25*state['features']/max(1,state['total']),
             'Read palette frame features',state['features'],state['total'],
             force=state['features']==1,
             frame_index=state['feature_indices'].get(str(args[0] if args else kwargs.get('path'))))
        return result
    sim._frame_features=features
    original_init=sim.FrameFeatureCache.__init__
    def initialize(self,frames,*args,**kwargs):
        state.update(features=0,total=len(frames),
                     feature_indices={str(path):index for index,path in enumerate(frames)})
        phase(1,'Read palette frame features')
        return original_init(self,frames,*args,**kwargs)
    sim.FrameFeatureCache.__init__=initialize

    def palette(tree):
        for node in ast.walk(tree):
            if isinstance(node,ast.For):
                target=ast.unparse(node.target)
                if target=='requested' and ast.unparse(node.iter)=='sample_counts':
                    total="len(set(min(n,int(count)) for count in sample_counts))"
                    code=f"_webenc_scope(25+25*len(candidates)/({total}),25/({total}),f'MOSAIC-GM global candidate {{len(candidates)+1}}/{{{total}}}')"
                    # Do not announce candidates skipped by the encoder's
                    # duplicate-sample check on short inputs.
                    insertion=next(index for index,item in enumerate(node.body)
                                   if isinstance(item,ast.Assign) and isinstance(item.value,ast.Call)
                                   and ast.unparse(item.value.func)=='train_mosaic')
                    node.body[insertion:insertion]=ast.parse(code).body
                    continue
                elif target=='(start, end)' and ast.unparse(node.iter)=='segments':
                    code="_webenc_scope(50+49*segments.index((start,end))/len(segments),49/len(segments),f'MOSAIC-GM segment {segments.index((start,end))+1}/{len(segments)}')"
                else:continue
                node.body[0:0]=ast.parse(code).body
    rewrite(sim,'segment_and_train',palette)
    import palette_algorithms
    def mosaic(tree):
        for node in ast.walk(tree):
            if isinstance(node,ast.For) and ast.unparse(node.target)=='core_size':
                node.body[0:0]=ast.parse('_webenc_core(len(current.palettes),core_sizes.index(core_size),len(core_sizes))').body
    rewrite(palette_algorithms,'build_mosaic_palettes',mosaic)
    sim.build_mosaic_palettes=palette_algorithms.build_mosaic_palettes
    for name in ['errors','color_histograms']:
        original=getattr(palette_algorithms.PaletteEvaluator,name)
        def wrapper(*args,_original=original,**kwargs):
            result=_original(*args,**kwargs)
            state['evaluations']+=1
            # Actual completed operations keep the GUI alive within a fit.
            if state['stage']==1 and time.monotonic()-state['sent']>=.5:
                emit(1,state['percent'],f"{state['scope']} · {state['evaluations']} evaluations completed")
            return result
        setattr(palette_algorithms.PaletteEvaluator,name,wrapper)

    def quant(tree):
        for node in ast.walk(tree):
            if isinstance(node,ast.For) and ast.unparse(node.target)=='i' and ast.unparse(node.iter)=='range(n)':
                node.body[0:0]=ast.parse("_webenc_frames(2,i,n,'Quantize frames')").body
    rewrite(sim,'precompute_quant',quant)
    original_one=sim._quant_one
    def quant_one(index):
        result=original_one(index)
        frames(2,index+1,state['quant_total'],'Quantize frames',frame_index=index)
        return result
    sim._quant_one=quant_one
    original_quant=sim.precompute_quant
    def quantize(source_frames,*args,**kwargs):
        state['quant_total']=len(source_frames)
        result=original_quant(source_frames,*args,**kwargs)
        phase(2,'Analyze palette fades and scroll')
        return result
    sim.precompute_quant=quantize

    import raw_prefetch, upgrade_planner
    for module,name,label in [(raw_prefetch,'forecast_requests','Forecast VRAM prefetch'),
                              (upgrade_planner,'predict_update_demand_details','Predict future video demand')]:
        def forecast(tree,_label=label):
            for node in ast.walk(tree):
                if isinstance(node,ast.For) and ast.unparse(node.iter)=='range(n)':
                    index=ast.unparse(node.target)
                    node.body[0:0]=ast.parse(f'_webenc_frames(3,{index},n,{_label!r})').body
        rewrite(module,name,forecast)
        original=getattr(module,name)
        def finish_forecast(*args,_original=original,**kwargs):
            result=_original(*args,**kwargs)
            phase(3,'Continue delivery planning')
            return result
        setattr(module,name,finish_forecast)

    def main(tree):
        mapping={'Extract':(1,'Train MOSAIC-GM'),'Palette':(2,'Quantize and analyze fades'),
                 'Quantize':(3,'Plan future demand and delivery'),
                 'Forecast':(4,'Encode frame decisions'),'Decide':(4,'Verify delivery and finalize')}
        boundaries={ast.literal_eval(node.value.args[0]):node.lineno for node in ast.walk(tree)
                    if isinstance(node,ast.Assign) and isinstance(node.value,ast.Call)
                    and ast.unparse(node.value.func)=='_mark'}
        for node in ast.walk(tree):
            for field in ['body','orelse','finalbody']:
                body=getattr(node,field,None)
                if not isinstance(body,list):continue
                for index in range(len(body)-1,-1,-1):
                    item=body[index]
                    if isinstance(item,ast.Assign) and isinstance(item.value,ast.Call) and ast.unparse(item.value.func)=='_mark':
                        name=ast.literal_eval(item.value.args[0])
                        if name in mapping:
                            stage,label=mapping[name]
                            body[index+1:index+1]=ast.parse(f'_webenc_phase({stage},{label!r})\n_webenc_report({name!r},locals())').body
        for node in ast.walk(tree):
            if isinstance(node,ast.For) and ast.unparse(node.target)=='i' and ast.unparse(node.iter)=='range(n)' and boundaries['Forecast']<node.lineno<boundaries['Decide']:
                node.body[0:0]=ast.parse("_webenc_frames(4,i,n,'Encode frame decisions')").body
    rewrite(sim,'main',main)
    return emit
