"""Materialize reviewed, evidence-bound weak annotations for all v3 tasks.

No model or optimizer is created here. Proposed configurations and declared
budgets are explicitly distinguished from observed decks and duel outcomes.
"""
from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import replace
from itertools import combinations
import json
from math import comb
from pathlib import Path
import sqlite3
import sys

ROOT=Path(__file__).resolve().parent
sys.path.insert(0,str(ROOT))
sys.path.insert(0,str(ROOT.parent.parent/'src'))
import prepare_v3 as preparation
from ygo_kito.multifactor.axis_candidates import AxisCandidate
from ygo_kito.multifactor.conditions import Resource
from ygo_kito.multifactor.contracts import (AnalysisContext, DeckSpec, Factors, FunctionSeed,
    GRAPH_FUNCTIONS, LabelCell, LabelSet, RoleInput, UnitSpec, digest)
from ygo_kito.multifactor.splits import build_leakage_groups
from ygo_kito.multifactor.task_queries import BINARY_COORDINATES,CATEGORY_COORDINATES,LEARNED_TASKS

ARTIFACT=Path('N:/YGO-Kito/data/axis_generic/v3/full18-20261110-008')
NORMALS=(69247929,7359741)
EXTRA_MASK=0x40|0x2000|0x800000|0x4000000


def read(path):
    return json.loads(Path(path).read_text('utf-8-sig'))


def write_new(path,value):
    path=Path(path);path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x',encoding='utf-8') as stream:
        json.dump(value,stream,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)
        stream.write('\n')


def cell(value,reference,confidence=.8):
    return LabelCell(value,'known',confidence,'reviewed_card_text_and_declared_context',
                     (reference,),'reviewed').to_dict()


def label(task,subject,values,reference,confidence=.8):
    return LabelSet(task,tuple(subject),tuple((coordinate,LabelCell.from_dict(cell(value,reference,confidence)))
                    for coordinate,value in values.items())).to_dict()


def load_catalog(path,codes):
    connection=sqlite3.connect(Path(path).resolve().as_uri()+'?mode=ro',uri=True)
    connection.row_factory=sqlite3.Row
    try:
        codes=sorted(set(codes));result={}
        for start in range(0,len(codes),800):
            part=codes[start:start+800]
            sql='select d.*,t.name,t.desc from datas d join texts t on d.id=t.id where d.id in ('+','.join('?' for _ in part)+')'
            result.update((r['id'],dict(r)) for r in connection.execute(sql,part))
        if set(result)!=set(codes):raise ValueError('reviewed card missing from pinned catalog')
        return result
    finally:
        connection.close()


def install(deck,codes,catalog):
    """Explicit equal-slot replacements; this does not assert format legality."""
    sections={s:None if getattr(deck,s) is None else Counter(dict(getattr(deck,s))) for s in ('main','extra','side')}
    wanted=set(codes)
    replacements=[]
    for code in sorted(wanted):
        section='extra' if catalog[code]['type']&EXTRA_MASK else 'main'
        stock=sections[section]
        if stock is None:raise ValueError('cannot propose a replacement in an unknown section')
        if stock[code]:continue
        removable=sorted(c for c,n in stock.items() if n and c not in wanted)
        if not removable:raise ValueError('no explicitly removable slot for reviewed package')
        old=removable[-1];stock[old]-=1;stock[code]+=1
        replacements.append(dict(section=section,remove=old,add=code,quantity=1))
    return DeckSpec(*(None if sections[s] is None else tuple(sorted((c,n) for c,n in sections[s].items() if n))
                      for s in ('main','extra','side'))),replacements


def objective(focus,priority,normal_budget,primary_operations=()):
    # These are newly declared query priorities, not parsed old plan text.
    mapping={'negate_activation':'negate','destroy':'destroy','draw':'draw','search':'search','recover':'recover',
        'send_grave':'grave','mill':'grave','special_summon':'special_summon','tribute':'tribute',
        'fusion_summon':'fusion','return_cards_to_deck':'recover','banish':'banish','ritual':'ritual',
        'synchro':'synchro','xyz':'xyz','link':'link'}
    weight={'main':1.,'secondary':.6,'support':.2}[priority]
    target_weight=('goal_interaction_weight' if focus in ('negate_activation','protect','interfere') else
                   'goal_board_break_weight' if focus=='destroy' else 'goal_recovery_weight' if focus in ('recover','follow_up') else
                   'goal_consistency_weight' if focus in ('draw','search') else 'goal_engine_weight')
    values={'goal_engine_weight':.2 if priority=='main' else 1.,'goal_consistency_weight':.2,
            'normal_summon_headroom':float(normal_budget),'remaining_main_space':0.,'remaining_extra_space':0.}
    values[target_weight]=max(values.get(target_weight,0),weight)
    from ygo_kito.multifactor.contracts import CONTEXT_FACTORS
    for operation in primary_operations:
        name='objective_'+operation
        if name in CONTEXT_FACTORS:values[name]=.2 if priority=='main' else 1.
    if focus in mapping:
        name='objective_'+mapping[focus];values[name]=max(values.get(name,0),weight)
    return Factors.observed('context',values,source='explicit_full18_functional_request',confidence=1.)


