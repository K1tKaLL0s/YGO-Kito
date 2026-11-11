"""Compare a previously downloaded Baige bulk snapshot with the local CDB.

No requests, training, model loading, engine calls, or source-database writes.
"""
import argparse
from collections import Counter, defaultdict
from contextlib import closing
from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3


def normalized(text):
    # Normalize only line endings and leading/trailing whitespace per line.
    return '\n'.join(line.strip() for line in (text or '').splitlines()).strip()


def cdb_sections(row):
    desc = row['desc'] or ''
    if row['type'] & 0x1000000:
        marker = re.search(r'【怪兽(?:效果|描述)】', desc)
        if marker is None:
            return None, normalized(desc)
        pendulum, monster = desc[:marker.start()], desc[marker.end():]
        pendulum = re.sub(r'^\s*←\d+\s*【灵摆】\s*\d+→\s*', '', pendulum)
        pendulum = re.sub(r'^\s*【灵摆效果】\s*', '', pendulum)
        return normalized(pendulum), normalized(monster)
    return '', normalized(desc)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baige', type=Path, required=True)
    parser.add_argument('--cdb', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=False)
    cards = json.loads(args.baige.read_text(encoding='utf-8'))
    with closing(sqlite3.connect(args.cdb.resolve().as_uri()+'?mode=ro', uri=True)) as db:
        db.row_factory = sqlite3.Row
        rows = {r['id']: dict(r) for r in db.execute('select d.*,t.name,t.desc from datas d join texts t on d.id=t.id')}
    by_id = defaultdict(list)
    for cid, card in cards.items():
        by_id[card['id']].append((cid, card))
    counts, fields, populations = Counter(), Counter(), Counter()
    missing, differences, unique_canonical_ids = [], [], set()
    with (args.output/'baige-cards.jsonl').open('w', encoding='utf-8', newline='\n') as out:
        for cid, card in cards.items():
            code = card['id']
            result = dict(cid=int(cid), card_id=code, name=card.get('cn_name'), differences={})
            counts['baige_rows_checked'] += 1
            row = rows.get(code)
            if code == 0 or not card.get('data'):
                result['status'] = 'source_metadata_only_no_usable_password'
                counts['baige_metadata_only_no_usable_password'] += 1
            elif row is None:
                result['status'] = 'missing_local_id'
                counts['baige_missing_local_id'] += 1
                missing.append(dict(cid=int(cid), card_id=code, name=card.get('cn_name'), type=card.get('data',{}).get('type')))
            else:
                counts['matched_ids'] += 1
                if not row['alias'] and not row['type'] & 0x4000:
                    unique_canonical_ids.add(code)
                for field in ('ot','setcode','type','atk','def','level','race','attribute'):
                    if field not in card.get('data',{}):
                        result['differences'][field] = dict(status='absent_from_baige')
                    elif row[field] != card['data'][field]:
                        result['differences'][field] = dict(local=row[field], baige=card['data'][field])
                if row['name'] != card.get('cn_name'):
                    result['differences']['name'] = dict(local=row['name'], baige=card.get('cn_name'))
                pendulum, monster = cdb_sections(row)
                for field, local, published in (('pendulum_text', pendulum, normalized(card.get('text',{}).get('pdesc',''))),
                                                ('monster_or_spell_trap_text', monster, normalized(card.get('text',{}).get('desc','')))):
                    if local != published:
                        result['differences'][field] = dict(local=local, baige=published)
                fields.update(result['differences'].keys())
                if result['differences']:
                    counts['matched_with_differences'] += 1
                    differences.append(result)
                    result['status'] = 'different_snapshot_or_mapping'
                else:
                    counts['matched_equal_all_comparable_fields'] += 1
                    result['status'] = 'equal_all_comparable_fields'
            out.write(json.dumps(result,ensure_ascii=False,separators=(',',':'))+'\n')
    local_only = []
    with (args.output/'local-cards.jsonl').open('w',encoding='utf-8',newline='\n') as out:
        for code, row in sorted(rows.items()):
            group = 'alias' if row['alias'] else 'token' if row['type'] & 0x4000 else 'canonical'
            populations[group] += 1
            ids = [int(cid) for cid,_ in by_id.get(code, [])]
            result = dict(card_id=code,name=row['name'],group=group,baige_cids=ids)
            if not ids:
                local_only.append(result)
                counts['local_only_'+group] += 1
            out.write(json.dumps(result,ensure_ascii=False,separators=(',',':'))+'\n')
    summary = dict(
        observed_at_utc=datetime.now(timezone.utc).isoformat(),
        baige_file=str(args.baige.resolve()),cdb_file=str(args.cdb.resolve()),
        counts=dict(counts),different_fields=dict(fields),local_populations=dict(populations),
        unique_canonical_local_ids_matched=len(unique_canonical_ids),
        duplicate_baige_ids={str(code):[int(cid) for cid,_ in items] for code,items in by_id.items() if len(items)>1},
        missing_local_cards=missing,local_only_cards=local_only,
        unavailable_comparison_fields=['CDB alias','CDB category','CDB str1..str16'],
        normalization='line endings, per-line edge whitespace, CDB pendulum headers only',
        all_baige_rows_checked=counts['baige_rows_checked']==len(cards),
        all_local_rows_checked=sum(populations.values())==len(rows),
        source_differences_are_not_automatically_card_errors=True,
        source_databases_modified=False)
    (args.output/'summary.json').write_text(json.dumps(summary,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    (args.output/'differences.json').write_text(json.dumps(differences,ensure_ascii=False,indent=2)+'\n',encoding='utf-8')
    print(json.dumps({k:v for k,v in summary.items() if k not in ('missing_local_cards','local_only_cards','duplicate_baige_ids')},ensure_ascii=False,indent=2))
    print('missing examples',json.dumps(missing[:12],ensure_ascii=False))
    print('difference examples',json.dumps(differences[:4],ensure_ascii=False)[:5000])


if __name__ == '__main__':
    main()
