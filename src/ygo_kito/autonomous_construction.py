"""Host-bound autonomous task selection using the existing construction models.

Programs enumerate real catalog facts and bounded tasks/lists. Existing goal and
optimizer networks rank them; no rule proposal is called a learned model. The
group owns weights, optimizers, LoRA and recovery. This module never trains,
loads weights, downloads data, or certifies a graph as an executable CB.
"""
from collections import Counter
from copy import copy, deepcopy
import hashlib
import math

import torch
from torch import nn
from torch.nn import functional as F
from torch.nn.utils import parametrize

from .build_contracts import BuildTask, DeckParts, digest
from .build_model import BuildEncoder, BuildRanker
from .build_training import BuildTrainer
from .construction_binding import CatalogBindingAdapter, PublicFactTag
from .construction_controller import ConstructionController
from .construction_fill import existing_goal_verifier
from .construction_logic import ConstructionSession, LogicTag, ThemeScope
from .construction_model import LogicCodec, LogicFeatureEncoder, LogicModelAdapter
from .construction_effect_blocks import reviewed_effect_blocks
from .device import model_device
from .duel_model import parameter_digest
from .validation import ContractError, integer
from .effect_mechanisms import MechanismCatalog, SEMANTIC_VERSION, MECHANISM_WIDTH

FEATURE_VERSION = "autonomous-catalog-task-course-v2-effect-mechanisms"
ROLES = ("build_goal", "build_optimizer")
EXTRA_TYPES = 0x40 | 0x2000 | 0x800000 | 0x4000000


def _available(assets, supplied):
    requested = tuple(sorted(set(supplied)))
    allowed = getattr(assets, "allowed_card_ids", None)
    found, rejected = [], []
    for code in requested:
        integer(code, "host available card", 1, 2**32 - 1)
        row = assets.rows.get(code)
        reason = ("catalog_missing" if row is None else "outside_period_pool" if allowed is not None and code not in allowed
                  else "non_ocg_or_token" if not row["ot"] & 1 or row["type"] & 0x4000
                  else "forbidden" if assets.limits.get(row["alias"] or code, 3) <= 0 else None)
        if reason:
            rejected.append({"card_id": code, "reason": reason})
        else:
            found.append(code)
    return tuple(found), rejected


class CourseBuildEncoder(BuildEncoder):
    """A local task pool uses stable, explicitly initialized global card IDs."""
    def __init__(self, task, assets, config, *, card_ids, available_ids, migration):
        super().__init__(task, assets, config)
        self.card_ids = tuple(card_ids)
        self.card_index = {c: i + 1 for i, c in enumerate(self.card_ids)}
        self.available_ids = frozenset(available_ids)
        if len(self.card_index) != len(self.card_ids) or not self.available_ids <= self.card_index.keys():
            raise ContractError("course global vocabulary/availability differs")
        self.annotations_sha256 = digest(list(task.annotations))
        self.vocabulary_sha256 = digest({"cards": self.card_ids, "annotations": self.tags})
        self.migration = deepcopy(migration)
        self._seal = digest(self.binding())

    def binding(self):
        return {"feature_version": FEATURE_VERSION, "semantic_version":SEMANTIC_VERSION, "cards": list(self.card_ids),
                "available_ids": sorted(self.available_ids), "annotations": list(self.tags),
                "annotations_sha256": self.annotations_sha256, "environment_sha256": self.environment_sha256,
                "vocabulary_sha256": self.vocabulary_sha256, "migration": deepcopy(self.migration)}

    def assert_binding(self):
        if (digest(self.binding()) != self._seal or self.card_index != {c: i + 1 for i, c in enumerate(self.card_ids)}
                or self.tag_index != {t: i + 1 for i, t in enumerate(self.tags)}):
            raise ContractError("course encoder vocabulary/identity was changed")

    def encode(self, task, deck):
        self.assert_binding()
        if (not isinstance(task, BuildTask) or not set(task.pool) <= self.available_ids
                or digest(list(task.annotations)) != self.annotations_sha256
                or digest(task.environment) != self.environment_sha256):
            raise ContractError("course task pool, environment or annotations differ")
        self.assets.check_task(task)
        # Only the pool equality view changes; global index and learned rows do
        # not. No OOV ID is sent to the padding/unknown row.
        view = copy(self)
        view.card_ids = task.pool
        return BuildEncoder.encode(view, task, deck)