def source_meta(case,name,reference):
    return dict(source_namespace='full18_reviewed_context',parent_namespace='consumed_axis_references',
        parent_id='legacy-case:'+case['case_id'],reference=case['case_id'],case_id=case['case_id'],
        source_rowid=case.get('deck_cache_rowid'),previously_consumed=True,final_eval_eligible=False,
        annotation_method='assistant_reviewed_weak_context',source_kind='proposed_configuration_on_observed_deck',
        observed_receiver_ref='existing_cases.json#'+case['case_id'],review_ref=reference,
        query_definition=name,legality='not_assessed',duel_execution=False)


def printed_span(catalog, code, quote):
    printed = catalog[code]['desc']
    start = printed.find(quote)
    if not quote or start < 0:
        raise ValueError(f'review quote differs from card {code}')
    return dict(card_id=code, start=start, end=start+len(quote), quote=quote)


def contrast_evidence(review, catalog):
    from ygo_kito.construction_inventory import matches, query_supported
    from ygo_kito.effect_mechanisms import SEMANTIC_VERSION, analyze_card
    from ygo_kito.effect_records import effect_records

    mechanisms, receivers = [], []
    for spec in review['mechanism_contrasts']:
        code = spec['card_id']
        cells = spec['coordinates']
        if (not set(cells) <= set(BINARY_COORDINATES['mechanism']) or set(cells.values()) != {0, 1}
                or not spec['basis']):
            raise ValueError('mechanism contrast requires reviewed positive and negative coordinates')
        mechanisms.append(dict(spec, source=printed_span(catalog, code, spec['quote']),
                               complete_text_span=[0, len(catalog[code]['desc'])]))
    for spec in review['receiver_contrasts']:
        code, check = spec['card_id'], spec['check']
        source = printed_span(catalog, code, spec['quote'])
        record = dict(spec, source=source)
        row = catalog[code]
        effects = effect_records(analyze_card(row), semantic_version=SEMANTIC_VERSION, row=row)
        if check == 'extra_cost':
            costs = [c for effect in effects for c in effect['costs']
                     if c['kind'] == 'banish' and c.get('from_zones') == ['extra']]
            if not costs or not all(type(c.get('quantity')) is int for c in costs):
                raise ValueError('reviewed Extra payment no longer has a known quantity')
            minimum = min(c['quantity'] for c in costs)
            if (len(spec['extra_stock']) != minimum or any(not catalog[c]['type'] & EXTRA_MASK for c in spec['extra_stock'])):
                raise ValueError('reviewed Extra capacity differs from the payment')
            record['minimum'] = minimum
        elif check == 'target':
            allowed = {'extra'} if spec['section'] == 'extra' else {'hand', 'deck'}
            operations = [op for effect in effects for op in effect['operations']
                          if op.get('reason') == 'effect' and op.get('quantity') == 1
                          and spec['quote'] in op['source'] and op.get('from_zones')
                          and set(op['from_zones']) <= allowed and query_supported(op.get('selector_query'))]
            if len(operations) != 1:
                raise ValueError('reviewed target must bind a single complete source operation')
            query = operations[0]['selector_query']
            if not matches(catalog[spec['eligible']], query) or matches(catalog[spec['ineligible']], query):
                raise ValueError('reviewed target pair disagrees with the printed selection')
            record['selector'] = query
        elif check in ('grave_destination', 'normal_lock'):
            source_code = spec['context_card']
            record['context_source'] = printed_span(catalog, source_code, spec['context_quote'])
            context_row = catalog[source_code]
            context_effects = effect_records(analyze_card(context_row), semantic_version=SEMANTIC_VERSION, row=context_row)
            if check == 'grave_destination' and not any(op.get('replacement_rule') and op['kind']=='grave_destination_replace'
                    for effect in context_effects for op in effect['operations']):
                raise ValueError('reviewed destination change requires a parsed replacement rule')
            if check == 'normal_lock' and not any(r['kind'] == 'cannot_activate'
                    for effect in context_effects for r in effect['card_restrictions']):
                raise ValueError('reviewed activation lock requires the printed restriction')
        else:
            raise ValueError('unknown reviewed compatibility contrast')
        receivers.append(record)
    return mechanisms, receivers


