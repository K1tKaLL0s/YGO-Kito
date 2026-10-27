"""Source-bound public effect reviews, separate from coarse connectors.

The current reviewed examples are Pearl cards. Consumption uses tag/type/text
bindings for any supplied review table; theme or card-name branches are absent.

These host text assessments are not a complete effect parser or learned claims.
Actual timing, materials and fusion execution remain the core's responsibility.
"""
from .build_contracts import digest
from .construction_binding import CardTagAssessment
from .construction_logic import LogicTag

MILL = LogicTag('effect', '卡组送墓')
GRAVE_FUSION = LogicTag('effect', '墓地融合')
REVIEWS = (
    (73956664, MILL, '从卡组把「珠泪哀歌族·雷诺哈特」以外的1只「珠泪哀歌族」怪兽送去墓地。'),
    (74078255, MILL, '从自己卡组上面把3张卡送去墓地。'),
    (572850, MILL, '从自己卡组上面把3张卡送去墓地。'),
    (37961969, MILL, '从自己卡组上面把3张卡送去墓地。'),
    (92731385, MILL, '从自己卡组上面把5张卡送去墓地。'),
    *((code, GRAVE_FUSION, '融合怪兽卡决定的包含墓地的这张卡的融合素材怪兽从自己的手卡·场上·墓地用喜欢的顺序回到持有者卡组下面，把那1只融合怪兽从额外卡组融合召唤。')
      for code in (572850, 37961969, 74078255)),
)


def reviewed_effect_blocks(assets, pool, reviews=REVIEWS):
    assessments = []
    for code, tag, quote in reviews:
        row = assets.rows.get(code)
        if code not in pool or row is None or quote not in row['desc']:
            continue  # Changed/unknown text is not silently asserted as satisfied.
        assessments.append(CardTagAssessment(code, tag, 'satisfied', assets.receipt['resources']['cards'],
            digest(row['desc']), quote, 'host-public-card-text-review:pearl-20261027-v1',
            'Only the quoted function is reviewed; activation conditions and execution require actual core evidence.'))
    tags = tuple(dict.fromkeys(a.tag for a in assessments))
    return tags, tuple(assessments)


# Compatibility name for the already recorded first curriculum instance.
pearl_effect_blocks = reviewed_effect_blocks
