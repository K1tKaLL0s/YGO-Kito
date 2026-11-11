"""Small relation-aware set network. No positional, name or identity embeddings."""

from dataclasses import asdict, dataclass

import torch
from torch import nn

from .contracts import CONTEXT_FACTORS, GROUP_FACTORS, RELATION_FACTORS, ROLES, FactorContractError, Factors, RoleInput


@dataclass(frozen=True)
class NetworkConfig:
    hidden_dim: int = 48
    message_rounds: int = 2
    seed: int = 14
    feature_schema: str = "legacy-v7"
    stream_mode: str = "dual"
    use_route_features: bool = False
    graph_block_size: int = 512
    graph_node_budget: int = 65536
    graph_edge_budget: int = 262144
    dropout: float = 0.0

    def __post_init__(self):
        if type(self.dropout) not in (int, float) or not 0 <= self.dropout < 1:
            raise FactorContractError("dropout must be finite in [0,1)")
        if self.feature_schema != "axis-graph-v3" and self.dropout:
            raise FactorContractError("dropout is only supported by the v3 graph network")
        for name, low, high in (("hidden_dim", 8, 256), ("message_rounds", 1, 4), ("seed", 0, 2**31 - 1)):
            if type(getattr(self, name)) is not int or not low <= getattr(self, name) <= high:
                raise FactorContractError(f"invalid {name}")
        if self.feature_schema not in ("legacy-v7","axis-graph-v3") or self.stream_mode not in ("single","dual") or type(self.use_route_features) is not bool:
            raise FactorContractError("explicit feature schema, stream mode and route switch required")
        for name in ("graph_block_size","graph_node_budget","graph_edge_budget"):
            if type(getattr(self,name)) is not int or not 1<=getattr(self,name)<=1048576:
                raise FactorContractError("bounded graph block/budget required")

    @classmethod
    def v3(cls,**values):
        return cls(**dict(dict(hidden_dim=64,message_rounds=2,feature_schema='axis-graph-v3',
                              stream_mode='dual',use_route_features=False),**values))


def encode_batch(examples, *, device="cpu", config=None, training=False):
    if config is not None and config.feature_schema=="axis-graph-v3":
        if not isinstance(examples,(tuple,list)) or not 1<=len(examples)<=64:
            raise FactorContractError("1..64 v3 records required")
        from .graph_network import encode_graph_batch
        from .task_queries import comparison_for_record
        values=list(examples)
        comparisons={}
        for index,row in enumerate(examples):
            if isinstance(row,dict) and row.get("comparison") is not None:
                comparison=comparison_for_record(row)
                comparisons[index]=len(values)
                values.append(comparison["right"])
        batch=encode_graph_batch(values,device=device,config=config,training=training)
        batch["comparison_indices"]=comparisons
        batch["record_count"]=len(examples)
        return batch
    if training:
        raise FactorContractError('training-only query support requires explicit v3 encoding')
    if not isinstance(examples, (list, tuple)) or not 1 <= len(examples) <= 64 or any(not isinstance(e, RoleInput) for e in examples):
        raise FactorContractError("1..64 typed role examples required")
    if any(e.analysis_mode is not None for e in examples):
        raise FactorContractError("v3 requires an explicit v3 NetworkConfig and GraphBuild/record observations")
    size, count = len(examples), max(len(e.groups) for e in examples)
    groups = torch.zeros(size, count, 4 * len(GROUP_FACTORS), device=device)
    relations = torch.zeros(size, count, count, 4 * len(RELATION_FACTORS), device=device)
    relations[:] = torch.tensor(Factors("relation").channels(), device=device)
    mask = torch.zeros(size, count, dtype=torch.bool, device=device)
    context = torch.tensor([e.context.channels() for e in examples], dtype=torch.float32, device=device)
    for b, example in enumerate(examples):
        mask[b, :len(example.groups)] = True
        groups[b, :len(example.groups)] = torch.tensor([group.encoded_factors().channels() for group in example.groups], device=device)
        indices = {group.key: i for i, group in enumerate(example.groups)}
        for edge in example.relations:
            relations[b, indices[edge.source], indices[edge.target]] = torch.tensor(edge.factors.channels(), device=device)
    structural_mask=mask.clone()
    for b,example in enumerate(examples):
        for g,group in enumerate(example.groups):
            if any(group.factors.get(name).value==1 for name in ("node_primary_plan","node_plan_clause","node_goal_only_card","node_condition")):structural_mask[b,g]=False
    structural_groups=groups.clone();structural_context=context.clone()
    unknown=torch.tensor((0.,0.,0.,1.),device=device)
    for i,name in enumerate(GROUP_FACTORS):
        if name.startswith("plan_") or name in ("node_goal_only_card","node_primary_plan","node_plan_clause","unit_conditions_satisfied"):structural_groups[...,4*i:4*i+4]=unknown
    for i,name in enumerate(CONTEXT_FACTORS):
        if name.startswith(("objective_","plan_","goal_")):structural_context[...,4*i:4*i+4]=unknown
    role_mask=mask.clone();role_groups=groups.clone()
    for b,example in enumerate(examples):
        for g,group in enumerate(example.groups):
            if group.factors.get("node_condition").value==1 and group.factors.get("condition_construct_compatibility").value!=1:role_mask[b,g]=False
    i=GROUP_FACTORS.index("unit_conditions_satisfied");role_groups[...,4*i:4*i+4]=unknown
    return dict(groups=groups,relations=relations,context=context,mask=mask,structural_groups=structural_groups,structural_context=structural_context,structural_mask=structural_mask,role_groups=role_groups,role_mask=role_mask)


