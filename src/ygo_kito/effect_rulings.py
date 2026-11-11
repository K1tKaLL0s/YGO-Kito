"""Source-bound official card observations; no deck scoring or legality claims."""
from copy import deepcopy
from functools import lru_cache
from importlib.resources import files
import json


@lru_cache(maxsize=1)
def _rulings():
    data=json.loads(files('ygo_kito').joinpath('resources/rules/card-text-rulings.json').read_text(encoding='utf-8'))
    if data['schema_version']!=1:raise ValueError('unsupported card-text ruling schema')
    return {(r['card_id'],r['card_type'],r['text_sha256']):r for r in data['rulings']}


def apply_reviewed_ruling(record, row):
    """Apply only a reviewed identity, unchanged full text and exact effect span."""
    ruling=_rulings().get((row.get('id'),row.get('type'),record['text_sha256']))
    if not ruling:return
    patch=next((p for p in ruling['effects'] if p['source_text']==record['source_text']),None)
    if patch is None:return
    view=record['block_view']
    # Verify all payment bindings before applying any field from the ruling.
    bindings=[]
    for payment in patch.get('payments',[]):
        costs=[c for c in record['costs'] if c['kind']==payment['kind'] and c['source']==payment['source']]
        blocks=[b for b in view['cost_blocks'] if b['kind']==payment['kind'] and b['source']==payment['source']]
        if len(costs)!=1 or len(blocks)!=1:raise ValueError('reviewed payment no longer matches the parser output')
        bindings.append((payment,costs[0],blocks[0]))
    source=deepcopy(ruling['source'])
    source.update(card_id=row['id'],text_sha256=record['text_sha256'],effect_key=record['effect_key'])
    record['official_rulings']=[source]
    view['official_rulings']=[deepcopy(source)]
    record['trigger'].update(deepcopy(patch['trigger']),basis='official_ruling')
    record['conditions'].update(status='recognized',basis='official_ruling',additional_conditions=patch['state_requirement'])
    record['knowledge']['activation_boundary']='recognized'
    for payment,cost,block in bindings:
        cost.update(deepcopy(payment['values']),ruling_source=source['id'])
        cost.pop('quantity_source',None)
        block['qualifiers']={k:deepcopy(v) for k,v in cost.items() if k not in ('kind','source','cost_index','effect_index')}
    if patch.get('targets')=='none':
        record['targets']=[]
        view['target_refs']=[]
        record['knowledge']['targets']='none_in_reviewed_effect'
    view['connectors']=[c for c in view['connectors'] if not (c['source']=='condition' and c['target']=='effect_group')]
    for kind in patch['connectors']:
        view['connectors'].append(dict(connector_id=f"{record['effect_key']}:connector:{len(view['connectors'])}",
            kind=kind,effect_key=record['effect_key'],source='condition',target='effect_group',condition_source=None,
            starts_chain=True,activation_kind=patch['trigger']['activation_kind'],ruling_source=source['id']))
    resolved={'unnumbered_effect_boundaries','activation_boundary','activation_condition','additional_activation_conditions'}
    record['unknown']=[v for v in record['unknown'] if v not in resolved]
    record['unknown'].append(patch['state_requirement'])
    view['unknown']=list(dict.fromkeys(record['unknown']))
    view['grouping_status']='reviewed_effect_scope'
