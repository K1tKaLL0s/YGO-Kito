"""Lossless allocation and optional, source-bound recognition consumers.

Only input-free, fully known supplies without prerequisite claims are delegated
here. All other relations retain the existing conservative evaluation path.
"""

from collections import defaultdict

from .multifactor.conditions import Condition, ConditionGroup, Resource
from .validation import ContractError


class CatalogRecognitionFacts:
    """Use the existing card observer through build_analysis_graph, never train."""
    def __init__(self, assets, *, structure_links=(), function_seeds=(), unit_contracts=()):
        self.assets = assets
        self.structure_links, self.function_seeds, self.unit_contracts = structure_links, function_seeds, unit_contracts

    def __call__(self, deck, context, unit):
        from .multifactor.analysis import AnalysisFacts
        codes = {c for z in ('main', 'extra', 'side') for c, _ in
                 (() if deck is None or getattr(deck, z) is None else getattr(deck, z))}
        codes.update(c for c, _ in (() if unit is None else unit.members))
        stock = tuple(Resource('card', 'card:' + str(c), n, resource_id=f'inventory:{z}:{c}',
            pool_id=f'inventory:{z}:{c}', capacity=n, deck_section=z, source='actual_candidate_inventory')
            for z in ('main', 'extra', 'side') for c, n in
            (() if deck is None or getattr(deck, z) is None else getattr(deck, z)))
        return AnalysisFacts(card_rows={c: dict(self.assets.rows[c]) for c in codes if c in self.assets.rows},
            structure_links=self.structure_links, function_seeds=self.function_seeds, unit_contracts=self.unit_contracts,
            source_ref='construction_catalog_observations', resources=stock)


class ConstructionRecognitionProvider:
    """Host-owned analyzer plus an optional existing layer-evidence policy.

    layer_policy(task, deck, layers, facts) returns the existing source-bound
    functional supplement protocol. Recognition defines no prices or losses.
    """
    def __init__(self, analyzer=None, *, context_provider=None, layer_policy=None, layer_policy_version=""):
        from .multifactor.analysis import RoleAnalyzer
        if analyzer is not None and not isinstance(analyzer, RoleAnalyzer):
            raise ValueError('explicit RoleAnalyzer required')
        if any(v is not None and not callable(v) for v in (context_provider, layer_policy)):
            raise ValueError('host recognition context/layer policy must be callable')
        if layer_policy is not None and (not isinstance(layer_policy_version, str) or not layer_policy_version.strip()):
            raise ValueError('host recognition layer policy requires an explicit version')
        self.analyzer, self.context_provider, self.layer_policy = analyzer, context_provider, layer_policy
        self.layer_policy_version = layer_policy_version

    def analyze_candidate(self, task, deck, assets, *, mode):
        from collections import Counter
        from dataclasses import replace
        from .multifactor import AnalysisContext, AnalysisRequestContext, DeckSpec, RoleAnalyzer
        context = self.context_provider(task, deck) if self.context_provider else AnalysisRequestContext(
            context_ref=task.sha256, declared_goal=_goal(task), mode=mode,
            rules=AnalysisContext(format='OCG', period=str(task.environment)))
        if not isinstance(context, AnalysisRequestContext) or context.context_ref != task.sha256 or context.declared_goal != _goal(task):
            raise ValueError('recognition context must preserve the exact original task and goal')
        context = replace(context, mode=mode)
        analyzer = self.analyzer or RoleAnalyzer(CatalogRecognitionFacts(assets))
        return analyzer.analyze_deck(DeckSpec(**{z: tuple(sorted(Counter(getattr(deck, z)).items()))
                                               for z in ('main', 'extra', 'side')}), context)


def _goal(task):
    import json
    return json.dumps(task.goal, sort_keys=True, ensure_ascii=False, separators=(',', ':'))


def recognition_mode(mode):
    from .validation import ContractError
    if mode not in ('off', 'observe', 'assist'):
        raise ContractError('recognition mode must be off/observe/assist')
    return mode


