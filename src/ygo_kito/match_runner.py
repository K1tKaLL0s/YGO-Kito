"""Host BO3 state, private sideboarding and existing-ranker side selection.

The game adapter owns actual core/model/bot execution. Policy requests contain
only their participant's cards and public results, never the opposing profile,
duel seed or private episode. Draw adjudication is deliberately not invented.
"""
from collections import Counter
from copy import deepcopy
from dataclasses import asdict, dataclass, field
import math
import time

from .agent_registry import identifier
from .build_contracts import BuildTask, DeckParts, ZONES, digest
from .deck_profile import validate_deck_parts
from .validation import ContractError, array, fields, integer

PUBLIC_GAME_FIELDS = ("game_number", "selected_first_participant_id", "actual_first_participant_id",
                      "winner_participant_id", "terminal", "completed", "draw", "anomaly")


@dataclass(frozen=True)
class MatchParticipant:
    participant_id: str
    deck: DeckParts

    def __post_init__(self):
        identifier(self.participant_id)
        if not isinstance(self.deck, DeckParts):
            raise ContractError("match participant requires typed complete deck parts")


@dataclass(frozen=True)
class GameSpec:
    match_id: str
    game_number: int
    participants: tuple[MatchParticipant, MatchParticipant]
    first_participant_id: str
    adapter_revision: int = 5
    _issuer_token: object = field(default=None, repr=False, compare=False)

    def __post_init__(self):
        identifier(self.match_id)
        integer(self.game_number, "BO3 game number", 1, 3)
        if (not isinstance(self.participants, tuple) or len(self.participants) != 2 or
                any(not isinstance(p, MatchParticipant) for p in self.participants) or
                len({p.participant_id for p in self.participants}) != 2):
            raise ContractError("match requires two distinct stable participant identities")
        integer(self.adapter_revision, "explicit match adapter", 3, 5)
        if self.first_participant_id not in self.participant_ids:
            raise ContractError("explicit supported first participant and adapter revision required")

    @property
    def participant_ids(self):
        return tuple(p.participant_id for p in self.participants)

    @property
    def seat_order(self):
        return (self.first_participant_id, next(p for p in self.participant_ids if p != self.first_participant_id))

    def seat_of(self, participant_id):
        if participant_id not in self.participant_ids:
            raise ContractError("participant is not in this match")
        return self.seat_order.index(participant_id)

    def profile(self):
        decks = {p.participant_id: p.deck for p in self.participants}
        return {"schema_version": 2, "adapter_revision": self.adapter_revision,
                "name": f"{self.match_id}-game-{self.game_number}",
                "decks": [list(decks[p].main) for p in self.seat_order],
                "extras": [list(decks[p].extra) for p in self.seat_order],
                "sides": [list(decks[p].side) for p in self.seat_order]}

    @property
    def sha256(self):
        return digest({"match_id": self.match_id, "game_number": self.game_number,
                       "seat_order": self.seat_order, "profile": self.profile()})


@dataclass(frozen=True)
class GameResult:
    game_number: int
    winner_core_seat: int | None
    actual_first_core_seat: int | None
    terminal: bool
    evidence_source: str
    elapsed_seconds: float
    native_decisions: int | None
    anomaly: str | None = None

    def __post_init__(self):
        integer(self.game_number, "BO3 result game number", 1, 3)
        if type(self.terminal) is not bool:
            raise ContractError("game terminal flag must be explicit")
        if self.winner_core_seat is not None:
            integer(self.winner_core_seat, "terminal core winner", 0, 2)
        if self.terminal != (self.winner_core_seat is not None):
            raise ContractError("only an actual terminal game has a winner/draw result")
        if self.actual_first_core_seat is not None:
            integer(self.actual_first_core_seat, "observed turn-one core seat", 0, 1)
        identifier(self.evidence_source)
        if (type(self.elapsed_seconds) not in (float, int) or not math.isfinite(self.elapsed_seconds)
                or self.elapsed_seconds < 0):
            raise ContractError("game elapsed time must be a finite observed duration")
        if self.native_decisions is not None:
            integer(self.native_decisions, "observed native decisions", 0)
        if self.anomaly is not None:
            identifier(self.anomaly)


