"""Independent CPU Transformer rankers for goal construction and deck edits.

Architecture code is reusable; each role owns every parameter and optimizer.
Effects are read as public facts/receipts, not understood by a downloaded LLM.
"""

from dataclasses import asdict, dataclass

import torch
from torch import nn

from .build_contracts import BuildTask, DeckParts, ZONES, digest
from .device import model_device, move_batch
from .validation import ContractError, canonical_json, integer
from .effect_mechanisms import MechanismCatalog, MECHANISM_WIDTH, SEMANTIC_VERSION

LEGACY_FEATURE_VERSION = "build-task-catalog-candidate-v5-combined-native-objectives"
FEATURE_VERSION = "build-task-catalog-candidate-v6-effect-mechanisms"


@dataclass(frozen=True)
class BuildModelConfig:
    width: int = 32
    card_width: int = 16
    heads: int = 4
    layers: int = 1
    feedforward: int = 64
    max_tokens: int = 192

    def __post_init__(self):
        for key, value in asdict(self).items():
            integer(value, key, 1, 512)
        if (self.width > 128 or self.card_width > 64 or self.heads > 16 or self.width % self.heads
                or self.layers > 2 or self.feedforward > 512 or self.max_tokens > 256):
            raise ContractError("building model exceeds CPU prototype limits")


