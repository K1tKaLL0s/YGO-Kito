"""Bounded, repeatable queries inside an unchanged construction task pool."""
from .build_contracts import DeckParts
from .build_pipeline import EXTRA_TYPES
from .build_semantics import matches as public_matches
from .construction_inventory import InventoryDependencies, matches, recall_dependencies
from .effect_blocks import functional_tags
from .effect_mechanisms import MechanismCatalog
from .validation import ContractError, integer


def candidate_ids(task, assets, graph, *, base=None, scopes=(), cursor=0, limit=128, catalog=None, theme_profile=None):
    """Retrieve after coarse logic; a result never replaces BuildTask.pool.

    Explicit counts, graph functions and actual missing components determine
    query priority. A rotating part of each batch also explores the remainder.
    All generated lists are checked against the original task by the caller.
    """
    integer(cursor, 'card query cursor', 0)
    integer(limit, 'card query batch', 16, 256)
    assets.check_task(task)
    catalog = catalog or MechanismCatalog(assets, task.pool)
    base = base or DeckParts((), (), ())
    required = {r['card_id'] for r in task.requirements}
    selected = set(base.main + base.extra + base.side) | required
    if not selected <= set(task.pool):
        raise ContractError('query inventory exceeds the original task pool')
    if len(selected) > limit:
        raise ContractError('query batch cannot contain the current inventory and fixed cards')
    requests = []
    if selected:
        inventory = InventoryDependencies(catalog).evaluate(base, graph)
        for row in inventory['cards'].values():
            for effect in (*row['effects'], *((row['materials'],) if row['materials'] else ())):
                if effect['status'] == 'missing':
                    requests.extend(r['query'] for r in effect['requirements'] if r['shortfall'])
    predicates = [dict(field=s.field, value=s.value) for s in scopes]
    if task.goal['kind'] == 'deck_constraints':
        predicates += [r['predicate'] for r in task.goal['constraints'] if r['minimum'] > 0]
    wanted = {t.value for n in graph.nodes for t in n.tags if t.dimension == 'effect'}
    if theme_profile is not None:
        from .effect_blocks import LABELS
        wanted.update(t['value'] for t in theme_profile.get('goal_tags',()) if t['dimension']=='effect')
        wanted.update(LABELS[kind] for g in theme_profile.get('goals',())
                      if (kind := g['function']['kind']) in LABELS)
    start = cursor % len(task.pool)
    ordered = task.pool[start:] + task.pool[:start]
    rank = {}
    for position, code in enumerate(ordered):
        tags = {v['tag']['value'] for v in functional_tags(catalog.effect_blocks(code))} if wanted else set()
        rank[code] = (int(any(matches(assets.rows[code], p) for p in requests)),
                      len(wanted & tags), int(any(public_matches(assets.rows[code], p) for p in predicates)),
                      -position)
    ranked = sorted(task.pool, key=lambda c: rank[c], reverse=True)
    # Keep room for the ordinary dependency recall, and for cards that did not
    # occur in an earlier query. Limits govern this batch, never future queries.
    reserve = min(16, max(0, limit-len(selected)))
    ceiling = max(len(selected), limit-reserve)
    for predicate in predicates:
        for code in ranked:
            if len(selected) >= min(ceiling, len(required)+len(set(base.main+base.extra+base.side))+24):
                break
            if public_matches(assets.rows[code], predicate):
                selected.add(code)
    def capacity(zone=None):
        identities = {assets.rows[c]['alias'] or c for c in selected if zone is None or
            bool(assets.rows[c]['type'] & EXTRA_TYPES) == (zone == 'extra')}
        return sum(assets.limits.get(c, 3) for c in identities)
    for zone in ('main', 'extra', None):
        needed = task.sizes[zone] if zone else sum(task.sizes.values())
        for code in ranked:
            if capacity(zone) >= needed or len(selected) >= ceiling:
                break
            if zone is None or bool(assets.rows[code]['type'] & EXTRA_TYPES) == (zone == 'extra'):
                selected.add(code)
    explore = min(16, max(0, ceiling-len(selected)))
    for code in ordered:
        if code not in selected and explore:
            selected.add(code)
            explore -= 1
    for code in ranked:
        if len(selected) >= ceiling:
            break
        selected.add(code)
    recalled, recall = recall_dependencies(catalog, selected, task.pool, limit=limit-len(selected))
    result = tuple(sorted(recalled))
    return result, dict(task_sha256=task.sha256, logic_sha256=graph.sha256,
        source='task_pool_public_functions_and_missing_components', universe_count=len(task.pool),
        candidate_ids=list(result), cursor=cursor, next_cursor=cursor+max(1, min(16, len(task.pool))),
        dependency_recall=recall, query_count=len(requests), task_pool_unchanged=True,
        exhaustive_construction_search=False)
