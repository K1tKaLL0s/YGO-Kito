"""Bounded synthetic optimizer/RNG proof, separate from formal course credit."""
import argparse
from copy import deepcopy
import json
import os
from pathlib import Path
import sys

os.environ.setdefault('CUBLAS_WORKSPACE_CONFIG', ':4096:8')
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT), str(ROOT / 'scripts')]


def verify(models, assets, output):
    import torch
    from ygo_kito.course_models import CourseModels
    from ygo_kito.group_runner import tree_digest
    from ygo_kito.device import model_device
    from ygo_kito.build_contracts import DeckParts
    from ygo_kito.contracts import DecisionRequest
    from tests.test_duel_model import player_request
    torch.use_deterministic_algorithms(True)
    output.mkdir(parents=True, exist_ok=False)
    boundary = models.save_state()
    path = output / 'verification-boundary.weights'
    torch.save(boundary, path)
    def update(bundle):
        before = bundle.versions()
        optimizers = dict(bundle.builder.optimizers, duel=bundle.duel.optimizer,
                          coordinator=bundle.coordinator.optimizer)
        schedulers = dict(bundle.builder.schedulers, duel=bundle.duel.scheduler,
                          coordinator=bundle.coordinator.scheduler)
        losses = {}
        forward_devices = {}
        for role, model in bundle.models().items():
            if str(model_device(model)) != 'cuda:0': raise AssertionError('Wrong parameter device')
            # Declared synthetic objective on every trainable tensor, including
            # a CUDA RNG draw. No duel, corpus sample or formal credit is claimed.
            if role.startswith('build_'):
                prediction = model(bundle.builder.encoder.batch(bundle.builder.task, [DeckParts(())]))
            elif role == 'duel':
                request = player_request()
                request['observation']['cards'][0]['card_id'] = bundle.duel.encoder.card_ids[0]
                logits, values = model(bundle.duel.encoder.batch([DecisionRequest.from_dict(request)]))
                prediction = torch.cat((logits.softmax(-1).flatten(), values.flatten()))
            else:
                logits, predictions = model(torch.zeros(1, 14))
                prediction = torch.cat((logits.flatten(), predictions.flatten()))
            forward_devices[role] = str(prediction.device)
            if prediction.device != bundle.device: raise AssertionError('Forward left CUDA')
            loss = (prediction - 0.25).square().mean()
            loss = loss + 0.01 * sum(p.square().mean() for p in model.parameters() if p.requires_grad)
            loss = loss * (0.5 + torch.rand((), device=bundle.device))
            if not torch.isfinite(loss): raise AssertionError('Nonfinite loss')
            if role in bundle.sessions:
                bundle.sessions[role].step(loss)
            else:
                optimizers[role].zero_grad(set_to_none=True)
                loss.backward(); optimizers[role].step(); schedulers[role].step()
            losses[role] = float(loss.detach())
        after = bundle.versions()
        if any(before[r] == after[r] for r in before): raise AssertionError('A role did not update')
        return {'losses': losses, 'forward_devices': forward_devices, 'versions': after,
                'optimizers': tree_digest({r: o.state_dict() for r, o in optimizers.items()}),
                'schedulers': tree_digest({r: s.state_dict() for r, s in schedulers.items()}),
                'adapters': tree_digest({r: s.state() for r, s in bundle.sessions.items()}),
                'rng': tree_digest(bundle.rng_state())}
    expected = update(models)
    restored = CourseModels.from_state(torch.load(path, map_location='cpu', weights_only=True),
        assets=assets, expected_binding=models.binding)
    actual = update(restored)
    if expected != actual: raise AssertionError('Next CUDA update after restore differs')
    report = {'success': True, 'scope': 'synthetic-four-role-optimizer-and-rng-proof',
        'formal_training_started': False, 'device': str(restored.device),
        'python': sys.version, 'torch': torch.__version__, 'cuda': torch.version.cuda,
        'boundary_sha256': boundary['state_sha256'], 'next_update_equal': True,
        'roles': list(actual['versions']), 'losses': actual['losses'],
        'forward_devices': actual['forward_devices'],
        'peak_allocated_bytes': torch.cuda.max_memory_allocated()}
    (output / 'results.json').write_text(json.dumps(report, indent=2) + '\n')
    return report


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--output', type=Path, required=True)
    p.add_argument('--base', type=Path)
    p.add_argument('--course', type=Path)
    a = p.parse_args()
    import torch
    torch.set_num_threads(2)
    if not torch.cuda.is_available(): raise RuntimeError('CUDA required; no skipped proof')
    torch.cuda.set_per_process_memory_fraction(0.2)
    from ygo_kito.course_models import CourseModels
    if a.course:
        if not a.base: raise ValueError('--base required with --course')
        from local_foundation_course import run
        def status(*args, **kwargs): print(json.dumps({'stage': args}, default=str), flush=True)
        course = run(a.base, a.course, a.course / 'unused-stop', status, resume=True,
            continuation={'state_root': str(a.course)}, execution_source_root=ROOT,
            resource_base=a.base, restore_only=True, required_device='cuda:0')
        models, assets = course.models, course.assets
    else:
        from tests.test_course_models import models_fixture, artificial_steps
        import tempfile
        with tempfile.TemporaryDirectory() as temp:
            models, assets = models_fixture(Path(temp))
            artificial_steps(models)
            state = deepcopy(models.save_state())
            models = CourseModels.migrate_to_cuda(state, assets=assets,
                expected_binding=models.binding, device='cuda:0', cuda_seed=20261111)
            if state['execution']['device'] != 'cpu': raise AssertionError('Source changed')
    print(json.dumps(verify(models, assets, a.output), indent=2))


if __name__ == '__main__': main()
