"""Explicit two-model headless self-play, separate from formal course volume.

The existing game adapter owns core execution and PPO admission. This caller
freezes one effective opponent per match, keeps both actual model groups, and
saves only closed small-game boundaries. It does not choose a curriculum ratio,
qualify common-deck coverage, or resume an interrupted native half-game.
"""
from contextlib import contextmanager
from copy import deepcopy
from dataclasses import asdict, dataclass
import fcntl
import hashlib
import io
import json
import math
import os
from pathlib import Path
import re
import shutil
import sqlite3
import time

import torch

from .agent_registry import identifier
from .build_contracts import BuildTask, DeckParts, digest
from .build_pipeline import BuildAssets
from .course_game_adapter import CourseGameAdapter
from .course_models import CourseModels
from .data_isolation import DataIndex
from .group_runner import tree_digest
from .implementation_identity import source_tree_snapshot
from .match_runner import FirstOrderPolicy, MatchParticipant, MatchRules, MatchState, ModelSideboardPolicy
from .model_opponents import FrozenDuelSnapshot, ModelOpponentRuntime
from .validation import ContractError, canonical_json, fields, integer, read_json

PARTITIONS = ('train', 'validation', 'final_eval')
BOUNDARY_GROWTH_BYTES = 4 * 1024 * 1024


class SelfPlayStorageLimit(ContractError):
    pass


@dataclass(frozen=True)
class SelfPlayPlayer:
    player_id: str
    models: CourseModels
    deck: DeckParts
    task: BuildTask | None = None

    def __post_init__(self):
        identifier(self.player_id)
        if not isinstance(self.models, CourseModels) or not isinstance(self.deck, DeckParts):
            raise ContractError('self-play requires actual course models and a typed own deck')
        if self.task is not None and not isinstance(self.task, BuildTask):
            raise ContractError('self-play own task must be typed')

    @property
    def own_task(self): return self.models.builder.task if self.task is None else self.task


class FrozenModelPool:
    """Immutable initial/history snapshots with explicit partition assignment."""
    def __init__(self):
        self._entries, self._initial, self._assignments = {}, {}, {}

    def capture(self, player, assets, *, initial=False):
        if not isinstance(player, SelfPlayPlayer): raise ContractError('typed source player required')
        if initial and player.player_id in self._initial: raise ContractError('initial snapshot cannot be replaced')
        model = player.models
        model._check()
        snapshot = FrozenDuelSnapshot.capture(model.duel, assets=assets,
            adapter_session=model.sessions['duel'], source_binding=model.binding,
            source_label='selfplay-' + player.player_id + '-effective-' + str(model.sessions['duel'].updates))
        key = 'snapshot-' + digest({'player': player.player_id, 'snapshot': snapshot.identity()})[:48]
        if key not in self._entries: self._entries[key] = (player.player_id, snapshot)
        if initial: self._initial[player.player_id] = key
        return key

    def snapshot(self, key):
        if key not in self._entries: raise ContractError('unknown retained model snapshot')
        snapshot = self._entries[key][1]; snapshot.assert_integrity()
        return snapshot

    def player_id(self, key):
        self.snapshot(key)
        return self._entries[key][0]

    def assign(self, key, purpose):
        if purpose not in PARTITIONS: raise ContractError('explicit snapshot partition required')
        snapshot = self.snapshot(key).identity()
        identity = digest({k: snapshot[k] for k in ('model_sha256', 'vocab_sha256')} |
                          {'resources': snapshot['provenance']['resources'],
                           'versions': snapshot['provenance']['source_versions']})
        for other, split in self._assignments.items():
            candidate = self.snapshot(other).identity()
            candidate_identity = digest({k: candidate[k] for k in ('model_sha256', 'vocab_sha256')} |
                {'resources': candidate['provenance']['resources'], 'versions': candidate['provenance']['source_versions']})
            if candidate_identity == identity and split != purpose:
                raise ContractError('same actual frozen model cannot cross self-play partitions')
        if key in self._assignments and self._assignments[key] != purpose:
            raise ContractError('retained snapshot partition cannot be relabelled')
        self._assignments[key] = purpose

    def runtime(self, key, purpose, *, policy_mode='greedy'):
        self.assign(key, purpose)
        return ModelOpponentRuntime(self.snapshot(key), key, source='engineering_fixture', policy_mode=policy_mode)

    def manifest(self):
        return {'initial': deepcopy(self._initial), 'history': {key: {'player_id': player,
            'partition': self._assignments.get(key), 'identity': snapshot.identity()}
            for key, (player, snapshot) in self._entries.items()}, 'strength_qualified': False}

    def state_dict(self):
        body = {'schema_version': 1, 'initial': deepcopy(self._initial),
            'assignments': deepcopy(self._assignments), 'entries': {key: {'player_id': player,
                'snapshot': snapshot.to_state()} for key, (player, snapshot) in self._entries.items()}}
        return dict(body, state_sha256=tree_digest(body))

    @classmethod
    def from_state(cls, value):
        fields(value, {'schema_version', 'initial', 'assignments', 'entries', 'state_sha256'})
        body = {k: v for k, v in value.items() if k != 'state_sha256'}
        if value['schema_version'] != 1 or tree_digest(body) != value['state_sha256']:
            raise ContractError('retained model pool state differs')
        result = cls()
        for key, row in value['entries'].items():
            fields(row, {'player_id', 'snapshot'}); identifier(row['player_id'])
            snapshot = FrozenDuelSnapshot.from_state(row['snapshot'])
            if key != 'snapshot-' + digest({'player': row['player_id'], 'snapshot': snapshot.identity()})[:48]:
                raise ContractError('retained snapshot key differs from its actual identity')
            result._entries[key] = (row['player_id'], snapshot)
        for player, key in value['initial'].items():
            if key not in result._entries or result._entries[key][0] != player:
                raise ContractError('initial snapshot player binding differs')
        result._initial = deepcopy(value['initial'])
        for key, purpose in value['assignments'].items(): result.assign(key, purpose)
        return result


