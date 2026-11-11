"""Join every reviewed card with literal findings and the remaining questions."""
from pathlib import Path
import argparse
from collections import Counter,defaultdict
import csv,gzip,json,re

STATUS_LABELS={
    'confirmed_problem':'确认有问题','specific_semantic_questions_remain':'待复核',
    'no_coarse_discrepancy_found_in_this_review':'本轮未发现粗功能差异',
    'source_metadata_only':'仅资料条目','missing_current_cdb_entry':'本地快照缺卡',
    'normal_monster_description_no_effect':'通常怪兽说明，无效果',
    'token_record_checked_not_independent_effect_owner':'衍生物资料已核对',
    'equal_all_comparable_fields':'可比字段相同','different_snapshot_or_mapping':'来源快照或映射有差异',
    'missing_local_id':'本地快照缺卡','source_metadata_only_no_usable_password':'无可用密码或基本数据',
}
FAMILY_LABELS={
    'printed_activation_payment_not_structured':'发动费用漏记或原文被截断',
    'created_token_misrecorded_as_existing_field_resource':'生成衍生物误记为调用场上怪兽',
    'token_source_without_creation':'衍生物限制句误记为生成衍生物',
    'noun_or_trigger_reference_as_processing':'对象或诱发前提误记为效果处理',
    'missing_common_option_payment':'共同发动费用漏记','missing_summon_negation':'召唤无效漏记',
    'activation_head_as_processing':'发动费用或前提混入效果处理',
    'summon_negation_or_event_as_special_summon':'召唤无效或时点误记为特召',
    'damage_timing_as_damage_amount_change':'伤害步骤内的其他处理误记为伤害变更',
    'face_up_adjective_as_reveal':'表侧状态误记为翻开卡片',
    'processing_order_as_deck_order_change':'处理顺序误记为调整卡组顺序',
    'printed_victory_condition_not_in_coarse_view':'特殊胜利条件漏记',
    'rule_name_alias_wrongly_excluded_from_dictionary':'规则同名卡被离线词典漏收',
    'missing_prelude_self_destruction':'前言中的定时自毁漏记',
    'existing_counter_count_as_counter_placement':'已有指示物数量误记为放置指示物',
    'missing_prelude_activation_permission':'从手牌或盖放当回合发动的权限漏记',
    'position_event_as_position_change':'表示形式变更的时点误记为变更表示',
    'stat_formula_as_level_change':'攻守计算公式误记为等级变更',
    'missing_extra_in_shared_origin':'卡组及额外卡组并列来源漏记额外卡组',
    'negated_selector_suppresses_positive_processing':'不能通常召唤的筛选条件误压掉检索或特召',
    'summon_procedure_as_effect':'特召手续错归效果','normal_pendulum_scope':'P效果错归怪兽效果',
    'material_level_reference_as_substitution':'素材等级引用误记为素材等级代用',
    'summoned_token_reference_as_creation':'已特召衍生物的引用误记为生成衍生物',
    'counter_eligible_card_selector_as_counter_placement':'可放置指示物的对象误记为放置指示物',
    'opponent_payment_event_as_payment':'对方支付LP的事件误记为支付LP效果',
    'dictionary_export_contract':'词典导出记录缺标签和编号',
    'cost_from_trigger_description':'其他卡支付费用的诱发前提误记为本卡费用',
    'destroyed_monster_reference_as_destroy_effect':'被战破怪兽的引用误记为破坏效果',
}
NOTE_LABELS={'optional_identity_tag_refinement':'细身份标签待完善，原始卡种仍保留',
             'empty_pendulum_section':'原文没有P效果，不计漏效',
             'actual_attach_instruction':'原文确实补充超量素材，已排除引用误报'}

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--evidence',type=Path,required=True)
p.add_argument('--baseline',type=Path,required=True)
p.add_argument('--baige',type=Path,required=True)
p.add_argument('--semantic',type=Path,required=True)
p.add_argument('--output',type=Path,required=True)
args=p.parse_args()
ROOT=args.evidence
OLD=args.baseline
SOURCE=args.baige
SEMANTIC=args.semantic
OUTPUT=args.output
OUTPUT.mkdir(exist_ok=False)
raw=json.loads(SOURCE.read_text(encoding='utf-8'))
cards={v['id']:v for v in raw.values() if v['id']>0}
entries={}
with gzip.open(OLD/'live-blocks.jsonl.gz','rt',encoding='utf-8') as stream:
    for line in stream:
        entry=json.loads(line);entries[entry['card_id']]=entry
