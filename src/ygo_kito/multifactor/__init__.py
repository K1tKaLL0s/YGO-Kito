"""Optional factor-based role analysis, independent of construction execution.

Importing the input contract does not import Torch, a card catalog or an engine.
Use .network, .training and .scoring explicitly when neural analysis is wanted.
"""

from .analysis import AnalysisBudget, AnalysisFacts, RoleAnalyzer, migrate_v2_input
from .conditions import Condition, ConditionGroup, Resource, SolverBudget, solve_requirements
from .functional_units import BranchConditions, minimum_member_branches
from .axis_candidates import AxisCandidate, CandidateBudget, CandidateSet, generate_axis_candidates
from .semantics import GraphBudget, GraphBuild, build_analysis_graph
from .metrics import (axis_set_metrics, binary_metrics, categorical_metrics, group_bootstrap,
                      macro_f1, macro_f1_report, probability_calibration)
from .splits import GENERALIZATION_PROTOCOLS, SPLIT_VERSION, assign_group_splits, build_leakage_groups, group_rows, leakage_group
from .contracts import (
    ANALYSIS_MODES, CONTEXT_FACTORS, GROUP_FACTORS, RELATION_FACTORS, ROLES, FactorContractError, DeckSpec, UnitSpec,
    AnalysisContext, AnalysisGraph, CandidateInsert, Factors, FunctionSeed, GraphEdge, GraphNode,
    Group, LabelCell, LabelSet, Mechanism, Observation, Relation, RoleInput, StructureLink,
    AnalysisRequestContext, AnalysisValue, CapabilityStatus, CopyChange, CopyComparison,
    DeckAnalysis, ExternalLegality, RECOGNITION_MODES, SamplingSpec, UnitAssessment,
)

__all__ = [
    "ANALYSIS_MODES", "BranchConditions", "CONTEXT_FACTORS", "GENERALIZATION_PROTOCOLS", "GROUP_FACTORS",
    "RELATION_FACTORS", "ROLES", "Condition", "ConditionGroup", "DeckSpec",
    "FactorContractError", "Factors", "Group", "LabelCell", "Mechanism", "Observation",
    "Relation", "Resource", "RoleInput", "UnitSpec", "AnalysisContext", "CandidateInsert", "LabelSet", "SolverBudget", "minimum_member_branches", "assign_group_splits", "binary_metrics",
    "group_rows", "leakage_group", "macro_f1", "migrate_v2_input", "solve_requirements",
    "AnalysisGraph", "AxisCandidate", "CandidateBudget", "CandidateSet", "FunctionSeed", "GraphBudget",
    "GraphBuild", "GraphEdge", "GraphNode", "StructureLink", "build_analysis_graph", "generate_axis_candidates",
    "SPLIT_VERSION", "axis_set_metrics", "build_leakage_groups", "categorical_metrics", "group_bootstrap",
    "macro_f1_report", "probability_calibration",
    "AnalysisBudget", "AnalysisFacts", "AnalysisRequestContext", "AnalysisValue", "CapabilityStatus",
    "CopyChange", "CopyComparison", "DeckAnalysis", "ExternalLegality", "RECOGNITION_MODES",
    "RoleAnalyzer", "SamplingSpec", "UnitAssessment",
]
