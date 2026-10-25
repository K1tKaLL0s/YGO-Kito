"""Frozen, executable local opponent versions; external providers stay unverified.

Only the host object knows registered deck lists. Its trusted decision policy
receives a legal seat DTO and the public catalogue, not a native handle/audit.
"""
import inspect
import json
import hashlib
from pathlib import Path

from .agent_registry import OpponentRegistry
from .build_contracts import digest
from .contracts import Versions,ActionSelection,validate_selection
from .effect_duel import choose_effect_duel_action,public_card_facts
from .validation import ContractError

LOCAL_DRIVERS=('visible-effects-first-v1','visible-effects-last-option-v1')
SNAPSHOT_DRIVER='frozen-duel-greedy-v1'


class PublicRulePolicy:
    def __init__(self,driver,seat,versions,facts):
        if driver not in LOCAL_DRIVERS:raise ContractError('unknown executable local opponent version')
        self.driver,self.seat,self.versions,self.facts=driver,seat,versions,facts

    def choose(self,request):
        if (request.observation.observer!=self.seat or request.context.seed is not None
            or request.context.versions!=self.versions):raise ContractError('opponent seat/version boundary differs')
        action=request.actions[-1] if self.driver==LOCAL_DRIVERS[1] and request.prompt.message==14 else choose_effect_duel_action(request,self.facts)
        validate_selection(request,ActionSelection(request.context.run_id,request.duel_id,request.decision_id,action.action_id))
        return action


class PublicSnapshotPolicy:
    def __init__(self,seat,versions,state):
        import torch
        from .duel_model import DuelActorCritic,DuelModelConfig,PlayerEncoder,parameter_digest
        self.seat,self.versions=seat,versions
        config=DuelModelConfig(**state['config']['model'])
        self.encoder=PlayerEncoder(state['card_ids'],config)
        # Loading an opponent must not advance the actor/training RNG stream.
        with torch.random.fork_rng(devices=[]):
            self.model=DuelActorCritic(config,len(state['card_ids'])).to('cpu')
        self.model.load_state_dict(state['model'],strict=True);self.model.eval();self.model.requires_grad_(False)
        self.model_sha256=parameter_digest(self.model)
        if self.model_sha256!=state['model_sha256'] or self.encoder.vocab_sha256!=state['vocab_sha256']:
            raise ContractError('local snapshot model/vocabulary checksum differs')

    def choose(self,request):
        import torch
        from .hierarchical_policy import score_requests
        if request.observation.observer!=self.seat or request.context.seed is not None or request.context.versions!=self.versions:
            raise ContractError('snapshot opponent seat/version boundary differs')
        with torch.no_grad():logits,_=score_requests(self.model,self.encoder,[request])
        action=request.actions[int(logits[0].argmax())]
        validate_selection(request,ActionSelection(request.context.run_id,request.duel_id,request.decision_id,action.action_id))
        return action


