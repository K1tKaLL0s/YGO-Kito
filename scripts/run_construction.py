"""Run the maintained construction pipeline with existing course weights.

No optimizer step or training worker is started. Basic CB is opt-in and gated.
Artifacts and a resumable kernel session are written to --output.
The workspace holds reusable reference evaluations.
"""
import argparse
import json
import os
from pathlib import Path
import re
import signal
import time
import traceback

from ygo_kito.construction_checkpoint import (ConstructionCheckpoint, ConstructionReferenceCache,
    KERNEL_FILENAME, LEGACY_KERNEL_FILENAME, write_json)


def export_candidate_artifacts(output, task, candidate, progress):
    """Export the working list and report pending candidates by identity only."""
    output = Path(output)
    from ygo_kito.build_contracts import digest

    def complete(deck):
        return all(len(deck.get(z, ())) == task['sizes'][z] for z in ('main', 'extra', 'side'))

    def ydk(path, deck):
        path.write_text('#created by construction model\n#main\n'+
            '\n'.join(map(str, deck['main']))+'\n#extra\n'+
            '\n'.join(map(str, deck['extra']))+'\n!side\n'+
            '\n'.join(map(str, deck['side']))+'\n', encoding='utf-8')

    listing_complete = bool(candidate and complete(candidate.get('deck', {})))
    current_artifact = 'candidate.json' if listing_complete else 'skeleton.json' if candidate else None
    if candidate:
        write_json(output/current_artifact, {key: candidate[key] for key in
            ('deck', 'deck_sha256', 'candidate_version', 'strategy', 'evaluation_status') if key in candidate})
        if listing_complete:
            write_json(output/'deck.json', candidate['deck'])
            ydk(output/'deck.ydk', candidate['deck'])
    if current_artifact != 'skeleton.json':
        (output/'skeleton.json').unlink(missing_ok=True)
    if not listing_complete:
        for name in ('candidate.json', 'deck.json', 'deck.ydk'):
            (output/name).unlink(missing_ok=True)
    for path in output.iterdir():
        if re.fullmatch(r'pending-candidate-\d{2}\.(?:json(?:\.tmp)?|ydk)', path.name) and not path.is_dir():
            path.unlink()

    progress = progress or {}
    reference_stage = progress.get('pending_reference') or {}
    pending = progress.get('pending_quality') or reference_stage.get('candidate_batch') or {}
    exports = []
    for index, row in enumerate(pending.get('candidates', ())):
        if not complete(row['deck']):
            raise RuntimeError('pending optimizer candidate is not a complete listing')
        evaluations = pending.get('evaluations', {})
        status = ('awaiting_reference' if reference_stage else 'evaluated_awaiting_batch_selection'
                  if str(index) in evaluations or index in evaluations else 'static_evaluation_pending')
        exports.append(dict(candidate_index=index, status=status,
                            deck_sha256=row.get('deck_sha256') or digest(row['deck'])))
    write_json(output/'candidate-exports.json', dict(listing_complete=listing_complete,
        current_artifact=current_artifact, pending_candidates=exports))
    return listing_complete, exports


def prepare_inference_device(models, requested=None):
    """Move validated weights for this invocation, without rewriting a training checkpoint."""
    os.environ.setdefault('CUBLAS_WORKSPACE_CONFIG', ':4096:8')
    import torch
    from ygo_kito.device import resolve_device, model_device

    source = str(models.device)
    device = resolve_device(source if requested is None else requested)
    if device.type == 'cuda':
        torch.cuda.set_device(device)
        torch.cuda.reset_peak_memory_stats(device)
    receipt = dict(source_checkpoint_device=source, inference_device=str(device),
                   torch=str(torch.__version__), cuda_runtime=torch.version.cuda,
                   gpu=torch.cuda.get_device_name(device) if device.type == 'cuda' else None,
                   cublas_workspace_config=os.environ['CUBLAS_WORKSPACE_CONFIG'],
                   training_checkpoint_migrated=False, roles={})
    for role, model in models.models().items():
        model.to(device).eval()
        actual = str(model_device(model))
        if actual != str(device):
            raise RuntimeError('inference model did not reach requested device: '+role)
        row = dict(parameter_device=actual, forward_calls=0, output_devices=[])
        receipt['roles'][role] = row
        def observe(_model, _args, output, row=row):
            def tensors(value):
                if isinstance(value, torch.Tensor):
                    return [value]
                if isinstance(value, dict):
                    return [t for child in value.values() for t in tensors(child)]
                if isinstance(value, (list, tuple)):
                    return [t for child in value for t in tensors(child)]
                return []
            outputs = tensors(output)
            if not outputs or any(t.device != device for t in outputs):
                raise RuntimeError('model inference output is not on the requested device')
            if any(not torch.isfinite(t).all() for t in outputs):
                raise RuntimeError('nonfinite model inference output')
            row['forward_calls'] += 1
            if str(device) not in row['output_devices']:
                row['output_devices'].append(str(device))
        model.register_forward_hook(observe)
    models.device = device
    for trainer in (models.builder, models.duel, models.coordinator):
        trainer.device = device
    for adapter in models.kernel.adapters.values():
        adapter.device = device
    return receipt


