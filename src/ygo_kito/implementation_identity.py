"""Content identity for the complete Python policy/observation implementation."""
import hashlib
from pathlib import Path

from .validation import ContractError


def source_tree_snapshot(package_root):
    root = Path(package_root).resolve(strict=True)
    if not root.is_dir():
        raise ContractError("Python implementation package root is unavailable")
    result = {}
    try:
        for path in sorted(root.rglob("*")):
            if path.is_symlink():
                raise ContractError("Python implementation source symlinks are unsupported")
            if path.suffix == ".py" and path.is_file():
                result[path.relative_to(root).as_posix()] = hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as error:
        raise ContractError("Python implementation source tree cannot be read") from error
    if "__init__.py" not in result:
        raise ContractError("complete Python implementation package required")
    return result


def assert_source_tree(package_root, expected):
    if source_tree_snapshot(package_root) != expected:
        raise ContractError("Python implementation content or module membership changed after driver binding")