for line in (ROOT/'rule-name-alias-live.jsonl').read_text(encoding='utf-8').splitlines():
    entry=json.loads(line);entries[entry['card_id']]=entry
alias_rows=json.loads((ROOT/'rule-name-alias-review.json').read_text(encoding='utf-8'))
aliases={r['card_id']:r for r in alias_rows}
source_results={}
for line in (OLD/'baige-comparison-final/baige-cards.jsonl').read_text(encoding='utf-8').splitlines():
    row=json.loads(line);source_results[row['cid']]=row
findings=defaultdict(list)
refinements=defaultdict(list)
for line in (OLD/'candidates-final.jsonl').read_text(encoding='utf-8').splitlines():
    item=json.loads(line);code=item['card_id']
    if item['family']=='missing_identity_subtype':
        refinements[code].append(dict(family='optional_identity_tag_refinement',detail=item['detail'],
                                     judgement='original type bits retained; absent fine label alone is not a card-data error'))
        continue
    if item['family']=='normal_pendulum_scope' and not cards.get(code,{}).get('text',{}).get('pdesc',''):
        refinements[code].append(dict(family='empty_pendulum_section',judgement='no printed P effect; not a missing function'))
        continue
    item['basis']='verified narrow literal mismatch; no card-pool sampling'
    findings[code].append(item)
reviewed_modifiers=defaultdict(list)
for item in json.loads((ROOT/'confirmed-additional-reference-errors.json').read_text(encoding='utf-8')):
    # These three sources really do instruct attaching a card. The noun regex
    # hit the explanatory parentheses; it was a checker error, not a card error.
    if item['family']=='noun_or_trigger_reference_as_processing' and item['card_id'] in {71166481,72859417,96637156}:
        refinements[item['card_id']].append(dict(family='actual_attach_instruction',source=item['source'],judgement='valid broad attach function; initial reference candidate rejected'))
        continue
    # These change an earlier search's quantity/selector/source. At the coarse
    # level another search block can encode that option; do not assert an
    # additional search action without checking the consumer's option binding.
    if item['family']=='noun_or_trigger_reference_as_processing' and item['card_id'] in {39392286,48589580,51869363,91188343,99398682}:
        reviewed_modifiers[item['card_id']].append(dict(card_id=item['card_id'],name=item['name'],scope='same_effect',source=item['source'],actual=[dict(kind=item['actual_kind'])],unresolved_atoms=[],reason='search modifier versus additional action needs consumer option-binding review'))
        continue
    findings[item['card_id']].append(item)
for code,row in aliases.items():
    findings[code].append(dict(card_id=code,name=row['name'],family='rule_name_alias_wrongly_excluded_from_dictionary',
        source=cards[code]['text']['desc'],alias=row['alias'],different_card_text=not row['same_card_text'],
        basis='all 526 non-token aliases compared: 507 exact duplicates; these 19 have distinct printed data'))

