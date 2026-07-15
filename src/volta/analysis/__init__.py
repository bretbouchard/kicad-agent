"""Structural analysis tools for KiCad designs."""

from volta.analysis.connectivity import NetGraph
from volta.analysis.net_classifier import NetClassifier, SignalIntegrity, NetImportance
from volta.analysis.topology_graph import TopologyBuilder, CircuitTopology, TopologyNode, TopologyEdge, NetStats
from volta.analysis.types import NetClassification, PinRole
from volta.analysis.subcircuit_detector import SubcircuitDetector, Subcircuit, SubcircuitType
from volta.analysis.circuit_classifier import CircuitClassifier, ClassificationResult
from volta.analysis.feature_extraction import SubcircuitFeatures, extract_features
from volta.analysis.intent_schemas import DesignGoal, DesignIntent, SubcircuitIntent
from volta.analysis.intent_inference import InferenceResult, IntentInferrer
from volta.analysis.design_review import (
    DesignFinding,
    DesignReview,
    DesignReviewer,
    ReviewCategory,
    ReviewSeverity,
)
from volta.analysis.design_rules import (
    DesignRule,
    DesignRuleReport,
    DesignRuleViolation,
    RuleCategory,
    RuleSeverity,
)
from volta.analysis.design_rule_engine import DesignRuleEngine
from volta.analysis.builtin_rules import get_builtin_rules
from volta.analysis.rule_config import RuleConfig, RuleConfigLoader
from volta.analysis.rule_report import generate_json_report, generate_markdown_report
from volta.analysis.spatial_benchmark import (
    BoardContext,
    Difficulty,
    SpatialReasoningTask,
    TaskCategory,
    TaskGenerator,
)
from volta.analysis.benchmark_runner import (
    BenchmarkReport,
    BenchmarkRunner,
    CategoryScore,
    GemmaVisionAdapter,
    ModelAdapter,
    QwenTextAdapter,
    TaskResult,
    score_task,
)
from volta.analysis.gap_analyzer import (
    BoardInfo,
    GapAnalyzer,
    GapReport,
    IncompleteNet,
    NetNamingIssue,
    RoutingStats,
    UnroutedNet,
)
from volta.analysis.gap_fill_engine import (
    GapFillEngine,
    GapFillIteration,
    GapFillResult,
)
from volta.analysis.net_completion_filler import NetCompletionFiller
from volta.analysis.drc_auto_fixer import DrcAutoFixer
from volta.analysis.net_naming_validator import NetNamingValidator

__all__ = [
    "NetGraph",
    "NetClassifier",
    "SignalIntegrity",
    "NetImportance",
    "TopologyBuilder",
    "CircuitTopology",
    "TopologyNode",
    "TopologyEdge",
    "NetStats",
    "NetClassification",
    "PinRole",
    "SubcircuitDetector",
    "Subcircuit",
    "SubcircuitType",
    "CircuitClassifier",
    "ClassificationResult",
    "SubcircuitFeatures",
    "extract_features",
    "DesignGoal",
    "DesignIntent",
    "SubcircuitIntent",
    "InferenceResult",
    "IntentInferrer",
    "DesignFinding",
    "DesignReview",
    "DesignReviewer",
    "ReviewCategory",
    "ReviewSeverity",
    "DesignRule",
    "DesignRuleReport",
    "DesignRuleViolation",
    "RuleCategory",
    "RuleSeverity",
    "DesignRuleEngine",
    "get_builtin_rules",
    "RuleConfig",
    "RuleConfigLoader",
    "generate_json_report",
    "generate_markdown_report",
    "BoardContext",
    "Difficulty",
    "SpatialReasoningTask",
    "TaskCategory",
    "TaskGenerator",
    "BenchmarkReport",
    "BenchmarkRunner",
    "CategoryScore",
    "GemmaVisionAdapter",
    "ModelAdapter",
    "QwenTextAdapter",
    "TaskResult",
    "score_task",
    "GapAnalyzer",
    "GapReport",
    "UnroutedNet",
    "IncompleteNet",
    "NetNamingIssue",
    "BoardInfo",
    "RoutingStats",
    "GapFillEngine",
    "GapFillIteration",
    "GapFillResult",
    "NetCompletionFiller",
    "DrcAutoFixer",
    "NetNamingValidator",
]