def collect_recognition(provider, mode, task, decks, assets):
    """Called only with complete candidates. Off never touches the provider."""
    from .build_contracts import digest
    from .multifactor import DeckAnalysis
    from copy import deepcopy
    recognition_mode(mode)
    if mode == 'off' or provider is None:
        return {}
    records = {}
    for deck in decks:
        key = digest(deck.to_dict())
        if key in records:
            continue
        record = dict(mode=mode, deck_sha256=key, task_sha256=task.sha256, status='unknown')
        records[key] = record
        try:
            callback = getattr(provider, 'analyze_candidate', provider)
            result = callback(deepcopy(task), deck, assets, mode=mode)
            if not isinstance(result, DeckAnalysis):
                raise ValueError('provider must return a DeckAnalysis')
            report = result.to_dict()
            if report['context_ref'] != task.sha256 or report['declared_goal'] != _goal(task) or report['mode'] != mode:
                raise ValueError('recognition result task/goal/mode differs')
            for zone in ('main', 'extra', 'side'):
                from collections import Counter
                row = report['deck_summary'][zone]
                if row['count'] != len(getattr(deck, zone)) or {c['card_id']: c['copies'] for c in row['cards']} != dict(Counter(getattr(deck, zone))):
                    raise ValueError('recognition result inventory differs from complete candidate')
            record.update(status='recorded', report=report)
            if mode == 'assist':
                record['facts'] = assist_fact_view(report)
        except Exception as error:
            record.update(reason_code='RECOGNITION_PROVIDER_UNAVAILABLE', detail=type(error).__name__)
    return records


def assist_fact_view(report):
    """Only explicitly available capabilities can cross into host decisions."""
    from .build_contracts import digest
    caps = report['capabilities']
    enabled = {name: row for name, row in caps.items() if row.get('assist_available') is True
               and row.get('validated') is True and row.get('producer') and row.get('version') and row.get('evidence_refs')}
    enabled = {name: row for name, row in enabled.items() if
        (name == 'function_facts' and report['functions'] and report['units']) or
        (name == 'requirements' and report['requirement_assessment']) or
        any(p['task'] == name for p in report['applied_prediction'])}
    def unique(rows):
        return list({digest(row): row for row in rows}.values())
    result = dict(capabilities=enabled, functions=[], candidates=[], requirements=[], predictions=[],
        coverage=dict(candidates_complete=not report['derived_summary'].get('candidate_overflow', True),
                      unresolved=report.get('unresolved', ())))
    if 'function_facts' in enabled:
        result.update(functions=unique(report['functions']), candidates=unique(report['units']))
    if 'requirements' in enabled:
        result['requirements'] = unique(report['requirement_assessment'])
        result['starting_resources'] = report['derived_summary'].get('starting_resources')
    result['predictions'] = unique([r for r in report['applied_prediction'] if r['task'] in enabled])
    return result


def recognized_mechanism_cards(record, task, deck):
    """Use only calibrated, applied card predictions from this incumbent."""
    from .build_contracts import digest

    if (not record or record.get('mode') != 'assist' or record.get('task_sha256') != task.sha256
            or record.get('deck_sha256') != digest(deck.to_dict())):
        return frozenset()
    facts = record.get('facts') or {}
    if 'mechanism' not in facts.get('capabilities', {}):
        return frozenset()
    cards = set()
    for row in facts.get('predictions', ()):
        if row['task'] != 'mechanism' or row['value'] is not True or len(row['subject']) != 1:
            continue
        kind, _, code = row['subject'][0].partition(':')
        if kind == 'card' and code.isascii() and code.isdigit():
            cards.add(int(code))
    return frozenset(cards)


def recognition_quality_evidence(existing, provider, records, mode, *, validator=None):
    """Keep the exact old evidence provider in off/observe modes."""
    mapper = getattr(provider, 'layer_policy', None) if mode == 'assist' else None
    if mapper is None or not records or not getattr(provider, 'layer_policy_version', ''):
        return existing
    def evidence(task, deck, layer):
        from copy import deepcopy
        from .build_contracts import digest
        prior = existing(task, deck, layer) if existing else {}
        record = records.get(digest(deck.to_dict()), {})
        facts = record.get('facts', {})
        if not facts.get('capabilities'):
            return prior
        try:
            supplied = mapper(deepcopy(task), deck, deepcopy(layer), deepcopy(facts))
            if not supplied:
                return prior
            if not isinstance(supplied, dict):
                raise ValueError('host layer policy must return existing evidence protocol')
            # The existing normalizer remains the authority for semantic binding
            # and resolving variables. Never merge prices or override prior facts.
            if any(supplied.get(k) for k in ('losses', 'slot_uses', 'generic_fits', 'duplicate_purposes', 'side_deck')):
                raise ValueError('recognition policy must use semantic functional evidence')
            result = deepcopy(prior or {})
            for key, value in supplied.items():
                if key in result and result[key] != value:
                    if key == 'variables':
                        merged = dict(result[key])
                        if any(k in merged and merged[k] != v for k, v in value.items()):
                            raise ValueError('recognition evidence conflicts with host evidence')
                        merged.update(value)
                        result[key] = merged
                        continue
                    raise ValueError('recognition evidence cannot replace existing host fields')
                result[key] = value
        except (ContractError, ValueError, RuntimeError) as error:
            record['layer_policy'] = dict(status='unknown', reason_code='HOST_POLICY_UNAVAILABLE', detail=type(error).__name__)
            return prior
        if validator is not None:
            try:
                validator(result, task, deck, layer)
            except ContractError as error:
                record['layer_policy'] = dict(status='unknown', reason_code='HOST_EVIDENCE_REJECTED', detail=str(error))
                return prior
        record['layer_policy'] = dict(status='host_evidence_supplied', capabilities=list(facts['capabilities']))
        return result
    return evidence


