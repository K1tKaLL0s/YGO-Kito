"""An independent small CPU Transformer actor/critic over legal player DTOs.

No engine handle, full replay, deck order, opponent hand or RNG seed enters encoding.
This is a bounded engineering prototype, not a competitive pretrained model.
"""

from dataclasses import asdict, dataclass
import hashlib
import math

import torch
from torch import nn

from .contracts import DecisionRequest
from .validation import ContractError, canonical_json, integer

KINDS = ("summon", "special_summon", "set", "activate", "attack", "select", "order", "number", "position", "yes", "no", "pass")
ZONES = ("state", "hand", "monster", "spell_trap", "graveyard", "banished", "extra", "search", "history", "overlay", "sum", "deck")
PHASES = ("draw", "standby", "main1", "battle", "main2", "end")
EVENTS = ("none", "reveal", "move", "activate", "summon", "attack", "phase", "result", "turn", "chain", "lp", "counter", "shuffle", "battle", "position", "announce", "random", "equip", "target", "disabled", "hint")
OPERATIONS = (None, "add", "remove", "finish", "cancel", "shuffle", "sum")
FEATURE_VERSION = "legal-player-dto-v4-private-selection-hierarchy"


@dataclass(frozen=True)
class DuelModelConfig:
    width: int = 32
    card_width: int = 16
    heads: int = 4
    layers: int = 1
    feedforward: int = 64
    history_events: int = 32
    max_tokens: int = 256
    max_actions: int = 2048

    def __post_init__(self):
        for key, value in asdict(self).items():
            integer(value, key, 1, 4096)
        if (self.width % self.heads or self.width > 128 or self.card_width > 64 or self.heads > 16
                or self.layers > 2 or self.feedforward > 512 or self.history_events > 128
                or self.max_actions > 2048 or self.max_tokens > 512):
            raise ContractError("model exceeds bounded CPU prototype configuration")


