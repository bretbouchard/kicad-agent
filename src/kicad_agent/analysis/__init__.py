"""Structural analysis tools for KiCad designs."""

from kicad_agent.analysis.connectivity import NetGraph
from kicad_agent.analysis.net_classifier import NetClassifier, SignalIntegrity, NetImportance
from kicad_agent.analysis.topology_graph import TopologyBuilder, CircuitTopology, TopologyNode, TopologyEdge, NetStats
from kicad_agent.analysis.types import NetClassification, PinRole
from kicad_agent.analysis.subcircuit_detector import SubcircuitDetector, Subcircuit, SubcircuitType
from kicad_agent.analysis.circuit_classifier import CircuitClassifier, ClassificationResult
from kicad_agent.analysis.feature_extraction import SubcircuitFeatures, extract_features

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
]