def reviewed_contrast_records(case, catalog, mechanisms, receivers):
    from ygo_kito.construction_inventory import matches

    base = DeckSpec(tuple(tuple(p) for p in case['main']), tuple(tuple(p) for p in case['extra']),
                    None if 'side' not in case else tuple(tuple(p) for p in case['side']))

    def row(kind, name, code, focus, deck, changes, spec, targets, *, resources=(), normal=0):
        evidence_key = str(code) if kind == 'mechanism' else spec['id']
        ref = 'full18-evidence.json#/' + kind + '_contrasts/' + evidence_key
        context = AnalysisContext(format='ocg', period=case.get('period', 'unknown'), public_resources=resources)
        query = RoleInput(ref, objective(focus, 'support', normal), (), analysis_mode='deck_analysis',
            analysis_context=context, deck=deck, unit_definition=UnitSpec('focal', ((code, 1),), 'function:'+focus))
        meta = source_meta(case, name, ref)
        meta.update(configuration_changes=changes, source_coordinates=[spec['source'], *(
            [spec['context_source']] if 'context_source' in spec else [])], contrast_kind=kind)
        return dict(schema_version='axis-source-record-v3', record_id='full18:'+case['case_id']+':'+name,
            observations=dict(input=query.to_dict()), targets=targets(ref),
            supervision=dict(kind='weak_context_annotation'), provenance=meta)

    for spec in mechanisms:
        code = spec['card_id']
        deck, changes = install(base, (code,), catalog)
        yield row('mechanism', str(code), code, spec['focus'], deck, changes, spec,
            lambda ref: dict(roles=[], compatibility=[], pairs=[], task_labels=[
                label('mechanism', ('card:'+str(code),), spec['coordinates'], ref, .95)]))

    for spec in receivers:
        code, check = spec['card_id'], spec['check']
        deck, changes = install(base, (code, *([spec['context_card']] if 'context_card' in spec else [])), catalog)
        for compatible in (True, False):
            resources = ()
            normal = 0
            variant = deck
            if check == 'extra_cost':
                stock = spec['extra_stock'] if compatible else spec['extra_stock'][:-1]
                variant = replace(deck, extra=tuple(sorted(Counter(stock).items())))
            elif check == 'target':
                section = spec['section']
                stock = Counter({c:n for c,n in getattr(deck, section) if not matches(catalog[c], spec['selector'])})
                stock[spec['eligible'] if compatible else spec['ineligible']] += 1
                variant = replace(deck, **{section: tuple(sorted(stock.items()))})
            elif check == 'grave_destination':
                resources = (Resource('destination_replacement', 'card:'+str(spec['context_card']), int(not compatible),
                    stage='resolution', state_zone='grave' if compatible else 'banished', source='declared_destination_rule'),)
            elif check == 'normal_lock':
                normal = int(not compatible)
                summon = 'special_summon' if compatible else 'normal_summon'
                resources = (Resource(summon, 'card:'+str(code), 1, stage='activation',
                    state_zone='field', source='declared_monster_summon_origin'),)
            difference = []
            for section in ('main', 'extra'):
                before, after = (dict(getattr(value, section)) for value in (deck, variant))
                difference.extend(dict(section=section, card_id=c, before=before.get(c, 0), after=after.get(c, 0))
                                  for c in sorted(before.keys() | after.keys()) if before.get(c, 0) != after.get(c, 0))
            outcome = 'compatible' if compatible else 'conflict'
            yield row('receiver', spec['id']+':'+outcome, code, spec['focus'], variant, changes+difference, spec,
                lambda ref: dict(roles=[], pairs=[], compatibility=[['query:unit', cell(int(compatible), ref, .95)]],
                    task_labels=[label('receiver_compatibility', ('query:unit',), {'compatibility':outcome}, ref, .95)]),
                resources=resources, normal=normal)