totals=Counter();family_counts=Counter();family_ids=defaultdict(set);pending_kinds=Counter()
samples={};statuses={};pending_examples=[]
with SEMANTIC.open(encoding='utf-8') as stream, (OUTPUT/'per-card-review.jsonl').open('w',encoding='utf-8') as per_card, \
        (OUTPUT/'confirmed-findings.jsonl').open('w',encoding='utf-8') as confirmed_out, \
        (OUTPUT/'pending-findings.jsonl').open('w',encoding='utf-8') as pending_out, \
        (OUTPUT/'per-card-review.csv').open('w',encoding='utf-8-sig',newline='') as table:
    writer=csv.writer(table)
    writer.writerow(['CID','卡号','卡名','原始卡库比对','积木核对结论','确认问题处数','待复核句数','确认问题类别','备注'])
    for line in stream:
        card=json.loads(line);code=card['card_id'];cid=card['cid'];pending=list(reviewed_modifiers.get(code,[]))
        source=source_results[cid]
        new_costs={}
        for group in card['groups']:
            for clause in group['clauses']:
                text=clause['source'];unresolved=[]
                for atom in clause['atoms']:
                    if not atom['state'].startswith('pending'):continue
                    kind,role=atom['kind'],atom['role']
                    if kind=='release' and '被解放' in text:continue
                    if kind in {'destroy','send_grave','release'} and re.search(r'被[^。]{0,30}(?:破坏|送去墓地|解放)[^。]{0,40}(?:回合|阶段|发动)',text):continue
                    if role=='cost' and kind in {'reveal','pay_lp','banish','remove_counter','return_hand','return_deck','discard','send_grave','release','detach'} and re.search(r'(?:才能|可以|则能|即可)发动',text):
                        # A complete generic/composite payment still records
                        # the cost link. Missing its fine label alone is not a
                        # confirmed coarse-granularity failure.
                        payments=[a for a in clause['actual'] if a['section'] in {'cost_blocks','record_costs'}]
                        if any(atom['phrase'] in a.get('source','') for a in payments):
                            unresolved.append(atom)
                            continue
                        key=(group['scope'],text)
                        item=new_costs.setdefault(key,dict(card_id=code,name=card['name'],scope=group['scope'],family='printed_activation_payment_not_structured',source=text,expected_payment_kinds=[],actual=clause['actual'],basis='explicit printed activation payment absent or only generic/truncated payment in current records'))
                        if kind not in item['expected_payment_kinds']:item['expected_payment_kinds'].append(kind)
                        continue
                    if kind in {'add_hand','special_summon'} and role=='effect' and '不能通常召唤的' in text and not re.search(r'不能(?:把|将|从)|不能特殊召唤$',text):
                        findings[code].append(dict(card_id=code,name=card['name'],scope=group['scope'],family='negated_selector_suppresses_positive_processing',source=text,expected_kind=kind,actual=clause['actual'],basis='cannot Normal Summon describes the selectable monster, not a ban on the printed search/summon'))
                        continue
                    if kind=='win' and role=='effect' and code in entries and not any(b['kind']=='win' for e in entries[code]['effects'] for b in e['blocks']):
                        findings[code].append(dict(card_id=code,name=card['name'],scope=group['scope'],family='printed_victory_condition_not_in_coarse_view',source=text,actual=clause['actual'],basis='literal victory sentence is present in Baige and the CDB but absent from the coarse view'))
                        continue
                    unresolved.append(atom)
                if clause['state'].startswith('pending') or unresolved:
                    pending.append(dict(card_id=code,name=card['name'],scope=group['scope'],source=text,unresolved_atoms=unresolved,actual=clause['actual'],reason='exact sentence retained; vocabulary/context or scope needs further interpretation'))
                    for atom in unresolved:pending_kinds[atom['kind']+':'+atom['role']]+=1
        findings[code].extend(new_costs.values())
        unique={json.dumps({k:v for k,v in f.items() if k not in {'basis','confirmed_basis'}},ensure_ascii=False,sort_keys=True):f for f in findings.get(code,[])}
        current=list(unique.values())
        if card['status']=='source_metadata_only':status='source_metadata_only'
        elif card['status']=='missing_runtime_card_entry':status='missing_current_cdb_entry'
        elif current:status='confirmed_problem'
        elif pending:status='specific_semantic_questions_remain'
        else:status='no_coarse_discrepancy_found_in_this_review'
        statuses[code]=status
        totals['cards_'+status]+=1
        totals['confirmed_findings']+=len(current)
        totals['pending_clauses']+=len(pending)
        if current and pending:totals['confirmed_problem_cards_also_with_pending_clauses']+=1
        if source['differences']:totals['source_cards_with_field_differences']+=1
        result=dict(cid=cid,card_id=code,name=card['name'],source_comparison=source,status=status,
                    confirmed_findings=current,pending_clauses=pending,granularity_notes=refinements.get(code,[]),
                    review_method='all-local source clauses, runtime blocks/shared costs and literal contradiction checks; not sampled',
                    full_detailed_rule_interpretation_certified=False)
        per_card.write(json.dumps(result,ensure_ascii=False,separators=(',',':'))+'\n')
        for f in current:
            family_counts[f['family']]+=1;family_ids[f['family']].add(code)
            confirmed_out.write(json.dumps(f,ensure_ascii=False,separators=(',',':'))+'\n')
        for f in pending:pending_out.write(json.dumps(f,ensure_ascii=False,separators=(',',':'))+'\n')
        if pending and not current:pending_examples.append(dict(card_id=code,name=card['name'],scope=pending[0]['scope'],source=pending[0]['source']))
        writer.writerow([cid,code,card['name'],STATUS_LABELS[source['status']],STATUS_LABELS[status],len(current),len(pending),
                         '；'.join(sorted({FAMILY_LABELS[f['family']] for f in current})),
                         '；'.join(sorted({NOTE_LABELS[n['family']] for n in refinements.get(code,[])}))])
        if code in {89631139,55144522,14558127,23434538,94886282,77414722,99789342,70791313,9126351,33420078,20001443,56832966,94212438,40605147,3294539}:
            samples[str(code)]=dict(name=card['name'],status=status,confirmed_families=sorted({f['family'] for f in current}),pending_clauses=len(pending))
