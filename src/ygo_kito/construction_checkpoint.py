"""Atomically commit a construction state and export its session revision."""

import json
import os

from .validation import ContractError, fields, integer, read_json, text


CHECKPOINT_VERSION = 'construction-checkpoint-v1'
SESSION_EXPORT_VERSION = 'construction-session-export-v1'


def write_json(path, value):
    temporary = path.with_suffix(path.suffix + '.tmp')
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
        if path.suffix.lower() != '.json' or path.name.lower() == 'session.json':
            raise ContractError('construction resume requires a committed kernel JSON file')
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
