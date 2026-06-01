"""Structural analysis tools for KiCad designs."""

from kicad_agent.analysis.connectivity import NetGraph
from kicad_agent.analysis.net_classifier import NetClassifier
from kicad_agent.analysis.topology_graph import TopologyBuilder, CircuitTopology

__all__ = ["NetGraph", "NetClassifier", "TopologyBuilder", "CircuitTopology"]
