"""Read every local CDB row and audit saved/live coarse effect projections.

Writes a per-card ledger and review candidates. It does not certify semantic
correctness, change the source databases, load models, or run the duel engine.
"""
import argparse
from collections import Counter
from contextlib import closing
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path
import re
import sqlite3
import sys
import time
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from ygo_kito.build_contracts import digest
from ygo_kito.effect_blocks import BLOCK_REVISION, LABELS
from ygo_kito.effect_mechanisms import MechanismCatalog


def open_readonly(path):
    db = sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)
    db.row_factory = sqlite3.Row
    db.execute('pragma query_only=on')
    return db


def emit(stream, value):
    stream.write(json.dumps(value, ensure_ascii=False, separators=(',', ':')) + '\n')


def labels(entry, key='blocks'):
    return sorted({b['kind'] for e in entry['effects'] for b in e[key]})


def expected_indexes(entry):
    code = entry['card_id']
    tags = [(code, t['dimension'], t['value'], '', '') for t in entry['identity_tags']]
    connectors = []
    for effect in entry['effects']:
        key = effect['effect_key']
        for section in ('blocks', 'cost_blocks', 'procedure_blocks', 'restrictions', 'description_blocks'):
            for block in effect[section]:
                tags.append((code, block['tag']['dimension'], block['tag']['value'], key, block['block_id']))
        connectors.extend((code, key, c['kind']) for c in effect['connectors'])
    tags.extend((code, t['tag']['dimension'], t['tag']['value'], t['effect_key'], 'compatibility')
                for t in entry['compatibility_tags'])
    return Counter(tags), Counter(connectors)


def source_errors(entry, row):
    errors = []
    if entry['card_id'] != row['id'] or entry['name'] != row['name']:
        errors.append('card_identity')
    if entry['text_sha256'] != digest(row['desc'] or ''):
        errors.append('card_text_binding')
    records = {r['effect_key']: r for r in entry['source_records']}
    for effect in entry['effects']:
        key = effect['effect_key']
        record = records.get(key)
        if record is None:
            errors.append(key + ':missing_source_record')
            continue
        text = record['source_text']
        if text not in (row['desc'] or ''):
            errors.append(key + ':source_text')
        if record['card_id'] != row['id'] or record['text_sha256'] != entry['text_sha256']:
            errors.append(key + ':record_binding')
        for section in ('blocks', 'cost_blocks', 'procedure_blocks', 'restrictions', 'description_blocks'):
            for block in effect[section]:
                source = block.get('source', '')
                block_id = block.get('block_id', key + ':' + section)
                # Shared restrictions can quote the card prelude. Their source
                # is the full card, rather than just this numbered effect.
                reference_text = (row['desc'] or '') if section == 'restrictions' else text
                if source and source not in reference_text:
                    errors.append(block_id + ':source_quote')
                if 'source_span' in block:
                    start, stop = block['source_span']
                    if text[start:stop] != source:
                        errors.append(block_id + ':source_span')
                if section == 'cost_blocks' and block['phase'] not in ('activation_payment', 'attack_payment', 'upkeep_payment', 'summon_payment', 'alternative_activation_payment', 'conditional_activation_payment'):
                    errors.append(block_id + ':payment_phase')
                if section == 'blocks' and block['kind'] not in LABELS:
                    errors.append(block_id + ':unknown_function')
    return errors