class BuildEncoder:
    def __init__(self, task, assets, config):
        assets.check_task(task)
        self.config, self.assets = config, assets
        self.card_ids = tuple(task.pool)
        self.card_index = {code: i + 1 for i, code in enumerate(self.card_ids)}
        self.tags = tuple(sorted({canonical_json(a) for a in task.annotations}))
        self.tag_index = {tag: i + 1 for i, tag in enumerate(self.tags)}
        self.environment_sha256 = digest(task.environment)
        self.vocabulary_sha256 = digest({"cards": self.card_ids, "annotations": self.tags})
        self.mechanisms = MechanismCatalog(assets)

    def effect_records(self, code):
        """Versioned structured observations; the legacy 18 slots stay intact."""
        return self.mechanisms.effect_records(code)

    def public_mechanism_summary(self, deck):
        if not isinstance(deck, DeckParts):
            raise ContractError('mechanism summary requires a typed public deck')
        return self.mechanisms.mechanism_summary(deck.main + deck.extra + deck.side)

    def mechanism_features(self, task, deck, tokens):
        """Source semantics enter the actual ranker, without changing ID slots.

        Conflict flags describe use of a card/route, not a ban on owning a card.
        Unknown is a separate feature, never the same value as unrestricted.
        """
        from .build_semantics import matches
        predicates=[c['predicate'] for c in task.goal.get('constraints',()) if c['predicate'].get('field') in ('setcode','race_any')]
        core=[c for c in task.pool if any(matches(self.assets.rows[c],p) for p in predicates)]
        summary=self.mechanisms.summarize(core or task.pool)
        rows=[]
        by_index={i:c for c,i in self.card_index.items()}
        for token in tokens:
            code=by_index.get(token[0])
            rows.append(self.mechanisms.vector(code,summary) if code is not None else [0.]*MECHANISM_WIDTH)
        if rows:
            main=[self.mechanisms.vector(c,summary) for c in deck.main]
            if main:
                rows[0]=[sum(v[i] for v in main)/len(main) for i in range(MECHANISM_WIDTH)]
                rows[0][0]*=float(bool(summary['grave_effect_triggers']))
                rows[0][1]*=float(bool(summary['fusion_effects']))
                starters=any(e.trigger.get('event')=='normal_or_special_summon'
                    for c in deck.main for e in self.mechanisms.card(c).effects)
                rows[0][8]*=float(starters)
            else:
                rows[0][0]=min(summary['grave_effect_triggers']/8,1.)
                rows[0][1]=min(summary['fusion_effects']/8,1.)
                rows[0][3]=min(summary['resource_returns']/8,1.)
                rows[0][11]=float(bool(summary['unparsed_effect_count']))
        return rows

    def encode(self, task, deck):
        if not isinstance(task, BuildTask) or not isinstance(deck, DeckParts):
            raise ContractError("building encoder requires typed task and candidate only")
        if digest(task.environment) != self.environment_sha256 or task.pool != self.card_ids:
            raise ContractError("building encoder resource/pool binding differs")
        ids, numbers = [[0, 0, 0, 0]], [[0.] * 10]

        def card(code, zone, kind, minimum=0, maximum=3, context=0.):
            if code not in self.card_index:
                raise ContractError("candidate card outside building vocabulary")
            count = getattr(deck, zone).count(code)
            ids.append([self.card_index[code], 1 + ZONES.index(zone), 0, kind])
            numbers.append(self.assets.facts(code) + [minimum / 3, maximum / 3, count / 3, context])

        semantic=task.goal['kind']=='deck_constraints'
        route_goal=task.goal.get('route_goal') if semantic else task.goal
        extra_goal = route_goal is not None and route_goal['kind']!='normal_summon'
        if semantic:
            from .build_semantics import count,matches
            for hard,items in ((True,task.goal['constraints']),(False,task.goal['preferences'])):
                for item in sorted(items,key=lambda c:canonical_json({k:v for k,v in c.items() if k!='id'})):
                    ids.append([0,0,0,6])
                    numbers.append([item.get('minimum',0)/90,item.get('maximum',90)/90,
                                    count(deck,item,self.assets.rows)/90,item.get('weight',0)/100,
                                    sum(1<<ZONES.index(z) for z in item['zones'])/7,float(hard),0.,0.,0.,0.])
                    for zone in ZONES:
                        if zone not in item['zones']:continue
                        for code in task.pool:
                            if matches(self.assets.rows[code],item['predicate']):
                                ids.append([self.card_index[code],1+ZONES.index(zone),0,6])
                                numbers.append(self.assets.facts(code)+[0.,0.,0.,1. if hard else -1.])
        if route_goal is not None:
            # Preserve the exact existing three encodings during base continuation.
            goal_context = {"normal_summon": 0., "synchro_summon": .5, "xyz_summon": 1., "fusion_summon": -.5}[route_goal["kind"]]
            card(route_goal["card_id"], "extra" if extra_goal else "main", 1, context=goal_context)
        if extra_goal:
            for code in route_goal["starting_conditions"]["requires_opening_hand"]:
                card(code, "main", 5)
            numbers[0][-1] = float("route" not in route_goal)
            for intent in route_goal.get("route", []):
                operation = intent["operation"]
                for code in intent["card_ids"]:
                    card(code, "extra" if operation == "special_summon" else "main", 6,
                         context=("activate", "summon", "search", "special_summon").index(operation) / 3)
        if semantic:
            from .build_pipeline import EXTRA_TYPES
            for key,context in (('required_activations',.5),('required_chain_resolutions',.75)):
                for code in task.goal.get(key,[]):
                    card(code,'extra' if self.assets.rows[code]['type']&EXTRA_TYPES else 'main',6,context=context)
        for req in task.requirements:
            card(req["card_id"], req["zone"], 2, req["minimum"], req["maximum"])
        for annotation in task.annotations:
            key = canonical_json(annotation)
            if key not in self.tag_index:
                raise ContractError("unseen building context annotation; not silently ignored")
            ids.append([0, 0, self.tag_index[key], 3])
            numbers.append([0.] * 9 + [("self", "opponent", "both").index(annotation["subject"]) / 2])
        for zone in ZONES:
            for code in sorted(getattr(deck, zone)):
                card(code, zone, 4)
        if len(ids) > self.config.max_tokens:
            raise ContractError("building context exceeds token budget")
        state = [len(getattr(deck, z)) / (60 if z == "main" else 15) for z in ZONES]
        state += [task.sizes[z] / (60 if z == "main" else 15) for z in ZONES]
        return ids, numbers, state

    def batch(self, task, decks, *, device=None):
        integer(len(decks), "building rank batch", 1, 32)
        encoded = [self.encode(task, deck) for deck in decks]
        length = max(len(row[0]) for row in encoded)
        batch = {"tokens": torch.zeros(len(decks), length, 4, dtype=torch.long),
                 "numbers": torch.zeros(len(decks), length, 10),
                 "mechanisms": torch.zeros(len(decks), length, MECHANISM_WIDTH),
                 "state": torch.tensor([row[2] for row in encoded], dtype=torch.float32),
                 "mask": torch.zeros(len(decks), length, dtype=torch.bool)}
        for i, (tokens, numbers, _) in enumerate(encoded):
            batch["tokens"][i, :len(tokens)] = torch.tensor(tokens)
            batch["numbers"][i, :len(tokens)] = torch.tensor(numbers)
            batch["mask"][i, :len(tokens)] = True
            batch['mechanisms'][i,:len(tokens)]=torch.tensor(self.mechanism_features(task,decks[i],tokens))
        return move_batch(batch, device) if device is not None else batch


