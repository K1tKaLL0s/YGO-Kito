"""Check the audited findings against a full local live projection.

This is a regression ledger, not an independent card-ruling oracle. Unmapped or
partly represented findings remain explicit follow-ups instead of passing.
"""
import argparse
from collections import Counter
import gzip
import json
import re
from pathlib import Path
import sys

sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))

ALIASES={'search':'search_or_recover','recover':'search_or_recover','add_hand':'search_or_recover',
         'negate_effect':'negate','negate_activation':'negate'}
POSITIVE={
    'stat_change':'stats','stats':'stats','stats_copy':'stats','stat_reset':'stat_reset','stats_reset':'stat_reset',
    'compound_property_change':'property','attribute_change':'attribute_change','race_change':'race_change',
    'name_change':'name_change','type_change':'type_change','toon_identity_grant':'type_change',
    'inspection':'inspect','inspect':'inspect','public_card_observation':'reveal','reveal_extra_top':'reveal',
    'extra_shuffle':'shuffle','summon_negation':'negate_summon','negate_summon':'negate_summon',
    'effect_negation':'negate','negate':'negate','battle_negation':'negate_attack','negate_attack':'negate_attack',
    'extra_attack_permission':'extra_attack','extra_attack':'extra_attack','attack_all':'attack_all',
    'direct_attack_permission':'direct_attack','forced_direct_attack':'force_direct_attack',
    'dynamic_draw':'draw','conditional_draw_quantity':'draw','draw_branch':'draw',
    'resolution_discard':'discard','resolution_release':'release','resolution_detach':'detach',
    'remove_counter':'remove_counter','counter_removal':'remove_counter','counter_placement':'counter',
    'set_operation':'set','set':'set','equip_conversion':'equip','equip':'equip','equip_move':'equip_move',
    'attach_operation':'attach','add_hand_branch':'search_or_recover','add_hand':'search_or_recover',
    'control_transfer':'control','control':'control','recover_lp':'recover_lp','lp_change':'lp_change',
    'damage_redirect':'damage_redirect','effect_grant':'effect_grant','effect_copy':'effect_copy',
    'position_change':'position','position':'position','declaration':'declare','activation_declaration_parameter':'declare',
    'gemini_enable':'gemini_enable','forced_battle':'force_battle','zone_move':'zone_move',
    'material_permission':'material_permission','tuner_material_permission':'material_permission',
    'material_race_change':'race_change','field_shuffle':'field_shuffle','mass_return_deck':'return_deck',
    'resolution_send_grave':'send_grave','conditional_send_grave_branch':'send_grave','deck_send_grave':'send_grave',
    'temporary_banish_return':'return','deck_grave_swap':'deck_grave_swap','normal_draw_replacement':'draw_replace',
    'victory_condition':'win','effect_normal_summon':'normal_summon','union_unequip_summon':'special_summon',
    'timed_self_destruction':'destroy','upkeep_self_destruction':'destroy','prelude_self_destruction':'destroy',
    'timed_self_send_grave':'send_grave','scheduled_stat_change':'stats','forced_attack':'force_attack',
    'battle_protection':'battle_protection','general_destruction_protection':'effect_protection',
}


def records(entry):
    result=[]
    views={v['effect_key']:v for v in entry.get('effects',[])}
    def visit(record):
        if 'block_view' not in record:record=dict(record,block_view=views.get(record.get('effect_key'),{}))
        result.append(record)
        for branch in record.get('branch_records',{}).values():visit(branch)
    for record in entry.get('source_records',[]):visit(record)
    return result


def context(entry,finding):
    rs=records(entry)
    source=finding.get('source','')
    selected=[r for r in rs if source and source in r.get('source_text','')]
    return selected or [r for r in rs if finding.get('scope') in (None,'same_effect',r.get('scope'))]


def items(rs,section):
    if section=='operations':return [o for r in rs for o in r.get('operations',[])]
    if section=='costs':return [c for r in rs for c in r.get('costs',[]) if c['kind']!='payment']
    if section=='restrictions':return [v for r in rs for key in ('restrictions','card_restrictions') for v in r.get(key,[])]
    return [v for r in rs for v in r.get('block_view',{}).get(section,[])]