@dataclass(frozen=True)
class IntermissionRequest:
    participant_id: str
    own_original_deck: DeckParts
    own_current_deck: DeckParts
    next_game_number: int
    public_match: dict

    def __post_init__(self):
        identifier(self.participant_id)
        if not isinstance(self.own_original_deck, DeckParts) or not isinstance(self.own_current_deck, DeckParts):
            raise ContractError("side/order policy can receive only its own typed complete decks")
        integer(self.next_game_number, "next BO3 game", 2, 3)
        public = fields(self.public_match, {"match_id", "participant_ids", "status", "wins", "games"})
        players = array(public["participant_ids"], "public match participants")
        if len(players) != 2 or len(set(players)) != 2 or self.participant_id not in players:
            raise ContractError("invalid public match participant scope")
        fields(public["wins"], set(players))
        for n in public["wins"].values(): integer(n, "public match win count", 0, 2)
        for game in array(public["games"], "public match results"):
            fields(game, set(PUBLIC_GAME_FIELDS))
        object.__setattr__(self, "public_match", deepcopy(public))


SideboardRequest = IntermissionRequest
TurnOrderRequest = IntermissionRequest


class MatchRules:
    """Snapshot of host-selected public listing rules, not historical proof."""
    def __init__(self, rows, limits, allowed_card_ids):
        self.rows = {code: {key: row[key] for key in ("id", "alias", "ot", "type")} for code, row in rows.items()}
        self.limits = dict(limits)
        self.allowed_card_ids = frozenset(allowed_card_ids)
        if not self.allowed_card_ids:
            raise ContractError("explicit allowed card pool required for a match")
        self.sha256 = digest({"rows": self.rows, "limits": self.limits, "allowed": sorted(self.allowed_card_ids)})

    def assert_integrity(self):
        if self.sha256 != digest({"rows": self.rows, "limits": self.limits, "allowed": sorted(self.allowed_card_ids)}):
            raise ContractError("match listing rules changed after binding")

    def validate(self, deck):
        self.assert_integrity()
        if not isinstance(deck, DeckParts):
            raise ContractError("sideboarding requires typed complete deck parts")
        validate_deck_parts(deck.to_dict(), self.rows, self.limits, allowed=self.allowed_card_ids)

    def validate_sideboard(self, original, proposal):
        if not isinstance(proposal, DeckParts):
            raise ContractError("side policy must return complete typed own deck parts")
        if any(len(getattr(original, z)) != len(getattr(proposal, z)) for z in ZONES):
            raise ContractError("sideboarding must preserve each original section count")
        if Counter(sum((getattr(original, z) for z in ZONES), ())) != Counter(sum((getattr(proposal, z) for z in ZONES), ())):
            raise ContractError("sideboarding must preserve the exact raw-card multiset")
        self.validate(proposal)