def recognition_binding(provider, records, mode):
    """Pending quality cannot reuse facts from another capability/policy set."""
    from .build_contracts import digest
    if mode != 'assist' or getattr(provider, 'layer_policy', None) is None or not getattr(provider, 'layer_policy_version', ''):
        return None
    facts = {key: row['facts'] for key, row in records.items() if row.get('facts', {}).get('capabilities')}
    return None if not facts else digest(dict(policy_version=provider.layer_policy_version, facts=facts))


def recognition_evidence_validator(adapter, policy, context):
    """Reuse the real normalizer's checks; invalid optional facts stay local."""
    def validate(supplement, task, deck, layer):
        from .construction_layer_flow import normalize_function_uses, _merge_function_evidence
        facts = normalize_function_uses(task, deck, adapter.catalog, policy=policy, budget=adapter.budget,
                                       context=context, layer_evaluation=layer)
        if facts.get('calculation_pending'):
            raise ContractError('static calculation must finish before validating recognition evidence')
        _merge_function_evidence(facts, supplement)
    return validate


def cb_search_hints(record):
    """Search hints only: no generated actions, legality or route success."""
    facts = record.get('facts', {})
    if record.get('mode') != 'assist' or not facts.get('capabilities'):
        return None
    requirements = facts.get('requirements', [])
    return dict(version='axis-cb-hints-v3', subject_deck_sha256=record['deck_sha256'], task_sha256=record['task_sha256'],
        candidates=facts.get('candidates', []), functions=facts.get('functions', []),
        starting_resources=facts.get('starting_resources'),
        branches=[b for r in requirements for b in r.get('branches', [])],
        timing=[b.get('state_assessment') for r in requirements for b in r.get('branches', [])],
        missing=[r.get('external_requirements') for r in requirements],
        capabilities=facts['capabilities'], legality='unknown', route_success='unknown', rule_authority=False)


def record_recognition_result(result, task, assets, provider, mode):
    """Observe after selection/gate/learning decisions, including cycle budgets."""
    from .build_contracts import DeckParts, digest
    recognition_mode(mode)
    if mode == 'off' or provider is None:
        return result
    records = {}
    if mode == 'assist':
        records.update(result.get('candidate_trace', {}).get('recognition', {}).get('records', {}))
        for phase in result.get('phases', []):
            records.update(phase.get('stage_3', {}).get('recognition', {}).get('records', {}))
    decks = []
    def add(row):
        if row is not None:
            decks.append(DeckParts.from_dict(row))
    add(result.get('best_deck'))
    for row in result.get('candidate_decks', []):
        add(row)
    trace = result.get('candidate_trace', {})
    for row in trace.get('candidates', []):
        add(row.get('recognition_inventory'))
    for row in result.get('portfolio', []):
        add(row['deck'])
    for phase in result.get('phases', []):
        stage = phase.get('stage_3', {})
        for row in stage.get('candidate_decks', []):
            add(row)
        for row in stage.get('candidate_trace', {}).get('candidates', []):
            add(row.get('recognition_inventory'))
        for row in stage.get('portfolio', []):
            add(row['deck'])
    add((result.get('construction_candidate') or {}).get('deck'))
    records.update(collect_recognition(provider, mode, task,
        [deck for deck in decks if digest(deck.to_dict()) not in records], assets))
    result['recognition'] = dict(mode=mode, records=records, decision_input=mode == 'assist')
    return result