summary=dict(source_rows=len(raw),totals=dict(totals),confirmed_by_family={k:dict(occurrences=n,cards=len(family_ids[k])) for k,n in family_counts.items()},
             pending_predicate_kinds=dict(pending_kinds),positive_and_negative_controls=samples,
             original_data_dispositions=dict(no_password_or_basic_data=44,source_present_but_missing_from_current_cdb=82,rule_name_aliases_excluded_from_saved_dictionary=19,normal_pendulum_with_real_P_effects_wrongly_scoped=33,empty_P_sections_not_counted_as_missing_effects=5,optional_subtype_tags_not_counted_as_data_corruption=489),
             source_cdb_modified=False,runtime_code_modified=False,training_run=False,native_engine_run=False,ci_run=False,
             all_source_rows_have_individual_outcome=sum(v for k,v in totals.items() if k.startswith('cards_'))==len(raw),
             all_cards_certified_semantically_correct=False)
(OUTPUT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
(OUTPUT/'pending-card-examples.json').write_text(json.dumps(pending_examples,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')

# Complete the project side too: independent cards absent from Baige, all
# alternate-art rows and all Token rows still receive an explicit disposition.
local_only={
    20240828:dict(card_id=20240828,name='德科平',status='normal_monster_description_no_effect',
                  source_basis='bound CDB only; no matching Baige password',confirmed_findings=[],pending_clauses=[]),
    68811206:dict(card_id=68811206,name='伟大的战士 泰勒',status='confirmed_problem',
                  source_basis='bound CDB only; no matching Baige password',
                  confirmed_findings=[dict(card_id=68811206,name='伟大的战士 泰勒',family='destroyed_monster_reference_as_destroy_effect',
                      source='给与对方等于被破坏怪兽的攻击力数值的伤害',actual_kind='destroy',
                      basis='被破坏怪兽 is the damage formula reference; this instruction inflicts damage and does not destroy another monster')],pending_clauses=[]),
}
for code,review in local_only.items():
    entry=entries[code]
    review['source_text']=[r['source_text'] for r in entry['source_records']]
    review['actual_functions']=[dict(kind=b['kind'],source=b.get('source','')) for e in entry['effects'] for b in e['blocks']]
(OUTPUT/'current-only-card-review.json').write_text(json.dumps(list(local_only.values()),ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
(OUTPUT/'all-confirmed-findings.jsonl').write_text((OUTPUT/'confirmed-findings.jsonl').read_text(encoding='utf-8')+
    ''.join(json.dumps(f,ensure_ascii=False,separators=(',',':'))+'\n' for r in local_only.values() for f in r['confirmed_findings']),encoding='utf-8')
reviewed={r['card_id']:r for r in (json.loads(line) for line in (OUTPUT/'per-card-review.jsonl').read_text(encoding='utf-8').splitlines()) if r['card_id']>0}
raw_rows=[json.loads(line) for line in (OLD/'cards-final.jsonl').read_text(encoding='utf-8').splitlines()]
raw_by_id={r['card_id']:r for r in raw_rows}
alias_identity={r['card_id']:r for r in json.loads((ROOT/'all-alias-identity-review.json').read_text(encoding='utf-8'))}
project_counts=Counter(); project_distinct_counts=Counter()
with (OUTPUT/'per-project-card-review.jsonl').open('w',encoding='utf-8') as project_out, \
        (OUTPUT/'per-project-card-review.csv').open('w',encoding='utf-8-sig',newline='') as project_table:
    project_writer=csv.writer(project_table)
    project_writer.writerow(['卡号','卡名','记录类型','对应卡号','原始行已核对','积木核对结论','确认问题处数','待复核句数','确认问题类别','外部来源比对'])
    for raw_row in raw_rows:
        code=raw_row['card_id'];kind='independent_card';subject=code
        if raw_row['raw_information']['type']&0x4000:
            kind='token';status='token_record_checked_not_independent_effect_owner';review={}
        elif code in alias_identity and not alias_identity[code]['different_fields']:
            kind='identical_alternate_art';subject=alias_identity[code]['alias'];review=reviewed.get(subject,local_only.get(subject))
            assert review is not None,(code,subject)
            status=review['status']
        else:
            review=reviewed.get(code,local_only.get(code));assert review is not None,code
            status=review['status'];project_distinct_counts[status]+=1
        project_counts[kind]+=1
        result=dict(card_id=code,name=raw_row['name'],record_kind=kind,semantic_subject=subject,
                    original_fields=raw_row,status=status,confirmed_findings=review.get('confirmed_findings',[]),
                    pending_clauses=review.get('pending_clauses',[]),
                    basis='every local row visited; alternate-art equivalence checked by all printed fields; Tokens checked as card records')
        project_out.write(json.dumps(result,ensure_ascii=False,separators=(',',':'))+'\n')
        project_writer.writerow([code,raw_row['name'],{'independent_card':'独立卡','identical_alternate_art':'相同卡文别图','token':'衍生物'}[kind],subject,
                                  '是' if raw_row['source_row_checked'] else '否',STATUS_LABELS[status],len(result['confirmed_findings']),len(result['pending_clauses']),
                                  '；'.join(sorted({FAMILY_LABELS[f['family']] for f in result['confirmed_findings']})),
                                  STATUS_LABELS[review['source_comparison']['status']] if 'source_comparison' in review else '未匹配百鸽密码；两份CDB原始字段一致'])
summary['project_review']=dict(total_rows=len(raw_rows),row_kinds=dict(project_counts),independent_card_outcomes=dict(project_distinct_counts),
    all_rows_have_individual_outcome=sum(project_counts.values())==len(raw_rows),
    local_only_cards=2,local_only_confirmed_problem_cards=1,local_only_confirmed_findings=1,
    all_local_independent_cards_semantically_certified=False)
summary['project_review']['confirmed_findings']=totals['confirmed_findings']+1
summary['project_review']['confirmed_problem_cards']=project_distinct_counts['confirmed_problem']
summary['project_review']['cards_with_pending_clauses']=totals['cards_specific_semantic_questions_remain']+totals['confirmed_problem_cards_also_with_pending_clauses']
(OUTPUT/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
print(json.dumps(summary,ensure_ascii=False,indent=2))