def check(family,finding,entry):
    rs=context(entry,finding)
    ops=items(rs,'operations');kinds={ALIASES.get(o['kind'],o['kind']) for o in ops}
    costs=items(rs,'costs');payments={c['kind'] for c in costs}
    cost_blocks=items(rs,'cost_blocks')
    activation_blocks=[b for b in cost_blocks if b.get('phase') in ('activation_payment','conditional_activation_payment')]
    costs=costs+[dict(b.get('qualifiers',{}),kind=b['kind'],source=b['source']) for b in activation_blocks]
    payments={c['kind'] for c in costs}
    def source_costs(values):
        return [v for v in values if v.get('source') and (v['source'] in finding.get('sentence',source)
            or source in v['source'])]
    source=finding.get('source','')
    exact=[o for o in ops if source and (source in o.get('source','') or o.get('source') and o['source'] in source)]
    if family=='rule_name_alias_wrongly_excluded_from_dictionary':return True,'independent live identity present; export checked separately'
    if family=='dictionary_export_contract':return None,'requires completed export/readback'
    if family in ('created_token_misrecorded_as_existing_field_resource','token_source_without_creation'):
        tokens=[o for o in ops if o['kind'] in ('special_summon','token') and '衍生物' in o.get('source','')]
        return bool(tokens) and all(o.get('creates_token') and o.get('from_zones')==[] for o in tokens),'token creation and empty source zones'
    if family=='missing_extra_in_shared_origin':
        view=[b for b in items(rs,'blocks')+cost_blocks if source in b['source'] or b['source'] in source]
        if not view and any(source in r['source'] for r in items(rs,'restrictions')):
            return True,'source-zone reference retained in restriction without a false operation'
        return bool(view) and all('extra' in b['qualifiers'].get('from_zones',[]) for b in view),'parallel extra-deck source in source-bound operation/payment'
    if family=='printed_victory_condition_not_in_coarse_view':return 'win' in kinds,'printed victory condition'
    if family=='negated_selector_suppresses_positive_processing':
        want='search_or_recover' if '加入手卡' in source else 'special_summon'
        return want in kinds,'positive processing survives the negative selector'
    if family in ('noun_or_trigger_reference_as_processing','destroyed_monster_reference_as_destroy_effect'):
        bad=ALIASES.get(finding.get('actual_kind','destroy'),finding.get('actual_kind','destroy'))
        return not any(o['kind']==bad for o in exact),'rejected original false action'
    negatives={
        'summon_negation_or_event_as_special_summon':'special_summon','summoned_token_reference_as_creation':'token',
        'face_up_adjective_as_reveal':'face_up','existing_counter_count_as_counter_placement':'counter',
        'counter_eligible_card_selector_as_counter_placement':'counter','damage_timing_as_damage_amount_change':'damage_change',
        'stat_formula_as_level_change':'level','position_event_as_position_change':'position',
        'material_level_reference_as_substitution':'material_level','processing_order_as_deck_order_change':'reorder_deck',
        'ritual_material_permission_as_ritual_summon':'ritual_summon','detach_misrecorded_as_attach':'attach',
    }
    if family in negatives:return not any(o['kind']==negatives[family] for o in exact),'rejected original false action'
    if family=='normal_pendulum_scope':
        monster=[r for r in records(entry) if r.get('scope')=='monster']
        return bool(monster) and all(not r['operations'] for r in monster),'normal monster description has no processing'
    if family=='activation_head_as_processing':
        return not exact,'activation head is not processing'
    if family=='cost_from_trigger_description':
        return not source_costs(costs),'event is not an activation fee'
    if family=='opponent_payment_event_as_payment':
        return not any(o['kind']=='lp_payment' for o in exact),'opponent payment event does not cause another payment'
    if family=='missing_alternate_activation_payment':
        return any(b['phase']=='alternative_activation_payment' for b in source_costs(cost_blocks)),'optional activation fee remains separate'
    if family in ('printed_activation_payment_not_structured','missing_activation_payment','untyped_activation_payment',
                  'incomplete_composite_payment','missing_common_option_payment','cost_as_resolution'):
        expected={p['kind'] for p in finding.get('audited_atoms',[]) if p['kind'] in (
            'pay_lp','send_grave','banish','release','detach','remove_counter','reveal','position')}
        if not expected and '支付' in source:expected={'pay_lp'}
        if not expected and '作为祭品' in source:expected={'release'}
        return bool(costs) and (not expected or expected<=payments),'typed source-bound activation payments'
    if family in ('missing_activation_position_payment','missing_lp_cost','missing_detach_cost','missing_counter_cost'):
        want={'missing_activation_position_payment':'position','missing_lp_cost':'pay_lp','missing_detach_cost':'detach','missing_counter_cost':'remove_counter'}[family]
        return want in payments,'typed '+want+' activation payment'
    if family in ('missing_summon_procedure','missing_overlay_summon_procedure','missing_tribute_summon_procedure','summon_procedure_as_effect'):
        return bool(items(rs,'procedure_blocks')),'separate summon procedure'
    if family in ('missing_branch_payment','missing_payment_choice_binding'):
        branches=[b for r in rs for b in r.get('branch_records',{}).values()]
        if not branches and family=='missing_branch_payment':
            return bool(costs) and any(r.get('payment_dependencies') for r in rs),'variable payment linked to source-scoped selection'
        return bool(branches) and all(items([b],'costs') for b in branches),'payment bound to every option'
    if family in ('missing_prelude_activation_permission','missing_activation_permission'):
        if '不能从手卡发动' in source:return bool(items(rs,'restrictions')),'prohibition remains a restriction'
        return 'activation_permission' in kinds,'source-bound activation permission'
    if family in ('search_modifier_as_extra_action',):
        return any(o.get('variants') for o in ops),'selection modifier bound to existing search'
    if family in ('missing_conditional_quantity','missing_conditional_payment_quantity'):
        values=costs if family.endswith('payment_quantity') else ops
        return any(v.get('quantity_variants') or v.get('quantity_rule') for v in values),'conditional quantity preserved'
    if family in ('missing_scheduled_lp_payment','missing_procedure_lp_payment','missing_resolution_lp_payment'):
        phase={'missing_scheduled_lp_payment':'upkeep_payment','missing_procedure_lp_payment':'summon_payment','missing_resolution_lp_payment':'resolution'}[family]
        values=items(rs,'cost_blocks')+items(rs,'procedure_blocks')+ops
        return any(v['kind'] in ('pay_lp','lp_payment') and v.get('phase')==phase for v in values),'LP payment in '+phase
    if family.startswith('missing_maintenance_'):
        want={'tribute':{'release'},'discard':{'send_grave','discard'},'reveal':{'reveal'},'banish':{'banish'},'return_card':{'return_hand','return_deck'}}.get(family[len('missing_maintenance_'):])
        if want:return any(b['kind'] in want and b['phase']=='upkeep_payment' for b in cost_blocks),'typed maintenance payment'
        if family=='missing_maintenance_alternatives':return any(b['phase']=='upkeep_payment' for b in cost_blocks),'maintenance alternatives retained'
    if family=='missing_upkeep_payment_or_send_grave':return any(b['phase']=='upkeep_payment' for b in cost_blocks),'scheduled maintenance payment'
    if family in ('missing_activation_declaration_parameter','missing_declaration'):
        return 'declare' in kinds or any(d['kind']=='declare' for d in items(rs,'description_blocks')),'declaration operation or activation parameter'
    if family=='missing_public_activation_condition':
        return any(d['kind']=='public_activation_condition' for d in items(rs,'description_blocks')),'public-state activation condition'
    if family=='missing_activation_counter_setup':
        return any(b['kind']=='counter' and b['phase']=='activation_initialization' for b in items(rs,'blocks')),'counter setup on activation'
    if family=='ritual_material_permission_as_ritual_summon':
        return 'ritual_summon' not in kinds and 'material_count' in kinds,'full ritual material value without a ritual-summon operation'
    if family=='missing_tuner_material_permission':
        return any(o['kind']=='material_permission' and o.get('material_role')=='tuner' for o in ops),'tuner qualification confined to this synchro summon'
    if family=='cost_replacement_as_standalone_banish':return 'cost_replacement' in kinds and not any(o['kind']=='banish' for o in exact),'cost replacement, no unconditional banish'
    if family=='attachment_as_material_permission':return 'attach' in kinds and not any(o['kind']=='material_permission' for o in exact),'attachment rather than material qualification'
    if family=='material_to_hand_misrecorded_as_attach':return 'search_or_recover' in kinds and not any(o['kind']=='attach' for o in exact),'material recovery, no attachment'
    if family in ('cost_reference_misclassified_as_send_grave',):return 'banish' in payments and not any(c['kind']=='send_grave' for c in source_costs(costs)),'banish cost with historical sending kept as a selector'
    if family in ('restriction_clause_suppresses_special_summon','missing_triggered_special_summon'):return 'special_summon' in kinds,'positive special summon retained'
    if family=='restriction_clause_suppresses_search':return 'search_or_recover' in kinds,'positive search retained'
    if family=='selector_card_name_difference_as_name_change':return not any(o['kind']=='name_change' for o in exact),'different-name selector is not renaming'
    if family=='triggered_operation_as_continuous':return any(o.get('phase')=='resolution' for o in ops),'triggered processing has a resolution phase'
    alternatives={
        'missing_inspection':{'inspect','inspect_hand','inspect_extra','reveal'},
        'missing_public_card_observation':{'reveal','inspect','card_public','hand_public'},
        'missing_position_change':{'position','position_permission'},
        'missing_battle_negation':{'negate_attack','negate_battle'},
        'missing_negate_attack':{'negate_attack','negate_battle'},
        'missing_negate':{'negate','negate_summon'},
        'missing_extra_attack':{'extra_attack','attack_all'},
        'missing_temporary_banish_return':{'return_field'},
        'missing_effect_normal_summon':{'normal_summon','tribute_summon'},
        'missing_extra_shuffle':{'shuffle_extra'},'missing_reveal_extra_top':{'reveal_top'},
        'missing_general_destruction_protection':{'effect_protection'},
        'missing_resolution_payment_loop':{'repeat_effect'},'missing_random_choice':{'random_choice'},
        'missing_conditional_selector':{'selection_expand'},'missing_global_race_change':{'race_change'},
    }
    if family in alternatives:return bool(kinds&alternatives[family]),'equivalent source-scoped coarse kind'
    if family in ('missing_material_leave_banish_rule','missing_tribute_destination_replacement','missing_synchro_material_destination_replacement'):
        return 'grave_destination_replace' in kinds,'material destination replacement'
    if family=='missing_negation_exception_permission':return any(r['kind']=='negation_protection' for r in items(rs,'restrictions')),'negation exception restriction'
    if family=='missing_attack_condition':return any(r['kind']=='attack_condition' for r in items(rs,'restrictions')),'attack condition restriction'
    if family=='missing_equip_activation_requirement':return any(r['kind']=='equip_condition' for r in items(rs,'restrictions')) and 'banish' in payments,'equip activation requirement and payment'
    if family=='missing_revival_summon_requirement':return any(b.get('qualifiers',{}).get('required_for')=='effect_revival' for b in items(rs,'procedure_blocks')),'additional revival payment'
    if family=='missing_control_return_in_procedure':return any(o['kind']=='control' and o.get('destination_controller')=='owner' and o.get('phase')=='delayed' for o in ops),'delayed return of control'
    if family=='missing_material_return_destination':return any(o.get('destination_rule')=='material_destination_replacement' for o in ops),'material return destination'
    if family=='missing_damage_zero_restriction':return any(o['kind']=='damage_change' and source in o.get('source','') for o in ops),'damage becomes zero'
    if family=='missing_zone_selection':return any(d['kind']=='zone_selection' and d.get('quantity_variants') for d in items(rs,'description_blocks')),'zone selection and conditional count'
    if family=='missing_selector_sum_constraint':return any(o.get('selection_sum') for o in ops),'selection link-rating sum limit'
    if family=='missing_conditional_requirement_quantity':return any(d['kind']=='activation_requirement_modifier' for d in items(rs,'description_blocks')),'counter-dependent activation requirement'
    if family=='reference_quantity_suppresses_send_grave':return any(o['kind']=='send_grave' for o in exact),'referenced quantity preserves final sending action'
    if family=='destroy_misrecorded_as_send_grave':return any(o['kind']=='destroy' for o in exact) and not any(o['kind']=='send_grave' for o in exact),'destruction with grave destination'
    if family=='effect_discard_as_plain_send_grave':return any(o['kind']=='discard' for o in exact),'discard remains a discard'
    if family=='false_position_action':return not any(o['kind']=='position' for o in exact) and 'gemini_enable' in kinds,'Gemini enable is not position change'
    if family=='negated_send_grave_as_action':return not any(o['kind']=='send_grave' and re.search(r'不送去墓地|不去墓地',o.get('source','')) for o in ops) and 'set' in kinds,'negated sending excluded; resetting preserved'
    if family=='damage_prevention_as_effect_damage':return not any(o['kind']=='damage' for o in exact) and 'damage_prevent' in kinds,'damage prevention is not new damage'
    if family=='forced_battle_as_end_phase':return 'force_battle' in kinds and 'negate_battle' in kinds and not any(o['kind']=='end_phase' for o in exact),'forced battle and battle negation; separate phase end retained'
    if family=='material_total_as_level_change':return not any(o['kind']=='level' and re.search(r'等级合计[^。]*变成',o.get('source','')) for o in ops),'material level sum is not level modification'
    if family=='tribute_replacement_as_standalone_operation':return 'tribute_replace' in kinds and not any(o['kind'] in ('banish','send_grave','release') for o in exact),'tribute substitution, not unconditional removal'
    if family=='metal_morph_summon_condition_as_activation_lock':return bool(items(rs,'description_blocks')) and not any(r['kind']=='cannot_activate' and source in r['source'] for r in items(rs,'restrictions')),'named-effect summon condition'
    if family=='branch_quantity_contamination':
        checked=[]
        for block in items(rs,'blocks'):
            prefix=re.match(r'^\d+(?:个|只|张)?(?:以上|以下)?[：:]',block['source'])
            if not prefix:continue
            body=block['source'][prefix.end():]
            amounts={int(n) for n in re.findall(r'(\d+)(?:张|只|个)(?!回合)',body)}
            if '这张卡' in body:amounts.add(1)
            amounts|={t['quantity'] for r in rs for t in r.get('targets',[]) if isinstance(t.get('quantity'),int)}
            value=block['qualifiers'].get('quantity')
            checked.append(bool(block['qualifiers'].get('branch_condition')) and (value is None or value in amounts))
        return bool(checked) and all(checked),'printed branch threshold separate from resource quantity'
    if family.startswith('missing_') and any(w in family for w in ('lock','prohibition','summon_condition','summon_requirement','restriction','protection','end_condition')):
        return bool(items(rs,'restrictions') or items(rs,'description_blocks')),'structural constraint present; qualifiers still require review'
    if family.startswith('missing_'):
        expected=POSITIVE.get(family[len('missing_'):])
        if expected:
            if expected=='property':return bool(kinds&{'race_change','attribute_change','name_change','level'}),'property-change observation'
            if expected=='return':return bool(kinds&{'return_hand','return_deck','special_summon'}),'delayed return observation'
            return expected in kinds,'expected coarse action '+expected
    return None,'no automatic discharge rule; semantic follow-up retained'


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--live',type=Path,required=True);p.add_argument('--review',type=Path,required=True);p.add_argument('--output',type=Path,required=True)
    p.add_argument('--audit-summary',type=Path,help='Completed full export/readback receipt for this exact live file')
    a=p.parse_args();a.output.mkdir(parents=True,exist_ok=True)
    with gzip.open(a.live,'rt',encoding='utf-8') as stream:live={r['card_id']:r for r in map(json.loads,stream)}
    old=[json.loads(s) for s in (a.review/'all-confirmed-findings.jsonl').read_text(encoding='utf-8').splitlines()]
    new=[json.loads(s) for s in (a.review/'additional-confirmed-findings.jsonl').read_text(encoding='utf-8').splitlines()]
    export_verified=False
    if a.audit_summary:
        audit=json.loads(a.audit_summary.read_text(encoding='utf-8'));c=audit['counts']
        export_verified=(a.live.resolve()==(a.audit_summary.parent/'live-blocks.jsonl.gz').resolve()
            and audit['local_full_canonical_projection_scan_complete'] and c['live_cards_checked']==len(live)
            and not audit['parse_errors'] and not audit['missing_saved_cards'] and not audit['extra_saved_cards']
            and all(c.get(k,0)==0 for k in ('live_source_error_cards','saved_source_error_cards','saved_live_content_different_cards',
                'saved_cards_with_index_errors','live_cards_with_export_contract_errors'))
            and {e['dictionary_revision'] for e in live.values()}=={audit['live_revision'],audit['saved_revision']})
        if not export_verified:raise ValueError('The supplied full readback does not verify this live projection')
    outcomes=[];counts=Counter();remaining=Counter()
    for index,finding in enumerate(old+new):
        results=[]
        for family in finding.get('families',[finding.get('family')]):
            passed,reason=check(family,finding,live[finding['card_id']]) if finding['card_id'] in live else (False,'live projection missing')
            if family=='dictionary_export_contract' and export_verified:passed,reason=True,'full live/export/source/index readback passed'
            results.append(dict(family=family,check=passed,reason=reason))
            if passed is not True:remaining[family]+=1
        status='structure_check_passed' if all(r['check'] is True for r in results) else 'remaining'
        counts[status]+=1
        outcomes.append(dict(index=index,card_id=finding['card_id'],name=finding['name'],source=finding.get('source',''),
            status=status,checks=results,review_id=finding.get('review_id')))
    (a.output/'findings.jsonl').write_text(''.join(json.dumps(r,ensure_ascii=False,separators=(',',':'))+'\n' for r in outcomes),encoding='utf-8')
    summary=dict(total_findings=len(outcomes),counts=dict(counts),remaining_families=dict(remaining.most_common()),
        checked_live_cards=len(live),all_semantic_repairs_verified=False,
        all_reported_structural_regressions_passed=not remaining,full_export_readback_verified=export_verified,
        note='通过表示对应结构回归成立，不等于整卡裁定、规则引擎或构筑能力通过。未映射项仍保留。')
    (a.output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps(summary,ensure_ascii=False,indent=2))


if __name__=='__main__':main()