def _config(value, players):
    d = fields(value, {'series_id'}, {'training_enabled', 'ratio', 'allocation', 'opponent_policy_mode', 'checkpoint_policy'})
    identifier(d['series_id'])
    if len(d['series_id']) > 40: raise ContractError('series id must leave room for stable match ids')
    result = {'training_enabled': False, 'ratio': None, 'allocation': None, 'opponent_policy_mode': 'greedy', **d}
    policy = result.setdefault('checkpoint_policy', {'keep_last': None, 'milestone_every': None,
        'min_free_bytes': 64 * 1024 * 1024, 'max_state_bytes': None})
    fields(policy, {'keep_last', 'milestone_every', 'min_free_bytes', 'max_state_bytes'})
    for key in ('keep_last', 'milestone_every'):
        if policy[key] is not None: integer(policy[key], key, 1, 1000000)
    integer(policy['min_free_bytes'], 'minimum physical free bytes', 0, 30000000000)
    if policy['max_state_bytes'] is not None: integer(policy['max_state_bytes'], 'series-only byte cap', 1, 30000000000)
    if result['opponent_policy_mode'] not in ('greedy', 'sample'):
        raise ContractError('explicit supported frozen opponent policy mode required')
    if type(result['training_enabled']) is not bool: raise ContractError('explicit self-play enable flag required')
    if result['ratio'] is not None and (type(result['ratio']) not in (int, float) or
            not math.isfinite(result['ratio']) or not 0 < result['ratio'] <= 1):
        raise ContractError('declared self-play ratio must be finite and in (0,1]')
    allocation = result['allocation']
    if allocation is not None:
        fields(allocation, {'max_matches', 'max_small_games_per_player', 'wall_seconds', 'prior_budget_seconds'})
        integer(allocation['max_matches'], 'explicit self-play match allocation', 1, 100000)
        fields(allocation['max_small_games_per_player'], set(players))
        for n in allocation['max_small_games_per_player'].values(): integer(n, 'own game allocation', 1, 300000)
        wall, prior = allocation['wall_seconds'], allocation['prior_budget_seconds']
        if (type(wall) not in (int, float) or not math.isfinite(wall) or wall <= 0 or
                prior is not None and (type(prior) not in (int, float) or not math.isfinite(prior) or prior < 0) or
                prior is not None and prior + wall > 360000):
            raise ContractError('self-play allocation must retain the original 100-hour upper bound')
    if result['training_enabled'] and (result['ratio'] is None or allocation is None):
        raise ContractError('self-play training requires a separately declared ratio and allocation')
    if result['training_enabled'] and allocation['prior_budget_seconds'] is None:
        raise ContractError('unknown prior activity cannot enable self-play training')
    return deepcopy(result)


@contextmanager
def _frozen(players):
    states = [(p.models, p.models.rng_state(), p.models.fingerprint()) for p in players]
    try:
        for model, _, _ in states:
            for network in model.models().values(): network.eval()
        yield
    finally:
        for model, rng, _ in states: model.restore_rng(rng)
        if any(model.fingerprint() != before for model, _, before in states):
            raise ContractError('functional self-play changed a model, optimizer or training cursor')


