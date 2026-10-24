"""Trainable CPU text classifier for building scope; no LLM or native dependency.

A small softmax linear model learns character ngrams, words and auxiliary
lexicon/scope features. Auxiliary rule labels and their fixed confidence are
never used as a prediction. Synthetic fitting validates this implementation;
it provides no evidence of broad language generalization or calibration.
"""

from collections import Counter
from dataclasses import asdict, dataclass
import hashlib
import json
import math
from pathlib import Path
import re

from .build_intent import DEFAULT_LEXICON, DomainLexicon, _normalize, classify_build_intent
from .validation import ContractError

LABELS = ("narrow", "broad", "ambiguous")
_FORMAT = "ygo-kito-intent-linear-v1"


def _digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(",", ":"), allow_nan=False).encode()).hexdigest()


def _number(value, name, minimum, maximum):
    if (isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value)
            or not minimum <= value <= maximum):
        raise ContractError(name + " must be finite and within range")


@dataclass(frozen=True)
class IntentFeatureConfig:
    char_min: int = 1
    char_max: int = 3
    max_features: int = 4096
    auxiliary_scale: float = 0.5
    min_confidence: float = 0.60
    min_margin: float = 0.15
    min_lexical_coverage: float = 0.20
    l2: float = 0.0001

    def __post_init__(self):
        for name, lo, hi in (("char_min", 1, 4), ("char_max", 1, 4), ("max_features", 32, 16384)):
            value = getattr(self, name)
            if isinstance(value, bool) or not isinstance(value, int) or not lo <= value <= hi:
                raise ContractError("invalid intent feature configuration: " + name)
        if self.char_min > self.char_max:
            raise ContractError("intent ngram bounds are reversed")
        _number(self.auxiliary_scale, "auxiliary feature scale", 0, 2)
        _number(self.min_confidence, "confidence threshold", 0.5, 1)
        _number(self.min_margin, "margin threshold", 0, 1)
        _number(self.min_lexical_coverage, "lexical coverage threshold", 0, 1)
        _number(self.l2, "regularization", 0, 1)

    @classmethod
    def from_dict(cls, value):
        if not isinstance(value, dict) or set(value) != set(cls.__dataclass_fields__):
            raise ContractError("intent feature configuration fields differ")
        return cls(**value)

    def to_dict(self):
        return asdict(self)


@dataclass(frozen=True)
class IntentModelPrediction:
    kind: str
    confidence: float
    narrow_terms: tuple
    broad_terms: tuple
    excluded_terms: tuple
    reasons: tuple
    scores: tuple
    margin: float
    lexical_coverage: float
    model_sha256: str
    training_source: str
    classifier_status: str

    def to_dict(self):
        result = asdict(self)
        for name in ("narrow_terms", "broad_terms", "excluded_terms", "reasons"):
            result[name] = list(result[name])
        result["scores"] = dict(self.scores)
        result["confidence_calibrated"] = False
        result["generalization_verified"] = False
        return result


def _raw_features(request, lexicon, config):
    if not isinstance(request, str) or not request.strip() or len(request) > 4096:
        raise ContractError("building request must contain 1..4096 characters")
    normalized = _normalize(request)
    chars = re.sub(r"\s+", " ", normalized)
    lexical = {"char:" + chars[i:i + size]
               for size in range(config.char_min, config.char_max + 1)
               for i in range(len(chars) - size + 1)}
    lexical.update("word:" + token for token in re.findall(r"[a-z0-9_]+", normalized))
    features = {name: 1.0 for name in lexical}
    scope = classify_build_intent(request, lexicon)
    # Only evidence features enter the model. scope.kind and scope.confidence
    # are intentionally ignored; a fit can learn to override all these features.
    auxiliary = ["aux:narrow_count=" + str(min(3, len(scope.narrow_terms))),
                 "aux:broad_count=" + str(min(3, len(scope.broad_terms))),
                 "aux:excluded_count=" + str(min(3, len(scope.excluded_terms)))]
    for group in ("narrow_terms", "broad_terms", "excluded_terms"):
        auxiliary.extend("aux:" + group + "=" + term for term in getattr(scope, group))
    for name in ("negated:", "nonbinding_mention:", "alternative_axis_requires_resolution",
                 "unresolved_combination_term", "unrestricted_axis_conflicts"):
        if any(reason.startswith(name) for reason in scope.reasons):
            auxiliary.append("aux:scope=" + name)
    features.update((name, config.auxiliary_scale) for name in auxiliary if config.auxiliary_scale)
    return features, lexical, scope


