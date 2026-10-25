"""Trainable graph selection using the existing two BuildRanker instances.

The program enumerates bounded coarse graphs; models score/select them. This is
not autoregressive graph generation. Graph batches reuse the existing numeric,
position and kind projections, with no new network or card-embedding remapping.
"""
from dataclasses import asdict
from copy import deepcopy
from itertools import islice, permutations
import hashlib
import math
from pathlib import Path

import torch
from torch.nn import functional as F

from .build_contracts import digest
from .construction_logic import ConstructionLogic, LogicConnector, LogicMetadata, LogicNode, LogicTag
from .duel_model import parameter_digest
from .device import (model_device, execution_metadata, checkpoint_execution, optimizer_to,
                     capture_device_rng, restore_device_rng)
from .validation import ContractError, array, canonical_json, fields, integer

ROLES = ("build_goal", "build_optimizer")
FEATURE_VERSION = "construction-graph-numeric-v1"


class LogicCodec:
    """Lossless graph→indexed tags/nodes/connectors→graph, without card IDs."""
    def __init__(self, tags, connector_kinds=("ns", "ss", "送墓时发动")):
        self.tags = tuple(sorted(set(tags), key=lambda t: (t.dimension, t.value)))
        self.kinds = tuple(sorted(set(connector_kinds)))
        if not self.tags or len(self.tags) > 256 or any(not isinstance(t, LogicTag) for t in self.tags):
            raise ContractError("bounded typed graph tag vocabulary required")
        if not self.kinds or len(self.kinds) > 32 or any(not isinstance(k, str) or not 1 <= len(k) <= 32 for k in self.kinds):
            raise ContractError("bounded coarse connector vocabulary required")

    def encode(self, graph):
        ids = {n.node_id: i for i, n in enumerate(graph.nodes)}
        try:
            return {"logic_id": graph.logic_id, "revision": graph.revision, "parent_sha256": graph.parent_sha256,
                    "nodes": [{"id": n.node_id, "tags": [self.tags.index(t) for t in n.tags],
                               "metadata": [asdict(m) for m in n.metadata]} for n in graph.nodes],
                    "edges": [{"id": e.connector_id, "source": ids[e.source], "target": ids[e.target],
                               "kind": self.kinds.index(e.kind)} for e in graph.connectors],
                    "entries": [ids[n] for n in graph.entry_nodes], "goals": [ids[n] for n in graph.goal_nodes]}
        except ValueError as error:
            raise ContractError("graph contains an unseen tag/connector; extend the vocabulary explicitly") from error

    def decode(self, value):
        d = fields(value, {"logic_id", "revision", "parent_sha256", "nodes", "edges", "entries", "goals"})
        nodes = []
        for row in array(d["nodes"], "encoded graph nodes"):
            fields(row, {"id", "tags", "metadata"})
            tags = tuple(self.tags[integer(i, "tag index", 0, len(self.tags)-1)] for i in array(row["tags"], "tag indices"))
            nodes.append(LogicNode(row["id"], tags, tuple(LogicMetadata.from_dict(m) for m in array(row["metadata"], "metadata"))))
        def name(i):
            return nodes[integer(i, "node index", 0, len(nodes)-1)].node_id
        edges = []
        for row in array(d["edges"], "encoded edges"):
            fields(row, {"id", "source", "target", "kind"})
            edges.append(LogicConnector(row["id"], name(row["source"]), name(row["target"]),
                self.kinds[integer(row["kind"], "connector index", 0, len(self.kinds)-1)]))
        return ConstructionLogic(d["logic_id"], tuple(nodes), tuple(edges),
            tuple(name(i) for i in array(d["entries"], "entry indices")),
            tuple(name(i) for i in array(d["goals"], "goal indices")), d["revision"], d["parent_sha256"])

    def to_dict(self):
        return {"tags": [asdict(t) for t in self.tags], "connector_kinds": list(self.kinds)}

    @classmethod
    def from_dict(cls, value):
        d = fields(value, {"tags", "connector_kinds"})
        return cls(tuple(LogicTag.from_dict(t) for t in array(d["tags"], "tags")), tuple(array(d["connector_kinds"], "connector kinds")))


