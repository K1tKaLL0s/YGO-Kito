"""Typed source-bound fusion witnesses; no archetype/card-name dispatch.

This version handles chain-resolved fusion effects with owner material moves.
Procedure-only/contact fusion remains unsupported until it has its own witness.
"""
from .construction_binding import CardTagAssessment
from .build_contracts import digest
from .validation import ContractError, fields, integer


def validate_fusion_witness(value, pool, assets=None):
    fields(value, {'effect_assessments', 'minimum_materials', 'allowed_destination_zones', 'required_source_zones'})
    integer(value['minimum_materials'], 'fusion material event minimum', 1, 16)
    for key in ('allowed_destination_zones', 'required_source_zones'):
        zones=value[key]
        if not isinstance(zones,list) or not 1<=len(zones)<=7 or len(zones)!=len(set(zones)) or any(z not in (1,2,4,8,16,32,64) for z in zones):
            raise ContractError('explicit distinct fusion material zones required')
    rows=value['effect_assessments']
    if not isinstance(rows,list) or not 1<=len(rows)<=4:raise ContractError('bounded source-bound fusion effect assessments required')
    seen=set()
    for row in rows:
        review=CardTagAssessment.from_dict(row)
        if review.card_id not in pool or review.card_id in seen or review.status!='satisfied' or review.tag.dimension!='effect_type' or review.tag.value!='fusion_summon':
            raise ContractError('fusion effect must have an explicit matching typed source review')
        seen.add(review.card_id)
        if assets is not None:
            card=assets.rows[review.card_id]
            if review.cards_sha256!=assets.receipt['resources']['cards'] or review.effect_text_sha256!=digest(card['desc']) or review.quote not in card['desc']:
                raise ContractError('fusion effect assessment source/text changed')
    return tuple(sorted(seen))