def allocate_relation_group(group, index, states, counts, capacities, prefix, blocked=None, *, existential=False):
    from .construction_relations import InputGroup, _blank, _combine, _needs, _shared_allocation

    needs = tuple(_needs(group))
    if (any(n.need_id in index.incomplete_needs for n in needs) or
            any(counts[("main", c)] or counts[("extra", c)] for c in index.unresolved_cards)):
        return None
    wanted = {n.need_id: n for n in needs}
    matched_needs = defaultdict(list)
    for need in needs:
        for fid in index.matches.get(need.need_id, ()):
            matched_needs[fid].append(need)
    supplies = []
    capacity_by_need = defaultdict(dict)
    for fid in sorted(matched_needs):
        fact, state = index.facts[fid], states[fid]
        if state["status"] == "missing" or blocked and blocked in state["suppliers"]:
            continue
        if (state["status"] != "supported" or fact.inputs is not None or fact.claims or
                fact.conditions or fact.unknown or fact.choice != "joint" or
                any(state[k] for k in ("conditions", "unknown", "conflicts", "usage", "possible_usage"))):
            return None
        pool = fact.output_pool or "output:" + fact.effect_ref + ":" + fact.output.kind
        declared_pool = index.pools.get(pool)
        if declared_pool is not None and (declared_pool.inventory or declared_pool.reusable_if):
            return None  # No flattening of overlapping inventory or recovery claims.
        amount = fact.quantity
        if amount is None:
            return None
        if fact.inventory_scaled:
            amount *= counts[(fact.zone, fact.card_id)]
        if fact.card_id is not None and not counts[(fact.zone, fact.card_id)]:
            amount = 0
        capacity = capacities.get(pool, amount)
        if capacity is None or capacity > 4096:
            return None
        amount = min(amount, capacity)
        if amount > 99:
            return None
        aliases = tuple(n.need_id for n in matched_needs[fid] if n.resource.accepts(fact.output))
        if not aliases:
            continue
        if len(aliases) > 128:
            return None
        supplies.append(Resource("construction_supply", aliases[0], amount, selectors=aliases,
                                 resource_id=fid, pool_id=pool, capacity=capacity, source=fact.source))
        for need_id in aliases:
            pools = capacity_by_need[need_id]
            pools[pool] = max(pools.get(pool, 0), amount)

    def convert(node):
        if not isinstance(node, InputGroup):
            return Condition("construction_supply", node.need_id, node.quantity,
                             consume_mode="reusable" if node.mode == "presence" else "consume")
        children = tuple(convert(v) for v in node.items)
        while len(children) > 16:
            children = tuple(ConditionGroup(node.operator, children[i:i + 16]) for i in range(0, len(children), 16))
        return children[0] if len(children) == 1 else ConditionGroup(node.operator, children)

    if any(n.quantity > 4096 for n in needs):
        return None
    result = _shared_allocation(index, convert(group), tuple(supplies), existential=existential)
    rows = []
    for branch in result["branches"]:
        if branch["satisfied"] is not True:
            continue
        row = _blank("supported")
        for allocation in branch["matched_resources"]:
            pid = allocation["slot"][0]
            mode = "presence" if wanted[allocation["selector"]].mode == "presence" else "consume"
            token = mode + ":" + prefix + ":" + allocation["selector"]
            entries = row["usage"].setdefault(pid, {})
            entries[token] = entries.get(token, 0) + 1
            row["suppliers"].append(allocation["resource_id"])
            row["bottlenecks"].append(pid)
        row["possible_usage"] = {p: dict(v) for p, v in row["usage"].items()}
        row["suppliers"] = sorted(set(row["suppliers"]))
        row["bottlenecks"] = sorted(set(row["bottlenecks"]))
        rows.append(row)
    combined = _combine(rows, "any", prefix, index, capacities, states) if rows else _blank(
        "unknown" if result["satisfied"] is None else "missing", prefix)
    if result["overflow"] and not (existential and result['satisfied'] is True):
        combined["status"] = "unknown"
        combined["unknown"].append("shared_allocation_budget:" + prefix)
    combined["allocation_witnesses"] = result["branches"]
    combined["allocation_producer"] = "multifactor.conditions"
    for need in needs:
        upper = sum(capacity_by_need[need.need_id].values())
        combined["quantities"][need.need_id] = dict(required=need.quantity, capacity_upper=upper,
                                                  shortfall_lower=max(0, need.quantity - upper))
    if result["satisfied"] is False:
        combined["allocation_conflicts"] = result["conflicts"]
    return combined