class PlayerEncoder:
    def __init__(self, card_ids, config):
        integer(len(card_ids), "public vocabulary size", 1, 50000)
        for code in card_ids:
            integer(code, "public vocabulary card", 1, 2**32 - 1)
        if list(card_ids) != sorted(set(card_ids)):
            raise ContractError("public card vocabulary must be sorted and unique")
        self.card_ids, self.config = tuple(card_ids), config
        self.index = {code: i + 1 for i, code in enumerate(card_ids)}
        self.vocab_sha256 = hashlib.sha256(canonical_json(list(card_ids)).encode()).hexdigest()

    def _card(self, code):
        if code is None:
            return 0
        if code not in self.index:
            raise ContractError("visible card absent from model vocabulary")
        return self.index[code]

    def encode(self, request):
        if not isinstance(request, DecisionRequest) or request.context.seed is not None:
            raise ContractError("model requires a typed player request without an RNG seed")
        obs, cfg = request.observation, self.config
        relative = lambda player: 2 if player is None else int(player != obs.observer)
        tokens, numbers, refs = [[0, 0, 2, 0, 0, 0, 0]], [[0.] * 4], {}
        for card in obs.cards:
            refs[card.ref] = len(tokens)
            hidden = card.visibility == "hidden"
            if hidden and (card.card_id is not None or card.attack is not None or card.defense is not None):
                raise ContractError("hidden identity/stats cannot enter model")
            tokens.append([self._card(card.card_id), ZONES.index(card.zone), relative(None if hidden else card.owner),
                           relative(card.controller), ("public", "observer", "hidden").index(card.visibility), card.position or 0, 0])
            numbers.append([0. if card.attack is None else card.attack / 10000,
                            0. if card.defense is None else card.defense / 10000,
                            float(card.attack is not None), float(card.defense is not None)])
            if card.attached_to is not None:
                if card.attached_to not in refs:
                    raise ContractError("material host must precede material in player encoding")
                numbers[-1] = [0., 0., refs[card.attached_to] / cfg.max_tokens, 1.]
            elif card.material_count is not None:
                numbers[-1][3] += card.material_count / 128
        if request.sum_selection is not None:
            spec = request.sum_selection
            tokens.append([0, ZONES.index("sum"), 2, 0, 0, 0, 0])
            numbers.append([spec.target / 65536, float(spec.mode == "minimal_at_least"),
                            spec.minimum_optional / 128, spec.maximum_optional / 128])
            cards = {c.ref: c for c in obs.cards}
            for required, group in ((True, spec.mandatory), (False, spec.optional)):
                for choice in group:
                    tokens.append([self._card(cards[choice.ref].card_id), ZONES.index("sum"), 0, 0, 1, 0, 0])
                    numbers.append([choice.values[0] / 65536, choice.values[-1] / 65536,
                                    float(required), refs[choice.ref] / cfg.max_tokens])
        for choice in request.search_choices:
            refs[choice.ref] = len(tokens)
            tokens.append([self._card(choice.card_id), ZONES.index("search"), relative(choice.owner), relative(choice.owner), 1, 0, 0])
            numbers.append([float(choice.scope == "ordering"), 0., 0., 0.])
        for choice in request.selection_choices:
            refs[choice.ref] = len(tokens)
            tokens.append([self._card(choice.card_id), ZONES.index(choice.zone), relative(choice.owner),
                           relative(choice.controller), 2 if choice.visibility == "hidden" else 1, 0, 0])
            numbers.append([0., 0., 0., 0.])
        for event in obs.public_history[-cfg.history_events:]:
            for code in event.card_ids or (None,):
                tokens.append([self._card(code), ZONES.index("history"), 2, 0, 0, 0, EVENTS.index(event.kind)])
                numbers.append([0.] * 4)
            if event.details is not None:
                d = event.details
                # Typed facts, not raw audit records. Distinct tokens preserve
                # timing, costs, resolutions, numeric announcements and public
                # locations; no private sequence or seed is accepted by DTOs.
                payloads = [[d.message/255, relative(d.player)/2, (d.turn or 0)/100, (d.link or 0)/128],
                            [(d.amount or 0)/10000, ((d.value or 0)&0xffff)/65536, ((d.value or 0)>>16)/65536, float(d.value is not None)],
                            [((d.reason or 0)&0xffff)/65536, ((d.reason or 0)>>16)/65536,
                             ((d.description or 0)&0xffff)/65536, ((d.description or 0)>>16)/65536],
                            [0. if d.life_points is None else d.life_points[obs.observer]/8000,
                             0. if d.life_points is None else d.life_points[1-obs.observer]/8000,
                             float(d.life_points is not None), 0. if d.phase is None else (PHASES.index(d.phase)+1)/6]]
                payloads += [[(v&0xffff)/65536, (v>>16)/65536, (i+1)/255, 1.] for i,v in enumerate(d.values)]
                payloads += [[relative(p.controller), (0 if p.zone == "none" else ZONES.index(p.zone) if p.zone != "deck" else 12)/12,
                              0. if p.sequence is None else (p.sequence+1)/256, (p.position or 0)/15] for p in d.locations]
                for payload in payloads:
                    tokens.append([0, ZONES.index("history"), 2, 0, 0, 0, EVENTS.index(event.kind)])
                    numbers.append(payload)
        if len(tokens) > cfg.max_tokens or len(request.actions) > cfg.max_actions:
            raise ContractError("player input exceeds model token/action budget")
        p, other = obs.observer, 1 - obs.observer
        state = [obs.life_points[p] / 8000, obs.life_points[other] / 8000,
                 obs.hand_counts[p] / 60, obs.hand_counts[other] / 60,
                 obs.deck_counts[p] / 60, obs.deck_counts[other] / 60,
                 math.tanh(obs.turn / 50), float(obs.turn_player == p),
                 *[float(obs.phase == phase) for phase in PHASES]]
        actions, action_numbers, pointers = [], [], []
        for action in request.actions:
            details = action.details
            description = details.description if details and details.description is not None else 0
            dest = details.destination if details else None
            operation = details.operation if details else None
            actions.append([KINDS.index(action.kind), self.index.get(description // 16, 0), description % 16,
                            OPERATIONS.index(operation), 0 if dest is None else 1 + relative(dest.controller),
                            0 if dest is None else (1 if dest.zone == "monster" else 2),
                            0 if dest is None else dest.sequence + 1])
            if request.prompt is not None and request.prompt.message == 142 and action.kind == "number":
                # Declared names are public candidate identities, not hidden
                # card state. Their learned embeddings must reach the head.
                actions[-1][1] = self._card(action.value)
            action_numbers.append([0. if action.value is None else math.tanh(action.value / 1000),
                                   float(action.value is not None), len(action.card_refs) / 10,
                                   0. if request.prompt is None else request.prompt.message / 255,
                                   0. if action.value is None else action.value/2**32,
                                   0. if not details or not details.quantities else 1. + (details.counter_type or 0)/65536,
                                   0. if not details else sum((1 << (p.sequence + (0 if p.zone=="monster" else 8))) * (1 if p.controller==obs.observer else 0) for p in details.destinations)/65536,
                                   0. if not details else sum((1 << (p.sequence + (0 if p.zone=="monster" else 8))) * (1 if p.controller!=obs.observer else 0) for p in details.destinations)/65536])
            pointer = [0.] * len(tokens)
            for i, ref in enumerate(action.card_refs):
                pointer[refs[ref]] = details.quantities[i] if details and details.quantities else 1 / (i + 1) if action.kind == "order" else 1
            total = sum(pointer)
            pointers.append([value / total if total else 0. for value in pointer])
        return {"tokens": torch.tensor(tokens, dtype=torch.long), "numbers": torch.tensor(numbers, dtype=torch.float32),
                "state": torch.tensor(state, dtype=torch.float32), "actions": torch.tensor(actions, dtype=torch.long),
                "action_numbers": torch.tensor(action_numbers, dtype=torch.float32),
                "pointers": torch.tensor(pointers, dtype=torch.float32)}

    def batch(self, requests, *, pad_actions_to=None):
        if not requests:
            raise ContractError("empty policy batch")
        encoded = [self.encode(r) for r in requests]
        count, length = len(encoded), max(e["tokens"].shape[0] for e in encoded)
        action_count = max(e["actions"].shape[0] for e in encoded)
        if pad_actions_to is not None:
            integer(pad_actions_to, "action padding", action_count, self.config.max_actions)
            action_count = pad_actions_to
        b = {"tokens": torch.zeros(count, length, 7, dtype=torch.long), "numbers": torch.zeros(count, length, 4),
             "state": torch.stack([e["state"] for e in encoded]), "actions": torch.zeros(count, action_count, 7, dtype=torch.long),
             "action_numbers": torch.zeros(count, action_count, 8), "pointers": torch.zeros(count, action_count, length),
             "context_mask": torch.zeros(count, length, dtype=torch.bool), "action_mask": torch.zeros(count, action_count, dtype=torch.bool)}
        for i, e in enumerate(encoded):
            n, a = e["tokens"].shape[0], e["actions"].shape[0]
            b["tokens"][i, :n], b["numbers"][i, :n] = e["tokens"], e["numbers"]
            b["actions"][i, :a], b["action_numbers"][i, :a] = e["actions"], e["action_numbers"]
            b["pointers"][i, :a, :n] = e["pointers"]
            b["context_mask"][i, :n], b["action_mask"][i, :a] = True, True
        return b


class DuelActorCritic(nn.Module):
    def __init__(self, config, vocabulary_size):
        super().__init__()
        self.config = config
        w = config.width
        self.card = nn.Embedding(vocabulary_size + 1, config.card_width, padding_idx=0)
        self.card_project = nn.Linear(config.card_width, w)
        self.token_embeddings = nn.ModuleList(nn.Embedding(size, w) for size in (len(ZONES), 3, 2, 3, 16, len(EVENTS)))
        self.token_numbers, self.state_project = nn.Linear(4, w), nn.Linear(14, w)
        self.positions, self.input_norm = nn.Embedding(config.max_tokens, w), nn.LayerNorm(w)
        layer = nn.TransformerEncoderLayer(w, config.heads, config.feedforward, dropout=0., batch_first=True)
        self.encoder = nn.TransformerEncoder(layer, config.layers, enable_nested_tensor=False)
        self.action_embeddings = nn.ModuleList(nn.Embedding(size, w) for size in (len(KINDS), 16, len(OPERATIONS), 3, 3, 9))
        self.action_numbers = nn.Linear(8, w)
        self.policy_head = nn.Sequential(nn.Linear(w * 2, w), nn.Tanh(), nn.Linear(w, 1))
        self.value_head = nn.Sequential(nn.Linear(w, w), nn.Tanh(), nn.Linear(w, 1))

    def forward(self, batch):
        if batch["state"].device.type != "cpu" or not batch["action_mask"].any(dim=1).all():
            raise ContractError("CPU policy requires at least one legal action per row")
        tokens, actions = batch["tokens"], batch["actions"]
        x = self.card_project(self.card(tokens[..., 0])) + self.token_numbers(batch["numbers"])
        for i, embedding in enumerate(self.token_embeddings):
            x = x + embedding(tokens[..., i + 1])
        x[:, 0] = x[:, 0] + self.state_project(batch["state"])
        x = x + self.positions(torch.arange(x.shape[1]))[None]
        x = self.encoder(self.input_norm(x), src_key_padding_mask=~batch["context_mask"])
        state = x[:, 0]
        a = torch.bmm(batch["pointers"], x) + self.action_numbers(batch["action_numbers"])
        a = a + self.card_project(self.card(actions[..., 1]))
        for column, embedding in zip((0, 2, 3, 4, 5, 6), self.action_embeddings):
            a = a + embedding(actions[..., column])
        logits = self.policy_head(torch.cat((state[:, None].expand(-1, a.shape[1], -1), a), dim=-1)).squeeze(-1)
        logits = logits.masked_fill(~batch["action_mask"], torch.finfo(logits.dtype).min)
        return logits, self.value_head(state).squeeze(-1)


def parameter_digest(model):
    digest = hashlib.sha256()
    for name, tensor in sorted(model.state_dict().items()):
        digest.update(name.encode())
        digest.update(tensor.detach().cpu().contiguous().numpy().tobytes())
    return digest.hexdigest()
