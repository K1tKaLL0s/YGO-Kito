"""Independent CPU Transformer rankers for goal construction and deck edits.

Architecture code is reusable; each role owns every parameter and optimizer.
Effects are read as public facts/receipts, not understood by a downloaded LLM.
"""

from dataclasses import asdict, dataclass

import torch
from torch import nn

from .build_contracts import BuildTask, DeckParts, ZONES, digest
from .validation import ContractError, canonical_json, integer

FEATURE_VERSION = "build-task-catalog-candidate-v1"


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

    def encode(self, task, deck):
        if not isinstance(task, BuildTask) or not isinstance(deck, DeckParts):
            raise ContractError("building encoder requires typed task and candidate only")
        if digest(task.environment) != self.environment_sha256 or task.pool != self.card_ids:
            raise ContractError("building encoder resource/pool binding differs")
        ids, numbers = [[0, 0, 0, 0]], [[0.] * 10]

        def card(code, zone, kind, minimum=0, maximum=3):
            if code not in self.card_index:
                raise ContractError("candidate card outside building vocabulary")
            count = getattr(deck, zone).count(code)
            ids.append([self.card_index[code], 1 + ZONES.index(zone), 0, kind])
            numbers.append(self.assets.facts(code) + [minimum / 3, maximum / 3, count / 3, 0.])

        card(task.goal["card_id"], "main", 1)
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

    def batch(self, task, decks):
        integer(len(decks), "building rank batch", 1, 32)
        encoded = [self.encode(task, deck) for deck in decks]
        length = max(len(row[0]) for row in encoded)
        batch = {"tokens": torch.zeros(len(decks), length, 4, dtype=torch.long),
                 "numbers": torch.zeros(len(decks), length, 10),
                 "state": torch.tensor([row[2] for row in encoded], dtype=torch.float32),
                 "mask": torch.zeros(len(decks), length, dtype=torch.bool)}
        for i, (tokens, numbers, _) in enumerate(encoded):
            batch["tokens"][i, :len(tokens)] = torch.tensor(tokens)
            batch["numbers"][i, :len(tokens)] = torch.tensor(numbers)
            batch["mask"][i, :len(tokens)] = True
        return batch


class BuildRanker(nn.Module):
    def __init__(self, config, vocabulary_size, annotation_count):
        super().__init__()
        self.card = nn.Embedding(vocabulary_size + 1, config.card_width, padding_idx=0)
        self.card_project = nn.Linear(config.card_width, config.width)
        self.zone = nn.Embedding(4, config.width)
        self.kind = nn.Embedding(5, config.width)
        self.annotation = nn.Embedding(annotation_count + 1, config.width, padding_idx=0)
        self.numeric, self.state = nn.Linear(10, config.width), nn.Linear(6, config.width)
        self.position = nn.Embedding(config.max_tokens, config.width)
        self.norm = nn.LayerNorm(config.width)
        layer = nn.TransformerEncoderLayer(config.width, config.heads, config.feedforward, dropout=0., batch_first=True)
        self.encoder = nn.TransformerEncoder(layer, config.layers, enable_nested_tensor=False)
        self.head = nn.Sequential(nn.Linear(config.width, config.width), nn.Tanh(), nn.Linear(config.width, 1))

    def forward(self, batch):
        if batch["state"].device.type != "cpu" or not batch["mask"][:, 0].all():
            raise ContractError("building ranker requires CPU/valid context")
        t = batch["tokens"]
        x = (self.card_project(self.card(t[..., 0])) + self.zone(t[..., 1]) + self.annotation(t[..., 2])
             + self.kind(t[..., 3]) + self.numeric(batch["numbers"]))
        x[:, 0] = x[:, 0] + self.state(batch["state"])
        x = x + self.position(torch.arange(x.shape[1]))[None]
        encoded = self.encoder(self.norm(x), src_key_padding_mask=~batch["mask"])
        return self.head(encoded[:, 0]).squeeze(-1)