def source_record(case,unit,priority,catalog,normal_budget):
    base=DeckSpec(tuple(tuple(p) for p in case['main']),tuple(tuple(p) for p in case['extra']),
                  None if 'side' not in case else tuple(tuple(p) for p in case['side']))
    codes=set(unit['cards'])|set(NORMALS)
    deck,replacements=install(base,codes,catalog)
    context_ref='reviewed-request:'+unit['id']+':'+priority
    focus=unit['focus'];members=tuple((c,1) for c in sorted(unit['cards']))
    resources=[Resource('normal_summon','normal_summon',normal_budget,resource_id='normal-allocation',pool_id='normal-allocation',
                        source='explicit_construction_allocation')]
    if unit.get('normal_control'):
        resources.extend(Resource('card','card:'+str(c),1,stage='activation',state_zone='field',resource_id='visible:'+str(c),
                                  pool_id='visible:'+str(c),source='declared_review_state') for c in NORMALS)
    primary_operations=case.get('objective_tags',())
    example=RoleInput(context_ref,objective(focus,priority,normal_budget,primary_operations),(),analysis_mode='deck_analysis',
        analysis_context=AnalysisContext(format='ocg',period=case.get('period','unknown'),public_resources=tuple(resources)),
        deck=deck,unit_definition=UnitSpec('focal',members,'function:'+focus))
    function_ref='reviewed-function:'+unit['id']
    seed=FunctionSeed(function_ref,tuple(('card:'+str(c),1) for c in sorted(unit['cards'])),
                      tuple(sorted(unit['functions'])),confidence=.85,evidence_refs=('review:'+unit['id'],))
    candidate=AxisCandidate(seed.function_ref,seed.members,seed.functions,seed.conditions,seed.mode_choices,seed.confidence,seed.evidence_refs)
    axis=candidate.candidate_id
    ref='full18-evidence.json#unit:'+unit['id']
    role_values={name:1 for name in unit['role_positive']}
    role_values.update({name:0 for name in unit['role_negative']})
    known_functions={f:1 for f in unit['functions']}
    known_functions.update({f:0 for f in unit['negative_functions']})
    focus_operation={'negate_activation':'negate','fusion_summon':'fusion','mill':'grave','send_grave':'grave','return_cards_to_deck':'recover'}.get(focus,focus)
    priority_known=priority=='main' or bool(set(primary_operations)-{focus_operation})
    position=label('axis_position',(axis,),{'position':priority},'full18-protocol.json#declared_priorities',.75)
    if not priority_known:position['cells']['position']=LabelCell().to_dict()
    labels=[label('axis_function',(axis,),known_functions,ref),
        label('function_role',('query:unit','function:'+focus),role_values,ref),
        label('contribution',('query:unit','function:'+focus),{'carrier':1,'enhancer':int(bool(unit.get('enhancer')))},ref),
        position,
        label('axis_origin',(axis,),{'origin':unit['origin']},ref,.7),
        label('transferability',('query:unit','function:'+focus),{'portability':unit['transferability']},ref,.7)]
    compatibility = []
    if unit['normal_summon']:
        compatible = bool(normal_budget)
        ref_normal = 'full18-protocol.json#normal_allocation'
        labels.append(label('receiver_compatibility', ('query:unit',),
                            {'compatibility':'compatible' if compatible else 'conflict'}, ref_normal, .95))
        compatibility.append(['query:unit', cell(int(compatible), ref_normal, .95)])
    for code in unit['cards']:
        labels.append(label('axis_membership',(axis,'card:'+str(code)),{'member':1},ref))
    # A card outside the seed is not automatically a negative member. Normal
    # monsters can substitute for generic ritual materials or a non-effect body.
    nonmember=None
    if unit['id'] not in ('black_luster_ritual','tenyi_bounce'):
        if unit.get('normal_control'):
            nonmember=next((c for c,n in deck.main if c not in unit['cards'] and catalog[c]['type']&0x20),None)
        else:
            nonmember=next(c for c in NORMALS if c not in unit['cards'])
    if nonmember is not None:
        labels.append(label('axis_membership',(axis,'card:'+str(nonmember)),{'member':0},ref))
    # Fully read Normal Monster texts/type provide explicit negatives, not missing parser tags.
    for code in NORMALS:
        labels.append(label('mechanism',('card:'+str(code),),{f:0 for f in BINARY_COORDINATES['mechanism']},
                            'full18-evidence.json#normal:'+str(code),1.))
    flags={
        74063034:{'once_per_turn':1,'recycle':1,'target':1},
        1984618:{'summon_lock':1},58699500:{'cost':1,'target':1},
        23431858:{'cost':1,'target':1},92107604:{'once_per_turn':1,'recycle':1,'target':1}}
    card_values={int(code):{f:1 for f in functions} for code,functions in unit.get('mechanism_by_card',{}).items()}
    for code,values in flags.items():
        if code in unit['cards']:card_values.setdefault(code,{}).update(values)
    for code,values in card_values.items():
        labels.append(label('mechanism',('card:'+str(code),),values,ref,.9))
    if unit.get('enhancer'):
        labels.append(label('contribution',('query:unit','card:'+str(unit['enhancer']),'function:'+focus),
                            {'carrier':0,'enhancer':1},ref,.9))
    legacy=[LabelCell().to_dict(),LabelCell().to_dict(),
            cell(int(priority!='support'),'full18-protocol.json#declared_priorities',.75) if priority_known else LabelCell().to_dict(),
            cell(int(priority!='main'),'full18-protocol.json#declared_priorities',.75) if priority_known else LabelCell().to_dict(),
            cell(unit['legacy_generic_utility'],ref,.9) if 'legacy_generic_utility' in unit else LabelCell().to_dict()]
    rid='full18:'+case['case_id']+':'+unit['id']+':'+priority
    meta=source_meta(case,rid,ref)
    meta.update(configuration_changes=replacements,normal_summon_allocation=normal_budget,
                declared_primary_role=priority,requested_function=focus,priority_label_known=priority_known,
                explicit_primary_operations=list(primary_operations))
    return dict(schema_version='axis-source-record-v3',record_id=rid,
        observations=dict(input=example.to_dict(),function_seeds=[seed.to_dict()]),
        targets=dict(roles=[['query:unit',legacy]],compatibility=compatibility,
                     pairs=[],task_labels=labels),supervision=dict(kind='weak_context_annotation'),provenance=meta)


