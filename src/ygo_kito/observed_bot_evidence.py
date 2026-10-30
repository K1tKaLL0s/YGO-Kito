"""Admit already completed paired training games as current bot runtime evidence.

This consumes existing normal-game/replay bytes. It never runs a qualification
batch, rewrites an old receipt, or claims historical/competitive strength.
"""
from copy import deepcopy
import hashlib
from pathlib import Path
import re

from .build_contracts import BuildTask, digest
from .implementation_identity import source_tree_snapshot
from .model_build_feedback import validate_model_comparison
from .training_pilot import _bytes
from .validation import ContractError, fields, parse_json

KIND = 'observed-paired-period-bot-runtime-v1'
# These are controller/learning additions, outside protocol/core/visible DTOs.
# Exact old/new maps remain part of the receipt; runtime bot bytes cannot vary.
COMPATIBLE = frozenset(('autonomous_construction.py', 'construction_effect_blocks.py', 'course_game_adapter.py', 'observed_bot_evidence.py', 'scenario_course.py', 'cli.py', 'construction_controller.py', 'construction_fill.py', 'construction_model.py', 'construction_service.py', 'model_auxiliary.py', 'semantic_training.py'))


def validate_source_review_schema(review):
    """Validate an explicit host review; a boolean cannot authorize a bridge."""
    fields(review, {'kind', 'qualification_sha256', 'from_source_map', 'to_source_map', 'changes', 'ordinary_duel_review'})
    if review['kind'] != 'observed-bot-source-review-v1':raise ContractError('unsupported observed bot source review')
    def checksum(value):return isinstance(value,str) and re.fullmatch('[0-9a-f]{64}',value) is not None
    if not checksum(review['qualification_sha256']):raise ContractError('source review needs its exact qualification checksum')
    for key in ('from_source_map','to_source_map'):
        mapping=review[key]
        if (not isinstance(mapping,dict) or not mapping or any(not isinstance(name,str) or
                not re.fullmatch(r'[A-Za-z0-9_]+\.py',name) or not checksum(value) for name,value in mapping.items())):
            raise ContractError('source review needs complete module checksum maps')
    before,after=review['from_source_map'],review['to_source_map']
    expected={name:{'before_sha256':before.get(name),'after_sha256':after.get(name)}
              for name in set(before)|set(after) if before.get(name)!=after.get(name)}
    if review['changes']!=expected:raise ContractError('source review changes do not exactly cover its maps')
    ordinary=fields(review['ordinary_duel_review'],{'scope','reviewed_changes','evidence'})
    if ordinary['scope']!='ordinary_effect_duel_default_path' or ordinary['reviewed_changes']!=expected:
        raise ContractError('ordinary duel review does not cover the exact source transition')
    evidence=ordinary['evidence']
    if not isinstance(evidence,list) or not evidence:raise ContractError('ordinary duel source review needs pinned evidence')
    paths=set()
    for reference in evidence:
        fields(reference,{'path','sha256'})
        value=reference['path']
        if not isinstance(value,str):raise ContractError('source review evidence needs an absolute JSON path')
        path=Path(value)
        if not path.is_absolute() or '..' in path.parts or path.suffix!='.json' or value in paths or not checksum(reference['sha256']):
            raise ContractError('source review evidence needs unique absolute JSON paths and checksums')
        paths.add(value)
    return deepcopy(review)


def validate_observed_source_review(report,actual,qualification_sha256,review=None):
    """Keep the historical guard, then admit only an exactly reviewed bridge."""
    old,new=report['original_source_map'],report['current_source_map']
    changed={name for name in set(old)|set(new) if old.get(name)!=new.get(name)}
    if not changed<=COMPATIBLE:
        raise ContractError('observed runtime source migration includes an unreviewed driver/protocol change')
    if review is None:
        if new!=actual:raise ContractError('observed runtime source migration includes an unreviewed driver/protocol change')
        return None
    review=validate_source_review_schema(review)
    if (review['qualification_sha256']!=qualification_sha256 or
            review['from_source_map']!=new or review['to_source_map']!=actual):
        raise ContractError('observed source review belongs to another qualification or source transition')
    for reference in review['ordinary_duel_review']['evidence']:
        path=Path(reference['path'])
        if not path.is_file():raise ContractError('ordinary duel source review evidence is missing')
        raw=path.read_bytes()
        if hashlib.sha256(raw).hexdigest()!=reference['sha256']:raise ContractError('ordinary duel source review evidence checksum differs')
        evidence=parse_json(raw.decode('utf-8'))
        if (not isinstance(evidence,dict) or evidence.get('kind')!='ordinary-duel-source-review-evidence-v1' or
                evidence.get('scope')!='ordinary_effect_duel_default_path' or evidence.get('reviewed_changes')!=review['changes'] or
                not isinstance(evidence.get('checks'),list) or not evidence['checks'] or
                any(not isinstance(check,str) or not check.strip() for check in evidence['checks'])):
            raise ContractError('ordinary duel source review evidence lacks its exact review scope and checks')
    return {'kind':review['kind'],'qualification_sha256':qualification_sha256,
            'changed_source_files':sorted(review['changes']),'evidence':deepcopy(review['ordinary_duel_review']['evidence'])}