def advance_construction(kernel, selection, checkpoint, *, pause_requested, status, basic_cb_enabled=False, **options):
    def commit(result):
        revision = checkpoint.commit(kernel.state_dict(for_write=True), stop_reason=result['stop_reason'])
        state = result.get('continuation') or {}
        pending = state.get('pending_quality') or {}
        status('construction_progress', mode=result['execution']['mode'], slices=result['execution']['slices'],
            checkpoint_revision=revision, iteration=state.get('iteration'), stop_reason=result['stop_reason'],
            completed_evaluations=len(pending.get('evaluations', {})),
            pending_evaluations=len(pending.get('pending_indices', ())),
            completed_comparisons=(pending.get('comparison_progress') or {}).get('next_pair'),
            gate_status=(result.get('construction_gate') or {}).get('status'))

    return kernel.run_selected(selection, base=None, basic_cb_enabled=basic_cb_enabled,
        pause_requested=pause_requested, _checkpoint=commit, **options)


def isolate_trial_kernel(models, candidate_budget=None):
    from ygo_kito.autonomous_construction import AutonomousConstructionKernel

    original = models.kernel
    source_binding = dict(original.source_binding)
    if candidate_budget is not None:
        source_binding["construction_candidate_budget"] = candidate_budget
    kernel = AutonomousConstructionKernel(models.builder, models.coordinator, assets=original.assets,
        host_available_ids=original.requested_ids, source_binding=source_binding,
        theme_minimum=original.theme_minimum, pool_limit=original.pool_limit,
        candidate_limit=original.candidate_limit, allowed_theme_ids=original.allowed_theme_ids)
    kernel.updates = dict(original.updates)
    kernel.graph_updates = dict(original.graph_updates)
    models.kernel = kernel
    return kernel


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--checkpoint', type=Path, required=True)
    parser.add_argument('--model-binding', type=Path, required=True)
    parser.add_argument('--environment', type=Path, required=True)
    parser.add_argument('--workspace', type=Path, required=True)
    parser.add_argument('--native-root', type=Path, required=True)
    parser.add_argument('--period', required=True)
    parser.add_argument('--request', help='Chinese, English, or Japanese construction task; defaults to the course wording')
    parser.add_argument('--theme', help='Verify the host-selected theme identifier')
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--mode', choices=('development','online'), default='development')
    parser.add_argument('--seconds', type=float, help='Online task deadline; development has no deadline')
    parser.add_argument('--slice-seconds', type=float, default=30., help='Internal calculation/checkpoint slice')
    parser.add_argument('--iterations', type=int, default=4, help='Optimizer iterations per internal slice')
    parser.add_argument('--resume', type=Path, help='kernel.json.gz or kernel.json from a previous slice using these weights')
    parser.add_argument('--no-reference-cache', action='store_true', help='Bypass the workspace reference cache')
    parser.add_argument('--native-query-resume', type=Path,
        help='Continue a native-rule-checks.json frontier using the original workspace receipts')
    parser.add_argument('--device', default='cuda:0', help='Inference device (default cuda:0)')
    parser.add_argument('--basic-cb', action='store_true', help='Run existing basic CB only after static admission')
    parser.add_argument('--candidate-budget', type=int, choices=range(2,33), metavar='N',
        help='Generate at most N candidates per round (2–5 for new runs)')
    args = parser.parse_args(argv)
    if args.mode == 'development' and args.seconds is not None:
        parser.error('--seconds is an online deadline; development uses --slice-seconds internally')
    if args.iterations < 1 or args.iterations > 64:
        parser.error('--iterations must be 1..64 per internal slice')
    if args.resume is None and args.candidate_budget is not None and args.candidate_budget > 5:
        parser.error('--candidate-budget must be 2..5 for a new run')
    compressed, legacy = args.output/KERNEL_FILENAME, args.output/LEGACY_KERNEL_FILENAME
    resume_path = args.resume.resolve() if args.resume is not None else None
    in_place = next((path for path in (compressed, legacy) if path.resolve() == resume_path), None)
    if args.output.exists() and any(args.output.iterdir()) and in_place is None:
        parser.error('--output must be new, empty, or the directory containing the resumed kernel')
    if in_place is not None and compressed.exists() and legacy.exists():
        parser.error('--output contains two construction kernels')
    args.output.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    def status(event, **details):
        payload = dict(event=event,elapsed_seconds=round(time.monotonic()-started,3))
        payload.update(details)
        print(json.dumps(payload,ensure_ascii=False), flush=True)
    checkpoint = ConstructionCheckpoint(in_place or compressed)
    pause = False

    def request_pause(_signal, _frame):
        nonlocal pause
        pause = True

    previous_handler = signal.signal(signal.SIGINT, request_pause)
    try:
        status('loading_modules')
        os.environ.setdefault('CUBLAS_WORKSPACE_CONFIG', ':4096:8')
        import torch
        from ygo_kito.course_construction_request import course_construction_text
        from ygo_kito.course_models import CourseModels
        from ygo_kito.period_runtime import PeriodBuildAssets
        environment = json.loads(args.environment.read_text(encoding='utf-8'))
        # Accept the existing active-environment envelope as well as the direct
        # period input; no environment values are inferred from a period name.
        environment = environment.get('environment', environment)
        status('loading_assets')
        assets = PeriodBuildAssets(args.native_root,args.period,environment,args.workspace,
                                  adapter_revision=5,evidence_source='user_supplied')
        if args.native_query_resume is not None:
            assets.construction_rules.load_frontier(json.loads(args.native_query_resume.read_text(encoding='utf-8')))
        status('restoring_weights',period=args.period)
        saved = torch.load(args.checkpoint,map_location='cpu',weights_only=True)
        binding = json.loads(args.model_binding.read_text(encoding='utf-8'))
        models = CourseModels.from_state(saved['models'], assets=assets, expected_binding=binding)
        kernel = isolate_trial_kernel(models, args.candidate_budget)
        device_receipt = prepare_inference_device(models, args.device)
        write_json(args.output/'device.json', device_receipt)
        status('inference_device', **device_receipt)
        before = dict(models.builder.updates)
        if args.resume:
            committed = checkpoint.read(args.resume)
            kernel.load_state_dict(committed['state'])
            checkpoint.revision = committed['revision']
            selections = list(kernel.selections.values())
            if len(selections) != 1:
                raise ValueError('resume requires one saved construction task')
            selection = selections[0]
            request = selection.get("construction_request")
            if request is None:
                raise ValueError("resume needs a checkpoint for a formal request; start a new run for it")
            if args.request is not None and args.request != request["text"]:
                raise ValueError("resume request differs from the saved wording")
            session = kernel.sessions.get(selection["candidate_id"])
            if session is not None and session.logic is not None:
                from ygo_kito.construction_logic import has_scoped_effect_blocks

                if not has_scoped_effect_blocks(session.logic):
                    raise ValueError("saved construction draft lacks scoped effect blocks; start a new run for the saved wording")
        else:
            if pause:
                write_json(args.output/'summary.json', dict(status='construction_suspended', stop_reason='user_pause'))
                status('finished', status='construction_suspended', stop_reason='user_pause')
                return 130
            request_text = args.request if args.request is not None else course_construction_text(args.period)
            request = models.coordinator.parse_construction_request(request_text, expected_period=args.period)
            selection = kernel.select_task(construction_request=request)
        if selection.get('status') != 'model_selected_task':
            raise ValueError('construction task selection unresolved: '+str(selection.get('status')))
        if args.theme and selection['theme']['theme_id'] != args.theme:
            raise ValueError('host selected a different theme from the requested one')
        write_json(args.output/'selection.json',selection)
        write_json(args.output/'task.json',selection['task'])
        if args.resume is None:
            checkpoint.commit(kernel.state_dict(for_write=True), stop_reason='task_selected')
        status('constructing',theme=selection['theme']['theme_id'],task_pool_count=len(selection['task']['pool']),
               candidate_budget=selection['task']['candidate_budget'],
               updates=before,mode=args.mode,seconds=args.seconds,slice_seconds=args.slice_seconds,
               iterations_per_slice=args.iterations)
        with torch.no_grad():
            reference_cache = None if args.no_reference_cache else ConstructionReferenceCache(
                args.workspace / 'construction-reference-cache')
            result = advance_construction(kernel, selection, checkpoint, pause_requested=lambda: pause, status=status,
                basic_cb_enabled=args.basic_cb,
                run_mode=args.mode,seconds=args.seconds,slice_seconds=args.slice_seconds,
                max_iterations=args.iterations, _reference_cache=reference_cache)
        write_json(args.output / "native-rule-checks.json", assets.construction_rules.report())
        if models.builder.updates != before:
            raise RuntimeError('construction unexpectedly changed model update counters')
        if models.device.type == 'cuda':
            torch.cuda.synchronize(models.device)
            device_receipt['peak_allocated_bytes'] = torch.cuda.max_memory_allocated(models.device)
            device_receipt['peak_reserved_bytes'] = torch.cuda.max_memory_reserved(models.device)
        write_json(args.output/'device.json', device_receipt)
        from ygo_kito.construction_progress import construction_report
        write_json(args.output/'result.json', construction_report(result))
        session = kernel.sessions.get(selection['candidate_id'])
        export_error = None
        if session:
            try:
                snapshot = session._snapshot()
                progress = snapshot.pop('construction_progress') or {}
                snapshot['construction_progress'] = {key: progress[key] for key in
                    ('status', 'stop_reason', 'iteration', 'candidate_version', 'task_sha256') if key in progress}
                checkpoint.export_session(args.output/'session.json', snapshot)
            except OSError as error:
                export_error = str(error)
                status('session_export_failed', checkpoint_revision=checkpoint.revision, message=export_error)
        candidate = result.get('construction_candidate') or result.get('best')
        listing_complete, pending_exports = export_candidate_artifacts(args.output, selection['task'], candidate,
            session.construction_progress if session else None)
        summary = dict(status=result['status'],stop_reason=result['stop_reason'],
            checkpoint_revision=checkpoint.revision,session_export_error=export_error,
            execution=result.get('execution'),stage_transition=result.get('stage_transition'),
            construction_passed=result['construction_passed'],gate=result.get('construction_gate'),
            elapsed_seconds=round(time.monotonic()-started,3),updates_before=before,
            updates_after=dict(models.builder.updates),training_run=False,
            cb_run=result.get('basic_cb_inference_performed',False),cb_enabled=args.basic_cb,
            device=device_receipt,
            task_pool_count=len(selection['task']['pool']),
            candidate_counts={z:len((candidate or {}).get('deck',{}).get(z,())) for z in ('main','extra','side')},
            listing_complete=listing_complete, pending_candidate_exports=pending_exports,
            quality=(candidate or {}).get('quality_evaluation',{}).get('total'),
            artifact_directory=str(args.output))
        write_json(args.output/'summary.json',summary)
        status('finished',status=summary['status'],stop_reason=summary['stop_reason'],
            construction_passed=summary['construction_passed'],candidate_counts=summary['candidate_counts'],
            listing_complete=summary['listing_complete'],
            gate_status=(summary['gate'] or {}).get('status'),
            gate_reasons=(summary['gate'] or {}).get('reasons',[]),
            updates_before=before,updates_after=summary['updates_after'],training_run=False,cb_run=summary['cb_run'],
            artifact_directory=str(args.output))
        return 130 if result['stop_reason'] == 'user_pause' else 0
    except (Exception, KeyboardInterrupt) as error:
        interrupted = isinstance(error, KeyboardInterrupt)
        failure = dict(type=type(error).__name__, message=str(error), stop_reason='user_pause' if interrupted else 'error',
            traceback=traceback.format_exc(), elapsed_seconds=round(time.monotonic()-started, 3),
            checkpoint_revision=checkpoint.revision, training_run=False, cb_run=False)
        try:
            write_json(args.output/'failure.json', failure)
        except OSError as reporting_error:
            status('failure_record_unavailable', message=str(reporting_error))
        status('failed', error_type=type(error).__name__, message=str(error), checkpoint_revision=checkpoint.revision)
        return 130 if interrupted else 1
    finally:
        signal.signal(signal.SIGINT, previous_handler)


if __name__ == '__main__':
    raise SystemExit(main())