def explicit_incomplete_query(complete,unit):
    """A different exact query, with a quoted mandatory member excluded.

    This is a negative legacy minimum-unit label, never a closed-portability
    label for a broken unit. The complete fact branch remains observable.
    """
    row=deepcopy(complete)
    example=RoleInput.from_dict(row['observations']['input'])
    excluded=unit['exclude_required_member']
    selected=tuple((c,n) for c,n in example.unit_definition.members if c!=excluded)
    if len(selected)==len(example.unit_definition.members):raise ValueError('required exclusion absent')
    example=replace(example,unit_definition=replace(example.unit_definition,members=selected))
    row['observations']['input']=example.to_dict()
    ref='full18-protocol.json#strict_complete_unit'
    row['targets']=dict(roles=[['query:unit',[LabelCell().to_dict() for _ in range(4)]+[cell(0,ref,.95)]]],
                        compatibility=[],pairs=[],task_labels=[])
    row['record_id']+=':exact-member-excluded'
    row['provenance'].update(review_ref=ref,query_definition='exact_required_member_exclusion:'+unit['id'],
        excluded_query_member=excluded,minimum_unit_basis=unit['basis'],
        excluded_scope='excluded from the exact queried unit; other observed cards cannot be silently borrowed')
    return row


def relation_record(case,catalog):
    codes={38814750,49036338,47679935,74063034,86120751,10802915,53129443,12580477}|set(NORMALS)
    base=DeckSpec(tuple(tuple(p) for p in case['main']),tuple(tuple(p) for p in case['extra']),None)
    deck,replacements=install(base,codes,catalog)
    resources=(Resource('card','monster',0,owner='self',stage='activation',state_zone='field',resource_id='own-visible-monsters',
                        pool_id='own-visible-monsters',source='declared_review_state'),
               Resource('card','monster',1,owner='opponent',stage='activation',state_zone='field',resource_id='opponent-visible-monsters',
                        pool_id='opponent-visible-monsters',source='declared_review_state'),
               Resource('normal_summon','normal_summon',1,resource_id='normal-allocation',pool_id='normal-allocation',source='explicit_construction_allocation'))
    example=RoleInput('reviewed-relation-request',objective('negate_activation','support',1),(),analysis_mode='deck_analysis',
        analysis_context=AnalysisContext(format='ocg',period=case.get('period','unknown'),public_resources=resources),deck=deck,
        unit_definition=UnitSpec('focal',((38814750,1),(49036338,1)),'function:negate_activation'))
    ref='full18-protocol.json#directed_relations'
    scopes=[(38814750,49036338,{'dependency':1,'substitute':0,'conflict':0}),
            (53129443,12580477,{'substitute':1,'dependency':0,'conflict':0}),
            (47679935,74063034,{'support':1,'conflict':0}),
            (10802915,86120751,{'conflict':1,'support':0,'dependency':0,'substitute':0})]
    labels=[label('pair_relation',('card:'+str(a),'card:'+str(b)),values,ref,.85) for a,b,values in scopes]
    pairs=[['card:38814750','card:49036338',cell(1,ref,.9)],['card:10802915','card:86120751',cell(0,ref,.9)]]
    meta=source_meta(case,'relations',ref);meta['configuration_changes']=replacements
    meta['declared_state_assumptions']=['own field empty for the board-wipe substitution comparison','one normal-summon allocation shared by the two normal starters']
    return dict(schema_version='axis-source-record-v3',record_id='full18:'+case['case_id']+':relations',
        observations=dict(input=example.to_dict()),targets=dict(roles=[],compatibility=[],pairs=pairs,task_labels=labels),
        supervision=dict(kind='weak_context_annotation'),provenance=meta)


