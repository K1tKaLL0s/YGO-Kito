"""Determinism and path helpers for axis_generic runs."""
import os
import random
import sys
from pathlib import Path
from contextlib import contextmanager


def hash_seed_is_fixed():
    return os.environ.get("PYTHONHASHSEED") == "0"


def warn_if_hash_seed_unset(stream=sys.stderr):
    if not hash_seed_is_fixed():
        print("WARNING: PYTHONHASHSEED is not 0; set it before starting Python for reproducible prepare/ablation.",
              file=stream)


def seed_preparation(seed):
    """Preparation uses local seeded samplers and never initializes a device."""
    random.seed(seed)


def seed_everything(seed):
    random.seed(seed)
    try:
        import numpy as np
        np.random.seed(seed)
    except Exception:
        pass
    try:
        import torch
        torch.manual_seed(seed)
        torch.cuda.manual_seed_all(seed)
        torch.backends.cudnn.deterministic = True
        torch.backends.cudnn.benchmark = False
    except Exception:
        pass


def data_root(config, default):
    value = config.get("data_root")
    return Path(value).resolve() if value else Path(default).resolve()


@contextmanager
def training_lock(run):
    """OS lock releases on process exit; no stale permission flag to clear."""
    run = Path(run)
    run.mkdir(parents=True,exist_ok=True)
    with (run/'.training.lock').open('a+b') as stream:
        stream.seek(0,2)
        if stream.tell()==0:
            stream.write(b'0')
            stream.flush()
        stream.seek(0)
        if os.name=='nt':
            import msvcrt
            msvcrt.locking(stream.fileno(),msvcrt.LK_NBLCK,1)
        else:
            import fcntl
            fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
        try:
            yield
        finally:
            stream.seek(0)
            if os.name=='nt':
                msvcrt.locking(stream.fileno(),msvcrt.LK_UNLCK,1)
            else:
                fcntl.flock(stream,fcntl.LOCK_UN)
