"""Join the completed local, per-fragment adjudications with the earlier audit."""
import argparse
from collections import Counter
import csv
import json
from pathlib import Path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--work', type=Path, required=True)
    parser.add_argument('--review', type=Path, required=True)
    args = parser.parse_args()
    pending = [json.loads(s) for s in (args.work/'pending-with-context.jsonl').read_text(encoding='utf-8').splitlines()]
    decisions = json.loads((args.work/'decisions.json').read_text(encoding='utf-8'))
    assert set(decisions) == {str(r['review_id']) for r in pending}
    joined = [dict(r, adjudication=decisions[str(r['review_id'])]) for r in pending]
    for r in joined:
        assert r['card_id'] == r['adjudication']['card_id']
    args.review.mkdir(parents=True, exist_ok=True)
    with (args.review/'completed-adjudications.jsonl').open('w', encoding='utf-8', newline='\n') as stream:
        for r in joined:
            stream.write(json.dumps(r, ensure_ascii=False, separators=(',', ':'))+'\n')
    with (args.review/'completed-adjudications.csv').open('w', encoding='utf-8-sig', newline='') as stream:
        writer = csv.writer(stream)
        writer.writerow(['序号', '卡号', '卡名', '核对原句', '裁定', '理由', '问题类型'])
        for r in joined:
            d = r['adjudication']
            writer.writerow([r['review_id'], r['card_id'], r['name'], r['sentence'], d['verdict'], d['reason'], ';'.join(d['issue_families'])])
    old = [json.loads(s) for s in (args.review/'all-confirmed-findings.jsonl').read_text(encoding='utf-8').splitlines()]
    new = [dict(card_id=r['card_id'], name=r['name'], scope=r['scope'], source=r['source'],
                sentence=r['sentence'], review_id=r['review_id'], families=r['adjudication']['issue_families'],
                reason=r['adjudication']['reason'],audited_atoms=r['unresolved_atoms']) for r in joined if r['adjudication']['verdict']=='confirmed_problem']
    (args.review/'additional-confirmed-findings.jsonl').write_text(''.join(json.dumps(r, ensure_ascii=False, separators=(',', ':'))+'\n' for r in new), encoding='utf-8')
    uncertain = [dict(card_id=64389297, name='迷宫变化', review_id=18,
        question='解放支付实体的精确数量', printed='卡文要求解放装备中的本卡和被装备的迷宫壁',
        local_script='c64389297.lua 的 spcost 只将 tc 交给 Duel.Release(tc,REASON_COST)',
        confirmed='发动费用应有解放；当前记录缺失',
        unresolved='卡文与脚本在本卡是否也以解放送墓上有出入，不能把脚本的一实体支付当成已核准裁定')]
    (args.review/'uncertain-details.json').write_text(json.dumps(uncertain, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    counts = Counter(r['adjudication']['verdict'] for r in joined)
    summary = dict(reviewed_pending_fragments=len(joined), reviewed_pending_cards=len({r['card_id'] for r in joined}),
        verdict_counts=dict(counts), undecided_fragments=0, uncertain_details=len(uncertain),
        earlier_confirmed_occurrences=len(old), additional_confirmed_fragments=len(new),
        union_confirmed_cards=len({r['card_id'] for r in old+new}),
        issue_families=dict(Counter(f for r in new for f in r['families']).most_common()),
        method='逐项阅读本地完整卡文、同分区全部积木及递归分支记录；疑难费用/处理以本地Lua文本旁证，未执行引擎。',
        distinction='这是原待复核队列的逐项语义裁定；其余无字面差异条目不因此升级为官方裁定或完整引擎验证。',
        repair_authorized=True, training_started=False, native_started=False, web_per_card_queries=0)
    (args.review/'completed-summary.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2)+'\n', encoding='utf-8')
    corrections = args.work/'decision-corrections.json'
    if corrections.exists():
        (args.review/'adjudication-corrections.json').write_bytes(corrections.read_bytes())
    print(json.dumps({k:v for k,v in summary.items() if k!='issue_families'}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
