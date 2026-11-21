"""Atomically commit a construction state and export its session revision."""

import gzip
import json
import os
from pathlib import Path
from tempfile import TemporaryDirectory
import zlib

from .validation import ContractError, fields, integer, parse_json, read_json, text


CHECKPOINT_VERSION = 'construction-checkpoint-v1'
SESSION_EXPORT_VERSION = 'construction-session-export-v1'
KERNEL_FILENAME = 'kernel.json.gz'
LEGACY_KERNEL_FILENAME = 'kernel.json'


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
    if path.name.lower().endswith('.json.gz'):
        # json.dumps uses the C encoder. Encode UTF-8 in chunks so the
        # compressed path does not hold a second full serialized copy.
        encoded = json.dumps(value, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
        chunk_size = 1024 * 1024
        with temporary.open('wb') as output:
            with gzip.GzipFile(filename='', fileobj=output, mode='wb', compresslevel=1, mtime=0) as compressed:
                for offset in range(0, len(encoded), chunk_size):
                    compressed.write(encoded[offset:offset+chunk_size].encode('utf-8'))
                compressed.write(b'\n')
            output.flush()
            os.fsync(output.fileno())
    else:
        with temporary.open('w', encoding='utf-8') as output:
            json.dump(value, output, ensure_ascii=False, separators=(',', ':'), allow_nan=False)
            output.write('\n')
            output.flush()
            os.fsync(output.fileno())
    temporary.replace(path)


class ConstructionCheckpoint:
    """One writer owns a checkpoint path. Only the replaced file commits."""

    def __init__(self, path, *, revision=0):
        self.path = path
        self.revision = integer(revision, 'construction checkpoint revision')

    @staticmethod
    def read(path):
        name = path.name.lower()
        if not name.endswith(('.json', '.json.gz')) or name in ('session.json', 'session.json.gz'):
            raise ContractError('construction resume requires a committed kernel JSON file')
        if name.endswith('.json.gz'):
            with gzip.open(path, 'rt', encoding='utf-8') as source:
                data = parse_json(source.read())
        else:
            data = read_json(path)
        if isinstance(data, dict) and data.get('schema_version') == 1 and 'selections' in data and 'sessions' in data:
            return dict(version=CHECKPOINT_VERSION, revision=0, stop_reason=None, state=data)
        data = fields(data, {'version', 'revision', 'stop_reason', 'state'})
        if data['version'] != CHECKPOINT_VERSION or not isinstance(data['state'], dict):
            raise ContractError('unsupported construction checkpoint')
        integer(data['revision'], 'construction checkpoint revision', 1)
        text(data['stop_reason'], 'construction checkpoint stop reason')
        return data

    def commit(self, state, *, stop_reason):
        revision = self.revision + 1
        write_json(self.path, dict(version=CHECKPOINT_VERSION, revision=revision, stop_reason=stop_reason, state=state))
        self.revision = revision
        return revision

    def export_session(self, path, state):
        write_json(path, dict(version=SESSION_EXPORT_VERSION, revision=self.revision, state=state))


class ConstructionReferenceCache:
    """Optional, bounded disk cache for finished reference calculations."""

    VERSION = 'construction-reference-cache-v1'
    MAX_COMPRESSED_BYTES = 8 * 1024 * 1024
    MAX_RECORD_CHARS = 48 * 1024 * 1024

    def __init__(self, directory):
        self.directory = directory

    def _path(self, binding):
        from .build_contracts import digest

        # Sixteen slots keep storage bounded. The full binding is checked on read.
        return self.directory / (digest(binding)[0] + '.json.gz')

    def load(self, binding, *, task, deck, policy, catalog):
        from .build_contracts import digest
        from .construction_layer_flow import NORMALIZATION_VERSION, functional_asset_version
        from .construction_quality import validate_evaluation

        path = self._path(binding)
        try:
            if path.stat().st_size > self.MAX_COMPRESSED_BYTES:
                return None
            with gzip.open(path, 'rt', encoding='utf-8') as source:
                payload = source.read(self.MAX_RECORD_CHARS + 1)
            if len(payload) > self.MAX_RECORD_CHARS:
                return None
            record = fields(parse_json(payload), {'version', 'binding', 'evaluation'})
            if record['version'] != self.VERSION or record['binding'] != binding:
                return None
            evaluation = record['evaluation']
            validate_evaluation(evaluation)
            inventory = deck.to_dict()
            expected = dict(task_sha256=task.sha256, inventory=inventory, deck_sha256=digest(inventory),
                            logic_sha256=digest(None), policy_sha256=digest(policy),
                            normalization_version=NORMALIZATION_VERSION,
                            asset_version=functional_asset_version(catalog), evaluation_timed_out=False)
            if ('calculation_pending' in evaluation
                    or any(evaluation.get(key) != value for key, value in expected.items())):
                return None
        except (OSError, ValueError, EOFError, RecursionError, zlib.error):
            return None
        return evaluation

    def store(self, binding, evaluation):
        path = self._path(binding)
        try:
            self.directory.mkdir(parents=True, exist_ok=True)
            with TemporaryDirectory(dir=self.directory, prefix='pending-') as scratch:
                temporary = Path(scratch) / path.name
                write_json(temporary, dict(version=self.VERSION, binding=binding, evaluation=evaluation))
                if temporary.stat().st_size <= self.MAX_COMPRESSED_BYTES:
                    temporary.replace(path)
        except OSError:
            # A failed cache write must leave both the active calculation and
            # any previous complete entry usable.
            pass