def validate_observed_bot_evidence(assets, bot, report, profile, adapter, *, source_review=None):
    fields(report, {'kind', 'comparison', 'task', 'private_trace', 'closed_case',
        'actor_seat', 'original_source_map', 'current_source_map', 'native_receipt_sha256',
        'period_context_sha256', 'extra_qualification_games', 'strength_qualified'})
    if report['kind'] != KIND or report['extra_qualification_games'] != 0 or report['strength_qualified'] is not False:
        raise ContractError('existing normal-game evidence required; no synthetic qualification')
    if (report['native_receipt_sha256'] != digest(assets.receipt) or
            report['period_context_sha256'] != digest(assets.period_context)):
        raise ContractError('observed bot proof uses another native/period environment')
    def read(reference):
        _, raw = _bytes(bot.workspace, reference)
        return parse_json(raw.decode('utf-8'))
    task = BuildTask.from_dict(read(report['task']))
    comparison = read(report['comparison'])
    validate_model_comparison(task, assets, comparison)
    trace, case = read(report['private_trace']), read(report['closed_case'])
    driver = comparison['plan']['driver']
    if (driver['executor_id'] != bot.executor_id or driver['source_id'] != bot.source_id or
            driver['opponent_id'] != bot.opponent_id or driver['audit_sha256'] != bot.audit['sha256']):
        raise ContractError('observed comparison belongs to another actual audited opponent')
    _, audit_bytes = _bytes(bot.workspace, bot.audit)
    audit = parse_json(audit_bytes.decode('utf-8'))
    if driver['assembly_sha256'] != audit['assembly_sha256']:
        raise ContractError('observed comparison used different compiled bot bytes')
    actor = report['actor_seat']
    if type(actor) is not int or actor not in (0, 1):
        raise ContractError('observed actor seat missing')
    matching = [g for g in comparison['games'] if g['actor_seat'] == actor and
                g['trace_sha256'] == digest(trace)]
    if (len(matching) != 1 or trace['profile'] != profile or trace['resources'] != assets.receipt or
            trace['kind'] != 'registered-opponent-private-replay-v1' or
            trace['seed_audit_only'] != matching[0]['seed_audit_only'] or
            trace['outcome'] != matching[0]['outcome'] or trace['events'][-1]['kind'] != 5 or
            not any(r['player'] == 1-actor for r in trace['responses']) or
            case.get('plan_sha256') != comparison['plan_sha256'] or
            case.get('receipt_sha256') != digest(matching[0]) or
            case.get('private_trace_sha256') != digest(trace) or case.get('replay_verified') is not True):
        raise ContractError('observed evidence lacks its actual bot decisions/terminal/replay boundary')
    old, new = report['original_source_map'], report['current_source_map']
    actual = source_tree_snapshot(Path(__file__).resolve().parent)
    changed = {name for name in set(old) | set(new) if old.get(name) != new.get(name)}
    reviewed=validate_observed_source_review(report,actual,bot.qualification['sha256'],source_review)
    definitions = [d for d in bot.registry.inventory['origins'] if d['source_id'] == bot.source_id and
                   (d['class_name'] == bot.executor_id or d['bot_id'] == bot.executor_id)]
    if len(definitions) != 1 or bot.variant_root is not None:
        raise ContractError('observed evidence needs its exact unmodified compiled Executor')
    material = {'source': definitions[0]['sha256'], 'assembly': audit['assembly_sha256']}
    expected = deepcopy(adapter.binding)
    expected['driver_implementation_sha256'] = digest(dict(material, python_modules=old))
    if (expected != trace['opponent_binding'] or
            adapter.binding['driver_implementation_sha256'] != digest(dict(material, python_modules=actual))):
        raise ContractError('observed bot/source/tools/deck/profile binding changed')
    adapter.assert_runtime(assets.root, profile, actor)
    result={'kind': KIND, 'actual_existing_game_reused': True,
            'extra_qualification_games': 0, 'strength_qualified': False,
            'original_binding_sha256': digest(trace['opponent_binding']),
            'current_binding_sha256': digest(adapter.binding), 'changed_source_files': sorted(changed)}
    if reviewed is not None:result['source_review']=reviewed
    return result