def preference_records(case,catalog):
    base=DeckSpec(tuple(tuple(p) for p in case['main']),tuple(tuple(p) for p in case['extra']),None)
    deck,replacements=install(base,{53129443,*NORMALS},catalog)
    main=Counter(dict(deck.main))
    # Freeze exactly one focus copy, replacing any surplus with an explicit irrelevant control.
    surplus=main[53129443]-1
    main[53129443]=1;main[NORMALS[0]]+=surplus
    deck=DeckSpec(tuple(sorted((c,n) for c,n in main.items() if n)),deck.extra,deck.side)
    left=RoleInput('reviewed-copy-access-request',objective('destroy','main',1),(),analysis_mode='deck_analysis',
        analysis_context=AnalysisContext(format='ocg',period=case.get('period','unknown')),deck=deck,
        unit_definition=UnitSpec('focal',((53129443,1),),'function:destroy'))
    ref='full18-protocol.json#copy_access_probability'
    n=sum(main.values())
    for mode in ('right','left','equal'):
        a=left
        right_main=Counter(main)
        if mode=='equal':
            remove,add=NORMALS
        else:
            remove,add=NORMALS[0],53129443
        right_main[remove]-=1;right_main[add]+=1
        b=RoleInput(a.context_ref,a.context,(),analysis_mode=a.analysis_mode,analysis_context=a.analysis_context,
            deck=DeckSpec(tuple(sorted((c,n) for c,n in right_main.items() if n)),deck.extra,deck.side),unit_definition=a.unit_definition)
        if mode=='left':a,b=b,a;remove,add=add,remove
        ka,kb=dict(a.deck.main)[53129443],dict(b.deck.main)[53129443]
        probability=lambda k:1-comb(n-k,min(5,n))/comb(n,min(5,n))
        pa,pb=probability(ka),probability(kb)
        answer='equal' if pa==pb else 'left' if pa>pb else 'right'
        meta=source_meta(case,'copy:'+mode,ref)
        meta.update(configuration_changes=replacements,comparison_criterion='first-five-card access to the fixed one-card focus function; equal slot budget; no global card-strength claim',
                    access=dict(deck_size=n,draws=min(5,n),left_copies=ka,right_copies=kb,left_probability=pa,right_probability=pb))
        yield dict(schema_version='axis-source-record-v3',record_id='full18:'+case['case_id']+':copy:'+mode,
            observations=dict(input=a.to_dict()),comparison=dict(right=dict(input=b.to_dict()),left_key='query:unit',right_key='query:unit',
                operation=dict(add=dict(card_id=add,section='main',quantity=1),remove=dict(card_id=remove,section='main',quantity=1),kind='replacement')),
            targets=dict(roles=[],compatibility=[],pairs=[],task_labels=[label('copy_preference',('query:unit','query:unit'),{'preference':answer},ref,.95)]),
            supervision=dict(kind='weak_context_annotation'),provenance=meta)


def required_classes():
    from ygo_kito.multifactor.contracts import TASK_DOMAINS
    return {(t,c,str(v)) for t in LEARNED_TASKS for c in BINARY_COORDINATES.get(t,(CATEGORY_COORDINATES.get(t,'value'),))
            for v in (TASK_DOMAINS[t] if t in CATEGORY_COORDINATES else (0,1))}


def carry_lineage(records,case_components):
    """Keep known transitive history even when unreviewed variant rows are omitted."""
    for row in records:
        meta=row['provenance'];case_id=meta['case_id']
        if case_id not in case_components:raise ValueError('historical source component missing for '+case_id)
        component=case_components[case_id]
        meta['historical_source_component']=component
        meta['derived_from']=sorted(set(meta.get('derived_from',()))|{'historical-component:'+component})


def freeze_partitions(records):
    # Source grouping is frozen before splitting. This is label-stratified development
    # allocation, not selection against model/final-test results.
    stubs=preparation._source_stubs(records)
    grouping=build_leakage_groups([r for r,_ in stubs],near_duplicate_swaps=2,max_near_pairs=1000000)
    masks=defaultdict(set)
    for (row,_),group in zip(stubs,grouping['row_groups']):
        migrated,_=preparation.migrate_targets(row,RoleInput.from_dict(row['observations']['input']))
        for task,coordinate,known in preparation.iter_target_cells(migrated):
            if known.known:
                c=coordinate[-1] if task in BINARY_COORDINATES or task in CATEGORY_COORDINATES else 'value'
                masks[group].add((task,c,str(known.value if task in CATEGORY_COORDINATES else int(known.value>=.5))))
    required=required_classes();groups=sorted(grouping['groups'],key=lambda g:digest(('full18-v1',g)))
    absent=required-set().union(*masks.values())
    if absent:raise ValueError('reviewed source class gaps: '+str(sorted(absent)))
    def covers(selected):return required<=set().union(*(masks[g] for g in selected))
    chosen=None;examined=0
    for size in (2,3,4):
        for calibration in combinations(groups,size):
            if not covers(calibration):continue
            remaining=[g for g in groups if g not in calibration]
            for selection in combinations(remaining,3):
                examined+=1
                if examined>20000:raise ValueError('bounded stratified split search exhausted')
                if not covers(selection):continue
                rest=[g for g in remaining if g not in selection]
                for retrospective in combinations(rest,3):
                    training=[g for g in rest if g not in retrospective]
                    if covers(retrospective) and covers(training):
                        chosen=(training,selection,calibration,retrospective);break
                if chosen:break
            if chosen:break
        if chosen:break
    if chosen is None:raise ValueError('no disjoint full-class source allocation; retain scope and add evidence')
    training,selection,calibration,retrospective=map(set,chosen)
    folds={g:'train' if g in training else 'validation' if g in selection|calibration else 'test' for g in groups}
    for row,group in zip(records,grouping['row_groups']):row['supervision']['partition']=folds[group]
    return dict(training_groups=sorted(training),selection_groups=sorted(selection),calibration_groups=sorted(calibration),
                retrospective_groups=sorted(retrospective),source_groups=len(groups),protocol='unseen_deck',independent_final=False)