def _softmax(logits):
    peak = max(logits)
    values = [math.exp(value - peak) for value in logits]
    total = sum(values)
    return [value / total for value in values]


class LinearIntentClassifier:
    """Small learned classifier. New instances abstain until fit/load succeeds."""

    def __init__(self, lexicon=None, config=None):
        self.lexicon = DEFAULT_LEXICON if lexicon is None else lexicon
        self.config = IntentFeatureConfig() if config is None else config
        if not isinstance(self.lexicon, DomainLexicon) or not isinstance(self.config, IntentFeatureConfig):
            raise ContractError("typed intent lexicon and feature configuration required")
        self.vocabulary = ()
        self.weights = [[], [], []]
        self.bias = [0.0, 0.0, 0.0]
        self.trained = False
        self.training = None
        self._index = {}
        self._bound_lexicon_sha256 = _digest(self.lexicon.to_dict())
        self._bound_config_sha256 = _digest(self.config.to_dict())

    def _check_binding(self):
        if (not isinstance(self.lexicon, DomainLexicon) or not isinstance(self.config, IntentFeatureConfig)
                or _digest(self.lexicon.to_dict()) != self._bound_lexicon_sha256
                or _digest(self.config.to_dict()) != self._bound_config_sha256):
            raise ContractError("intent classifier feature or lexicon binding changed")

    @property
    def lexicon_sha256(self):
        return _digest(self.lexicon.to_dict())

    def _state(self):
        self._check_binding()
        return {"format": _FORMAT, "labels": list(LABELS), "lexicon": self.lexicon.to_dict(),
                "lexicon_sha256": self.lexicon_sha256, "feature_config": self.config.to_dict(),
                "feature_config_sha256": _digest(self.config.to_dict()), "vocabulary": list(self.vocabulary),
                "weights": self.weights, "bias": self.bias, "trained": self.trained, "training": self.training}

    @property
    def sha256(self):
        return _digest(self._state())

    def _vector(self, features):
        vector = sorted((self._index[name], value) for name, value in features.items() if name in self._index)
        norm = math.sqrt(sum(value * value for _, value in vector))
        return [(index, value / norm) for index, value in vector] if norm else []

    def _scores(self, vector):
        return _softmax([self.bias[label] + sum(self.weights[label][index] * value for index, value in vector)
                         for label in range(len(LABELS))])

    def fit(self, examples, *, epochs=120, learning_rate=1.0):
        """Fresh full-batch gradient fit on explicit, small synthetic examples.

        This CPU engineering hook does not download data or train project models.
        Every class must be represented; each row has only text and label fields.
        """
        self._check_binding()
        if not isinstance(examples, list) or not 3 <= len(examples) <= 1024:
            raise ContractError("intent fitting requires 3..1024 explicit examples")
        if isinstance(epochs, bool) or not isinstance(epochs, int) or not 1 <= epochs <= 500:
            raise ContractError("intent engineering fit requires 1..500 epochs")
        _number(learning_rate, "learning rate", 0.000001, 5)
        rows, labels, frequencies = [], [], Counter()
        for example in examples:
            if (not isinstance(example, dict) or set(example) != {"text", "label"}
                    or example["label"] not in LABELS):
                raise ContractError("intent examples require text and a known label")
            features, _, _ = _raw_features(example["text"], self.lexicon, self.config)
            rows.append(features)
            labels.append(LABELS.index(example["label"]))
            frequencies.update(features.keys())
        if set(labels) != set(range(len(LABELS))):
            raise ContractError("intent training must include narrow, broad and ambiguous examples")
        # Common features first, stable lexical tie break; bounded CPU vocabulary.
        self.vocabulary = tuple(sorted(sorted(frequencies, key=lambda name: (-frequencies[name], name))
                                       [:self.config.max_features]))
        self._index = {name: index for index, name in enumerate(self.vocabulary)}
        self.weights = [[0.0] * len(self.vocabulary) for _ in LABELS]
        self.bias = [0.0] * len(LABELS)
        vectors = [self._vector(row) for row in rows]

        def loss():
            return sum(-math.log(max(self._scores(vector)[label], 1e-300))
                       for vector, label in zip(vectors, labels)) / len(vectors)

        initial_loss = loss()
        for _ in range(epochs):
            gradient = [[0.0] * len(self.vocabulary) for _ in LABELS]
            bias_gradient = [0.0] * len(LABELS)
            for vector, label in zip(vectors, labels):
                scores = self._scores(vector)
                for output in range(len(LABELS)):
                    error = scores[output] - (1.0 if output == label else 0.0)
                    bias_gradient[output] += error / len(vectors)
                    for index, value in vector:
                        gradient[output][index] += error * value / len(vectors)
            for output in range(len(LABELS)):
                self.bias[output] -= learning_rate * bias_gradient[output]
                for index in range(len(self.vocabulary)):
                    self.weights[output][index] -= learning_rate * (gradient[output][index]
                                                                  + self.config.l2 * self.weights[output][index])
        self.trained = True
        self.training = {"source": "synthetic_engineering", "examples_sha256": _digest(examples),
                         "example_count": len(examples), "label_counts": dict(Counter(e["label"] for e in examples)),
                         "optimizer_steps": epochs, "learning_rate": learning_rate,
                         "initial_loss": initial_loss, "final_loss": loss(),
                         "evaluation_scope": "CPU implementation validation only"}
        return {**self.training, "model_sha256": self.sha256, "vocabulary_size": len(self.vocabulary),
                "generalization_verified": False}

    def predict(self, request, lexicon=None):
        self._check_binding()
        if lexicon is not None and (not isinstance(lexicon, DomainLexicon)
                                    or _digest(lexicon.to_dict()) != self.lexicon_sha256):
            raise ContractError("intent model lexicon binding differs")
        features, lexical, scope = _raw_features(request, self.lexicon, self.config)
        scores = self._scores(self._vector(features))
        ranked = sorted(range(len(LABELS)), key=lambda index: (-scores[index], index))
        confidence = scores[ranked[0]]
        margin = confidence - scores[ranked[1]]
        coverage = sum(name in self._index for name in lexical) / len(lexical) if lexical else 0.0
        reasons = []
        if not self.trained:
            reasons.append("untrained_classifier")
        if confidence < self.config.min_confidence:
            reasons.append("low_learned_confidence")
        if margin < self.config.min_margin:
            reasons.append("low_learned_margin")
        if coverage < self.config.min_lexical_coverage:
            reasons.append("lexical_out_of_vocabulary")
        predicted = LABELS[ranked[0]]
        kind = "ambiguous" if reasons else predicted
        if not reasons:
            reasons.append("learned_softmax:" + predicted)
        return IntentModelPrediction(kind, confidence, scope.narrow_terms, scope.broad_terms, scope.excluded_terms,
                                     tuple(reasons), tuple(zip(LABELS, scores)), margin, coverage, self.sha256,
                                     self.training["source"] if self.training else "none",
                                     "cpu_synthetic_trained" if self.trained else "untrained")

    def save(self, path):
        state = self._state()
        with Path(path).open("x", encoding="utf-8") as target:
            json.dump({"state": state, "sha256": _digest(state)}, target, ensure_ascii=False,
                      sort_keys=True, separators=(",", ":"), allow_nan=False)

    @classmethod
    def load(cls, path, *, lexicon=None, config=None):
        try:
            payload = json.loads(Path(path).read_text(encoding="utf-8"))
            if not isinstance(payload, dict) or set(payload) != {"state", "sha256"}:
                raise ContractError("intent checkpoint envelope differs")
            state = payload["state"]
            if not isinstance(state, dict) or _digest(state) != payload["sha256"]:
                raise ContractError("intent checkpoint digest differs")
            expected = {"format", "labels", "lexicon", "lexicon_sha256", "feature_config", "feature_config_sha256",
                        "vocabulary", "weights", "bias", "trained", "training"}
            if set(state) != expected or state["format"] != _FORMAT or state["labels"] != list(LABELS):
                raise ContractError("intent checkpoint schema differs")
            loaded_lexicon = DomainLexicon.from_dict(state["lexicon"])
            loaded_config = IntentFeatureConfig.from_dict(state["feature_config"])
            if (_digest(state["lexicon"]) != state["lexicon_sha256"]
                    or _digest(state["feature_config"]) != state["feature_config_sha256"]):
                raise ContractError("intent checkpoint feature or lexicon digest differs")
            if lexicon is not None and (not isinstance(lexicon, DomainLexicon)
                                        or _digest(lexicon.to_dict()) != state["lexicon_sha256"]):
                raise ContractError("requested intent lexicon differs from checkpoint")
            if config is not None and (not isinstance(config, IntentFeatureConfig)
                                       or config != loaded_config):
                raise ContractError("requested intent features differ from checkpoint")
            result = cls(loaded_lexicon, loaded_config)
            vocabulary = state["vocabulary"]
            if (not isinstance(vocabulary, list) or len(vocabulary) > result.config.max_features
                    or any(not isinstance(name, str) or not name or len(name) > 128 for name in vocabulary)
                    or vocabulary != sorted(set(vocabulary))):
                raise ContractError("intent checkpoint vocabulary differs")
            if (not isinstance(state["weights"], list) or len(state["weights"]) != len(LABELS)
                    or not isinstance(state["bias"], list) or len(state["bias"]) != len(LABELS)
                    or type(state["trained"]) is not bool):
                raise ContractError("intent checkpoint dimensions differ")
            for row in state["weights"]:
                if not isinstance(row, list) or len(row) != len(vocabulary):
                    raise ContractError("intent checkpoint weight dimensions differ")
                for value in row:
                    _number(value, "intent weight", -1e12, 1e12)
            for value in state["bias"]:
                _number(value, "intent bias", -1e12, 1e12)
            training = state["training"]
            if state["trained"]:
                if (not isinstance(training, dict) or set(training) != {"source", "examples_sha256", "example_count",
                        "label_counts", "optimizer_steps", "learning_rate", "initial_loss", "final_loss", "evaluation_scope"}
                        or training["source"] != "synthetic_engineering" or not vocabulary):
                    raise ContractError("intent checkpoint training provenance differs")
                _number(training["initial_loss"], "initial loss", 0, 1e12)
                _number(training["final_loss"], "final loss", 0, 1e12)
                _number(training["example_count"], "example count", 3, 1024)
                _number(training["optimizer_steps"], "optimizer steps", 1, 500)
                _number(training["learning_rate"], "learning rate", 0.000001, 5)
                if (not isinstance(training["examples_sha256"], str)
                        or not re.fullmatch(r"[a-f0-9]{64}", training["examples_sha256"])
                        or type(training["example_count"]) is not int
                        or type(training["optimizer_steps"]) is not int
                        or training["evaluation_scope"] != "CPU implementation validation only"
                        or not isinstance(training["label_counts"], dict)
                        or set(training["label_counts"]) != set(LABELS)
                        or any(type(count) is not int or count < 1 for count in training["label_counts"].values())
                        or sum(training["label_counts"].values()) != training["example_count"]):
                    raise ContractError("intent checkpoint training counts or source digest differ")
            elif training is not None or vocabulary or any(state["bias"]):
                raise ContractError("untrained intent checkpoint contains learned state")
            result.vocabulary = tuple(vocabulary)
            result._index = {name: index for index, name in enumerate(result.vocabulary)}
            result.weights, result.bias = state["weights"], state["bias"]
            result.trained, result.training = state["trained"], training
            return result
        except (ValueError, TypeError, KeyError, OverflowError) as error:
            raise ContractError("invalid intent checkpoint") from error
