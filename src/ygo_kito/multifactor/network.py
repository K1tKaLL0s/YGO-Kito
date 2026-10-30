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

    def __post_init__(self):
        for name, low, high in (("hidden_dim", 8, 256), ("message_rounds", 1, 4), ("seed", 0, 2**31 - 1)):
            if type(getattr(self, name)) is not int or not low <= getattr(self, name) <= high:
                raise FactorContractError(f"invalid {name}")


def encode_batch(examples, *, device="cpu"):
    if not isinstance(examples, (list, tuple)) or not 1 <= len(examples) <= 64 or any(not isinstance(e, RoleInput) for e in examples):
        raise FactorContractError("1..64 typed role examples required")
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
    return dict(groups=groups, relations=relations, context=context, mask=mask)


class RoleNetwork(nn.Module):
    def __init__(self, config=NetworkConfig()):
        super().__init__()
        self.config = config
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

    def forward(self, batch):
        mask = batch["mask"]
        count = mask.sum(1, keepdim=True).clamp_min(1)
        node = self.group_encoder(batch["groups"]) * mask.unsqueeze(-1)
        context = self.context_encoder(batch["context"])
        relation = self.relation_encoder(batch["relations"])
        pair_mask = mask[:, :, None] & mask[:, None, :]
        # Internal dependency is a group factor, not a duplicate self-edge.
        off_diagonal = ~torch.eye(node.shape[1], device=node.device, dtype=torch.bool)
        message_mask = pair_mask & off_diagonal
        degree = message_mask.sum(2, keepdim=True).clamp_min(1)
        for message, update in zip(self.messages, self.updates):
            left = node[:, :, None, :].expand(-1, -1, node.shape[1], -1)
            right = node[:, None, :, :].expand(-1, node.shape[1], -1, -1)
            directed = message(torch.cat((left, right, relation), dim=-1)) * message_mask.unsqueeze(-1)
            outgoing = directed.sum(2) / degree
            incoming = directed.sum(1) / degree
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

    def config_dict(self):
        return asdict(self.config)