def initialize_course_vocabulary(builder, host_available_ids, *, seed=45881):
    """Explicit new-course initialization before any update or active LoRA.

    Existing rows keep their index and bytes. New rows use distinct explicitly
    untrained, local-generator initializations. Optimizers/schedulers retain identity
    and configuration; only their old embedding parameter pointer is rebound.
    This is neither checkpoint resume nor implicit optimizer/RNG migration.
    """
    if not isinstance(builder, BuildTrainer):
        raise ContractError("existing BuildTrainer required")
    integer(seed,"course vocabulary initialization seed",0,2**63-1)
    if (any(builder.updates.values()) or builder.batch_cursor or
            any(o.state for o in builder.optimizers.values()) or
            any(parametrize.is_parametrized(m) for model in builder.models.values() for m in model.modules())):
        raise ContractError("course vocabulary expansion requires fresh unupdated base models without LoRA")
    available, rejected = _available(builder.encoder.assets, host_available_ids)
    if isinstance(builder.encoder, CourseBuildEncoder):
        builder.encoder.assert_binding()
        if (builder.encoder.available_ids != frozenset(available) or
                builder.encoder.migration["initialization_seed"] != seed):
            raise ContractError("an initialized course requires its exact vocabulary; use a new explicit course")
        return deepcopy(builder.encoder.migration)
    old = tuple(builder.encoder.card_ids)
    target = old + tuple(c for c in available if c not in set(old))
    migration = {"kind": "explicit-fresh-course-vocabulary", "source_vocabulary_sha256": builder.encoder.vocabulary_sha256,
        "source_card_ids": list(old), "target_card_ids": list(target), "available_ids": list(available),
        "excluded": rejected, "old_indices_preserved": True, "new_rows": len(target)-len(old),
        "new_row_initialization": "explicit_role_card_seeded_untrained", "initialization_seed":seed,
        "new_row_hashes":{},"optimizer_state_inherited": False,
        "models_replaced": False, "ability_verified": False}
    plans = {}
    for role in ROLES:
        model = builder.models[role]
        if not isinstance(model, BuildRanker) or model.card.num_embeddings != len(old) + 1:
            raise ContractError("existing role embedding differs from its source vocabulary")
        parameter = model.card.weight
        groups = builder.optimizers[role].param_groups
        if sum(p is parameter for group in groups for p in group["params"]) != 1:
            raise ContractError("fresh role optimizer is not bound to its old embedding")
        rows = parameter.detach().new_zeros((len(target) + 1, parameter.shape[1]))
        rows[:len(old)+1].copy_(parameter.detach())
        if torch.count_nonzero(rows[0]):
            raise ContractError("source padding embedding must retain its zero-row contract")
        for index,code in enumerate(target[len(old):],start=len(old)+1):
            identity=digest({"seed":seed,"role":role,"card_id":code,"source_vocabulary":builder.encoder.vocabulary_sha256})
            generator=torch.Generator(device="cpu").manual_seed(int(identity[:16],16)%(2**63-1))
            rows[index].copy_(torch.randn(parameter.shape[1],generator=generator,dtype=parameter.dtype).to(parameter.device) / math.sqrt(parameter.shape[1]))
        migration["new_row_hashes"][role]=hashlib.sha256(rows[len(old)+1:].detach().cpu().contiguous().numpy().tobytes()).hexdigest()
        plans[role] = (nn.Embedding.from_pretrained(rows, freeze=False, padding_idx=0), parameter)
    encoder = CourseBuildEncoder(builder.task, builder.encoder.assets, builder.encoder.config,
        card_ids=target, available_ids=available, migration=migration)
    for role, (embedding, old_parameter) in plans.items():
        builder.models[role].card = embedding
        for group in builder.optimizers[role].param_groups:
            group["params"] = [embedding.weight if p is old_parameter else p for p in group["params"]]
    builder.encoder = encoder
    return deepcopy(migration)


class _SharedLogicAdapter(LogicModelAdapter):
    """Existing graph scorer with host-managed training, no new optimizer."""
    def __init__(self, task, builder, codec, updates, *, required_tags=(), required_connector_kinds=()):
        self.task, self.models, self.deck_encoder, self.codec = task, builder.models, builder.encoder, codec
        self.device = model_device(self.models[ROLES[0]])
        self.codec_sha256 = digest(codec.to_dict())
        self.required_tags=tuple(required_tags);self.required_connector_kinds=tuple(required_connector_kinds)
        self.requirements_sha256=digest(self.requirements())
        self.encoder = LogicFeatureEncoder(codec, builder.encoder.config.max_tokens)
        self.updates, self.last_selection = updates, {}

    def train_preference(self, *args, **kwargs):
        raise ContractError("use kernel differentiable losses with the existing host-managed updater")

    def save(self, *args, **kwargs):
        raise ContractError("shared construction weights and LoRA belong to the group checkpoint")

    load = save


def _referenced_ids(value):
    if isinstance(value, dict):
        out = set()
        if value.get("field") == "card_ids": out.update(value["value"])
        for key, item in value.items():
            if key == "card_id" and isinstance(item, int): out.add(item)
            elif key in ("card_ids", "requires_opening_hand", "required_activations", "required_chain_resolutions"):
                out.update(item)
            else: out.update(_referenced_ids(item))
        return out
    if isinstance(value, (list, tuple)):
        return set().union(*(_referenced_ids(v) for v in value)) if value else set()
    return set()