class RoleNetwork(nn.Module):
    def __init__(self, config=NetworkConfig()):
        super().__init__()
        self.config = config
        if config.feature_schema=="axis-graph-v3":
            from .graph_network import GraphRoleNetwork
            self.graph_network = GraphRoleNetwork(config)
            return
        width = config.hidden_dim
        # Initialization must not change the host's random stream.
        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(config.seed)
            self.group_encoder = nn.Sequential(nn.Linear(4 * len(GROUP_FACTORS), width), nn.SiLU())
            self.context_encoder = nn.Sequential(nn.Linear(4 * len(CONTEXT_FACTORS), width), nn.SiLU())
            self.relation_encoder = nn.Sequential(nn.Linear(4 * len(RELATION_FACTORS), width), nn.SiLU())
            self.messages = nn.ModuleList(nn.Sequential(nn.Linear(3 * width, width), nn.SiLU())
                                          for _ in range(config.message_rounds))
            self.updates = nn.ModuleList(nn.Sequential(nn.Linear(4 * width, width), nn.SiLU(), nn.LayerNorm(width))
                                         for _ in range(config.message_rounds))
            self.readout = nn.Sequential(nn.Linear(4 * width, width), nn.SiLU())
            self.role_head = nn.Linear(width, len(ROLES))
            self.compatibility_head = nn.Linear(width, 1)
            self.utility_head = nn.Linear(width, 1)
            self.pair_head = nn.Sequential(nn.Linear(4 * width, width), nn.SiLU(), nn.Linear(width, 1))

    def _forward_once(self, batch):
        mask = batch["mask"]
        count = mask.sum(1, keepdim=True).clamp_min(1)
        node = self.group_encoder(batch["groups"]) * mask.unsqueeze(-1)
        context = self.context_encoder(batch["context"])
        relation = self.relation_encoder(batch["relations"])
        pair_mask = mask[:, :, None] & mask[:, None, :]
        # Internal dependency is a group factor, not a duplicate self-edge.
        off_diagonal = ~torch.eye(node.shape[1], device=node.device, dtype=torch.bool)
        observed_relation_mask = batch["relations"][..., 1::4].bool().any(-1)
        message_mask = pair_mask & off_diagonal & observed_relation_mask
        degree = message_mask.sum(2, keepdim=True).clamp_min(1)
        incoming_degree = message_mask.sum(1).unsqueeze(-1).clamp_min(1)
        for message, update in zip(self.messages, self.updates):
            left = node[:, :, None, :].expand(-1, -1, node.shape[1], -1)
            right = node[:, None, :, :].expand(-1, node.shape[1], -1, -1)
            directed = message(torch.cat((left, right, relation), dim=-1)) * message_mask.unsqueeze(-1)
            outgoing = directed.sum(2) / degree
            incoming = directed.sum(1) / incoming_degree
            ctx = context[:, None, :].expand_as(node)
            node = update(torch.cat((node, incoming, outgoing, ctx), -1)) * mask.unsqueeze(-1)
        pooled = node.sum(1) / count
        # Mean expresses composition; bounded sum retains set multiplicity/load.
        total = node.sum(1) / 64
        global_context = context + pooled + total
        shared = self.readout(torch.cat((node, pooled[:, None, :].expand_as(node),
                                         total[:, None, :].expand_as(node), context[:, None, :].expand_as(node)), -1))
        left, right = node[:, :, None, :], node[:, None, :, :]
        symmetric_relation = relation + relation.transpose(1, 2)
        pair_context = global_context[:, None, None, :].expand_as(symmetric_relation)
        pair_logits = self.pair_head(torch.cat((left + right, left * right, symmetric_relation, pair_context), -1)).squeeze(-1)
        return dict(role_logits=self.role_head(shared) * mask.unsqueeze(-1),
                    compatibility_logits=self.compatibility_head(shared).squeeze(-1) * mask,
                    utility=self.utility_head(shared).squeeze(-1) * mask,
                    pair_logits=pair_logits * pair_mask, mask=mask, pair_mask=pair_mask & off_diagonal,
                    set_representation=pooled, set_load_representation=total)

    def forward(self,batch):
        if self.config.feature_schema=="axis-graph-v3":
            return self.graph_network(batch)
        role_batch=dict(batch,groups=batch["role_groups"],mask=batch["role_mask"])
        result=self._forward_once(role_batch)
        structural=dict(batch,groups=batch["structural_groups"],context=batch["structural_context"],mask=batch["structural_mask"])
        axes=self._forward_once(structural)["role_logits"][...,:2]
        result["role_logits"]=torch.cat((axes,result["role_logits"][...,2:]),dim=-1)
        return result

    def score_queries(self,output,batch,queries):
        if self.config.feature_schema!="axis-graph-v3":
            raise FactorContractError("typed task queries require v3")
        ordinary=[(i,q) for i,q in enumerate(queries) if q[1]!="copy_preference"]
        result=[None]*len(queries)
        for (index,_),value in zip(ordinary,self.graph_network.score_queries(output,batch,[q for _,q in ordinary])):
            result[index]=value
        for i,(index,task,subject,coordinate) in enumerate(queries):
            if task!="copy_preference":
                continue
            right=batch.get("comparison_indices",{}).get(index)
            if right is None or coordinate!="preference":
                raise FactorContractError("copy preference needs a paired configuration record")
            # Endpoints were checked against both fact domains during encoding.
            result[i]=self.graph_network.score_preference(output,batch,subject[0],subject[1],left_index=index,right_index=right)
        return result

    def config_dict(self):
        return asdict(self.config)