class MatchState:
    """One match; only fully closed game/intermission boundaries are saved."""
    def __init__(self, match_id, participants, rules, binding, initial_first_participant_id, *, adapter_revision=5):
        identifier(match_id)
        self.original_participants = tuple(participants)
        GameSpec(match_id, 1, self.original_participants, initial_first_participant_id, adapter_revision)
        if not isinstance(rules, MatchRules) or not isinstance(binding, dict) or not binding:
            raise ContractError("typed listing rules and explicit host match binding required")
        for participant in self.original_participants:
            rules.validate(participant.deck)
        self.match_id, self.rules, self.binding = match_id, rules, deepcopy(binding)
        self._binding_sha256, self._rules_sha256 = digest(self.binding), rules.sha256
        self.adapter_revision = adapter_revision
        self.initial_first_participant_id = initial_first_participant_id
        self._current = {p.participant_id: p.deck for p in self.original_participants}
        self._wins = {p.participant_id: 0 for p in self.original_participants}
        self._status, self._next_first = "ready", initial_first_participant_id
        self._loser, self._pending = None, None
        self._token, self._log, self._attempts = object(), [], []

    @property
    def status(self): return self._status

    @property
    def participant_ids(self): return tuple(p.participant_id for p in self.original_participants)

    def assert_integrity(self):
        self.rules.assert_integrity()
        if digest(self.binding) != self._binding_sha256 or self.rules.sha256 != self._rules_sha256:
            raise ContractError("match resource/model/rules binding changed after initialization")

    def public_view(self):
        return {"match_id": self.match_id, "participant_ids": list(self.participant_ids),
                "status": self._status, "wins": dict(self._wins),
                "games": [{k: game[k] for k in PUBLIC_GAME_FIELDS} for game in self._attempts]}

    def intermission_request(self, participant_id):
        if self._status not in ("awaiting_sideboards", "awaiting_first_choice") or participant_id not in self._current:
            raise ContractError("participant has no current match intermission")
        original = next(p.deck for p in self.original_participants if p.participant_id == participant_id)
        return IntermissionRequest(participant_id, original, self._current[participant_id],
                                   len(self._attempts) + 1, self.public_view())

    def issue_game_spec(self):
        self.assert_integrity()
        if self._status != "ready" or self._pending is not None or len(self._attempts) >= 3:
            raise ContractError("no new BO3 game can start at this boundary")
        self._pending = GameSpec(self.match_id, len(self._attempts) + 1,
            tuple(MatchParticipant(p, self._current[p]) for p in self.participant_ids),
            self._next_first, self.adapter_revision, self._token)
        return self._pending

    def assert_game_spec(self, spec):
        self.assert_integrity()
        if (not isinstance(spec, GameSpec) or spec is not self._pending or spec._issuer_token is not self._token or self._status != "ready"
                or spec.match_id != self.match_id or spec.game_number != len(self._attempts) + 1
                or any(p.deck != self._current[p.participant_id] for p in spec.participants)):
            raise ContractError("game spec was not issued by this exact current match boundary")

    def record_game(self, spec, result):
        self.assert_game_spec(spec)
        if not isinstance(result, GameResult) or result.game_number != spec.game_number:
            raise ContractError("game result belongs to a different match boundary")
        anomaly = result.anomaly
        if not result.terminal: anomaly = anomaly or "nonterminal-game"
        if result.actual_first_core_seat is None: anomaly = anomaly or "first-player-unobserved"
        elif result.actual_first_core_seat != 0: anomaly = anomaly or "first-player-choice-not-realized"
        winner = spec.seat_order[result.winner_core_seat] if result.winner_core_seat in (0, 1) else None
        first = spec.seat_order[result.actual_first_core_seat] if result.actual_first_core_seat in (0, 1) else None
        complete = result.terminal and anomaly is None
        self._attempts.append({"game_number": spec.game_number, "selected_first_participant_id": spec.first_participant_id,
            "actual_first_participant_id": first, "winner_participant_id": winner, "terminal": result.terminal,
            "completed": complete, "draw": result.winner_core_seat == 2, "anomaly": anomaly,
            "evidence_source": result.evidence_source, "elapsed_seconds": result.elapsed_seconds,
            "native_decisions": result.native_decisions})
        self._log.append({"kind": "game", "spec_sha256": spec.sha256, "result": asdict(result)})
        self._pending = None
        if not complete:
            self._status = "aborted"
        elif result.winner_core_seat == 2:
            self._status = "pending_draw_policy"
        else:
            self._wins[winner] += 1
            self._loser = next(p for p in self.participant_ids if p != winner)
            self._status = "complete" if self._wins[winner] == 2 else "awaiting_sideboards"
            if len(self._attempts) == 3 and self._status != "complete":
                raise ContractError("three decisive games failed to produce the required two wins")

    def submit_sideboards(self, proposals):
        self.assert_integrity()
        if self._status != "awaiting_sideboards" or set(proposals) != set(self.participant_ids):
            raise ContractError("both private sideboard proposals are required at the proper boundary")
        for participant in self.original_participants:
            self.rules.validate_sideboard(participant.deck, proposals[participant.participant_id])
        self._current = dict(proposals)  # Commit both together after all checks.
        self._log.append({"kind": "sideboards", "decks": {p: proposals[p].to_dict() for p in self.participant_ids}})
        self._status = "awaiting_first_choice"

    def choose_next_first(self, decider_id, first_participant_id):
        if self._status != "awaiting_first_choice" or decider_id != self._loser or first_participant_id not in self.participant_ids:
            raise ContractError("only the preceding game's loser may choose the next first participant")
        self._next_first = first_participant_id
        self._log.append({"kind": "first_choice", "decider_id": decider_id, "first_participant_id": first_participant_id})
        self._status = "ready"

    def abort_intermission(self, error_kind):
        if self._status not in ("awaiting_sideboards", "awaiting_first_choice"):
            raise ContractError("no open intermission to abort")
        identifier(error_kind)
        self._log.append({"kind": "intermission_error", "error_kind": error_kind})
        self._status = "aborted"

    def summary(self):
        completed = [g for g in self._attempts if g["completed"]]
        return dict(self.public_view(), games=deepcopy(self._attempts), attempted_matches=1, complete_matches=int(self._status == "complete"),
            pending_matches=int(self._status == "pending_draw_policy"), aborted_matches=int(self._status == "aborted"),
            game_attempts=len(self._attempts), terminal_games=sum(g["terminal"] for g in self._attempts),
            complete_games=len(completed), anomalous_game_attempts=sum(not g["completed"] for g in self._attempts),
            draw_games=sum(g["draw"] for g in completed),
            match_winner=next((p for p, n in self._wins.items() if n == 2), None),
            draw_policy="unfrozen_pending", formal_acceptance_qualified=False)

    def to_dict(self):
        self.assert_integrity()
        if self._pending is not None:
            raise ContractError("active native half-games cannot be saved as a match boundary")
        body = {"schema_version": 1, "kind": "bo3-host-private-state-v1", "match_id": self.match_id,
            "binding": deepcopy(self.binding), "binding_sha256": digest(self.binding), "rules_sha256": self.rules.sha256,
            "initial_first_participant_id": self.initial_first_participant_id, "adapter_revision": self.adapter_revision,
            "participants": [{"participant_id": p.participant_id, "deck": p.deck.to_dict()} for p in self.original_participants],
            "transitions": deepcopy(self._log), "summary": self.summary()}
        return dict(body, state_sha256=digest(body))

    @classmethod
    def from_dict(cls, value, *, rules, expected_binding):
        d = fields(value, {"schema_version", "kind", "match_id", "binding", "binding_sha256", "rules_sha256",
            "initial_first_participant_id", "adapter_revision", "participants", "transitions", "summary", "state_sha256"})
        integer(d["schema_version"], "BO3 state schema", 1, 1)
        if not isinstance(rules, MatchRules): raise ContractError("typed rules required to restore a match")
        rules.assert_integrity()
        body = {k: v for k, v in d.items() if k != "state_sha256"}
        if (d["kind"] != "bo3-host-private-state-v1" or digest(body) != d["state_sha256"]
                or d["binding"] != expected_binding or digest(expected_binding) != d["binding_sha256"] or rules.sha256 != d["rules_sha256"]):
            raise ContractError("saved match state resource/model/rules binding differs")
        participants = []
        for row in array(d["participants"], "saved match participants"):
            fields(row, {"participant_id", "deck"})
            participants.append(MatchParticipant(row["participant_id"], DeckParts.from_dict(row["deck"])))
        state = cls(d["match_id"], participants, rules, expected_binding, d["initial_first_participant_id"], adapter_revision=d["adapter_revision"])
        transitions = array(d["transitions"], "saved match transitions")
        if len(transitions) > 7: raise ContractError("saved match exceeds the BO3 transition bound")
        for transition in transitions:
            if not isinstance(transition, dict): raise ContractError("typed saved transition required")
            kind = transition.get("kind")
            if kind == "game":
                fields(transition, {"kind", "spec_sha256", "result"})
                spec = state.issue_game_spec()
                if spec.sha256 != transition["spec_sha256"]:
                    raise ContractError("saved game does not match its legal sided match boundary")
                fields(transition["result"], {"game_number", "winner_core_seat", "actual_first_core_seat", "terminal",
                    "evidence_source", "elapsed_seconds", "native_decisions", "anomaly"})
                state.record_game(spec, GameResult(**transition["result"]))
            elif kind == "sideboards":
                fields(transition, {"kind", "decks"})
                state.submit_sideboards({p: DeckParts.from_dict(deck) for p, deck in transition["decks"].items()})
            elif kind == "first_choice":
                fields(transition, {"kind", "decider_id", "first_participant_id"})
                state.choose_next_first(transition["decider_id"], transition["first_participant_id"])
            elif kind == "intermission_error":
                fields(transition, {"kind", "error_kind"})
                state.abort_intermission(transition["error_kind"])
            else:
                raise ContractError("unknown saved BO3 transition")
        if state.to_dict() != value:
            raise ContractError("saved match projection is inconsistent with its transitions")
        return state


