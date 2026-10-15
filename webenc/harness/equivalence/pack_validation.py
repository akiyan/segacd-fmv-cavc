"""Keep mandatory scroll lists distinct from optional Main-CPU optimizations.

Scroll controls require the list tag to carry their position item, even when
the nominal bitmap comparison would be faster. This only corrects that pack
validation predicate. Frozen costs, stream bytes and all delivery checks stay
unchanged. Keep the repository's other in-progress codec files untouched.
"""
import inspect
import linecache


def install(pack_stream):
    source = inspect.getsource(pack_stream.main)
    marker = '''    if np.any(update_lists & (recomputed_list >= recomputed_legacy)):
        frame = int(np.flatnonzero(update_lists & (recomputed_list >= recomputed_legacy))[0])'''
    corrected = '''    optional_list_regressions = (
        update_lists & (frame_types == shadow_updates.FRAME_NORMAL)
        & (recomputed_list >= recomputed_legacy))
    if np.any(optional_list_regressions):
        frame = int(np.flatnonzero(optional_list_regressions)[0])'''
    if source.count(marker) != 1:
        raise RuntimeError('Shadow-list validation boundary changed; review the compatibility adapter')
    source = source.replace(marker, corrected)
    filename = '<cavc-mandatory-scroll-list-validation>'
    linecache.cache[filename] = (len(source), None, source.splitlines(True), filename)
    exec(compile(source, filename, 'exec'), pack_stream.__dict__)
