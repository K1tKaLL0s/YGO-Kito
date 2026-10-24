"""Explicit CPU/CUDA FP32 execution; no resource launch or implicit fallback."""
import torch
from .validation import ContractError, fields


def resolve_device(value="cpu"):
    try:
        device = torch.device(value)
    except (TypeError, RuntimeError) as error:
        raise ContractError("execution device must be cpu or cuda[:index]") from error
    if device.type == "cpu" and device.index is None:
        return device
    if device.type != "cuda":
        raise ContractError("only CPU/CUDA FP32 execution is implemented")
    index = 0 if device.index is None else device.index
    if not torch.cuda.is_available() or index >= torch.cuda.device_count():
        raise ContractError("explicit CUDA device unavailable; no CPU fallback")
    return torch.device("cuda", index)


def model_device(model):
    devices = {parameter.device for parameter in model.parameters()}
    if len(devices) != 1:
        raise ContractError("model parameters require one execution device")
    return resolve_device(next(iter(devices)))


def execution_metadata(device):
    return {"schema_version": 1, "device": str(resolve_device(device)), "dtype": "float32"}


def checkpoint_device(saved=None, requested=None):
    # Absence is an old CPU checkpoint, not permission to migrate it silently.
    saved = {"schema_version": 1, "device": "cpu", "dtype": "float32"} if saved is None else saved
    fields(saved, {"schema_version", "device", "dtype"})
    if type(saved["schema_version"]) is not int or saved["schema_version"] != 1 or saved["dtype"] != "float32":
        raise ContractError("execution checkpoint schema/dtype differs")
    target = resolve_device(saved["device"] if requested is None else requested)
    if str(target) != saved["device"]:
        raise ContractError("checkpoint execution device differs; explicit migration is required")
    return target


def checkpoint_execution(state, requested=None):
    if ("execution" in state) != ("device_rng" in state):
        raise ContractError("execution metadata and device RNG must be saved together")
    return checkpoint_device(state.get("execution"), requested)


def move_batch(value, device):
    if isinstance(device, str):
        device = resolve_device(device)
    if isinstance(value, torch.Tensor):
        return value.to(device=device)
    if isinstance(value, dict):
        return {key: move_batch(item, device) for key, item in value.items()}
    if isinstance(value, list):
        return [move_batch(item, device) for item in value]
    if isinstance(value, tuple):
        return tuple(move_batch(item, device) for item in value)
    return value


def optimizer_to(optimizer, device):
    # AdamW's scalar step remains on CPU for the existing noncapturable optimizer.
    for state in optimizer.state.values():
        for key, value in state.items():
            state[key] = value.cpu() if key == "step" and isinstance(value, torch.Tensor) else move_batch(value, device)


def capture_device_rng(device):
    device = resolve_device(device)
    return {"cpu": torch.get_rng_state(), "cuda": torch.cuda.get_rng_state(device) if device.type == "cuda" else None}


def restore_device_rng(state, device):
    device = resolve_device(device)
    fields(state, {"cpu", "cuda"})
    if (not isinstance(state["cpu"], torch.Tensor) or state["cpu"].dtype != torch.uint8
            or state["cpu"].device.type != "cpu" or state["cpu"].ndim != 1
            or (device.type == "cuda") != (state["cuda"] is not None)):
        raise ContractError("execution RNG checkpoint differs")
    if device.type == "cuda" and (not isinstance(state["cuda"], torch.Tensor)
            or state["cuda"].dtype != torch.uint8 or state["cuda"].device.type != "cpu" or state["cuda"].ndim != 1):
        raise ContractError("CUDA RNG checkpoint differs")
    previous = capture_device_rng(device)
    if (state["cpu"].numel() != previous["cpu"].numel()
            or (device.type == "cuda" and state["cuda"].numel() != previous["cuda"].numel())):
        raise ContractError("execution RNG state length differs")
    try:
        torch.set_rng_state(state["cpu"])
        if device.type == "cuda":
            torch.cuda.set_rng_state(state["cuda"], device)
    except (TypeError, RuntimeError, ValueError) as error:
        torch.set_rng_state(previous["cpu"])
        if device.type == "cuda":
            torch.cuda.set_rng_state(previous["cuda"], device)
        raise ContractError("execution RNG restoration failed; previous state restored") from error