def materialize(output=ARTIFACT):
    output=Path(output).resolve()
    if output.exists() and any(output.iterdir()):raise ValueError('new annotation directory required; existing evidence is immutable')
    config=read(ROOT/'config.v3.json');cases=read(ROOT/'existing_cases.json');review=read(ROOT/'full18_annotations.json')
    codes=set(NORMALS)|{12580477,53129443,10802915,86120751,47679935,74063034,38814750,49036338}
    codes.update(c for u in review['units'] for c in u['cards'])
    codes.update(c['card_id'] for c in review['mechanism_contrasts'])
    for contrast in review['receiver_contrasts']:
        codes.update(contrast[k] for k in ('card_id', 'eligible', 'ineligible', 'context_card') if k in contrast)
        codes.update(contrast.get('extra_stock', ()))
    codes.update(c for case in cases for section in ('main','extra','side') for c,n in case.get(section,[]))
    catalog=load_catalog(config['catalog'],codes)
    mechanisms, receiver_checks = contrast_evidence(review, catalog)
    for code in NORMALS:
        if catalog[code]['type']&0x10==0 or catalog[code]['type']&0x20:raise ValueError('negative control is not a verified Normal Monster')
    for unit in review['units']:
        unit['mechanism_by_card']={str(c):review['card_mechanisms'][str(c)] for c in unit['cards'] if str(c) in review['card_mechanisms']}
        if set(unit['functions'])&set(unit['negative_functions']):raise ValueError('contradictory functional review '+unit['id'])
        if (set(unit['functions'])|set(unit['negative_functions']))-set(GRAPH_FUNCTIONS):
            raise ValueError('unknown reviewed function')
        for code,quote in unit['quotes']:
            if quote not in catalog[code]['desc']:raise ValueError('review quote differs from actual card text: '+unit['id']+' '+str(code))
    evidence=dict(version=review['version'],annotation_method=review['annotation_method'],
        catalog_path=config['catalog'],cards={str(c):catalog[c] for c in sorted(codes)},
        units={u['id']:u for u in review['units']},normal_controls={str(c):dict(type=catalog[c]['type'],text=catalog[c]['desc']) for c in NORMALS})
    evidence.update(mechanism_contrasts={str(spec['card_id']): spec for spec in mechanisms},
                    receiver_contrasts={spec['id']: spec for spec in receiver_checks})
    legacy=dict(config.get('legacy_import') or read(ROOT/'config.v3.json').get('legacy_import') or {},parent_dir=None)
    if not legacy.get('cases'):
        legacy=dict(cases='existing_cases.json',labels='original_labels.json',plans='semantic_audit/primary_plans.json',
            audit='semantic_audit/reference_audit.json',low_support='semantic_audit/support_low_scope_resolution.json',
            generic='semantic_audit/construction_generic_review.json',parent_dir=None,source_namespace='consumed_axis_references')
    records=preparation.load_legacy_sources(config,legacy)
    historical_legacy=dict(legacy,parent_dir='N:/YGO-Kito/data/axis_generic/source/v6_2',parent_folds=['train','validation'])
    historical=preparation.load_legacy_sources(config,historical_legacy)
    historical_stubs=preparation._source_stubs(historical)
    historical_grouping=build_leakage_groups([r for r,_ in historical_stubs],near_duplicate_swaps=2,max_near_pairs=1000000)
    by_case=defaultdict(set)
    for (row,_),group in zip(historical_stubs,historical_grouping['row_groups']):by_case[row['provenance']['case_id']].add(group)
    if any(len(values)!=1 for values in by_case.values()):raise ValueError('a historical case crosses source components')
    case_components={case:next(iter(values)) for case,values in by_case.items()}
    carry_lineage(records,case_components)
    evidence['historical_lineage']=dict(records=len(historical),components=len(historical_grouping['groups']),case_components=case_components,
        source='v6_2 train/validation plus original cases; variants are used for source linkage, not copied as independent training evidence')
    del historical,historical_stubs,historical_grouping
    # Old generic labels can refer to opaque joint functions, primary plans or
    # action ordering that this legacy observation did not represent. Preserve
    # their history; newly explicit complete/excluded queries supply this head.
    for row in records:
        withdrawn=[]
        for key,values in row['targets']['roles']:
            if values[4]['status']=='known':
                withdrawn.append(dict(task='legacy:generic_utility',before=values[4],reason='legacy functional/plan scope not fully represented; use separately reviewed explicit queries'))
                values[4]=LabelCell().to_dict()
        if withdrawn:row['provenance']['source_scope_withdrawals']=withdrawn
    unique={}
    for case in cases:
        signature=digest((case['main'],case['extra'],case.get('side')))
        unique.setdefault(signature,case)
    receivers=[unique[k] for k in sorted(unique)]
    for index,case in enumerate(receivers):
        for unit in review['units']:
            modes=['support']
            if unit['id'] in ('invoked_fusion_bridge','complementary_board_clear','gamma_response'):modes+=['main','secondary']
            budget=int(digest((case['case_id'],unit['id']))[-1],16)%2
            for priority in modes:
                complete=source_record(case,unit,priority,catalog,budget)
                records.append(complete)
                if priority=='support' and unit.get('exclude_required_member'):
                    records.append(explicit_incomplete_query(complete,unit))
        records.append(relation_record(case,catalog));records.extend(preference_records(case,catalog))
        records.extend(reviewed_contrast_records(case, catalog, mechanisms, receiver_checks))
    carry_lineage(records, case_components)
    partitions=freeze_partitions(records)
    protocol=dict(version='axis-full18-review-protocol-v1',source_kind='weak_context_annotation',human_gold=False,engine_executed=False,
        declared_priorities={'main':'queried functional route is the primary declared mechanism','secondary':'queried route is a parallel strategic route and also supports the primary plan',
            'support':'queried route supplies a local service to another declared primary mechanism; no claim about an unobserved author intent'},
        normal_allocation='An explicit construction resource budget, not an inferred current-turn summon count. A reviewed one-normal starter conflicts with a zero allocation.',
        directed_relations='Gamma requires Driver; Dark Hole/Raigeki substitute for opponent-monster clearing with own field empty; Meltdown protects fusion activation; two one-normal starters compete for one allocation. Each label is scoped to these claims.',
        copy_access_probability='Compare exact first-five-card access to the fixed Dark Hole functional unit under an equal-slot replacement, 1-C(N-K,5)/C(N,5). Other card strength and duel outcomes are not inferred.',
        origin='Operational weak review: intrinsic named-engine closure; external self-contained general-purpose service; mixed named entry combined with a generic material or conversion bridge. This is independent of the declared goal priority.',
        portability='Complete function unit: open needs no receiver-specific mechanism; conditional needs stated normal/extra/resource or receiver constraints; closed is a named in-engine continuation whose usefulness presupposes that receiver mechanism. State readiness alone never supplies a negative.',
        negative_evidence='Explicitly reviewed whole-card coordinates or effectless Normal Monster controls. A missing parser observation leaves the coordinate unknown.',
        receiver_contrasts='Review only the named compatibility coordinate under the paired Extra capacity, legal target, destination replacement, or activation restriction. Other constraints and duel outcomes are outside these labels.',
        strict_complete_unit='Gamma/Driver for negation, Terrortop/Taketomborg/Totem Bird for the exact XYZ endpoint, and Vishuda/Monk for the specified non-effect-body bounce are explicitly reviewed complete minimum branches. Excluding the named mandatory member from the exact question is 0 for the legacy minimum-unit question; it never supplies a closed-portability target. Prior opaque-scope generic labels are withdrawn, not silently repurposed.',
        configuration_origin='Observed receiver lists plus fully recorded proposed slot replacements and explicit query budgets. These are reviewer-declared scenarios, not replay observations.',
        partitions=partitions)
    write_new(output/'full18-evidence.json',evidence);write_new(output/'full18-protocol.json',protocol)
    write_new(output/'source-records.json',dict(version=review['version'],records=records))
    write_new(output/'source-partitions.json',partitions)
    summary=dict(records=len(records),observed_receivers=len(receivers),reviewed_units=len(review['units']),partitions=partitions,
                 evidence=str(output/'full18-evidence.json'),source_records=str(output/'source-records.json'),training_started=False)
    write_new(output/'source-summary.json',summary)
    return summary


if __name__=='__main__':
    import argparse
    parser=argparse.ArgumentParser(description=__doc__);parser.add_argument('--output',default=str(ARTIFACT))
    args=parser.parse_args();print(json.dumps(materialize(args.output),ensure_ascii=False,indent=2))