class AutonomousConstructionKernel:
    def __init__(self, builder, coordinator, *, assets, host_available_ids, source_binding,
                 theme_minimum=1, pool_limit=128, candidate_limit=32, allowed_theme_ids=None):
        if not isinstance(builder, BuildTrainer) or not isinstance(builder.encoder, CourseBuildEncoder):
            raise ContractError("explicitly initialized course BuildTrainer/encoder required")
        if assets is not builder.encoder.assets or builder.task.goal["kind"] != "deck_constraints":
            raise ContractError("same actual assets and an explicit semantic course goal required")
        if not isinstance(source_binding, dict) or not source_binding:
            raise ContractError("actual host catalog/script availability source binding required")
        self.builder, self.coordinator, self.assets = builder, coordinator, assets
        self.requested_ids = tuple(sorted(set(host_available_ids)))
        self.available_ids, self.excluded = _available(assets, self.requested_ids)
        self.mechanisms = MechanismCatalog(assets, self.available_ids)
        if frozenset(self.available_ids) != builder.encoder.available_ids:
            raise ContractError("host availability differs from the frozen course vocabulary")
        integer(theme_minimum, "theme-axis minimum", 1, 60)
        integer(pool_limit, "local task pool limit", 14, 128)
        integer(candidate_limit, "returned ranked tasks", 2, 128)
        self.theme_minimum, self.pool_limit, self.candidate_limit = theme_minimum, pool_limit, candidate_limit
        if allowed_theme_ids is not None and (not isinstance(allowed_theme_ids, (list, tuple)) or not allowed_theme_ids or any(not isinstance(x, str) or not x for x in allowed_theme_ids)):
            raise ContractError("explicit nonempty theme identifiers required")
        self.allowed_theme_ids = tuple(sorted(set(allowed_theme_ids))) if allowed_theme_ids is not None else None
        self.source_binding = deepcopy(source_binding)
        if 'construction_goal' in self.source_binding:
            goal = self.source_binding['construction_goal']
            if not isinstance(goal,dict) or goal.get('kind') != 'deck_constraints':
                raise ContractError('explicit semantic construction objective required')
        if self.source_binding.get('basic_cb_stage')=='after_construction':
            objective=self.source_binding.get('construction_goal',builder.task.goal)
            if any(k in objective for k in ('route_goal','required_activations','required_chain_resolutions')):
                raise ContractError('after-construction CB inference cannot be a preassigned construction goal')
            if list(builder.task.requirements)!=self.source_binding.get('construction_card_requirements',[]):
                raise ContractError('fixed card components need an explicit construction request')
        self._models = dict(builder.models)
        self._binding = self._current_binding()
        self._binding_sha256 = digest(self._binding)
        self.selections, self.sessions, self.adapters = {}, {}, {}
        self.updates = {r: 0 for r in ROLES}
        self.graph_updates = {r: 0 for r in ROLES}
        self._proposal_seals=set()

    def _current_binding(self):
        fields = ("id", "alias", "ot", "type", "setcode", "race", "attribute", "level", "atk", "def", "desc")
        return {"feature_version": FEATURE_VERSION, "semantic_version":SEMANTIC_VERSION, "base_task_sha256": self.builder.task.sha256,
            "encoder": self.builder.encoder.binding(), "source": deepcopy(self.source_binding),
            "catalog_sha256": digest([{k: self.assets.rows[c].get(k) for k in fields} for c in self.available_ids]),
            "resources": deepcopy(self.assets.receipt), "period_context": deepcopy(getattr(self.assets, "period_context", None)),
            "available": list(self.available_ids), "limits": dict(self.assets.limits),
            "theme_minimum": self.theme_minimum, "pool_limit": self.pool_limit, "candidate_limit": self.candidate_limit,
            **({"allowed_theme_ids": list(self.allowed_theme_ids)} if self.allowed_theme_ids is not None else {})}

    def _check(self):
        self.builder.encoder.assert_binding()
        if digest(self._current_binding()) != self._binding_sha256:
            raise ContractError("autonomous course source/task/vocabulary changed")
        if set(self.builder.models)!=set(ROLES) or any(self.builder.models[r] is not self._models[r] or not isinstance(self.builder.models[r], BuildRanker) or
               self.builder.models[r].card.num_embeddings != len(self.builder.encoder.card_ids)+1 for r in ROLES):
            raise ContractError("actual existing construction role model is missing or incompatible")
        if {p.data_ptr() for p in self.builder.models[ROLES[0]].parameters()} & {p.data_ptr() for p in self.builder.models[ROLES[1]].parameters()}:
            raise ContractError("construction roles must keep independent model parameters")

    def enumerate_themes(self):
        self._check()
        from .build_semantics import matches
        facts = set()
        for code in self.available_ids:
            row = self.assets.rows[code]
            packed = row["setcode"] % (1 << 64)
            for shift in range(0, 64, 16):
                value = (packed >> shift) & 0xffff
                if value:
                    facts.add(("setcode", value)); facts.add(("setcode", value & 0xfff))
            mask = row["race"]
            while mask:
                bit = mask & -mask
                facts.add(("race_any", bit)); mask ^= bit
        result = []
        for field, value in sorted(facts):
            if not value: continue
            ids = [c for c in self.available_ids if matches(self.assets.rows[c], {"field": field, "value": value})]
            result.append({"theme_id": field + "-" + format(value, "x"), "field": field, "value": value,
                "tag": {"dimension": "field" if field == "setcode" else "race", "value": field + ":" + format(value, "x")},
                "card_ids": ids, "source": "actual-host-catalog:" + self.assets.receipt["resources"]["cards"]})
        return result

    def _route_goals(self, pool, theme=None):
        if self.source_binding.get('basic_cb_stage')=='after_construction':
            return [None]
        fixed = self.source_binding.get('construction_goal', self.builder.task.goal).get('route_goal')
        if fixed is not None: return [deepcopy(fixed)]
        core = [c for c in (theme['card_ids'] if theme else pool) if c in pool]
        # All existing supported summon families share the same bounded recall
        # seam. A fusion observation must not hide synchro/xyz alternatives.
        return (self.mechanisms.summon_goals(pool, core, limit=4)
                if self.builder.task.sizes['extra'] else []) or [None]

    def _task(self, theme, pool, route):
        base = self.builder.task.to_dict()
        goal = deepcopy(self.source_binding.get('construction_goal', base['goal']))
        if len(goal["constraints"]) >= 12:
            raise ContractError("autonomous axis needs an available semantic constraint slot")
        goal["constraints"].append({"id":"autonomous-axis", "zones":["main","extra"],
            "predicate":{"field":theme["field"],"value":theme["value"]},
            "minimum":self.theme_minimum,"maximum":75})
        requirements = {(r["zone"],r["card_id"]):deepcopy(r) for r in base["requirements"]}
        if route is not None:
            goal["route_goal"] = deepcopy(route)
            if (route['kind']=='fusion_summon' and any(r.get('source')==SEMANTIC_VERSION for r in
                    route.get('fusion_witness',{}).get('effect_assessments',[]))):
                effect_ids=[r['card_id'] for r in route['fusion_witness']['effect_assessments']]
                activations=list(dict.fromkeys([*goal.get('required_activations',()),
                    *route['starting_conditions']['requires_opening_hand'],*effect_ids]))
                goal['required_activations']=activations
                goal['required_chain_resolutions']=list(dict.fromkeys([*goal.get('required_chain_resolutions',()),*activations]))
            wanted = Counter(("main",c) for c in route["starting_conditions"]["requires_opening_hand"])
            wanted[("main" if route["kind"]=="normal_summon" else "extra",route["card_id"])] = max(1,wanted[("main" if route["kind"]=="normal_summon" else "extra",route["card_id"])])
            for code in set(goal.get('required_activations', ())) | set(goal.get('required_chain_resolutions', ())):
                zone = 'extra' if self.assets.rows[code]['type'] & EXTRA_TYPES else 'main'
                wanted[zone,code] = max(1,wanted[zone,code])
            for (zone,code), minimum in wanted.items():
                row = requirements.setdefault((zone,code),{"zone":zone,"card_id":code,"minimum":0,"maximum":3})
                row["minimum"] = max(row["minimum"],minimum)
        base.update(schema_version=4, task_id="auto-"+digest({"theme":theme["theme_id"],"pool":pool,"goal":goal})[:24],
                    goal=goal,pool=sorted(pool),requirements=list(requirements.values()))
        return BuildTask.from_dict(base)

    def _capacity(self, pool, zone=None):
        aliases={}
        for code in pool:
            row=self.assets.rows[code]
            if zone in ("main","extra") and bool(row["type"]&EXTRA_TYPES)!=(zone=="extra"):continue
            alias=row["alias"] or code
            aliases[alias]=self.assets.limits.get(alias,3)
        return sum(aliases.values())

    def _pool(self, theme, mandatory):
        if len(mandatory)>self.pool_limit:
            raise ContractError("fixed goal identities exceed the local course pool limit")
        current=list(sorted(mandatory))
        def core_priority(code):
            p=self.mechanisms.card(code)
            # Equal treatment of observed effects and supported summon targets;
            # curriculum/theme preferences belong to the explicit task.
            return int(bool(p.kinds)) + int(bool(self.assets.rows[code]['type'] & (0x40 | 0x2000 | 0x800000)))
        core_order=sorted(theme['card_ids'],key=lambda c:(-core_priority(c),self.mechanisms.card(c).text_sha256,c))
        for code in core_order[:min(32,max(1,self.pool_limit//2))]:
            if code not in current and len(current)<self.pool_limit:current.append(code)
        summary=self.mechanisms.summarize(theme['card_ids'])
        # No ID/capacity filler: every noncore proposal has an observed support
        # function or a public material predicate. Missing recall stays unknown.
        recalled=[]
        for code in self.available_ids:
            if code in current:continue
            score,reasons=self.mechanisms.support(code,summary)
            if score>0:recalled.append((code,score,reasons))
        recalled.sort(key=lambda v:(-v[1],self.mechanisms.card(v[0]).text_sha256,v[0]))
        for zone in ("main","extra",None):
            needed=sum(self.builder.task.sizes.values()) if zone is None else self.builder.task.sizes[zone]
            for code,score,reasons in recalled:
                if self._capacity(current,zone)>=needed:break
                if code in current:continue
                if zone is not None and bool(self.assets.rows[code]["type"]&EXTRA_TYPES)!=(zone=="extra"):continue
                if len(current)>=self.pool_limit:break
                current.append(code)
            if self._capacity(current,zone)<needed:
                raise ContractError("mechanism-supported recall lacks section/copy capacity; unsupported effects remain unknown")
        # Additional alternatives remain program proposals, never learned picks.
        for code,score,reasons in recalled:
            if len(current)>=min(self.pool_limit,max(32,len(mandatory)+16)):break
            if code not in current:current.append(code)
        return tuple(sorted(current))

    def _task_batch(self, tasks, decks=None):
        encoded = [self.builder.encoder.encode(task, DeckParts((),(),()) if decks is None else deck)
                   for task,deck in zip(tasks, [None]*len(tasks) if decks is None else decks)]
        length = max(len(r[0]) for r in encoded)
        result = {"tokens":torch.zeros(len(tasks),length,4,dtype=torch.long),
                  "numbers":torch.zeros(len(tasks),length,10),"state":torch.tensor([r[2] for r in encoded],dtype=torch.float32),
                   "mechanisms":torch.zeros(len(tasks),length,MECHANISM_WIDTH),
                  "mask":torch.zeros(len(tasks),length,dtype=torch.bool)}
        for i,(tokens,numbers,_) in enumerate(encoded):
            result["tokens"][i,:len(tokens)] = torch.tensor(tokens)
            result["numbers"][i,:len(tokens)] = torch.tensor(numbers)
            result["mask"][i,:len(tokens)] = True
            deck=DeckParts((),(),()) if decks is None else decks[i]
            result['mechanisms'][i,:len(tokens)]=torch.tensor(self.builder.encoder.mechanism_features(tasks[i],deck,tokens))
        return result

    def propose_tasks(self):
        self._check()
        mandatory = {r['card_id'] for r in self.builder.task.requirements} | _referenced_ids(self.source_binding.get('construction_goal', self.builder.task.goal))
        themes, candidates, omitted = self.enumerate_themes(), [], []
        if self.allowed_theme_ids is not None:
            themes = [t for t in themes if t["theme_id"] in self.allowed_theme_ids]
        if not mandatory <= set(self.available_ids):
            return {"status":"fixed_goal_card_unavailable","candidates":[],"omitted":[],"goal_preserved":True}
        for theme in themes:
            try:pool=self._pool(theme,mandatory)
            except ContractError as error:
                omitted.append({"theme_id":theme["theme_id"],"reason":str(error)});continue
            for route in self._route_goals(pool,theme):
                current = list(pool)
                protected = mandatory | _referenced_ids(route or {})
                try:
                    while True:
                        task = self._task(theme,current,route)
                        self.assets.check_task(task)
                        size = len(self.builder.encoder.encode(task,DeckParts((),(),()))[0]) + sum(task.sizes.values())
                        if size <= self.builder.encoder.config.max_tokens: break
                        removable=[c for c in current if c not in protected and c not in theme['card_ids']]
                        mechanism=self.mechanisms.summarize(theme['card_ids'])
                        remove=min(removable,key=lambda c:(self.mechanisms.support(c,mechanism)[0],c)) if removable else None
                        if remove is None:
                            raise ContractError("theme/task exceeds existing model context capacity")
                        current.remove(remove)
                    if not set(current) & set(theme["card_ids"]):
                        raise ContractError("no current theme card fits the bounded task pool")
                    if (any(self._capacity(current,z)<task.sizes[z] for z in ("main","extra")) or
                            self._capacity(current)<sum(task.sizes.values())):
                        raise ContractError("context-limited pool lacks legal listing capacity")
                    candidates.append({"candidate_id":task.sha256,"task":task.to_dict(),"theme":deepcopy(theme),
                        "mechanisms":self.mechanisms.summarize(theme['card_ids']),
                        "goal_proposal_origin":('host_explicit_route' if self.source_binding.get('construction_goal',self.builder.task.goal).get('route_goal')
                            else 'bounded_effect_semantics' if route and route['kind']=='fusion_summon' else 'public_attribute_proposal'),
                        "proposal_source":"bounded_public_catalog_tasks_not_learned_generation", "cb_goal_proposed":route is not None})
                except ContractError as error:
                    omitted.append({"theme_id":theme["theme_id"],"reason":str(error)})
        if not candidates:
            return {"status":"no_supported_task_candidates","candidates":[],"omitted":omitted,"goal_preserved":True}
        scores=[];model=self.builder.models["build_goal"];was_training=model.training
        model.eval()
        try:
            with torch.no_grad():
                for start in range(0,len(candidates),32):
                    tasks=[BuildTask.from_dict(c["task"]) for c in candidates[start:start+32]]
                    scores.extend(model(self._task_batch(tasks)).detach().cpu().tolist())
        finally: model.train(was_training)
        if any(not math.isfinite(v) for v in scores):raise ContractError("nonfinite actual goal-model task scores")
        for candidate,score in zip(candidates,scores):candidate["model_score_uncalibrated"]=score
        ranked=sorted(candidates,key=lambda c:(-c["model_score_uncalibrated"],c["candidate_id"]))
        output={"status":"model_ranked_tasks","candidates":ranked[:self.candidate_limit],"scored_candidate_count":len(candidates),
            "all_scores":[{"candidate_id":c["candidate_id"],"score":c["model_score_uncalibrated"]} for c in candidates],
            "omitted":omitted,"enumerated_theme_count":len(themes),"binding_sha256":self._binding_sha256,
            "model_sha256":parameter_digest(model),"trained_ability_verified":False}
        output["proposal_sha256"]=digest(output)
        self._proposal_seals.add(output["proposal_sha256"])
        return output

    def _check_proposals(self, proposals):
        raw={k:v for k,v in proposals.items() if k!="proposal_sha256"}
        if (proposals.get("proposal_sha256") not in self._proposal_seals or
                digest(raw)!=proposals.get("proposal_sha256") or proposals.get("binding_sha256")!=self._binding_sha256):
            raise ContractError("task proposals/scores changed or were not generated by this kernel")

    def select_task(self, proposals=None, *, rank=0):
        self._check()
        integer(rank,"actual model-ranked task position",0)
        proposals=self.propose_tasks() if proposals is None else proposals
        if proposals.get("status")!="model_ranked_tasks":return deepcopy(proposals)
        self._check_proposals(proposals)
        if proposals.get("binding_sha256")!=self._binding_sha256 or proposals.get("model_sha256")!=parameter_digest(self.builder.models["build_goal"]):
            raise ContractError("task selection scores belong to stale source/model state")
        candidates=proposals["candidates"]
        if candidates:integer(rank,"actual model-ranked task position",0,len(candidates)-1)
        if not candidates or (len({v["score"] for v in proposals["all_scores"]})<2 and not (len(candidates)==1 and self.allowed_theme_ids is not None)):
            return {"status":"model_selection_unresolved","reason":"no discriminating model scores; no rule-theme fallback"}
        selected=deepcopy(candidates[rank]);task=BuildTask.from_dict(selected["task"])
        self.assets.check_task(task)
        selected.update(status="model_selected_task", selection_method=("user_fixed_theme_single_task_model_scored" if len(candidates)==1 and self.allowed_theme_ids is not None else "model_ranked_task_choice"),binding_sha256=self._binding_sha256,
                        selected_model_sha256=proposals["model_sha256"],goal_sha256=digest(task.goal))
        self.selections[selected["candidate_id"]]=deepcopy(selected)
        return selected

    def _selection(self, selection):
        self._check()
        ident=selection.get("candidate_id")
        if ident not in self.selections or selection!=self.selections[ident]:
            raise ContractError("autonomous selection/task/theme changed or was not selected")
        return BuildTask.from_dict(selection["task"])

    def _validate_restored_selection(self, ident, selection):
        task=BuildTask.from_dict(selection["task"])
        theme=selection["theme"]
        actual=next((t for t in self.enumerate_themes() if t["theme_id"]==theme.get("theme_id")),None)
        if (actual!=theme or ident!=task.sha256 or selection["binding_sha256"]!=self._binding_sha256 or
                selection["goal_sha256"]!=digest(task.goal) or selection.get("status")!="model_selected_task" or
                task.to_dict()!=self._task(theme,task.pool,task.goal.get("route_goal")).to_dict()):
            raise ContractError("restored task/theme changed the original course goal")
        self.builder.encoder.encode(task,DeckParts((),(),()))

    def _session(self, selection):
        task=self._selection(selection);ident=selection["candidate_id"]
        if ident not in self.sessions:
            from .build_intent import IntentClassification
            theme=selection["theme"];term=theme["tag"]["value"]
            session=ConstructionSession("Autonomous model-selected explicit scope "+term,task)
            # This is an already-selected internal task, never a user-text
            # classifier prediction or a fabricated trained confidence score.
            session.classification=IntentClassification("narrow",1.0,(term,),reasons=("explicit internal task assignment; not text classification",))
            effect_tags, _ = reviewed_effect_blocks(self.assets, task.pool)
            theme_tag=LogicTag.from_dict(theme["tag"])
            requested=self.source_binding.get("construction_logic_requirements",{"tags":[],"connector_kinds":[]})
            if not isinstance(requested,dict) or set(requested)!={"tags","connector_kinds"}:
                raise ContractError("explicit construction logic requirements need tags and connector_kinds")
            mechanism=self.mechanisms.summarize(theme['card_ids'])
            inferred=tuple(t for t in effect_tags if mechanism['grave_effect_triggers'] and mechanism['fusion_effects'])
            required_tags=tuple(dict.fromkeys((theme_tag,*inferred,*(LogicTag.from_dict(t) for t in requested["tags"]))))
            required_kinds=tuple(requested["connector_kinds"])
            codec=LogicCodec((*required_tags,*effect_tags),tuple(dict.fromkeys(("ns","ss","送墓时发动",*required_kinds))))
            self.sessions[ident]=session
            self.adapters[ident]=_SharedLogicAdapter(task,self.builder,codec,self.graph_updates,
                required_tags=required_tags,required_connector_kinds=required_kinds)
        return self.sessions[ident],self.adapters[ident]

    def construction_mechanism_groups(self, selection):
        """Plug directly into construction_candidates.portfolio's existing seam."""
        task=self._selection(selection)
        core=tuple(c for c in selection['theme']['card_ids'] if c in task.pool)
        return self.mechanisms.construction_mechanism_groups(task.pool,core)

    def run_selected(self, selection, *, feedback=(), base=None, verifier=existing_goal_verifier,basic_cb_recorder=None,budget=None,basic_cb_verifier=None):
        session,adapter=self._session(selection)
        for item in feedback:
            session.record_feedback(item["source"],item["message"])
        theme=selection["theme"];tag=LogicTag.from_dict(theme["tag"])
        effect_tags, assessments = reviewed_effect_blocks(self.assets, session.task.pool, catalog=self.mechanisms)
        binding=CatalogBindingAdapter(self.assets,fact_tags=(PublicFactTag(tag,theme["field"],theme["value"],theme["source"]),),assessments=assessments)
        controller=ConstructionController(adapter,binding,self.coordinator)
        scope=ThemeScope(theme["tag"]["value"],theme["field"],theme["value"],theme["source"],self.theme_minimum)
        basic_provider=None
        if self.source_binding.get('basic_cb_stage')=='after_construction':
            from .basic_cb_inference import infer_basic_cb
            def basic_provider(task,deck,assets):
                seconds=20. if budget is None else min(20.,budget.check('before_basic_cb_provider'))
                inference=infer_basic_cb(task,deck,assets,builder=self.builder,seconds=seconds,
                                         verifier=basic_cb_verifier,budget=budget)
                if budget is not None:budget.check('after_basic_cb_provider')
                if basic_cb_recorder is not None:basic_cb_recorder(task,deck,inference)
                from .proof_visibility import without_private_selection_key
                return without_private_selection_key(inference)
        mechanism_groups=self.construction_mechanism_groups(selection)
        result=controller.run(session,scopes=(scope,),base=base,verifier=verifier,
                              basic_cb_provider=basic_provider,mechanism_groups=mechanism_groups)
        result.update(selected_task_sha256=session.task.sha256,selected_theme_id=theme["theme_id"],
            internal_task_assignment=True,text_classifier_inference=False,goal_preserved=True,
             mechanisms=self.mechanisms.summarize(theme['card_ids']),
             construction_mechanism_groups=mechanism_groups,
             mechanism_inference='bounded_card_text_recognition_not_trained_model_claim',
            ability_verified=False,
            effect_blocks={'status':'source_reviewed' if effect_tags else 'reviewed_effect_vocabulary_unavailable',
                           'tags':[{'dimension':t.dimension,'value':t.value} for t in effect_tags],
                           'assessment_count':len(assessments),'connectors_separate':True,
                            'user_requested':deepcopy(self.source_binding.get('construction_logic_requirements',{'tags':[],'connector_kinds':[]})),
                            'requirements_include_inferred_mechanism_proposals':True,
                            'requested':adapter.requirements(),'reviews_define_requirements':False})
        result["basic_cb_inference_performed"]=bool((result.get("basic_cb") or {}).get("inference_completed"))
        return result

    def preference_loss(self, proposals, preferred_id, *, source, purpose="train"):
        """Actual differentiable task-choice loss; host applies its own updater."""
        self._check()
        if purpose!="train" or source not in ("human_preference","real_duel_feedback","synthetic_code_path_only"):
            raise ContractError("explicit training-only preference provenance required")
        self._check_proposals(proposals)
        candidates=proposals["candidates"];ids=[c["candidate_id"] for c in candidates]
        if preferred_id not in ids or len(ids)<2:raise ContractError("preference requires an existing choice and alternatives")
        model=self.builder.models["build_goal"]
        logits=model(self._task_batch([BuildTask.from_dict(c["task"]) for c in candidates]))
        loss=F.cross_entropy(logits.unsqueeze(0),torch.tensor([ids.index(preferred_id)],device=logits.device))
        return {"loss":loss,"receipt":{"source":source,"purpose":purpose,"role":"build_goal",
            "binding_sha256":self._binding_sha256,"preferred_id":preferred_id,"ability_verified":False,
            "before_sha256":parameter_digest(model),
            "optimizer_step_performed":False,"data_admission_checked":False}}

    def graph_preference_loss(self, selection, preferred_index, *, role="build_optimizer",source,purpose="train"):
        """Existing graph proposals/features, real shared-role differentiable loss."""
        if role not in ROLES or purpose!="train" or source not in ("human_preference","real_duel_feedback","synthetic_code_path_only"):
            raise ContractError("explicit graph training preference required")
        from .construction_model import rule_graph_candidates
        session,adapter=self._session(selection)
        context={"request":session.request,"goal_sha256":session.goal_sha256,"task":session.task.to_dict(),
            "logic":session.logic.to_dict() if session.logic else None,"feedback":deepcopy(session.feedback),"role":role}
        if role=="build_optimizer" and session.logic is None:
            raise ContractError("graph optimization requires an existing target graph")
        graphs=adapter.candidates(context)
        integer(preferred_index,"graph preference index",0,len(graphs)-1)
        adapter._check(context,graphs)
        model=self.builder.models[role]
        logits=model(adapter.encoder.batch(context,graphs))
        return {"loss":F.cross_entropy(logits.unsqueeze(0),torch.tensor([preferred_index],device=logits.device)),
            "receipt":{"source":source,"purpose":purpose,"role":role,"task_sha256":session.task.sha256,
            "binding_sha256":self._binding_sha256,"graph_sha256s":[g.sha256 for g in graphs],
            "before_sha256":parameter_digest(model),"goal_preserved":True,
            "optimizer_step_performed":False,"data_admission_checked":False,"ability_verified":False}}

    def fill_preference_loss(self, selection, better, worse, *, role="build_optimizer",source,purpose="train"):
        task=self._selection(selection)
        if role not in ROLES or purpose!="train" or source not in ("human_preference","real_duel_feedback","synthetic_code_path_only"):
            raise ContractError("explicit same-goal training preference required")
        for deck in (better,worse):self.assets.validate(task,deck)
        logits=self.builder.models[role](self.builder.encoder.batch(task,[better,worse]))
        return {"loss":F.softplus(logits[1]-logits[0]),"receipt":{"role":role,"source":source,
            "task_sha256":task.sha256,"goal_preserved":True,"before_sha256":parameter_digest(self.builder.models[role]),
            "optimizer_step_performed":False,"data_admission_checked":False,"ability_verified":False}}

    def record_update(self, role, *, before_sha256, after_sha256, graph_objective=False):
        """Record a completed host-managed update, never perform an optimizer step."""
        self._check()
        if (role not in ROLES or not isinstance(before_sha256,str) or len(before_sha256)!=64 or
                before_sha256==after_sha256 or after_sha256!=parameter_digest(self.builder.models[role])):
            raise ContractError("host update must identify changed current role weights")
        self.updates[role]+=1
        if graph_objective:self.graph_updates[role]+=1
        return {"role":role,"host_update_count":self.updates[role],
                "graph_objective_update_count":self.graph_updates[role],"ability_verified":False}

    def state_dict(self):
        self._check()
        return {"schema_version":1,"feature_version":FEATURE_VERSION,"binding_sha256":self._binding_sha256,
            "encoder_binding":self.builder.encoder.binding(),"model_hashes":{r:parameter_digest(self.builder.models[r]) for r in ROLES},
            "selections":deepcopy(self.selections),"sessions":{k:{"state":s.to_dict(),"accepted_fill":deepcopy(s._accepted_fill)} for k,s in self.sessions.items()},
            "updates":dict(self.updates),"graph_updates":dict(self.graph_updates),
            "proposal_seals":sorted(self._proposal_seals),"weights_owned_by_group_checkpoint":True}

    def load_state_dict(self, state):
        self._check()
        if (not isinstance(state,dict) or state.get("schema_version")!=1 or state.get("feature_version")!=FEATURE_VERSION or
                state.get("binding_sha256")!=self._binding_sha256 or state.get("encoder_binding")!=self.builder.encoder.binding() or
                state.get("model_hashes")!={r:parameter_digest(self.builder.models[r]) for r in ROLES}):
            raise ContractError("autonomous metadata restore requires exact course/model/vocabulary binding")
        from .construction_logic import ConstructionLogic
        # Validate in temporary kernel metadata; failed restoration does not
        # mutate live selections or lose the previous feedback/session state.
        backup=(self.selections,self.sessions,self.adapters,self.updates,self.graph_updates,self._proposal_seals)
        try:
            self.selections=deepcopy(state["selections"]);self.sessions={};self.adapters={}
            self.updates={r:integer(state["updates"][r],"autonomous host update count",0) for r in ROLES}
            self.graph_updates={r:integer(state.get("graph_updates",{}).get(r,0),"graph objective update count",0,self.updates[r]) for r in ROLES}
            seals=state["proposal_seals"]
            if (not isinstance(seals,list) or len(set(seals))!=len(seals) or
                    any(not isinstance(s,str) or len(s)!=64 or any(c not in "0123456789abcdef" for c in s) for s in seals)):
                raise ContractError("restored task proposal seals differ")
            self._proposal_seals=set(seals)
            for ident,selection in self.selections.items():
                self._validate_restored_selection(ident,selection)
            for ident,saved in state["sessions"].items():
                session,adapter=self._session(self.selections[ident]);raw=saved["state"]
                if (raw["request"]!=session.request or raw["task"]!=session.task.to_dict() or
                        raw["goal_sha256"]!=session.goal_sha256 or raw["classification"]!=session.classification.to_dict()):
                    raise ContractError("restored session goal or explicit internal scope differs")
                for event in raw["history"]:
                    if event.get("stage")==1:
                        session.submit_logic(ConstructionLogic.from_dict(event["logic"]),role=event["role"],reason=event["reason"])
                if (session.logic.to_dict() if session.logic else None)!=raw["logic"]:
                    raise ContractError("restored logic revision ancestry differs")
                session.history=deepcopy(raw["history"])
                session.feedback=[]
                for item in raw["feedback"]:
                    session.record_feedback(item["source"],item["message"])
                session.feedback=deepcopy(raw["feedback"])
                required=raw["logic_requirements_sha256"]
                if required is not None and required!=adapter.requirements_sha256:
                    raise ContractError("restored graph tag requirements differ")
                if required is not None:session.logic_requirements_sha256=required
                accepted=deepcopy(saved["accepted_fill"])
                if accepted is not None:
                    if (session.logic is None or accepted["task_sha256"]!=session.task.sha256 or
                            accepted["logic_sha256"]!=session.logic.sha256):
                        raise ContractError("restored accepted fill belongs to another goal/logic")
                    self.assets.validate(session.task,DeckParts.from_dict(accepted["deck"]))
                session._accepted_fill=accepted
        except (ContractError,KeyError,TypeError,ValueError) as error:
            self.selections,self.sessions,self.adapters,self.updates,self.graph_updates,self._proposal_seals=backup
            raise ContractError("autonomous metadata restore rejected without changing live state") from error