def review_candidates(entry, row):
    """Narrow text contradictions and explicit projection gaps, not an oracle."""
    result = []

    def add(family, source, effect_key=None, detail=None):
        result.append(dict(family=family, effect_key=effect_key, source=source, detail=detail))

    tagset = {(t['dimension'], t['value']) for t in entry['identity_tags']}
    for flag, name in ((0x200, '灵魂'), (0x400, '同盟'), (0x800, '二重'),
                       (0x400000, '卡通'), (0x2000000, '特殊召唤')):
        if row['type'] & flag and ('card_type', name) not in tagset:
            add('missing_identity_subtype', hex(flag), detail=name)

    all_kinds = set(labels(entry))
    if (row['type'] & 0x1000000 and '【怪兽描述】' in (row['desc'] or '')
            and not any(e['scope'] == 'pendulum' for e in entry['effects'])):
        add('normal_pendulum_scope', '【怪兽描述】', detail='P section has no pendulum-scoped record')
    sections = (row['desc'] or '').split('【怪兽效果】')
    for section in sections:
        prelude = re.split(r'[①②③④⑤⑥⑦⑧⑨⑩][：:]', section, maxsplit=1)[0]
        for pattern, kind, family in (
            (r'[^。\r\n]*(?:从手卡也能用|从手卡发动|在盖放的回合也能发动|在盖放的回合发动)[^。\r\n]*',
             'activation_permission', 'missing_prelude_activation_permission'),
            (r'[^。\r\n]*第\d+次的自己准备阶段破坏', 'destroy', 'missing_prelude_self_destruction'),
        ):
            if kind not in all_kinds:
                for match in re.finditer(pattern, prelude):
                    if kind=='activation_permission' and re.search(r'不能|无法|不可',match[0]):continue
                    add(family, match[0])

    for effect, record in zip(entry['effects'], entry['source_records']):
        text, key = record['source_text'], effect['effect_key']
        kinds = {b['kind'] for b in effect['blocks']}
        for payment in effect['cost_blocks']:
            if re.search(r'被送去墓地$|被丢弃$', payment['source']):
                add('cost_from_trigger_description', payment['source'], key)
        if re.match(r'(?:可以)?(?:支付\d+(?:基本分|LP)|把(?:基本分|LP)支付一半)把以下效果发动', text):
            if not effect['cost_blocks']:
                add('missing_common_option_payment', text.split('。', 1)[0], key)
        if (re.search(r'那(?:次特殊召唤|次召唤|个)无效', text)
                and '之际' in text and not kinds & {'negate_summon', 'summon_negation'}):
            add('missing_summon_negation', text, key)
        if (re.search(r'这张卡可以把[^。]+丢弃[，,]从手卡[·、]墓地特殊召唤', text)
                and not effect['procedure_blocks']):
            add('summon_procedure_as_effect', text, key)
        for block in effect['blocks']:
            source, kind = block['source'], block['kind']
            if (re.search(r'(?:才能|可以)发动$', source)
                    and kind in {'discard', 'detach', 'send_grave', 'banish', 'release', 'special_summon', 'pay_lp'}):
                add('activation_head_as_processing', source, key)
            if kind == 'position' and re.search(r'(?:变成|成为|变更)(?:里侧|表侧)?(?:攻击|守备)表示(?:时|的场合)$', source):
                add('position_event_as_position_change', source, key)
            if (kind == 'face_up' and '全部表侧表示怪兽' in source
                    and not re.search(r'变成|翻开|确认|变回', source)):
                add('face_up_adjective_as_reveal', source, key)
            if kind == 'material_level' and re.search(r'得到.+作为融合素材的怪兽的原本等级的以下效果', source):
                add('material_level_reference_as_substitution', source, key)
            if kind == 'lp_payment' and source.startswith('每次') and '失去' in source:
                add('opponent_payment_event_as_payment', source, key)
            if kind == 'token' and re.search(r'只要.*这个效果特殊召唤的衍生物.*存在', source):
                add('summoned_token_reference_as_creation', source, key)
            if kind == 'special_summon' and re.search(r'特殊召唤无效|特殊召唤之际', source):
                add('summon_negation_or_event_as_special_summon', source, key)
            if kind == 'level' and re.fullmatch(
                    r'这张卡的攻击力(?:[·・]守备力)?变成这张卡的等级[×x]\d+', source):
                add('stat_formula_as_level_change', source, key)
            if re.search(r'从(?:自己|对方|双方)?(?:的)?卡组[·、]额外卡组', source):
                if 'extra' not in block['qualifiers'].get('from_zones', []):
                    add('missing_extra_in_shared_origin', source, key, block['qualifiers'])
            if kind == 'token' and not re.search(r'特殊召唤|(?:生成|召唤)[^。]*衍生物|衍生物[^。]*(?:生成|特殊召唤)', source):
                add('token_source_without_creation', source, key)
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--assets', type=Path, required=True)
    parser.add_argument('--dictionary', type=Path, required=True)
    parser.add_argument('--mirror', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    started = time.perf_counter()
    cdb = args.assets / 'engine-src/database/locales/zh-CN/cards.cdb'
    receipt = json.loads((args.assets / 'engine-build/receipt.json').read_text(encoding='utf-8'))
    with cdb.open('rb') as stream:
        source_sha = hashlib.file_digest(stream, 'sha256').hexdigest()
    if source_sha != receipt['resources']['cards']:
        raise ValueError('CDB differs from its resource receipt')
    with closing(open_readonly(cdb)) as db, closing(open_readonly(args.mirror)) as mirror:
        source_integrity = db.execute('pragma quick_check').fetchone()[0]
        rows = {r['id']: dict(r) for r in db.execute('select d.*,t.name,t.desc from datas d join texts t on d.id=t.id')}
        orphans = dict(
            datas_without_text=db.execute('select count(*) from datas left join texts using(id) where texts.id is null').fetchone()[0],
            texts_without_datas=db.execute('select count(*) from texts left join datas using(id) where datas.id is null').fetchone()[0])
        table_counts = {table: db.execute('select count(*) from ' + table).fetchone()[0] for table in ('datas', 'texts')}
        raw_field_errors = {}
        numeric_columns = ('id', 'ot', 'alias', 'setcode', 'type', 'atk', 'def', 'level', 'race', 'attribute', 'category')
        for code, row in rows.items():
            invalid = [column for column in numeric_columns if type(row[column]) is not int]
            invalid += [column for column in ('name', 'desc') if not isinstance(row[column], str)]
            if invalid:
                raw_field_errors[code] = invalid
        mirror_differences = {}
        mirror_extra = {}
        for table in ('datas', 'texts'):
            original = {r['id']: dict(r) for r in db.execute('select * from ' + table)}
            copied = {r['id']: dict(r) for r in mirror.execute('select * from ' + table)}
            mirror_differences[table] = {code: [k for k, value in item.items() if copied.get(code, {}).get(k) != value]
                                         for code, item in original.items() if copied.get(code) != item}
            mirror_extra[table] = sorted(copied.keys() - original.keys())
    catalog = MechanismCatalog(SimpleNamespace(rows=rows, receipt=receipt))
    from ygo_kito.card_identity import canonical_card_id
    canonical = {c for c, r in rows.items() if canonical_card_id(rows,c)==c and not r['type'] & 0x4000 and r['name'].strip()}
    counts = Counter()
    functions = Counter()
    costs = Counter()
    procedures = Counter()
    statuses = Counter()
    issues = Counter()
    issue_cards = {}
    errors = []
    changed_sections = Counter()
    with closing(open_readonly(args.dictionary)) as saved, \
            (args.output / 'cards.jsonl').open('w', encoding='utf-8', newline='\n') as ledger, \
            (args.output / 'candidates.jsonl').open('w', encoding='utf-8', newline='\n') as candidates, \
            gzip.open(args.output / 'live-blocks.jsonl.gz', 'wt', encoding='utf-8', compresslevel=1) as snapshots:
        stored_manifest = json.loads(saved.execute("select value from metadata where key='manifest'").fetchone()[0])
        stored_integrity = saved.execute('pragma quick_check').fetchone()[0]
        stored_ids = {r[0] for r in saved.execute('select card_id from cards')}
        indexed_tags, indexed_connectors = {}, {}
        for record in saved.execute('select * from tags'):
            indexed_tags.setdefault(record['card_id'], Counter())[tuple(record)] += 1
        for record in saved.execute('select * from connectors'):
            indexed_connectors.setdefault(record['card_id'], Counter())[tuple(record)] += 1
        for code, row in sorted(rows.items()):
            item = dict(card_id=code, name=row['name'], source_row_checked=True,
                        mirror_field_differences={t: mirror_differences[t].get(code, []) for t in ('datas', 'texts')},
                        raw_information={k: row[k] for k in ('ot', 'alias', 'setcode', 'type', 'atk', 'def', 'level', 'race', 'attribute', 'category')})
            counts['source_rows_checked'] += 1
            if code not in canonical:
                item.update(projection_scope='excluded_by_existing_dictionary_scope',
                            exclusion_reasons=[s for s, yes in (('alias', row['alias'] != 0), ('token', bool(row['type'] & 0x4000)),
                                               ('unnamed', not row['name'].strip())) if yes])
                counts['excluded_rows'] += 1
                emit(ledger, item)
                continue
            try:
                entry = catalog.effect_blocks(code)
                emit(snapshots, entry)
                source_checks = source_errors(entry, row)
                counts['live_cards_checked'] += 1
                counts['live_source_error_cards'] += bool(source_checks)
                counts['live_effect_groups'] += len(entry['effects'])
                for effect in entry['effects']:
                    statuses[effect['status']] += 1
                    counts['live_groups_with_unknown_details'] += bool(effect['unknown'])
                    functions.update(b['tag']['value'] for b in effect['blocks'])
                    costs.update(b['tag']['value'] for b in effect['cost_blocks'])
                    procedures.update(b['tag']['value'] for b in effect['procedure_blocks'])
                found = saved.execute('select payload from cards where card_id=?', (code,)).fetchone()
                old = json.loads(found[0]) if found else None
                sections_changed = [k for k, v in entry.items() if k != 'dictionary_revision' and (old is None or old.get(k) != v)]
                changed_sections.update(sections_changed)
                counts['saved_live_content_different_cards'] += bool(sections_changed)
                old_errors = source_errors(old, row) if old else ['missing_saved_card']
                counts['saved_source_error_cards'] += bool(old_errors)
                index_errors = []
                if old:
                    expected_tags, expected_connectors = expected_indexes(old)
                    if expected_tags != indexed_tags.get(code, Counter()):
                        index_errors.append('tag_index')
                    if expected_connectors != indexed_connectors.get(code, Counter()):
                        index_errors.append('connector_index')
                counts['saved_cards_with_index_errors'] += bool(index_errors)
                export_errors = []
                for effect in entry['effects']:
                    for section in ('blocks', 'cost_blocks', 'procedure_blocks', 'restrictions', 'description_blocks'):
                        for block in effect[section]:
                            missing = sorted({'block_id', 'tag'} - block.keys())
                            if missing:
                                export_errors.append(dict(effect_key=effect['effect_key'], section=section, missing=missing))
                counts['live_cards_with_export_contract_errors'] += bool(export_errors)
                review = review_candidates(entry, row)
                review.extend(dict(family='dictionary_export_contract', effect_key=error['effect_key'],
                                   source='', detail=error) for error in export_errors)
                for finding in review:
                    issues[finding['family']] += 1
                    issue_cards.setdefault(finding['family'], set()).add(code)
                    emit(candidates, dict(card_id=code, name=row['name'], **finding))
                item.update(projection_scope='canonical', live_source_errors=source_checks,
                            saved_source_errors=old_errors, saved_live_changed_sections=sections_changed,
                            export_contract_errors=export_errors, saved_index_errors=index_errors,
                            effect_groups=len(entry['effects']), live_function_kinds=labels(entry),
                            live_cost_kinds=labels(entry, 'cost_blocks'), live_procedure_kinds=labels(entry, 'procedure_blocks'),
                            candidate_families=sorted({f['family'] for f in review}),
                            semantic_review='not_individually_certified')
            except Exception as error:
                item['exception'] = repr(error)
                errors.append(dict(card_id=code, name=row['name'], error=repr(error)))
            emit(ledger, item)
            catalog._profiles.clear()
            catalog._texts.clear()
            if counts['live_cards_checked'] % 2000 == 0:
                print(json.dumps(dict(checked=counts['live_cards_checked'], elapsed_seconds=round(time.perf_counter()-started, 1))), flush=True)
    summary = dict(
        audit_version=1, observed_at_utc=datetime.now(timezone.utc).isoformat(),
        source_cdb=str(cdb.resolve()), mirror_cdb=str(args.mirror.resolve()), saved_dictionary=str(args.dictionary.resolve()),
        database_commit=receipt['source_commits']['database'], cards_sha256=source_sha,
        live_revision=BLOCK_REVISION, saved_revision=stored_manifest['dictionary_revision'],
        source_integrity=source_integrity, saved_integrity=stored_integrity, source_table_counts=table_counts,
        source_orphans=orphans, source_raw_field_errors=raw_field_errors,
        saved_index_orphan_card_ids=sorted((indexed_tags.keys() | indexed_connectors.keys())-stored_ids),
        mirror_different_rows={k: len(v) for k, v in mirror_differences.items()},
        mirror_extra_ids=mirror_extra, canonical_cards=len(canonical),
        missing_saved_cards=sorted(canonical-stored_ids), extra_saved_cards=sorted(stored_ids-canonical),
        counts=dict(counts), live_group_statuses=dict(statuses), live_functions=dict(sorted(functions.items())),
        live_costs=dict(sorted(costs.items())), live_procedures=dict(sorted(procedures.items())),
        saved_live_changed_sections=dict(changed_sections),
        review_candidates={k: dict(occurrences=v, cards=len(issue_cards[k])) for k, v in issues.items()},
        parse_errors=errors, elapsed_seconds=round(time.perf_counter()-started, 2),
        loaded_runtime_modules=[m for m in ('torch', 'ygo_kito.native', 'ygo_kito.build_training') if m in sys.modules],
        full_semantic_review_complete=False, official_live_full_pool_verified=False,
        local_full_row_scan_complete=counts['source_rows_checked']==len(rows),
        local_full_canonical_projection_scan_complete=counts['live_cards_checked']==len(canonical) and not errors,
        training_started=False, cb_started=False, native_engine_started=False, ci_run=False,
        outputs=['cards.jsonl', 'candidates.jsonl', 'live-blocks.jsonl.gz'])
    (args.output/'summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2)+'\n', encoding='utf-8', newline='\n')
    print(json.dumps({k:v for k,v in summary.items() if k not in ('live_functions','live_costs','live_procedures')}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
