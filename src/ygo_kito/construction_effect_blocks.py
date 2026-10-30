"""Source-bound functional tags derived from recognized effect clauses.

This compatibility adapter exposes coarse tags; effect-level semantics and
unknown clauses are retained separately in effect_mechanisms. No card-ID table
supplies the default answers. Actual execution remains the core's responsibility.
"""
from .build_contracts import digest
from .construction_binding import CardTagAssessment
from .construction_logic import LogicTag
from .effect_mechanisms import MechanismCatalog, SEMANTIC_VERSION

MILL = LogicTag('effect', '卡组送墓')
GRAVE_FUSION = LogicTag('effect', '墓地融合')
REVIEWS = ()  # Historical import compatibility; never a default semantic source.


def reviewed_effect_blocks(assets, pool, reviews=None, *, catalog=None):
    assessments = []
    if reviews is None:
        catalog = catalog or MechanismCatalog(assets, pool)
        for code in sorted(pool):
            profile = catalog.card(code)
            for value in profile.tags:
                effects = (profile.grave_fusion if value == GRAVE_FUSION.value else
                    tuple(e for e in profile.effects if any(o['kind'] in ('mill','send_grave') and
                        o.get('from_zones') == ('deck',) for o in e.observed_operations)))
                quote = effects[0].text[:512]
                assessments.append(CardTagAssessment(code, LogicTag('effect',value), 'satisfied',
                    profile.cards_sha256,profile.text_sha256,quote,SEMANTIC_VERSION,
                    'Recognized effect clauses '+','.join(str(e.index) for e in effects)+
                    '; conditions, payments and restrictions remain scoped to each effect; core execution unproved.'))
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


# Compatibility name for the already recorded first curriculum instance.
pearl_effect_blocks = reviewed_effect_blocks