def rule_graph_candidates(context, codec, *, limit=8):
    """Explicit program proposals, selected by the goal/optimizer model later.

    Every vocabulary tag is a required requested feature. Candidate order/edges
    vary; no topic enumeration and no exact card binding are used here.
    """
    integer(limit, "graph candidates", 2, 16)
    previous = ConstructionLogic.from_dict(context["logic"]) if context.get("logic") else None
    ident = previous.logic_id if previous else "logic-" + context["goal_sha256"][:16]
    revision, parent = (previous.revision + 1, previous.sha256) if previous else (0, None)
    tags = codec.tags
    if len(tags) > 8:
        raise ContractError("bounded graph proposal supports at most eight requested tags")
    proposals = []
    if previous:
        # The existing proposal is one option, with a new explicit revision.
        raw = previous.to_dict(); raw.update(revision=revision, parent_sha256=parent)
        proposals.append(ConstructionLogic.from_dict(raw))
    # Grouped and distributed views give a candidate even for one requested tag.
    metadata = (LogicMetadata("rule-candidate-generator-v1", "engineering", "Program proposal; model ranking is separate."),)
    proposals.append(ConstructionLogic(ident, (LogicNode("goal", tags, metadata),), (), ("goal",), ("goal",), revision, parent))
    orders = list(islice(permutations(tags), min(6, limit)))
    for order in orders:
        nodes = tuple(LogicNode("n" + str(i), (tag,), metadata) for i, tag in enumerate(order))
        # A role node is unnecessary: duplicate the feature to expose a coarse
        # connector choice for a one-feature request, without adding a new goal.
        if len(nodes) == 1:
            nodes += (LogicNode("n1", nodes[0].tags, metadata),)
        for kind in codec.kinds:
            edges = tuple(LogicConnector("e" + str(i), nodes[i].node_id, nodes[i+1].node_id, kind) for i in range(len(nodes)-1))
            proposals.append(ConstructionLogic(ident, nodes, edges, (nodes[0].node_id,), (nodes[-1].node_id,), revision, parent))
            if len(proposals) >= limit:
                break
        if len(proposals) >= limit:
            break
    # A branch/merge proposal is an ordinary coarse graph, not a legal CB.
    if len(tags) >= 3:
        nodes = tuple(LogicNode("n"+str(i), (tag,), metadata) for i,tag in enumerate(tags))
        pairs = [(0,1), (0,2), (1,len(nodes)-1), (2,len(nodes)-1)] if len(nodes)>3 else [(0,1),(0,2),(1,2)]
        graph = ConstructionLogic(ident, nodes, tuple(LogicConnector("b"+str(i), nodes[a].node_id, nodes[b].node_id, codec.kinds[0])
            for i,(a,b) in enumerate(pairs)), ("n0",), (nodes[-1].node_id,), revision, parent)
        proposals[-1] = graph
    unique = {g.sha256: g for g in proposals}
    return list(unique.values())[:limit]


def _numbers(value):
    """Fixed ten numeric features; no new embedding table or learned weights."""
    out = [0.] * 10
    encoded = value.encode("utf-8")
    # Byte bigrams retain a little shared text structure with fixed dimensions.
    for i in range(max(1, len(encoded)-1)):
        raw = hashlib.sha256(encoded[i:i+2]).digest()
        out[raw[0] % 10] += 1. if raw[1] & 1 else -1.
    norm = max(1., math.sqrt(sum(x*x for x in out)))
    return [x/norm for x in out]


class LogicFeatureEncoder:
    def __init__(self, codec, max_tokens):
        self.codec, self.max_tokens = codec, max_tokens

    def batch(self, context, graphs):
        integer(len(graphs), "graph rank batch", 1, 16)
        rows = []
        for graph in graphs:
            self.codec.encode(graph)
            tokens, numbers = [[0,0,0,0]], [_numbers(context["request"])]
            nodes = {n.node_id:i for i,n in enumerate(graph.nodes)}
            for node in graph.nodes:
                for tag in sorted(node.tags, key=lambda t:(t.dimension,t.value)):
                    tokens.append([0,0,0,6]); vector = _numbers(tag.dimension+":"+tag.value)
                    vector[-3:] = [nodes[node.node_id]/64, float(node.node_id in graph.goal_nodes), float(node.node_id in graph.entry_nodes)]
                    numbers.append(vector)
            for edge in graph.connectors:
                tokens.append([0,0,0,5]); vector = _numbers(edge.kind)
                vector[-2:] = [nodes[edge.source]/64,nodes[edge.target]/64]; numbers.append(vector)
            for item in context.get("feedback", [])[-8:]:
                tokens.append([0,0,0,3]); numbers.append(_numbers(item["message"]))
            if len(tokens)>self.max_tokens:
                raise ContractError("graph exceeds existing model token capacity")
            state = [len(graph.nodes)/64, len(graph.connectors)/128, len(graph.goal_nodes)/64,
                     len(graph.entry_nodes)/64, len(context.get("feedback",[]))/100, float(context["role"]=="build_optimizer")]
            rows.append((tokens,numbers,state))
        width=max(len(r[0]) for r in rows)
        batch={"tokens":torch.zeros(len(rows),width,4,dtype=torch.long), "numbers":torch.zeros(len(rows),width,10),
               "state":torch.tensor([r[2] for r in rows],dtype=torch.float32), "mask":torch.zeros(len(rows),width,dtype=torch.bool)}
        for i,(tokens,numbers,_) in enumerate(rows):
            batch["tokens"][i,:len(tokens)]=torch.tensor(tokens)
            batch["numbers"][i,:len(tokens)]=torch.tensor(numbers)
            batch["mask"][i,:len(tokens)]=True
        return batch


