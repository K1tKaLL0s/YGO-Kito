"""Linear basic-CB scope over existing public effect records and event DTOs."""
from collections import Counter
from copy import deepcopy

VERSION = 'basic-cb-linear-mainline-v1'
ZONES = {1:'deck', 2:'hand', 4:'monster', 8:'spell_trap', 16:'graveyard', 32:'banished', 64:'extra'}


def random_outputs(record):
    """Randomness and cost/effect provenance are independent dimensions."""
    result = []
    for phase, key in (('activation_payment','costs'), ('resolution','operations')):
        for operation in record.get(key, ()):
            if operation.get('random') or operation.get('kind') == 'draw':
                result.append(dict(operation, phase=phase, reason='cost' if key == 'costs' else operation.get('reason','effect')))
    return result


class LinearMainline:
    """Track guaranteed resources, ignoring identities revealed by random moves.

    Ambiguous effect identities and random-dependent conditions stay unknown.
    A fixed mill itself is permitted; it does not terminate independent actions.
    """
    def __init__(self, catalog, opening, extra):
        self.catalog = catalog
        self.known = Counter({('hand', c): n for c, n in Counter(opening).items()})
        self.known.update({('extra', c): n for c, n in Counter(extra).items()})
        self.selected = Counter()
        self.pending_activations = Counter()
        self.steps = []
        self.random_seen = False
        self.random_source_zones = set()
        self.event_cursor = 0
        self.unknown = []

    def observe(self, observation, events):
        for event in events[self.event_cursor:]:
            if event['kind'] == 70 and event.get('player') == 0:
                code=event.get('public_card')
                if self.pending_activations[code] > 0:
                    self.pending_activations[code] -= 1
                else:
                    self.unknown.append('automatic_effect_without_confirmed_action')
            if event['kind'] != 50 or event.get('player') != 0:
                continue
            code = event.get('public_card')
            origin, destination = ZONES.get(event.get('from_zone')), ZONES.get(event.get('to_zone'))
            if code is None:
                continue  # Hidden identities cannot supply a guaranteed resource.
            if self.known[origin, code] > 0:
                self.known[origin, code] -= 1
                self.known[destination, code] += 1
            elif origin == 'deck' and self.selected[code] > 0:
                self.selected[code] -= 1
                self.known[destination, code] += 1
            elif origin not in (None, 'deck') and origin not in self.random_source_zones:
                self.unknown.append('movement_of_unconfirmed_resource')
        self.event_cursor = len(events)
        visible = Counter((c.zone, c.card_id) for c in observation.cards if c.controller == 0 and c.card_id)
        # Targeted searches to hand have no public MOVE identity. The explicit
        # choice, not a revealed random card, establishes that known addition.
        for code, count in list(self.selected.items()):
            gain = min(count, max(0, visible['hand', code] - self.known['hand', code]))
            self.known['hand', code] += gain
            self.selected[code] -= gain
        for key in list(self.known):
            if key[0] != 'deck':
                self.known[key] = min(self.known[key], visible[key])

    def _effect(self, request, action):
        cards = {c.ref:c for c in request.observation.cards}
        codes = {cards[r].card_id for r in action.card_refs if r in cards}
        if len(codes) != 1:
            return None
        records = self.catalog.effect_records(next(iter(codes)))
        description = action.details.description if action.details else None
        if description is not None and description >= 10000:
            index = description % 16 + 1
            records = [r for r in records if r['effect_index'] == index]
        return records[0] if len(records) == 1 else None

    def known_cards(self, observation):
        visible = Counter((c.zone, c.card_id) for c in observation.cards if c.controller == 0 and c.card_id)
        return tuple(c for c in observation.cards if c.controller == 0 and c.card_id
            and 0 < visible[c.zone, c.card_id] <= self.known[c.zone, c.card_id])

    def supports_goal(self, goal):
        return not self.unknown and (goal['kind'] == 'effect_resolution' or self.known['monster', goal['card_id']] > 0)

    def allows(self, request, action):
        if self.unknown:
            return False
        if request.observation.observer != 0:
            return action.kind == 'pass'
        cards = {c.ref:c for c in request.observation.cards}
        searches = {c.ref:c for c in request.search_choices}
        selections = {c.ref:c for c in request.selection_choices}
        used = Counter()
        visible = Counter((c.zone,c.card_id) for c in request.observation.cards if c.controller == 0 and c.card_id)
        for ref in action.card_refs:
            if ref in searches:
                continue  # Explicit targeted catalog choice, independent of order.
            card = cards.get(ref) or selections.get(ref)
            if card is None or card.card_id is None:
                return False
            used[card.zone, card.card_id] += 1
        if any(n > self.known[key] or visible[key] > self.known[key] for key, n in used.items()):
            return False
        if action.kind in ('activate', 'yes'):
            record = self._effect(request, action)
            if record is None:
                return False
            # Unknown/random-sensitive activation conditions cannot be made
            # deterministic by one seeded core execution.
            if record['conditions']['status'] != 'recognized':
                return False
            if self.random_seen and (record.get('unknown') or record.get('trigger',{}).get('event') == 'sent_to_grave'):
                # A known fixed-cost/effect send can be represented later with
                # its own event dependency; do not infer it from a random hit.
                if any(key[0] == 'graveyard' and self.known[key] < n for key,n in used.items()) or record.get('unknown'):
                    return False
            for op in random_outputs(record):
                if op['kind'] in ('mill', 'send_grave') and (type(op.get('quantity')) is not int or op['quantity'] <= 0):
                    return False
        elif self.random_seen and not action.card_refs and action.kind not in ('pass','position','select'):
            return False
        return True

    def select(self, request, action):
        if not self.allows(request, action):
            raise ValueError('action depends on an unknown or random-result resource')
        cards = {c.ref:c for c in (*request.observation.cards, *request.search_choices, *request.selection_choices)}
        if request.observation.observer != 0:
            return
        record = self._effect(request, action) if action.kind in ('activate','yes') else None
        random = random_outputs(record) if record else []
        if record:
            self.pending_activations.update(cards[r].card_id for r in action.card_refs if r in cards)
        step = dict(order=len(self.steps)+1, operation=action.kind,
            card_ids=[cards[r].card_id for r in action.card_refs if r in cards],
            costs=deepcopy(record.get('costs',[])) if record else [],
            operations=deepcopy(record.get('operations',[])) if record else [],
            targets=deepcopy(record.get('targets',[])) if record else [],
            count_limits=deepcopy(record.get('count_limits',[])) if record else [],
            selection_role='materials' if getattr(request,'sum_selection',None) is not None or request.prompt.message == 20 else 'targets_or_cost' if action.kind == 'select' else None,
            random_outputs=deepcopy(random), random_result_branches_expanded=False)
        self.steps.append(step)
        for ref in action.card_refs:
            if any(c.ref == ref for c in request.search_choices):
                self.selected[cards[ref].card_id] += 1
        self.random_seen |= bool(random)
        for operation in random:
            if operation.get('owner') == 'opponent':
                continue
            origins=operation.get('from_zones') or (['deck'] if operation['kind']=='draw' else [])
            if not origins:
                self.unknown.append('random_operation_source_unknown')
            for origin in origins:
                zones=('monster','spell_trap') if origin=='field' else ('graveyard',) if origin=='grave' else (origin,)
                self.random_source_zones.update(zones)
                # Even a previously known card is no longer a guaranteed
                # resource when a random selection can remove it from its zone.
                for key in list(self.known):
                    if key[0] in zones:self.known[key]=0

    def receipt(self):
        return dict(version=VERSION, steps=deepcopy(self.steps),
            known_outputs=[dict(zone=z,card_id=c,quantity=n) for (z,c),n in sorted(self.known.items()) if n>0],
            random_result_branches_expanded=False, future_deck_order_fixed=False,
            opponent_dynamic_responses=False, cost_effect_distinct=True,
            opening_probability_evaluated=False, unknown=deepcopy(self.unknown))
