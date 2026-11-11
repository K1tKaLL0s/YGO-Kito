"""Wall-clock control for one process launched and owned by this host."""

import math
import os
from pathlib import Path
import signal
import subprocess
import time

from .validation import ContractError


def _reap(child, log):
    if child.poll() is not None:
        return child.wait(), None
    tree_terminated = False
    if os.name == 'nt':
        taskkill = Path(os.environ.get('SystemRoot', r'C:\Windows'))/'System32'/'taskkill.exe'
        try:
            result = subprocess.run([str(taskkill), '/PID', str(child.pid), '/T', '/F'], stdin=subprocess.DEVNULL,
                           stdout=log, stderr=subprocess.STDOUT, timeout=2,
                           creationflags=subprocess.CREATE_NO_WINDOW, check=False)
            tree_terminated = result.returncode == 0
        except (OSError, subprocess.TimeoutExpired):
            pass
    else:
        try:
            os.killpg(child.pid, signal.SIGKILL)
            tree_terminated = True
        except ProcessLookupError:
            pass
    if child.poll() is None:
        child.kill()
    return child.wait(timeout=2), tree_terminated


def run_owned_process(argv, *, cwd, log_path, seconds, env=None, cancel_requested=None):
    if type(seconds) not in (int, float) or not math.isfinite(seconds) or seconds <= 0:
        raise ContractError('owned worker requires a positive finite deadline')
    started = time.monotonic()
    with Path(log_path).open('xb') as log:
        if cancel_requested is not None and cancel_requested():
            return dict(process_started=False, child_reaped=False, exit_code=None, stop_reason='user_pause', elapsed_seconds=0.)
        child = subprocess.Popen(argv, cwd=cwd, env=env, stdin=subprocess.DEVNULL, stdout=log, stderr=subprocess.STDOUT,
            start_new_session=os.name != 'nt', creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
        reason = 'completed'
        try:
            while child.poll() is None:
                remaining = seconds - (time.monotonic() - started)
                if cancel_requested is not None and cancel_requested():
                    reason = 'user_pause'
                    break
                if remaining <= 0:
                    reason = 'timeout'
                    break
                try:
                    child.wait(timeout=min(.05, remaining))
                except subprocess.TimeoutExpired:
                    continue
        except KeyboardInterrupt:
            reason = 'user_pause'
        finally:
            code, tree_terminated = _reap(child, log)
        if reason == 'completed' and code:
            reason = 'worker_failed'
        return dict(process_started=True, child_reaped=True, exit_code=code, stop_reason=reason,
                    process_tree_terminated=tree_terminated, elapsed_seconds=time.monotonic()-started)
