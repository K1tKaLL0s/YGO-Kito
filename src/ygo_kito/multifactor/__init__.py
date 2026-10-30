"""Optional factor-based role analysis, independent of construction execution.

Importing the input contract does not import Torch, a card catalog or an engine.
Use .network, .training and .scoring explicitly when neural analysis is wanted.
"""

from .contracts import (
    CONTEXT_FACTORS, GROUP_FACTORS, RELATION_FACTORS, ROLES, FactorContractError,
    Factors, Group, Observation, Relation, RoleInput,
)

__all__ = [
    "CONTEXT_FACTORS", "GROUP_FACTORS", "RELATION_FACTORS", "ROLES",
    "FactorContractError", "Factors", "Group", "Observation", "Relation", "RoleInput",
]