class FrozenOpponent:
    def __init__(self,registry,opponent_id,own_deck_id,seat,*,checkpoint=None,checkpoint_sha256=None):
        if not isinstance(registry,OpponentRegistry):raise ContractError('typed opponent registry required')
        match=registry.match_configuration(opponent_id,own_deck_id,seat);record=match['opponent']
        snapshot=record['controller']=='local_snapshot' and record['driver_version']==SNAPSHOT_DRIVER
        if not snapshot and (record['controller']!='rule_baseline' or record['driver_version'] not in LOCAL_DRIVERS):
            raise ContractError('bot/external provider requires a verified legal-action transport; registration is not execution')
        self.registry,self.opponent_id,self.own_deck_id,self.seat=registry,opponent_id,own_deck_id,seat
        self.profile=match['profile'];self.versions=Versions.from_dict(match['versions'])
        self._checkpoint=None;self._checkpoint_sha256=None
        if snapshot:
            import torch
            from .duel_model import FEATURE_VERSION
            path=Path(checkpoint).resolve() if checkpoint is not None else None
            if path is None or not path.is_relative_to(registry.root) or not path.is_file():
                raise ContractError('snapshot must be an explicit managed local registry artifact')
            actual=hashlib.sha256(path.read_bytes()).hexdigest()
            if not isinstance(checkpoint_sha256,str) or checkpoint_sha256!=actual:raise ContractError('snapshot file checksum differs')
            try:state=torch.load(path,map_location='cpu',weights_only=True)
            except (OSError,ValueError,RuntimeError) as error:raise ContractError('snapshot artifact cannot be loaded') from error
            from .native_assets import verify_resources
            from .validation import fields,integer
            from .cpu_training import config_from_dict
            fields(state,{'schema_version','role','boundary','config','binding','card_ids','vocab_sha256','model','optimizer','scheduler',
                          'updates','episode_cursor','model_sha256','rng'}, {'execution','device_rng'})
            from .device import checkpoint_execution
            checkpoint_execution(state, requested='cpu')  # No implicit CUDA-to-CPU inference migration.
            fields(state['binding'],{'feature_version','resources','source_commits'},
                   {'profile_sha256','python_implementation_sha256','python','torch','registered_opponent_pool'})
            receipt=verify_resources(registry.native_root)
            if (state['schema_version']!=1 or state['role']!='duel' or state['boundary']!='complete-episode'
                or state['binding']['feature_version']!=FEATURE_VERSION or state['binding']['resources']!=receipt['resources']
                or state['binding']['source_commits']!=receipt['source_commits'] or record['model']!=state['model_sha256']):
                raise ContractError('snapshot is not a compatible completed duel checkpoint')
            config=config_from_dict(state['config'])
            integer(state['updates'],'snapshot updates',1,len(config.game_seeds))
            integer(state['episode_cursor'],'snapshot cursor',state['updates'],state['updates'])
            try:self.policy=PublicSnapshotPolicy(seat,self.versions,state)
            except (KeyError,TypeError,ValueError,RuntimeError) as error:raise ContractError('snapshot model state is incompatible') from error
            self._checkpoint,self._checkpoint_sha256=path,actual
        else:
            if checkpoint is not None or checkpoint_sha256 is not None:raise ContractError('rule opponent does not accept model artifacts')
            self.policy=PublicRulePolicy(record['driver_version'],seat,self.versions,public_card_facts(registry.native_root))
        self.binding={'schema_version':1,'opponent_id':opponent_id,'environment_id':record['environment_id'],
                      'registered_record_sha256':digest(record),'opponent_deck_sha256':registry.get('deck',record['deck_id'])['sha256'],
                      'own_deck_sha256':registry.get('deck',own_deck_id)['sha256'],'profile_sha256':digest(self.profile),
                      'driver_version':record['driver_version'],'driver_implementation_sha256':digest(inspect.getsource(PublicSnapshotPolicy) if snapshot else inspect.getsource(PublicRulePolicy)+inspect.getsource(choose_effect_duel_action)),
                      'source':record['source'],'controller':record['controller'],'strength_qualified':False,'external_provider_verified':False,
                      'model_sha256':self.policy.model_sha256 if snapshot else None}
        self.binding['opponent_deck_content_sha256']=digest({z:sorted(cards) for z,cards in registry.get('deck',record['deck_id'])['cards'].items()})

    def assert_runtime(self,root,profile,actor_seat):
        from pathlib import Path
        if self.registry.native_root!=Path(root).resolve() or self.seat!=1-actor_seat or digest(profile)!=self.binding['profile_sha256']:
            raise ContractError('frozen opponent profile/seat/runtime mismatch')
        current=FrozenOpponent(self.registry,self.opponent_id,self.own_deck_id,self.seat,checkpoint=self._checkpoint,checkpoint_sha256=self._checkpoint_sha256)
        if current.binding!=self.binding:raise ContractError('opponent binding changed after freeze')


class FrozenOpponentPool:
    def __init__(self,opponents):
        if not opponents or not all(isinstance(o,FrozenOpponent) for o in opponents):raise ContractError('executable opponents required')
        hashes=[digest(o.binding) for o in opponents]
        if len(hashes)!=len(set(hashes)):raise ContractError('duplicate frozen opponent version')
        self.opponents=tuple(opponents);self.version=digest(hashes)

    def choose(self,episode_cursor):
        from .validation import integer
        integer(episode_cursor,'opponent pool cursor',0,100000)
        return self.opponents[episode_cursor%len(self.opponents)]

    def manifest(self):
        return {'schema_version':1,'kind':'frozen-engineering-opponent-pool','version':self.version,
                'opponents':[o.binding for o in self.opponents],'formal_training_ready':False,'strength_qualified':False}


def replay_private(root,trace,*,engine_factory=None):
    from dataclasses import asdict
    from pathlib import Path
    from .native import NativeNormalEngine,NativeError
    from .normal_duel import request_digest
    from .validation import canonical_json,fields
    fields(trace,{'schema_version','kind','name','profile','seed_audit_only','selection_key_audit_only','resources','responses',
                  'events','outcome','final_observations','result','opponent_binding'})
    if trace['kind']!='registered-opponent-private-replay-v1':raise ContractError('unknown registered replay format')
    factory=NativeNormalEngine if engine_factory is None else engine_factory
    if not callable(factory):raise ContractError('trusted private replay engine factory must be callable')
    with factory(Path(root),scenario='effect-duel',deck_profile=trace['profile'],seed=trace['seed_audit_only'],
                            selection_key=trace['selection_key_audit_only']) as engine:
        if engine.receipt!=trace['resources']:raise ContractError('registered replay resource versions differ')
        req=engine.next_decision()
        for row in trace['responses']:
            if req is None or row['player']!=req.observation.observer or request_digest(req)!=row['request_sha256']:
                raise NativeError('registered replay request diverged')
            engine.submit(ActionSelection(req.context.run_id,req.duel_id,req.decision_id,row['action_id']));req=engine.next_decision()
        final=[json.loads(canonical_json(asdict(engine._observation(p)))) for p in (0,1)]
        if req is not None or engine.events!=trace['events'] or engine.outcome!=trace['outcome'] or final!=trace['final_observations']:
            raise NativeError('registered replay terminal/events/observations differ')
        return {'replay_verified':True,'natural_terminal':True,'public_histories_equal':final[0]['public_history']==final[1]['public_history'],
                'turns':engine.turn,'life_points':engine.life_points,'callback_errors':len(engine.callback_errors)}
