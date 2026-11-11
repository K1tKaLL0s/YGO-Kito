"""Explicit CUDA engineering check for the first-layer/legacy-ranker boundary.

Run from the complete checkout with PYTHONPATH=src. Uses synthetic inputs and
fresh weights only; no optimizer step, checkpoint, CB or rule-engine execution.
Requires CUDA and fails (never skips or falls back) if it is unavailable.
"""

import argparse
from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))


def validate():
    import torch
    from ygo_kito.build_contracts import DeckParts
    from ygo_kito.build_model import BuildEncoder, BuildModelConfig, BuildRanker, FEATURE_VERSION
    from ygo_kito.construction_layers import evaluate_axis
    from tests.test_construction_binding import catalog
    from tests.test_construction_layers import context, role, skeleton

    if not torch.cuda.is_available():
        raise RuntimeError("real CUDA execution required; no CPU fallback")
    device = torch.device("cuda:0")
    torch.set_num_threads(2)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    torch.cuda.set_device(device)
    torch.cuda.init()
    torch.cuda.reset_peak_memory_stats(device)
    started = time.perf_counter()

    # The new Python statistics remain separate from the existing model feature
    # version. This is a transport check, not an invented learned integration.
    axis = evaluate_axis(skeleton([1, 1, 1, 2]), context(assessments=(role(1), role(2))))
    function = axis["overview"]["functions"]["entry"]
    stats = torch.tensor([function[k] for k in ("K", "E", "axis_density", "deck_density")], dtype=torch.float64)
    gpu_stats = stats.to(device)
    assert gpu_stats.is_cuda
    torch.testing.assert_close(stats, gpu_stats.cpu(), rtol=0, atol=0)

    task, assets = catalog()
    config = BuildModelConfig()
    encoder = BuildEncoder(task, assets, config)
    first = DeckParts(tuple([1] * 3 + [2] * 3 + [3] * 3 + [4] * 3 +
                            [code for code in range(5, 19) for _ in range(2)]))
    second = DeckParts(first.main[:-1] + (5,))
    for deck in (first, second):
        assets.validate(task, deck)
    cpu_batch = encoder.batch(task, (first, second))
    gpu_batch = encoder.batch(task, (first, second), device=device)
    for key, tensor in gpu_batch.items():
        assert tensor.is_cuda, key
        torch.testing.assert_close(cpu_batch[key], tensor.cpu(), rtol=0, atol=0)

    roles = {}
    for index, name in enumerate(("build_goal", "build_optimizer")):
        torch.manual_seed(187 + index)
        cpu_model = BuildRanker(config, len(encoder.card_ids), len(encoder.tags)).train()
        gpu_model = deepcopy(cpu_model).to(device).train()
        before = {k: value.detach().clone() for k, value in gpu_model.named_parameters()}
        # Also exercise BuildRanker's existing automatic host -> device transfer.
        cpu_scores = cpu_model(cpu_batch)
        gpu_scores = gpu_model(cpu_batch)
        assert gpu_scores.is_cuda and torch.isfinite(gpu_scores).all()
        torch.testing.assert_close(cpu_scores, gpu_scores.cpu(), rtol=1e-5, atol=1e-6)
        target = torch.tensor([.25, -.25])
        cpu_loss = (cpu_scores - target).square().mean()
        gpu_loss = (gpu_scores - target.to(device)).square().mean()
        cpu_loss.backward()
        gpu_loss.backward()
        gradient_error = 0.
        gradient_magnitude = 0.
        gpu_parameters = dict(gpu_model.named_parameters())
        for key, cpu_parameter in cpu_model.named_parameters():
            gpu_parameter = gpu_parameters[key]
            assert cpu_parameter.grad is not None and gpu_parameter.grad is not None, key
            assert gpu_parameter.grad.is_cuda and torch.isfinite(gpu_parameter.grad).all(), key
            torch.testing.assert_close(cpu_parameter.grad, gpu_parameter.grad.cpu(), rtol=5e-4, atol=2e-5)
            gradient_error = max(gradient_error, (cpu_parameter.grad - gpu_parameter.grad.cpu()).abs().max().item())
            gradient_magnitude += gpu_parameter.grad.abs().sum().item()
            torch.testing.assert_close(before[key], gpu_parameter, rtol=0, atol=0)
        assert gradient_magnitude > 0
        roles[name] = {"passed": True, "parameters": sum(p.numel() for p in cpu_model.parameters()),
                       "forward_max_abs_error": (cpu_scores - gpu_scores.cpu()).abs().max().item(),
                       "gradient_max_abs_error": gradient_error,
                       "gradient_abs_sum": gradient_magnitude,
                       "loss_cpu": cpu_loss.item(), "loss_cuda": gpu_loss.item(),
                       "weights_unchanged": True}
    torch.cuda.synchronize(device)
    driver = subprocess.run(["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
                            capture_output=True, text=True, check=True, timeout=15).stdout.strip()
    return {"kind": "construction-layer-gpu-engineering-v1", "passed": True,
            "python": sys.version, "executable": sys.executable, "source_root": str(ROOT),
            "torch": torch.__version__, "cuda_runtime": torch.version.cuda,
            "driver": driver, "device": str(device), "gpu": torch.cuda.get_device_name(device),
            "device_total_bytes": torch.cuda.get_device_properties(device).total_memory,
            "peak_allocated_bytes": torch.cuda.max_memory_allocated(device),
            "elapsed_seconds": time.perf_counter() - started,
            "axis_values": stats.tolist(), "axis_tensor_roundtrip_exact": True,
            "encoder_batch_tensors": sorted(gpu_batch), "encoder_roundtrip_exact": True,
            "model_feature_version": FEATURE_VERSION, "roles": roles,
            "tolerances": {"forward": {"rtol": 1e-5, "atol": 1e-6},
                           "gradient": {"rtol": 5e-4, "atol": 2e-5}},
            "new_axis_features_integrated_into_model": False,
            "optimizer_steps": 0, "checkpoint_io": False, "cb_execution": False,
            "native_engine_execution": False, "formal_training": False}


def validate_relations():
    """Exercise actual layer-two candidate payloads on CUDA, with masks intact.

    Static dictionaries, dependency closure and combination counts stay on the
    CPU. Only the numeric export/consumer boundary is tested on the GPU. The
    legacy encoder sees the corresponding real candidate decks, not new fields.
    """
    from dataclasses import replace
    import torch
    from ygo_kito.build_contracts import BuildTask
    from ygo_kito.build_model import BuildEncoder, BuildModelConfig, BuildRanker, FEATURE_VERSION
    from ygo_kito.construction_layers import evaluate_layers
    from ygo_kito.construction_relations import (
        Claim, InputGroup, Need, ProbabilityRequest, RelationContext, RelationFact,
        Resource, ResourcePool, UseRequirement, compare_configurations, relation_index,
    )
    from tests.test_construction_layers import AdapterTests, context, skeleton

    if not torch.cuda.is_available():
        raise RuntimeError("real CUDA execution required; no CPU fallback")
    device = torch.device("cuda:0")
    torch.set_num_threads(2)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    torch.cuda.set_device(device)
    torch.cuda.init()
    torch.cuda.reset_peak_memory_stats(device)
    started = time.perf_counter()
    task, assets, catalog = AdapterTests.assets()
    raw = task.to_dict()
    raw["sizes"]["extra"] = 1
    task = BuildTask.from_dict(raw)
    assets.rows[100]["type"] = 0x41
    inputs = InputGroup("all", (Need("two-materials", Resource("material"), 2),))
    relations = RelationContext((UseRequirement("material-use", inputs, "anonymous two-copy task"),
        UseRequirement("unknown-use", InputGroup("all", (Need("uncertain", Resource("uncertain")),)),
                       "explicit unresolved target", required=False)), (
        RelationFact("stock", "material-stock", Resource("material"), "inventory source", 2,
                     inventory_scaled=True, output_pool="stock"),
        RelationFact("uncertain", "uncertain-effect", Resource("uncertain"), "source incomplete", 3,
                     unknown=("unresolved timing",), claims=(Claim("shared"),))),
        (ResourcePool("stock", "physical cards", inventory=(("main", 2),)),
         ResourcePool("shared", "same-name count", capacity=1)),
        probabilities=(ProbabilityRequest("two", (2,), 5, "uniform initial sample"),))
    ctx = replace(context(requirements=()), task=task, relations=relations)
    index = relation_index(catalog, ctx)
    evaluations, decks, comparisons = [], [], []
    previous = None
    for copies in range(4):
        # Every candidate has a complete legal 40/1/0 listing. The edit trades
        # filler slots for material copies without changing the original task.
        main = (1,) + (2,) * copies + tuple(range(3, 42-copies))
        spec = skeleton(main, (100,))
        output, value = evaluate_layers(spec, ctx, catalog, index=index, previous=previous, return_state=True)
        assert output["validation"] == "list_constraints_verified"
        full_output, full = evaluate_layers(spec, ctx, catalog, index=index, return_state=True)
        left, right = value.to_dict(), full.to_dict()
        left.pop("work"); right.pop("work")
        assert left == right, "incremental/full candidate payload mismatch"
        if previous is not None:
            comparisons.append(compare_configurations(previous, value, ctx).to_dict())
        evaluations.append(value.data)
        decks.append(spec.inventory)
        previous = value
    use_ids = sorted(evaluations[0]["uses"])
    code = {"missing": 0, "supported": 1, "unknown": -1}
    status = torch.tensor([[code[v["uses"][key]["status"]] for key in use_ids] for v in evaluations], dtype=torch.int8)
    known = status != -1
    inventory = torch.tensor([[v["probabilities"]["two"]["copies"], v["slots"]["main"], v["slots"]["extra"]]
                              for v in evaluations], dtype=torch.int64)
    probability = torch.tensor([[v["probabilities"]["two"][k] for k in ("acquired", "retained")]
                                for v in evaluations], dtype=torch.float64)
    tensors = {"status": status, "known": known, "inventory": inventory, "probability": probability}
    gpu = {key: tensor.to(device) for key, tensor in tensors.items()}
    for key, tensor in gpu.items():
        assert tensor.is_cuda
        torch.testing.assert_close(tensors[key], tensor.cpu(), rtol=0, atol=0)
    assert not gpu["known"][:, use_ids.index("unknown-use")].any()
    assert (gpu["status"][:, use_ids.index("unknown-use")] == -1).all()
    # Actual 0/1/2/3 integer stock yields false/false/true/true. E=1.9 must
    # never substitute for the two real material cards at this boundary.
    stock_support = gpu["inventory"][:, 0] >= 2
    torch.testing.assert_close(stock_support.cpu(), status[:, use_ids.index("material-use")] == 1)
    gpu_probability_delta = torch.diff(gpu["probability"], dim=0)
    cpu_probability_delta = torch.diff(probability, dim=0)
    torch.testing.assert_close(gpu_probability_delta.cpu(), cpu_probability_delta, rtol=1e-12, atol=1e-12)
    slot_delta = torch.diff(gpu["inventory"][:, 1:], dim=0).cpu()
    assert not slot_delta.any(), "zero-net-slot replacements must retain zero deltas"
    assert all(c["changes"]["cards"]["main"]["removed"] for c in comparisons)

    config = BuildModelConfig()
    encoder = BuildEncoder(task, assets, config)
    cpu_batch, gpu_batch = encoder.batch(task, decks), encoder.batch(task, decks, device=device)
    for key in cpu_batch:
        torch.testing.assert_close(cpu_batch[key], gpu_batch[key].cpu(), rtol=0, atol=0)
    torch.manual_seed(20261101)
    cpu_model = BuildRanker(config, len(encoder.card_ids), len(encoder.tags)).eval()
    cuda_model = deepcopy(cpu_model).to(device).eval()
    with torch.no_grad():
        cpu_scores, gpu_scores = cpu_model(cpu_batch), cuda_model(gpu_batch)
    assert torch.isfinite(gpu_scores).all()
    torch.testing.assert_close(cpu_scores, gpu_scores.cpu(), rtol=1e-5, atol=1e-6)
    for cpu_parameter, gpu_parameter in zip(cpu_model.parameters(), cuda_model.parameters()):
        torch.testing.assert_close(cpu_parameter, gpu_parameter.cpu(), rtol=0, atol=0)
        assert cpu_parameter.grad is None and gpu_parameter.grad is None
    torch.cuda.synchronize(device)
    driver = subprocess.run(["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
                            capture_output=True, text=True, check=True, timeout=15).stdout.strip()
    return {"kind": "construction-relations-gpu-engineering-v1", "passed": True,
        "python": sys.version, "executable": sys.executable, "source_root": str(ROOT),
        "torch": torch.__version__, "cuda_runtime": torch.version.cuda, "driver": driver,
        "device": str(device), "gpu": torch.cuda.get_device_name(device),
        "elapsed_seconds": time.perf_counter()-started,
        "peak_allocated_bytes": torch.cuda.max_memory_allocated(device),
        "candidates": len(decks), "use_ids": use_ids, "statuses": status.tolist(),
        "unknown_masks_preserved": True, "integer_inventory": inventory.tolist(),
        "integer_stock_support": stock_support.cpu().tolist(), "probabilities": probability.tolist(),
        "probability_deltas": cpu_probability_delta.tolist(), "slot_deltas": slot_delta.tolist(),
        "numeric_roundtrip_exact": True, "incremental_equals_full": True,
        "probability_delta_max_abs_error": (gpu_probability_delta.cpu()-cpu_probability_delta).abs().max().item(),
        "legacy_candidate_forward_max_abs_error": (cpu_scores-gpu_scores.cpu()).abs().max().item(),
        "comparisons": comparisons, "encoder_batch_tensors": sorted(cpu_batch),
        "model_feature_version": FEATURE_VERSION, "new_features_integrated_into_model": False,
        "static_relation_computation": "CPU", "weights_unchanged": True, "optimizer_steps": 0,
        "checkpoint_io": False, "cb_execution": False, "native_engine_execution": False,
        "formal_training": False,
        "tolerances": {"probability_delta": {"rtol": 1e-12, "atol": 1e-12},
                       "candidate_forward": {"rtol": 1e-5, "atol": 1e-6}}}


def validate_flow():
    """Run the actual fill and controller, with unchanged legacy CPU/CUDA rankers."""
    from dataclasses import replace
    from unittest.mock import patch
    import torch
    from ygo_kito.build_model import BuildEncoder, BuildModelConfig, BuildRanker, FEATURE_VERSION
    from ygo_kito.construction_controller import ConstructionController
    from ygo_kito.construction_layer_flow import ConstructionLayerAdapter
    from ygo_kito.construction_model import LogicCodec, LogicModelAdapter
    from ygo_kito.construction_relations import InputGroup, Need, RelationFact, Resource, UseRequirement
    from ygo_kito.coordinator_model import CoordinatorTrainer
    from tests.test_construction_layer_flow import flow_fixture, run_fill, session_for

    if not torch.cuda.is_available():
        raise RuntimeError("real CUDA execution required; no CPU fallback")
    device = torch.device("cuda:0")
    torch.set_num_threads(2)
    torch.backends.cuda.matmul.allow_tf32 = False
    torch.backends.cudnn.allow_tf32 = False
    torch.cuda.set_device(device)
    torch.cuda.reset_peak_memory_stats(device)
    started = time.perf_counter()
    fixture = flow_fixture()
    task, assets, graph, binder, decks, context = fixture
    unresolved = Resource("unresolved-execution")
    context = replace(context, relations=replace(context.relations,
        uses=(*context.relations.uses, UseRequirement("unknown", InputGroup("all", (Need("unknown", unresolved),)),
            "synthetic unresolved purpose", required=False)),
        facts=(*context.relations.facts, RelationFact("unknown", "unknown", unresolved,
            "synthetic missing execution condition", unknown=("condition_not_supplied",)))))
    adapter = ConstructionLayerAdapter(binder, context_provider=lambda *_: context)
    config = BuildModelConfig()
    encoder = BuildEncoder(task, assets, config)
    cpu_models, gpu_models, snapshots = {}, {}, {}
    for i, role in enumerate(("build_goal", "build_optimizer")):
        torch.manual_seed(381 + i)
        cpu_models[role] = BuildRanker(config, len(encoder.card_ids), len(encoder.tags)).eval()
        gpu_models[role] = deepcopy(cpu_models[role]).to(device).eval()
        snapshots[role] = {k: p.detach().clone() for k, p in gpu_models[role].named_parameters()}
    cpu_batch = encoder.batch(task, decks)
    gpu_batch = encoder.batch(task, decks, device=device)
    for key in cpu_batch:
        torch.testing.assert_close(cpu_batch[key], gpu_batch[key].cpu(), rtol=0, atol=0)
    results = {}
    for role in cpu_models:
        cpu = run_fill(fixture, adapter=adapter, models=cpu_models, encoder=encoder, role=role)
        gpu = run_fill(fixture, adapter=adapter, models=gpu_models, encoder=encoder, role=role)
        cr, gr = cpu["candidate_trace"]["candidates"], gpu["candidate_trace"]["candidates"]
        a = torch.tensor([r["model_score_uncalibrated"] for r in cr])
        b = torch.tensor([r["model_score_uncalibrated"] for r in gr])
        torch.testing.assert_close(a, b, rtol=1e-5, atol=1e-6)
        assert cpu["best_deck"] == gpu["best_deck"]
        assert cpu["candidate_trace"]["candidate_order"] == gpu["candidate_trace"]["candidate_order"]
        assert cpu["best_deck"]["main"].count(2) >= 2
        states = [[r["layer_evaluation"]["relations"]["uses"][u]["status"]
                   for u in ("two-materials", "unknown")] for r in gr]
        status = torch.tensor([[{"missing": 0, "supported": 1, "unknown": -1}[s] for s in row]
                               for row in states], dtype=torch.int8)
        inventory = torch.tensor([r["layer_evaluation"]["axis"]["inventory"]["main"].count(2)
                                  for r in gr], dtype=torch.int64)
        probability = torch.tensor([[r["layer_evaluation"]["relations"]["probabilities"]["material"][k]
                                    for k in ("acquired", "retained")] for r in gr], dtype=torch.float64)
        for tensor in (status, inventory, status != -1, probability):
            torch.testing.assert_close(tensor, tensor.to(device).cpu(), rtol=0, atol=0)
        assert torch.equal(inventory.to(device) >= 2, status[:, 0].to(device) == 1)
        assert (status[:, 1] == -1).all()
        results[role] = {"forward_max_abs_error": (a-b).abs().max().item(),
            "cpu_scores": a.tolist(), "gpu_scores": b.tolist(),
            "legacy_order": gpu["candidate_trace"]["layers"]["legacy_order"],
            "selected_order": gpu["candidate_trace"]["candidate_order"],
            "selected_index": gpu["candidate_trace"]["selected_candidate_index"],
            "integer_inventory": inventory.tolist(), "statuses": status.tolist(),
            "probabilities": probability.tolist(), "numeric_roundtrip_exact": True,
            "selection_cpu_cuda_equal": True}
    # Real catalog/model/controller path, with its original candidate generator;
    # neither context nor candidates are substituted in this second boundary.
    tag = graph.nodes[0].tags[0]
    graph_adapter = LogicModelAdapter(task, gpu_models, encoder, LogicCodec((tag,)), required_tags=(tag,))
    controller = ConstructionController(graph_adapter, binder, CoordinatorTrainer())
    with patch.object(torch.optim.AdamW, "step", side_effect=AssertionError("training prohibited")):
        controlled = controller.run(session_for(task, graph), base=decks[0], verifier=None)
    assert not controlled["construction_passed"]
    assert all(p["stage_3"]["candidate_trace"]["layers"]["status"] == "evaluated" for p in controlled["phases"] if p["role"] == "build_optimizer")
    final = controlled["construction_candidate"]
    assert final["deck"] == final["layer_evaluation"]["axis"]["inventory"]
    assert final["basic_cb"]["status"] == "not_run"
    assert controlled["training_status"]["graph_role_updates"] == {"build_goal": 0, "build_optimizer": 0}
    for role in gpu_models:
        for key, value in gpu_models[role].named_parameters():
            torch.testing.assert_close(snapshots[role][key], value, rtol=0, atol=0)
            assert value.grad is None
    torch.cuda.synchronize(device)
    driver = subprocess.run(["nvidia-smi", "--query-gpu=driver_version", "--format=csv,noheader"],
        capture_output=True, text=True, check=True, timeout=15).stdout.strip()
    return {"kind": "construction-flow-gpu-engineering-v1", "passed": True,
        "python": sys.version, "executable": sys.executable, "source_root": str(ROOT),
        "torch": torch.__version__, "cuda_runtime": torch.version.cuda, "driver": driver,
        "device": str(device), "gpu": torch.cuda.get_device_name(device),
        "elapsed_seconds": time.perf_counter()-started, "peak_allocated_bytes": torch.cuda.max_memory_allocated(device),
        "roles": results, "encoder_batch_tensors": sorted(cpu_batch), "model_feature_version": FEATURE_VERSION,
        "controller_actual_generation": True, "controller_phases": len(controlled["phases"]),
        "controller_layer_sources": [p["stage_3"]["candidate_trace"]["layers"]["context_source"] for p in controlled["phases"]],
        "controller_candidates_per_phase": [len(p["stage_3"]["candidate_trace"]["candidates"]) for p in controlled["phases"]],
        "controller_final_inventory_equal": True, "weights_unchanged": True,
        "new_features_integrated_into_model": False, "optimizer_steps": 0, "backward_calls": 0,
        "checkpoint_io": False, "cb_execution": False, "native_engine_execution": False, "formal_training": False,
        "tolerances": {"forward": {"rtol": 1e-5, "atol": 1e-6}, "integer_status_probability_roundtrip": "exact"}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--layer", choices=("axis", "relations", "flow"), default="axis")
    args = parser.parse_args()
    print("Starting explicit CUDA engineering validation (fresh weights; no optimizer step).", flush=True)
    result = {"axis": validate, "relations": validate_relations, "flow": validate_flow}[args.layer]()
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(result, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