class SelfPlaySeries:
    def __init__(self, *, players, assets, data_index, state_root, config):
        if (not isinstance(players, (tuple, list)) or len(players) != 2 or
                any(not isinstance(p, SelfPlayPlayer) for p in players) or
                len({p.player_id for p in players}) != 2):
            raise ContractError('exactly two distinct actual self-play players required')
        if not isinstance(assets, BuildAssets) or not isinstance(data_index, DataIndex):
            raise ContractError('actual typed assets and a private data index required')
        self.players = {p.player_id: p for p in players}; self.assets, self.index = assets, data_index
        self.config = _config(config, self.players)
        self.root = Path(state_root).resolve(); self.root.mkdir(parents=True, exist_ok=True)
        self._index_mode()
        self._independent()
        allowed = set.intersection(*(set(p.models.builder.encoder.available_ids) for p in players))
        self.rules = MatchRules(assets.rows, assets.limits, allowed)
        for p in players:
            if p.models.builder.encoder.assets is not assets: raise ContractError('both groups must use the same actual period assets')
            if str(p.models.duel.device) != 'cpu': raise ContractError('current self-play model transport is CPU only')
            assets.validate(p.own_task, p.deck); self.rules.validate(p.deck)
        self.binding = {'kind': 'two-course-model-selfplay-v1', 'config': deepcopy(self.config),
            'players': {p.player_id: {'source': deepcopy(p.models.binding), 'deck': p.deck.to_dict(),
                'task': p.own_task.to_dict(), 'duel_config': asdict(p.models.duel.config)} for p in players},
            'rules_sha256': self.rules.sha256, 'resources': deepcopy(assets.receipt),
            'period_context': deepcopy(getattr(assets, 'period_context', None)),
            'implementation': source_tree_snapshot(Path(__file__).resolve().parent)}
        self._binding_sha = digest(self.binding)
        self.pool = FrozenModelPool()
        for p in players: self.pool.capture(p, assets, initial=True)
        self.records, self.pending, self.evaluation_windows = [], None, {}
        self.revision, self.desired = 0, 'ready'
        self.active_seconds, self._activity_tick, self._last_checkpoint = 0., None, None
        self._blob_refs, self._match_refs, self._manifest_sha = {}, {}, None

    def _index_mode(self):
        # Functional smoke has its own experiment/index. It must not reserve a
        # future training pool's initial versions as held-out opponents.
        with sqlite3.connect(self.index.path) as db:
            rows = [json.loads(row[0]) for row in db.execute('SELECT payload FROM datasets')]
        if any(row['experiment_id'] != self.config['series_id'] or
                (row['purpose'] == 'train') != self.config['training_enabled'] for row in rows):
            raise ContractError('functional and training self-play require separate experiment/index/state scopes')

    def _independent(self):
        values = list(self.players.values()); a, b = (p.models for p in values)
        objects = lambda m: [m, m.duel, m.builder, m.coordinator, m.policy_rng, m.duel.policy_rng,
            m.duel.batch_rng, m.builder.batch_rng, m.coordinator.batch_rng, *m.models().values(), *m.sessions.values(),
            *(s.rng for s in m.sessions.values()), *(s.optimizer for s in m.sessions.values()),
            *m.builder.optimizers.values(), m.duel.optimizer, m.coordinator.optimizer]
        if {id(o) for o in objects(a)} & {id(o) for o in objects(b)}:
            raise ContractError('self-play learner groups, optimizers and RNG must not alias')
        if {p.data_ptr() for m in a.models().values() for p in m.parameters()} & {
                p.data_ptr() for m in b.models().values() for p in m.parameters()}:
            raise ContractError('self-play learner parameter storage must be independent')
        if set(a.duel.config.game_seeds) & set(b.duel.config.game_seeds):
            raise ContractError('each self-play learner must own a distinct physical training seed schedule')

    def _check(self):
        self._independent(); self.rules.assert_integrity(); self._index_mode()
        if (digest(self.binding) != self._binding_sha or self.config != self.binding['config'] or
                source_tree_snapshot(Path(__file__).resolve().parent) != self.binding['implementation']):
            raise ContractError('self-play source/configuration binding changed')
        for p in self.players.values():
            p.models._check()
            if (p.deck.to_dict() != self.binding['players'][p.player_id]['deck'] or
                    p.own_task.to_dict() != self.binding['players'][p.player_id]['task'] or
                    p.models.binding != self.binding['players'][p.player_id]['source'] or
                    asdict(p.models.duel.config) != self.binding['players'][p.player_id]['duel_config']):
                raise ContractError('self-play player/task/configuration changed')

    def _index_sha(self):
        from .scenario_course import index_identity
        return index_identity(self.index)

    def status(self):
        return {'kind': 'two-model-selfplay-status', 'series_id': self.config['series_id'], 'desired': self.desired,
            'functional_matches': sum(r['complete'] and r['purpose'] != 'train' for r in self.records),
            'selfplay_training_matches': sum(r['complete'] and r['purpose'] == 'train' for r in self.records),
            'attempted_matches': len(self.records) + int(self.pending is not None),
            'small_game_attempts': sum(len(r['summary']['games']) for r in self.records) +
                (0 if self.pending is None else len(self.pending['state'].summary()['games'])),
            'formal_training_matches': 0, 'common_deck_coverage_qualified': False,
            'formal_acceptance_verified': False, 'ratio': self.config['ratio'],
            'active_seconds': self.active_seconds, 'billing_verified': False,
            'budget_units_confirmed': False, 'allocation': deepcopy(self.config['allocation']),
            'storage': {'scope': 'this-series-only', 'state_bytes': self._state_bytes(),
                'checkpoint_policy': deepcopy(self.config['checkpoint_policy']),
                'all_assets_trajectories_and_temporary_peak_under_30GB_verified': False},
            'pending_match': None if self.pending is None else self.pending['state'].summary(),
            'history_pool': self.pool.manifest()}

    def _window(self, purpose, actor_id=None, snapshot_id=None):
        scope = {p.player_id: {'versions': p.models.versions(), 'deck': p.deck.to_dict()} for p in self.players.values()}
        if purpose in self.evaluation_windows and self.evaluation_windows[purpose]['players'] != scope:
            raise ContractError('fixed self-play evaluation models/decks changed')
        window = self.evaluation_windows.setdefault(purpose, {'players': scope, 'opponents': {}})
        if snapshot_id is not None:
            previous = window['opponents'].get(actor_id)
            if previous is not None and previous != snapshot_id:
                raise ContractError('fixed self-play evaluation opponent changed')
            window['opponents'][actor_id] = snapshot_id

    def functional_match(self, *, format='bo1', actor_id, seed_pairs, purpose='validation', opponent_snapshot_id=None):
        if self.config['training_enabled']:
            raise ContractError('functional presampling requires a separate disabled series/index/experiment')
        if purpose not in ('validation', 'final_eval'): raise ContractError('functional matches require an explicit held-out partition')
        try: self._run(format, actor_id, purpose, seed_pairs, opponent_snapshot_id)
        except SelfPlayStorageLimit:
            if (self.root/'in-flight.json').exists(): raise
            self.desired = 'storage_blocked'
        return self.status()

    def train_match(self, *, format='bo1', actor_id=None, opponent_snapshot_id=None):
        if not self.config['training_enabled']: raise ContractError('self-play training is disabled; no curriculum ratio was enabled')
        if self.evaluation_windows: raise ContractError('fixed evaluation has begun; its series cannot resume training')
        ids = tuple(self.players)
        ordinal = sum(r['purpose'] == 'train' for r in self.records)
        expected = ids[ordinal % 2]
        if actor_id not in (None, expected): raise ContractError('training actor must rotate between the independent learners')
        try: self._run(format, expected, 'train', (), opponent_snapshot_id)
        except SelfPlayStorageLimit:
            if (self.root/'in-flight.json').exists(): raise
            self.desired = 'storage_blocked'
        return self.status()

    def _charge(self):
        if self._activity_tick is not None:
            now = time.monotonic()
            self.active_seconds += max(0., now-self._activity_tick)
            self._activity_tick = now

    def _latest(self):
        path = self.root/'latest.json'
        if path.is_symlink(): raise ContractError('self-play checkpoint pointer cannot be a symlink')
        if path.exists():
            pointer = read_json(path)
            if self._last_checkpoint is None or pointer != self._last_checkpoint:
                raise ContractError('stale self-play reader must restore the latest checkpoint before executing')
            artifact = self.root/pointer['path']
            if artifact.is_symlink() or hashlib.sha256(artifact.read_bytes()).hexdigest() != pointer['sha256']:
                raise ContractError('latest self-play checkpoint artifact differs')
        elif self._last_checkpoint is not None:
            raise ContractError('latest self-play checkpoint disappeared')

    @contextmanager
    def _operation(self):
        with (self.root/'.series.lock').open('a') as lock:
            try: fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError as error: raise ContractError('another self-play worker owns this series') from error
            self._latest()
            self._activity_tick = time.monotonic()
            try:
                yield
            finally:
                self._charge(); self._activity_tick = None
                if self.revision and not (self.root/'in-flight.json').exists(): self.save()

    def _run(self, format, actor_id, purpose, seed_pairs, opponent_snapshot_id=None):
        with self._operation():
            self._check()
            if format not in ('bo1', 'bo3') or actor_id not in self.players: raise ContractError('explicit match format and actor required')
            if (self.root/'in-flight.json').exists(): raise ContractError('uncertain half-game exists; automatic replay is forbidden')
            if self.revision == 0 and (self.root/'latest.json').exists(): raise ContractError('existing self-play state must be explicitly restored')
            if self.desired == 'needs_inspection': raise ContractError('unresolved self-play match requires inspection')
            pairs = tuple(tuple(p) for p in seed_pairs)
            if purpose != 'train':
                if len(pairs) != (1 if format == 'bo1' else 3): raise ContractError('predeclare one or three held-out seed pairs for this match')
                seen = set()
                training_seeds = {s for p in self.players.values() for s in p.models.duel.config.game_seeds}
                for pair in pairs:
                    if len(pair) != 2: raise ContractError('private game/policy seed pair required')
                    for s in pair: integer(s, 'self-play held-out seed', 0, 2**32-8)
                    if pair[0] in training_seeds or pair[0] in seen: raise ContractError('self-play held-out physical seeds must be distinct from both learners')
                    seen.add(pair[0])
                self._window(purpose)
            if self.pending is None:
                if purpose == 'train':
                    allocation = self.config['allocation']; worst = 1 if format == 'bo1' else 3
                    if sum(r['purpose'] == 'train' for r in self.records) >= allocation['max_matches']:
                        raise ContractError('explicit self-play match allocation exhausted')
                    used = sum(len(r['summary']['games']) for r in self.records if r['purpose'] == 'train' and r['actor_id'] == actor_id)
                    actor = self.players[actor_id]
                    if (used + worst > allocation['max_small_games_per_player'][actor_id] or
                            actor.models.sessions['duel'].updates + worst > min(actor.models.sessions['duel'].config.max_updates,
                                len(actor.models.duel.config.game_seeds))):
                        raise ContractError('actor seed/LoRA or explicit self-play small-game allocation is insufficient')
                opponent = next(p for i, p in self.players.items() if i != actor_id)
                if opponent_snapshot_id is not None and self.pool.player_id(opponent_snapshot_id) != opponent.player_id:
                    raise ContractError('selected historical snapshot must belong to the other player')
                snapshot_id = (self.pool.capture(opponent, self.assets) if opponent_snapshot_id is None else opponent_snapshot_id)
                runtime = self.pool.runtime(snapshot_id, purpose, policy_mode=self.config['opponent_policy_mode'])
                match_id = self.config['series_id'] + '-match-' + str(len(self.records)+1)
                binding = {'series_binding_sha256': self._binding_sha, 'actor_id': actor_id, 'format': format,
                    'purpose': purpose, 'model_opponent': runtime.identity()}
                state = MatchState(match_id, tuple(MatchParticipant(p.player_id, p.deck) for p in self.players.values()),
                    self.rules, binding, tuple(self.players)[len(self.records) % 2],
                    adapter_revision=getattr(self.assets, 'adapter_revision', 5))
                self.pending = dict(state=state, actor_id=actor_id, purpose=purpose, format=format,
                    snapshot_id=snapshot_id, seed_pairs=pairs, evaluation_cursor=0, receipts=[],
                    side_models={i: p.models.versions()['build_optimizer'] for i, p in self.players.items()})
                self.save()
            p = self.pending
            if (p['actor_id'], p['purpose'], p['format'], p['seed_pairs']) != (actor_id, purpose, format, pairs):
                raise ContractError('unfinished self-play match cannot change actor/partition/format/seeds')
            if opponent_snapshot_id is not None and p['snapshot_id'] != opponent_snapshot_id:
                raise ContractError('unfinished match cannot change its frozen opponent snapshot')
            if purpose != 'train': self._window(purpose, actor_id, p['snapshot_id'])
            self.desired = 'running'
            while True:
                self._charge()
                state = p['state']; summary = state.summary()
                complete = (format == 'bo1' and len(summary['games']) == 1 and summary['games'][0]['completed'] or
                            format == 'bo3' and state.status == 'complete')
                if complete or state.status in ('aborted', 'pending_draw_policy'):
                    self.records.append({k: deepcopy(v) for k, v in p.items() if k != 'state'} |
                        {'complete': bool(complete), 'summary': summary, 'match_state': state.to_dict()})
                    self.pending = None; self.desired = 'ready' if complete else 'needs_inspection'
                    self.save(); return self.status()
                if (self.root/'pause.request').exists():
                    self.desired = 'paused'; self.save(); return self.status()
                if purpose == 'train' and self.active_seconds + self.players[actor_id].models.duel.config.episode_seconds > self.config['allocation']['wall_seconds']:
                    self.desired = 'budget_insufficient_for_next_game'; self.save(); return self.status()
                self._before_game_storage()
                if purpose == 'train': self._game()
                else:
                    with _frozen(tuple(self.players.values())): self._game()

    def _game(self):
        p = self.pending; state = p['state']; actor = self.players[p['actor_id']]
        try:
            if state.status == 'awaiting_sideboards':
                proposals = {}
                for ident, player in self.players.items():
                    if player.models.versions()['build_optimizer'] != p['side_models'][ident]:
                        raise ContractError('own side model changed during a frozen match')
                    policy = ModelSideboardPolicy(player.models.builder.models['build_optimizer'], player.models.builder.encoder,
                        player.own_task, self.assets, self.rules)
                    proposals[ident] = policy(state.intermission_request(ident))
                    p['receipts'].append({'kind': 'own-model-side-selection', 'player_id': ident, 'receipt': deepcopy(policy.last_receipt)})
                state.submit_sideboards(proposals)
            if state.status == 'awaiting_first_choice':
                loser = state._loser
                state.choose_next_first(loser, FirstOrderPolicy('always_first')(state.intermission_request(loser)))
        except (ContractError, RuntimeError, ValueError) as error:
            state.abort_intermission(type(error).__name__)
            return
        runtime = self.pool.runtime(p['snapshot_id'], p['purpose'], policy_mode=self.config['opponent_policy_mode'])
        opponent_id = next(i for i in self.players if i != p['actor_id'])
        adapter = CourseGameAdapter(assets=self.assets, match_state=state, actor_participant_id=p['actor_id'],
            trainer=actor.models.duel, adapter_session=actor.models.sessions['duel'], model_runtime=runtime,
            data_index=self.index, experiment_id=self.config['series_id'], purpose=p['purpose'],
            policy_rng=actor.models.policy_rng, opponent_policy_rng=self._opponent_rng(state, opponent_id),
            evaluation_pairs=p['seed_pairs'], evaluation_cursor=p['evaluation_cursor'])
        spec = state.issue_game_spec()
        marker = self.root/'in-flight.json'
        with marker.open('x', encoding='utf-8') as output:
            output.write(canonical_json({'series_binding_sha256': self._binding_sha, 'match_id': spec.match_id,
                'game_number': spec.game_number, 'automatic_replay': False})); output.flush(); os.fsync(output.fileno())
        result = adapter(spec)
        # A deliberately bounded private receipt/transition envelope gives the
        # pre-game disk reserve a concrete bound. Overflow preserves in-flight
        # uncertainty; no large payload is silently dropped or called complete.
        if len(canonical_json(adapter.last_receipt).encode()) > BOUNDARY_GROWTH_BYTES // 2:
            raise SelfPlayStorageLimit('private game receipt exceeds reserved boundary envelope')
        state.record_game(spec, result)
        p['receipts'].append(deepcopy(adapter.last_receipt)); p['evaluation_cursor'] = adapter.evaluation_cursor
        self.save(); marker.unlink()

    def _opponent_rng(self, state, opponent_id):
        if self.config['opponent_policy_mode'] == 'greedy': return None
        # This controller-only stream can be reconstructed at a closed-game
        # boundary. No seed/order/key is part of a player DTO or model identity.
        source_seed = self.binding['players'][opponent_id]['duel_config']['policy_seed']
        private_seed = int(digest({'kind': 'selfplay-private-opponent-game-rng-v1',
            'source_policy_seed': source_seed, 'match_id': state.match_id,
            'game_number': len(state.summary()['games']) + 1}), 16) % (2**63)
        return torch.Generator(device='cpu').manual_seed(private_seed)

    def _state_bytes(self):
        return sum(p.stat().st_size for p in self.root.rglob('*') if p.is_file() and not p.is_symlink())

    def _room(self, additional_bytes):
        policy = self.config['checkpoint_policy']
        if (policy['max_state_bytes'] is not None and
                self._state_bytes() + additional_bytes > policy['max_state_bytes']):
            self.desired = 'storage_blocked'
            raise SelfPlayStorageLimit('series byte cap cannot reserve the next durable boundary')
        if shutil.disk_usage(self.root).free < policy['min_free_bytes'] + additional_bytes:
            self.desired = 'storage_blocked'
            raise SelfPlayStorageLimit('physical free space is below the declared boundary reserve')

    def _before_game_storage(self):
        # Architecture/vocabulary cannot change inside the series. The only new
        # tensor allocation in the next checkpoint is the actor's Adam moments;
        # the private game receipt/transition has a separate enforced envelope.
        actor = self.players[self.pending['actor_id']]
        optimizer_growth = 2 * sum(p.numel()*p.element_size() for p in actor.models.sessions['duel'].parameters())
        current = 0 if self._last_checkpoint is None else (self.root/self._last_checkpoint['path']).stat().st_size
        # A final small game may write its game boundary, match-close boundary
        # and invocation boundary before another pre-game check. Reserve all
        # three, plus the immutable closed-match document, without relying on
        # pruning the current recovery point to make this game fit.
        self._room(3 * (current + optimizer_growth + BOUNDARY_GROWTH_BYTES) + BOUNDARY_GROWTH_BYTES)

    def _manifest(self):
        path = self.root/'storage-manifest.json'
        if path.is_symlink(): raise ContractError('owned storage manifest cannot be a symlink')
        if not path.exists():
            if self._manifest_sha is not None: raise ContractError('owned storage manifest disappeared')
            return {'schema_version': 1, 'kind': 'selfplay-owned-storage-v1',
                'binding_sha256': self._binding_sha, 'files': {}}
        value = read_json(path)
        fields(value, {'schema_version', 'kind', 'binding_sha256', 'files', 'state_sha256'})
        body = {k:v for k,v in value.items() if k != 'state_sha256'}
        if (value['schema_version'] != 1 or value['kind'] != 'selfplay-owned-storage-v1' or
                value['binding_sha256'] != self._binding_sha or digest(body) != value['state_sha256'] or
                self._manifest_sha not in (None, value['state_sha256'])):
            raise ContractError('owned storage manifest binding/hash changed')
        for name, row in value['files'].items():
            fields(row, {'sha256', 'bytes', 'kind', 'revision', 'deleted'})
            if (not isinstance(name,str) or '..' in Path(name).parts or Path(name).is_absolute() or
                    not isinstance(row['sha256'],str) or re.fullmatch('[0-9a-f]{64}',row['sha256']) is None or
                    row['kind'] not in ('checkpoint','snapshot','match') or type(row['deleted']) is not bool):
                raise ContractError('owned storage manifest entry is malformed')
            integer(row['bytes'],'owned file bytes',0); integer(row['revision'],'owned file revision',1)
        return body

    def _write_manifest(self, body):
        value = dict(body, state_sha256=digest(body))
        temporary = self.root/'storage-manifest.tmp'
        with temporary.open('x',encoding='utf-8') as output:
            output.write(canonical_json(value)); output.flush(); os.fsync(output.fileno())
        os.replace(temporary,self.root/'storage-manifest.json'); self._manifest_sha=value['state_sha256']

    def _read_ref(self, reference, expected_path, manifest):
        if reference['path'] != expected_path: raise ContractError('self-play artifact reference path differs')
        path=self.root/expected_path
        if path.is_symlink() or path.parent.is_symlink(): raise ContractError('self-play artifact reference cannot follow a symlink')
        row=manifest['files'].get(expected_path)
        if row is None or row['deleted'] or row['sha256'] != reference['sha256']:
            raise ContractError('self-play artifact is not an owned validated reference')
        try: raw=path.read_bytes()
        except OSError as error: raise ContractError('referenced self-play artifact is missing') from error
        if len(raw)!=row['bytes'] or hashlib.sha256(raw).hexdigest()!=reference['sha256']:
            raise ContractError('referenced self-play artifact bytes differ')
        return raw

    def _references(self, manifest):
        staged={}; entries={}; records=[]
        for key,(player,snapshot) in self.pool._entries.items():
            state_sha=snapshot._seal
            ref=self._blob_refs.get(key)
            if ref is None:
                path='snapshots/'+state_sha+'.weights'
                if path in manifest['files']:
                    ref={'player_id':player,'path':path,'sha256':manifest['files'][path]['sha256'],'state_sha256':state_sha}
                    raw=self._read_ref(ref,path,manifest)
                    loaded=FrozenDuelSnapshot.from_state(torch.load(io.BytesIO(raw),weights_only=True,map_location='cpu'))
                    if loaded.identity()!=snapshot.identity(): raise ContractError('existing snapshot blob identity differs')
                else:
                    stream=io.BytesIO();torch.save(snapshot.to_state(),stream);raw=stream.getvalue()
                    ref={'player_id':player,'path':path,'sha256':hashlib.sha256(raw).hexdigest(),'state_sha256':state_sha}
                    staged[path]=(raw,'snapshot')
            if ref['player_id']!=player or ref['state_sha256']!=state_sha:
                raise ContractError('retained snapshot reference differs from its source')
            entries[key]=deepcopy(ref)
        for record in self.records:
            key=record['summary']['match_id'];identifier(key)
            raw=canonical_json(record).encode();sha=hashlib.sha256(raw).hexdigest();path='matches/'+key+'.json'
            ref={'match_id':key,'path':path,'sha256':sha}
            if key in self._match_refs and self._match_refs[key]!=ref: raise ContractError('closed match cannot be rewritten')
            if path not in manifest['files']:staged[path]=(raw,'match')
            elif manifest['files'][path]['sha256']!=sha:raise ContractError('closed match artifact cannot be replaced')
            self._match_refs[key]=deepcopy(ref);records.append(ref)
        pool={'schema_version':1,'kind':'frozen-selfplay-pool-references-v1','initial':deepcopy(self.pool._initial),
            'assignments':deepcopy(self.pool._assignments),'entries':entries}
        pool['refs_sha256']=digest(pool)
        return pool,records,staged

    def _counts(self, records=None, pending=...):
        closed=self.records if records is None else records
        current=self.pending if pending is ... else pending
        records=closed+([] if current is None else [{'purpose':current['purpose'],
            'actor_id':current['actor_id'],'complete':False,'summary':current['state'].summary()}])
        return {'complete_matches':{p:sum(r['purpose']==p and r['complete'] for r in records) for p in PARTITIONS},
            'game_attempts_by_actor':{i:sum(len(r['summary']['games']) for r in records if r['actor_id']==i) for i in self.players},
            'next_training_actor_index':sum(r['purpose']=='train' for r in closed)%2,
            'formal_training_matches':0}

    def _prune(self, manifest):
        policy=self.config['checkpoint_policy'];keep=policy['keep_last']
        if keep is None:return
        rows=sorted(((name,row) for name,row in manifest['files'].items() if row['kind']=='checkpoint' and not row['deleted']),
                    key=lambda item:item[1]['revision'])
        protected={name for name,_ in rows[-keep:]}
        protected.add(self._last_checkpoint['path'])
        for name,row in rows:
            rev=row['revision']
            if rev==1 or name in protected or policy['milestone_every'] is not None and rev%policy['milestone_every']==0:continue
            if name!='checkpoint-'+str(rev)+'.weights':raise ContractError('pruning may only address generated checkpoint names')
            self._read_ref({'path':name,'sha256':row['sha256']},name,manifest)
            (self.root/name).unlink();row['deleted']=True
        self._write_manifest(manifest)

    def save(self):
        self._check(); self._latest(); self._charge()
        manifest=self._manifest()
        pool_refs,record_refs,staged=self._references(manifest)
        pending = None if self.pending is None else {k: deepcopy(v) for k, v in self.pending.items() if k != 'state'} | {
            'state': self.pending['state'].to_dict()}
        revision = self.revision + 1
        body = {'schema_version': 2, 'kind': 'two-model-selfplay-boundary-v2', 'binding': deepcopy(self.binding),
            'revision': revision, 'models': {i: p.models.save_state() for i, p in self.players.items()},
            'pool_refs': pool_refs, 'records': record_refs, 'consumed_counts':self._counts(), 'pending': pending,
            'evaluation_windows': deepcopy(self.evaluation_windows), 'desired': self.desired,
            'active_seconds': self.active_seconds,
            'data_index_sha256': self._index_sha()}
        payload = dict(body, state_sha256=tree_digest(body))
        stream=io.BytesIO();torch.save(payload,stream);checkpoint_raw=stream.getvalue()
        self._room(len(checkpoint_raw)+sum(len(raw) for raw,_ in staged.values())+2*len(canonical_json(manifest).encode())+65536)
        for name,(raw,kind) in staged.items():
            target=self.root/name
            if target.parent.is_symlink():raise ContractError('owned storage directory cannot be a symlink')
            target.parent.mkdir(parents=True,exist_ok=True)
            with target.open('xb') as output:output.write(raw);output.flush();os.fsync(output.fileno())
            manifest['files'][name]={'sha256':hashlib.sha256(raw).hexdigest(),'bytes':len(raw),'kind':kind,
                'revision':revision,'deleted':False}
        path = self.root/('checkpoint-' + str(revision) + '.weights')
        with path.open('xb') as output:output.write(checkpoint_raw);output.flush();os.fsync(output.fileno())
        pointer = {'path': path.name, 'sha256': hashlib.sha256(checkpoint_raw).hexdigest(), 'revision': revision}
        manifest['files'][path.name]={'sha256':pointer['sha256'],'bytes':len(checkpoint_raw),'kind':'checkpoint',
            'revision':revision,'deleted':False}
        self._write_manifest(manifest)
        temporary = self.root/('latest-' + str(revision) + '.json')
        with temporary.open('x', encoding='utf-8') as output:
            output.write(canonical_json(pointer)); output.flush(); os.fsync(output.fileno())
        os.replace(temporary, self.root/'latest.json'); self.revision = revision
        self._last_checkpoint = deepcopy(pointer)
        self._blob_refs=deepcopy(pool_refs['entries'])
        self._prune(manifest)
        return pointer

    def restore_latest(self):
        self._check()
        if (self.root/'in-flight.json').exists(): raise ContractError('uncertain half-game cannot be resumed or replayed')
        pointer_path = self.root/'latest.json'
        if pointer_path.is_symlink(): raise ContractError('self-play checkpoint pointer cannot be a symlink')
        pointer = fields(read_json(pointer_path), {'path', 'sha256', 'revision'})
        if Path(pointer['path']).name != pointer['path']: raise ContractError('self-play checkpoint escapes its state root')
        path = self.root/pointer['path']
        if path.is_symlink() or hashlib.sha256(path.read_bytes()).hexdigest() != pointer['sha256']:
            raise ContractError('self-play checkpoint artifact differs')
        manifest=self._manifest()
        raw=self._read_ref(pointer,pointer['path'],manifest)
        saved = torch.load(io.BytesIO(raw), weights_only=True, map_location='cpu')
        fields(saved, {'schema_version', 'kind', 'binding', 'revision', 'models', 'pool_refs', 'records', 'consumed_counts', 'pending',
            'evaluation_windows', 'desired', 'active_seconds', 'data_index_sha256', 'state_sha256'})
        if (saved['schema_version'] != 2 or saved['kind'] != 'two-model-selfplay-boundary-v2' or
                tree_digest({k: v for k, v in saved.items() if k != 'state_sha256'}) != saved['state_sha256'] or
                saved['binding'] != self.binding or saved['revision'] != pointer['revision'] or
                saved['data_index_sha256'] != self._index_sha()):
            raise ContractError('self-play checkpoint binding/data/accounting differs')
        if type(saved['active_seconds']) not in (int,float) or not math.isfinite(saved['active_seconds']) or saved['active_seconds'] < 0:
            raise ContractError('self-play activity accounting is invalid')
        fields(saved['models'], set(self.players))
        pool=self._load_pool_refs(saved['pool_refs'],manifest)
        records=[]
        for reference in saved['records']:
            fields(reference,{'match_id','path','sha256'});identifier(reference['match_id'])
            content=self._read_ref(reference,'matches/'+reference['match_id']+'.json',manifest)
            record=json.loads(content)
            self._validate_record(record,pool,reference['match_id'])
            records.append(record)
        if len({r['summary']['match_id'] for r in records})!=len(records):raise ContractError('closed self-play match repeated')
        pending = deepcopy(saved['pending'])
        if pending is not None:
            fields(pending,{'state','actor_id','purpose','format','snapshot_id','seed_pairs','evaluation_cursor','receipts','side_models'})
            if (pending['actor_id'] not in self.players or pending['purpose'] not in PARTITIONS or
                    pending['format'] not in ('bo1','bo3') or pool._assignments.get(pending['snapshot_id'])!=pending['purpose'] or
                    pool.player_id(pending['snapshot_id'])==pending['actor_id']):
                raise ContractError('pending self-play snapshot/player/partition differs')
            runtime = pool.runtime(pending['snapshot_id'], pending['purpose'], policy_mode=self.config['opponent_policy_mode'])
            expected = {'series_binding_sha256': self._binding_sha, 'actor_id': pending['actor_id'],
                'format': pending['format'], 'purpose': pending['purpose'], 'model_opponent': runtime.identity()}
            pending['state'] = MatchState.from_dict(pending['state'], rules=self.rules, expected_binding=expected)
            self._validate_participants(pending['state'])
        if self._counts(records,pending)!=saved['consumed_counts']:
            raise ContractError('referenced self-play records differ from the complete counters/cursor')
        candidates = {i: CourseModels.from_state(value, assets=self.assets, expected_binding=self.players[i].models.binding)
                      for i, value in saved['models'].items()}
        # All model groups and the match/pool are validated before publishing either.
        for i, candidate in candidates.items():
            self.players[i].models.__dict__.clear(); self.players[i].models.__dict__.update(candidate.__dict__)
        self.pool, self.pending = pool, pending
        self.records=records
        for key in ('evaluation_windows', 'desired', 'revision', 'active_seconds'): setattr(self, key, deepcopy(saved[key]))
        self._last_checkpoint = deepcopy(pointer)
        self._blob_refs=deepcopy(saved['pool_refs']['entries'])
        self._match_refs={r['match_id']:deepcopy(r) for r in saved['records']}
        self._manifest_sha=digest(manifest)
        self._check()
        return self.status()

    def _load_pool_refs(self, value, manifest):
        fields(value,{'schema_version','kind','initial','assignments','entries','refs_sha256'})
        if (value['schema_version']!=1 or value['kind']!='frozen-selfplay-pool-references-v1' or
                digest({k:v for k,v in value.items() if k!='refs_sha256'})!=value['refs_sha256']):
            raise ContractError('retained model pool reference digest differs')
        pool=FrozenModelPool()
        for key,reference in value['entries'].items():
            fields(reference,{'player_id','path','sha256','state_sha256'})
            if (reference['player_id'] not in self.players or not isinstance(reference['state_sha256'],str) or
                    re.fullmatch('[0-9a-f]{64}',reference['state_sha256']) is None):
                raise ContractError('retained model source or state hash differs')
            content=self._read_ref(reference,'snapshots/'+reference['state_sha256']+'.weights',manifest)
            try:snapshot=FrozenDuelSnapshot.from_state(torch.load(io.BytesIO(content),weights_only=True,map_location='cpu'))
            except (OSError,ValueError,TypeError,RuntimeError,EOFError) as error:
                raise ContractError('retained model blob cannot be validated') from error
            if (snapshot._seal!=reference['state_sha256'] or
                    key!='snapshot-'+digest({'player':reference['player_id'],'snapshot':snapshot.identity()})[:48]):
                raise ContractError('retained model reference does not identify its actual weights/provenance')
            pool._entries[key]=(reference['player_id'],snapshot)
        if set(value['initial'])!=set(self.players):raise ContractError('retained initial model roster differs')
        for player,key in value['initial'].items():
            if pool.player_id(key)!=player:raise ContractError('retained initial model player differs')
        pool._initial=deepcopy(value['initial'])
        for key,purpose in value['assignments'].items():pool.assign(key,purpose)
        return pool

    def _validate_participants(self, state):
        if tuple(state.original_participants)!=tuple(MatchParticipant(p.player_id,p.deck) for p in self.players.values()):
            raise ContractError('restored match does not preserve the bound original player decks')

    def _validate_record(self, record, pool, match_id):
        fields(record,{'actor_id','purpose','format','snapshot_id','seed_pairs','evaluation_cursor','receipts','side_models',
            'complete','summary','match_state'})
        if (record['actor_id'] not in self.players or record['purpose'] not in PARTITIONS or record['format'] not in ('bo1','bo3') or
                type(record['complete']) is not bool or pool._assignments.get(record['snapshot_id'])!=record['purpose'] or
                pool.player_id(record['snapshot_id'])==record['actor_id']):
            raise ContractError('closed self-play record has a different player/partition/snapshot')
        runtime=pool.runtime(record['snapshot_id'],record['purpose'],policy_mode=self.config['opponent_policy_mode'])
        expected={'series_binding_sha256':self._binding_sha,'actor_id':record['actor_id'],'format':record['format'],
            'purpose':record['purpose'],'model_opponent':runtime.identity()}
        state=MatchState.from_dict(record['match_state'],rules=self.rules,expected_binding=expected)
        self._validate_participants(state);summary=state.summary()
        complete=(record['format']=='bo1' and len(summary['games'])==1 and summary['games'][0]['completed'] or
                  record['format']=='bo3' and state.status=='complete')
        if record['summary']!=summary or summary['match_id']!=match_id or record['complete']!=bool(complete):
            raise ContractError('closed self-play record is inconsistent with its replayed match')
