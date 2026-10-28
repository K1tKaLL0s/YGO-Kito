"""Admit already completed paired training games as current bot runtime evidence.

This consumes existing normal-game/replay bytes. It never runs a qualification
batch, rewrites an old receipt, or claims historical/competitive strength.
"""
from copy import deepcopy
from pathlib import Path

from .build_contracts import BuildTask, digest
from .implementation_identity import source_tree_snapshot
from .model_build_feedback import validate_model_comparison
from .training_pilot import _bytes
from .validation import ContractError, fields, parse_json

KIND = 'observed-paired-period-bot-runtime-v1'
# These are controller/learning additions, outside protocol/core/visible DTOs.
# Exact old/new maps remain part of the receipt; runtime bot bytes cannot vary.
COMPATIBLE = frozenset(('autonomous_construction.py', 'construction_effect_blocks.py', 'course_game_adapter.py', 'observed_bot_evidence.py', 'scenario_course.py', 'cli.py', 'construction_controller.py', 'construction_fill.py', 'construction_model.py', 'construction_service.py', 'model_auxiliary.py', 'semantic_training.py'))


def validate_observed_bot_evidence(assets, bot, report, profile, adapter):
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
    if new != actual or not changed <= COMPATIBLE:
        raise ContractError('observed runtime source migration includes an unreviewed driver/protocol change')
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
    return {'kind': KIND, 'actual_existing_game_reused': True,
            'extra_qualification_games': 0, 'strength_qualified': False,
            'original_binding_sha256': digest(trace['opponent_binding']),
            'current_binding_sha256': digest(adapter.binding), 'changed_source_files': sorted(changed)}
