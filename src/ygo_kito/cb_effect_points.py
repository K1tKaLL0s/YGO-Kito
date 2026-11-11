"""Points for effect blocks in an already verified CB, never deck admission."""
import math

BLOCKS=('fusion_access','extra_fusion','body','extra_synchro','extra_xyz','targeted_send','grave_fusion',
        'extra_link','ritual_access','ritual_summon','effect_draw','effect_mill')


def route_effect_points(theme,adjustments=None):
    if not isinstance(theme,str) or not theme.strip():
        raise ValueError('an explicit construction theme is required')
    factors={} if adjustments is None else adjustments
    if set(factors)-set(BLOCKS):raise ValueError('unknown CB effect block')
    if any(type(v) not in (int,float) or not math.isfinite(v) or not 0<=v<=100 for v in factors.values()):
        raise ValueError('CB effect points must be finite and between 0 and 100')
    return {kind:float(factors.get(kind,1.)) for kind in BLOCKS}