class LogicModelAdapter:
    def __init__(self, task, models, deck_encoder, codec, *, optimizers=None, learning_rate=.001):
        from .build_model import BuildRanker
        if set(models)!=set(ROLES) or any(not isinstance(m,BuildRanker) for m in models.values()):
            raise ContractError("existing independent BuildRanker roles required")
        if {p.data_ptr() for p in models[ROLES[0]].parameters()} & {p.data_ptr() for p in models[ROLES[1]].parameters()}:
            raise ContractError("graph roles must retain independent parameters")
        deck_encoder.assets.check_task(task)
        self.task, self.models, self.deck_encoder, self.codec = task, models, deck_encoder, codec
        self.device = model_device(models[ROLES[0]])
        if any(model_device(model) != self.device for model in models.values()):
            raise ContractError("graph role models require one execution device")
        self.codec_sha256=digest(codec.to_dict())
        self.encoder=LogicFeatureEncoder(codec,deck_encoder.config.max_tokens)
        if type(learning_rate) not in (int,float) or not math.isfinite(learning_rate) or not 0<learning_rate<=.01:
            raise ContractError("graph learning rate outside CPU range")
        self.optimizers=optimizers if optimizers is not None else {r:torch.optim.AdamW(models[r].parameters(),lr=learning_rate,weight_decay=0.) for r in ROLES}
        if set(self.optimizers)!=set(ROLES):
            raise ContractError("graph optimizers require both existing roles")
        for role in ROLES:
            if not isinstance(self.optimizers[role],torch.optim.Optimizer):
                raise ContractError("typed graph role optimizer required")
            assigned=[p for group in self.optimizers[role].param_groups for p in group["params"]]
            expected=list(self.models[role].parameters())
            if len(assigned)!=len(expected) or {p.data_ptr() for p in assigned}!={p.data_ptr() for p in expected}:
                raise ContractError("graph optimizer is not bound to its role parameters")
        self.updates={r:0 for r in ROLES}; self.last_selection={}

    @classmethod
    def from_builder(cls, builder, codec):
        return cls(builder.task,builder.models,builder.encoder,codec,optimizers=builder.optimizers)

    def _check(self, context, graphs):
        if digest(self.codec.to_dict())!=self.codec_sha256:
            raise ContractError("requested logic tag/connector vocabulary changed")
        if (digest(context["task"]) != self.task.sha256 or context["role"] not in ROLES
                or digest({"request":context["request"],"task":context["task"]}) != context["goal_sha256"]):
            raise ContractError("graph context changed original concrete task")
        required=set(self.codec.tags)
        for graph in graphs:
            if not required <= {t for n in graph.nodes for t in n.tags}:
                raise ContractError("graph candidate drops a requested feature")
            if context.get("logic"):
                old=ConstructionLogic.from_dict(context["logic"])
                if graph.parent_sha256!=old.sha256 or graph.revision!=old.revision+1 or graph.logic_id!=old.logic_id:
                    raise ContractError("graph candidate has stale revision ancestry")

    def scores(self, context, graphs):
        self._check(context,graphs)
        model=self.models[context["role"]]; model.eval()
        with torch.no_grad():
            values=model(self.encoder.batch(context,graphs)).tolist()
        if any(not math.isfinite(s) for s in values):
            raise ContractError("nonfinite graph model scores")
        return values

    def propose(self, context):
        candidates=rule_graph_candidates(context,self.codec)
        scores=self.scores(context,candidates); index=max(range(len(scores)),key=lambda i:scores[i])
        graph=candidates[index]
        self.last_selection[context["role"]]={"candidate_generation":"bounded_program_graphs", "selection":"existing_BuildRanker",
            "scores":scores,"selected_index":index,"model_sha256":parameter_digest(self.models[context["role"]]),
            "graph_training_updates":self.updates[context["role"]],"graph_sha256":graph.sha256,
            "required_tags":[asdict(t) for t in self.codec.tags],"codec_sha256":self.codec_sha256,"feature_version":FEATURE_VERSION}
        return {"logic":self.codec.decode(self.codec.encode(graph)).to_dict(),
                "reason":"Existing role model selected a bounded program graph; scores are uncalibrated."}

    def providers(self):
        return {r:self.propose for r in ROLES}

    def train_preference(self, context, graphs, preferred_index, *, source):
        if source not in ("synthetic_code_path_only", "human_preference"):
            raise ContractError("explicit graph preference source required")
        integer(preferred_index,"preferred graph index",0,len(graphs)-1)
        if len(graphs)<2:raise ContractError("graph preference requires alternatives")
        self._check(context,graphs)
        role=context["role"]; model=self.models[role]; optimizer=self.optimizers[role]
        before=parameter_digest(model); model.train(); optimizer.zero_grad(set_to_none=True)
        logits=model(self.encoder.batch(context,graphs))
        loss=F.cross_entropy(logits.unsqueeze(0),torch.tensor([preferred_index],device=logits.device))
        if not torch.isfinite(loss):raise ContractError("nonfinite graph preference loss")
        loss.backward(); torch.nn.utils.clip_grad_norm_(model.parameters(),1.,error_if_nonfinite=True);optimizer.step()
        after=parameter_digest(model)
        if after==before:raise ContractError("graph preference step did not update role parameters")
        self.updates[role]+=1
        return {"role":role,"source":source,"loss":float(loss.detach()),"before_sha256":before,
                "after_sha256":after,"graph_updates":self.updates[role],"ability_verified":False}

    def save(self, path):
        if digest(self.codec.to_dict())!=self.codec_sha256:raise ContractError("requested logic vocabulary changed")
        state={"kind":FEATURE_VERSION,"task_sha256":self.task.sha256,"codec":self.codec.to_dict(),
               "execution":execution_metadata(self.device),"device_rng":capture_device_rng(self.device),
               "deck_vocabulary_sha256":self.deck_encoder.vocabulary_sha256,
               "config":asdict(self.deck_encoder.config),"updates":self.updates,
               "models":{r:m.state_dict() for r,m in self.models.items()},
               "model_hashes":{r:parameter_digest(m) for r,m in self.models.items()},
               "optimizers":{r:o.state_dict() for r,o in self.optimizers.items()}}
        with Path(path).open("xb") as handle:torch.save(state,handle)

    def load(self, path):
        if digest(self.codec.to_dict())!=self.codec_sha256:raise ContractError("requested logic vocabulary changed")
        state=torch.load(path,map_location="cpu",weights_only=True)
        fields(state,{"kind","task_sha256","codec","deck_vocabulary_sha256","config","updates","models","model_hashes","optimizers"},{"execution","device_rng"})
        checkpoint_execution(state,self.device)
        if any(state.get(k)!=v for k,v in {"kind":FEATURE_VERSION,"task_sha256":self.task.sha256,
            "codec":self.codec.to_dict(),"deck_vocabulary_sha256":self.deck_encoder.vocabulary_sha256,"config":asdict(self.deck_encoder.config)}.items()):
            raise ContractError("graph checkpoint task/codec/model vocabulary differs")
        fields(state["updates"],set(ROLES))
        for key in ("models","model_hashes","optimizers"):fields(state[key],set(ROLES))
        for role in ROLES:
            integer(state["updates"][role],"graph update count",0)
            trial=deepcopy(self.models[role])
            try:trial.load_state_dict(state["models"][role],strict=True)
            except (RuntimeError,ValueError,TypeError) as error:
                raise ContractError("graph checkpoint model layout differs") from error
            if any(not torch.isfinite(p).all() for p in trial.parameters()) or parameter_digest(trial)!=state["model_hashes"][role]:
                raise ContractError("graph model checksum differs")
        backup_models={r:deepcopy(m.state_dict()) for r,m in self.models.items()}
        backup_optimizers={r:deepcopy(o.state_dict()) for r,o in self.optimizers.items()}
        backup_rng=capture_device_rng(self.device)
        try:
            for role in ROLES:
                self.models[role].load_state_dict(state["models"][role],strict=True)
                self.optimizers[role].load_state_dict(state["optimizers"][role])
                optimizer_to(self.optimizers[role],self.device)
            if "device_rng" in state:restore_device_rng(state["device_rng"],self.device)
        except (ValueError,RuntimeError,KeyError,TypeError) as error:
            for role in ROLES:
                self.models[role].load_state_dict(backup_models[role])
                self.optimizers[role].load_state_dict(backup_optimizers[role])
            restore_device_rng(backup_rng,self.device)
            raise ContractError("graph checkpoint restore failed without changing active state") from error
        self.updates=dict(state["updates"])