class FirstOrderPolicy:
    """Explicit host preference, not a learned first/second-player policy."""
    def __init__(self, preference):
        if preference not in ("always_first", "always_second"):
            raise ContractError("explicit supported first-order preference required")
        self.preference = preference

    def __call__(self, request):
        return request.participant_id if self.preference == "always_first" else next(
            p for p in request.public_match["participant_ids"] if p != request.participant_id)


def keep_side(request):
    """Declared unchanged-side baseline; no learned sideboarding claim."""
    return request.own_current_deck


def sideboard_candidates(request, rules, *, max_swaps=2, candidate_limit=16):
    integer(max_swaps, "bounded side swap depth", 1, 3)
    integer(candidate_limit, "side candidate budget", 2, 32)
    seeds = [request.own_current_deck]
    if request.own_original_deck != seeds[0]: seeds.append(request.own_original_deck)
    for deck in seeds: rules.validate_sideboard(request.own_original_deck, deck)
    result = list(seeds)
    key = lambda d: tuple(tuple(sorted(getattr(d, z))) for z in ZONES)
    seen, frontier = {key(d) for d in seeds}, [seeds[0]]
    for depth in range(max_swaps):
        if len(result) >= candidate_limit: break
        remaining = candidate_limit - len(result)
        quota = remaining if depth == max_swaps - 1 else max(1, remaining // (max_swaps - depth))
        following = []
        for deck in frontier:
            def neighbors(zone):
                for outgoing in sorted(set(getattr(deck, zone))):
                    for incoming in sorted(set(deck.side)):
                        if outgoing == incoming: continue
                        parts = deck.to_dict()
                        parts[zone][parts[zone].index(outgoing)] = incoming
                        parts["side"][parts["side"].index(incoming)] = outgoing
                        yield DeckParts.from_dict(parts)
            streams = [iter(neighbors(zone)) for zone in ("main", "extra")]
            while streams and len(following) < quota:
                for stream in tuple(streams):
                    try: proposal = next(stream)
                    except StopIteration:
                        streams.remove(stream); continue
                    if key(proposal) in seen: continue
                    try: rules.validate_sideboard(request.own_original_deck, proposal)
                    except ContractError: continue
                    seen.add(key(proposal)); following.append(proposal); result.append(proposal)
                    if len(following) >= quota: break
            if len(following) >= quota: break
        if not following or len(result) >= candidate_limit: break
        frontier = following
    return tuple(result)


class ModelSideboardPolicy:
    """Reuse the actual build-optimizer ranker and encoder; no new weights."""
    FEATURE_VERSION = "own-sideboard-public-match-context-v1"

    def __init__(self, model, encoder, task, assets, rules, *, max_swaps=2, candidate_limit=16):
        from .build_model import BuildEncoder, BuildRanker
        if not isinstance(model, BuildRanker) or not isinstance(encoder, BuildEncoder) or not isinstance(task, BuildTask):
            raise ContractError("side scoring requires existing typed optimizer model, encoder and own build task")
        self.model, self.encoder, self.task, self.assets, self.rules = model, encoder, task, assets, rules
        self.max_swaps, self.candidate_limit = max_swaps, candidate_limit
        self.last_receipt = None

    def scope(self):
        from .duel_model import parameter_digest
        return {"kind": "existing-build-optimizer-side-selection", "feature_version": self.FEATURE_VERSION,
                "model_sha256": parameter_digest(self.model), "task_sha256": self.task.sha256,
                "encoder_vocabulary_sha256": self.encoder.vocabulary_sha256,
                "max_swap_search_depth": self.max_swaps, "candidate_limit": self.candidate_limit,
                "trained_sideboard_capability_verified": False}

    def score(self, request):
        import torch
        if not isinstance(request, IntermissionRequest):
            raise ContractError("side optimizer accepts only a private own-deck intermission request")
        self.assets.validate(self.task, request.own_original_deck)
        candidates = []
        for deck in sideboard_candidates(request, self.rules, max_swaps=self.max_swaps, candidate_limit=self.candidate_limit):
            try: self.assets.validate(self.task, deck)
            except ContractError: continue
            candidates.append(deck)
        if not candidates:
            raise ContractError("no legal goal-preserving sideboard candidate")
        batch = self.encoder.batch(self.task, candidates)
        # A versioned public context token reuses the existing kind/numeric
        # embeddings. Keep all original task, candidate and state features.
        if batch["tokens"].shape[1] + 1 > self.encoder.config.max_tokens:
            raise ContractError("public side context exceeds the declared encoder token budget")
        own = request.participant_id; public = request.public_match
        other = next(p for p in public["participant_ids"] if p != own)
        last = public["games"][-1] if public["games"] else {}
        context = [request.next_game_number / 3, public["wins"][own] / 2, public["wins"][other] / 2,
            sum(g["draw"] for g in public["games"]) / 3, float(last.get("actual_first_participant_id") == own),
            float(last.get("winner_participant_id") == own), 0., 0., 0., 0.]
        tokens = batch["tokens"].new_zeros((len(candidates), 1, 4)); tokens[:, :, 3] = 6
        numbers = batch["numbers"].new_tensor(context).reshape(1, 1, 10).expand(len(candidates), 1, 10)
        batch = dict(batch, tokens=torch.cat((batch["tokens"], tokens), dim=1),
            numbers=torch.cat((batch["numbers"], numbers), dim=1),
            mask=torch.cat((batch["mask"], batch["mask"].new_ones((len(candidates), 1))), dim=1))
        scores = self.model(batch)
        if scores.shape != (len(candidates),) or not torch.isfinite(scores).all():
            raise ContractError("side optimizer returned invalid candidate scores")
        return tuple(candidates), scores

    def __call__(self, request):
        import torch
        from .duel_model import parameter_digest
        with torch.no_grad(): candidates, scores = self.score(request)
        index = int(scores.argmax())
        self.last_receipt = dict(self.scope(), candidate_count=len(candidates), selected_deck_sha256=digest(candidates[index].to_dict()))
        return candidates[index]


def side_policy_scope(policy):
    if isinstance(policy, ModelSideboardPolicy): return policy.scope()
    return {"kind": "declared-keep-side-baseline" if policy is keep_side else "explicit-host-side-policy",
            "trained_sideboard_capability_verified": False}


class MatchRunner:
    def __init__(self, state, game_adapter, sideboard_policies, first_order_policies):
        if not isinstance(state, MatchState) or not callable(game_adapter):
            raise ContractError("typed match state and real explicit game adapter required")
        for policies in (sideboard_policies, first_order_policies):
            if set(policies) != set(state.participant_ids) or any(not callable(p) for p in policies.values()):
                raise ContractError("both participants require explicit host policies")
        self.state, self.game_adapter = state, game_adapter
        self.sideboard_policies, self.first_order_policies = dict(sideboard_policies), dict(first_order_policies)

    def run(self):
        while self.state.status in ("ready", "awaiting_sideboards", "awaiting_first_choice"):
            if self.state.status == "ready":
                spec = self.state.issue_game_spec(); started = time.monotonic()
                try:
                    result = self.game_adapter(spec)
                    self.state.record_game(spec, result)
                except Exception as error:
                    if self.state._pending is not spec: raise
                    self.state.record_game(spec, GameResult(spec.game_number, None, None, False,
                        "adapter_exception", time.monotonic() - started, None, type(error).__name__))
            else:
                try:
                    if self.state.status == "awaiting_sideboards":
                        proposals = {p: self.sideboard_policies[p](self.state.intermission_request(p)) for p in self.state.participant_ids}
                        self.state.submit_sideboards(proposals)
                    else:
                        loser = self.state._loser
                        first = self.first_order_policies[loser](self.state.intermission_request(loser))
                        self.state.choose_next_first(loser, first)
                except Exception as error:
                    self.state.abort_intermission(type(error).__name__)
        return dict(self.state.summary(), side_policy_scope={p: side_policy_scope(policy)
            for p, policy in self.sideboard_policies.items()})
