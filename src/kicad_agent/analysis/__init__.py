"""Structural analysis tools for KiCad designs."""

from kicad_agent.analysis.connectivity import NetGraph
from kicad_agent.analysis.net_classifier import NetClassifier, SignalIntegrity, NetImportance
from kicad_agent.analysis.topology_graph import TopologyBuilder, CircuitTopology, TopologyNode, TopologyEdge, NetStats
from kicad_agent.analysis.types import NetClassification, PinRole
from kicad_agent.analysis.subcircuit_detector import SubcircuitDetector, Subcircuit, SubcircuitType
from kicad_agent.analysis.circuit_classifier import CircuitClassifier, ClassificationResult
from kicad_agent.analysis.feature_extraction import SubcircuitFeatures, extract_features
from kicad_agent.analysis.intent_schemas import DesignGoal, DesignIntent, SubcircuitIntent
from kicad_agent.analysis.intent_inference import InferenceResult, IntentInferrer
from kicad_agent.analysis.design_review import (
    DesignFinding,
    DesignReview,
    DesignReviewer,
    ReviewCategory,
    ReviewSeverity,
)
from kicad_agent.analysis.design_rules import (
    DesignRule,
    DesignRuleReport,
    DesignRuleViolation,
    RuleCategory,
    RuleSeverity,
)
from kicad_agent.analysis.design_rule_engine import DesignRuleEngine
from kicad_agent.analysis.builtin_rules import get_builtin_rules
from kicad_agent.analysis.rule_config import RuleConfig, RuleConfigLoader
from kicad_agent.analysis.rule_report import generate_json_report, generate_markdown_report
from kicad_agent.analysis.spatial_benchmark import (
    BoardContext,
    Difficulty,
    SpatialReasoningTask,
    TaskCategory,
    TaskGenerator,
)
from kicad_agent.analysis.benchmark_runner import (
    BenchmarkReport,
    BenchmarkRunner,
    CategoryScore,
    GemmaVisionAdapter,
    ModelAdapter,
    QwenTextAdapter,
    TaskResult,
    score_task,
)
from kicad_agent.analysis.gap_analyzer import (
    BoardInfo,
    GapAnalyzer,
    GapReport,
    IncompleteNet,
    NetNamingIssue,
    RoutingStats,
    UnroutedNet,
)
from kicad_agent.analysis.gap_fill_engine import (
    GapFillEngine,
    GapFillIteration,
    GapFillResult,
)
from kicad_agent.analysis.net_completion_filler import NetCompletionFiller
from kicad_agent.analysis.drc_auto_fixer import DrcAutoFixer
from kicad_agent.analysis.net_naming_validator import NetNamingValidator

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