class BuildRanker(nn.Module):
    def __init__(self, config, vocabulary_size, annotation_count):
        super().__init__()
        self.card = nn.Embedding(vocabulary_size + 1, config.card_width, padding_idx=0)
        self.card_project = nn.Linear(config.card_width, config.width)
        self.zone = nn.Embedding(4, config.width)
        self.kind = nn.Embedding(7, config.width)
        self.annotation = nn.Embedding(annotation_count + 1, config.width, padding_idx=0)
        self.numeric, self.state = nn.Linear(10, config.width), nn.Linear(6, config.width)
        self.position = nn.Embedding(config.max_tokens, config.width)
        self.norm = nn.LayerNorm(config.width)
        layer = nn.TransformerEncoderLayer(config.width, config.heads, config.feedforward, dropout=0., batch_first=True)
        self.encoder = nn.TransformerEncoder(layer, config.layers, enable_nested_tensor=False)
        self.head = nn.Sequential(nn.Linear(config.width, config.width), nn.Tanh(), nn.Linear(config.width, 1))
        # Appended last to permit explicit old-parameter/Adam ordering migration.
        self.mechanism = nn.Linear(MECHANISM_WIDTH, config.width, bias=False)

    def forward(self, batch):
        batch = move_batch(batch, model_device(self))
        if not batch["mask"][:, 0].all():
            raise ContractError("building ranker requires CPU/valid context")
        t = batch["tokens"]
        x = (self.card_project(self.card(t[..., 0])) + self.zone(t[..., 1]) + self.annotation(t[..., 2])
             + self.kind(t[..., 3]) + self.numeric(batch["numbers"]))
        if 'mechanisms' in batch:
            if batch['mechanisms'].shape != (*t.shape[:2], MECHANISM_WIDTH):
                raise ContractError('effect-mechanism feature dimensions differ')
            x=x+self.mechanism(batch['mechanisms'])
        x[:, 0] = x[:, 0] + self.state(batch["state"])
        x = x + self.position(torch.arange(x.shape[1], device=x.device))[None]
        encoded = self.encoder(self.norm(x), src_key_padding_mask=~batch["mask"])
        return self.head(encoded[:, 0]).squeeze(-1)


def migrate_legacy_ranker(model_state, optimizer_state=None, *, source_feature_version,
                          source_checkpoint_sha256):
    """Explicit v5 model/Adam migration; never rebind a whole course checkpoint.

    Old weights/moments are copied, the appended projection starts at zero, and
    Adam initializes only its new parameter lazily. The caller must separately
    migrate and record source/vocabulary/course bindings and any LoRA adapters.
    Passing the old checkpoint directly to normal restore continues to fail.
    """
    from copy import deepcopy
    if source_feature_version != LEGACY_FEATURE_VERSION or len(source_checkpoint_sha256)!=64 or any(
            c not in '0123456789abcdef' for c in source_checkpoint_sha256):
        raise ContractError('explicit v5 feature identity and source checkpoint SHA-256 required')
    if ('mechanism.weight' in model_state or any('parametrizations' in k for k in model_state)
            or model_state.get('numeric.weight') is None or model_state['numeric.weight'].shape[1]!=10):
        raise ContractError('only an unparametrized v5 ranker can use this migration; adapters need explicit rebuild')
    state={k:v.detach().clone() for k,v in model_state.items()}
    state['mechanism.weight']=state['numeric.weight'].new_zeros((state['numeric.weight'].shape[0],MECHANISM_WIDTH))
    optimizer=deepcopy(optimizer_state)
    if optimizer is not None:
        if len(optimizer['param_groups'])!=1 or len(optimizer['param_groups'][0]['params'])!=len(model_state):
            raise ContractError('v5 Adam parameter ordering differs; no guessed optimizer migration')
        previous=optimizer['param_groups'][0]['params']
        if len(set(previous))!=len(previous):raise ContractError('duplicate legacy Adam parameter identifiers')
        previous.append(max(previous,default=-1)+1)
    return state,optimizer,{'kind':'explicit-v5-to-v6-ranker-and-adam-extension',
        'source_checkpoint_sha256':source_checkpoint_sha256,'source_feature_version':source_feature_version,
        'target_feature_version':FEATURE_VERSION,'semantic_version':SEMANTIC_VERSION,
        'old_parameters_and_moments_preserved':True,'new_projection':'zero_initialized',
        'new_adam_parameter':'lazy_state_initialization','whole_checkpoint_restore_performed':False,
        'requires_explicit_source_course_and_adapter_rebinding':True}
