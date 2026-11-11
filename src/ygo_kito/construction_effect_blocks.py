"""Source-bound functional tags derived from recognized effect clauses.

This compatibility adapter exposes coarse tags; effect-level semantics and
unknown clauses are retained separately in effect_mechanisms. No card-ID table
supplies the default answers. Actual execution remains the core's responsibility.
"""
from .build_contracts import digest
from .construction_binding import CardTagAssessment
from .construction_logic import LogicTag
from .effect_mechanisms import MechanismCatalog, SEMANTIC_VERSION
from .effect_blocks import BLOCK_VERSION, functional_tags

MILL = LogicTag('effect', '卡组送墓')
GRAVE_FUSION = LogicTag('effect', '墓地融合')


def logic_vocabulary():
    """Coarse functions exist before any task-specific card retrieval."""
    from .effect_blocks import LABELS
    return tuple(sorted({LogicTag('effect', name) for name in LABELS.values()} |
                        {MILL, GRAVE_FUSION}, key=lambda t: (t.dimension, t.value)))


def requested_logic_tags(task, tags=()):
    """Only a declared route, never observed optional effects, adds a goal."""
    from .effect_blocks import LABELS
    route = task.goal.get('route_goal', task.goal if task.goal['kind'] != 'deck_constraints' else None)
    result = tuple(tags)
    if route and route['kind'] in LABELS:
        result += (LogicTag('effect',LABELS[route['kind']]),)
    return tuple(dict.fromkeys(result))


def reviewed_effect_blocks(assets, pool, reviews=None, *, catalog=None):
    assessments = []
    if reviews is None:
        catalog = catalog or MechanismCatalog(assets, pool)
        for code in sorted(pool):
            entry = catalog.effect_blocks(code)
            for item in functional_tags(entry):
                assessments.append(CardTagAssessment(code, LogicTag(**item['tag']), 'satisfied',
                    entry['cards_sha256'],entry['text_sha256'],item['source'][:512],BLOCK_VERSION,
                    'Observed function in '+item['effect_key']+
                    '; scoped costs, choices, selectors and unknown dependencies remain in effect_records.'))
        return tuple(dict.fromkeys(a.tag for a in assessments)), tuple(assessments)
    # Explicit application-supplied assessments remain labelled external reviews.
    for code, tag, quote in reviews:
        row = assets.rows.get(code)
        if code not in pool or row is None or quote not in row['desc']:
            continue  # Changed/unknown text is not silently asserted as satisfied.
        assessments.append(CardTagAssessment(code, tag, 'satisfied', assets.receipt['resources']['cards'],
            digest(row['desc']), quote, 'explicit-host-public-card-text-review',
            'Only the quoted function is reviewed; activation conditions and execution require actual core evidence.'))
    tags = tuple(dict.fromkeys(a.tag for a in assessments))
    return tags, tuple(assessments)


