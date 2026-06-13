"""Shared types for circuit topology analysis.

NetClassification and PinRole enums live here so that both
topology_graph.py and net_classifier.py can import them without
creating a circular dependency (topology_graph -> net_classifier -> topology_graph).
"""

from __future__ import annotations

from enum import Enum


class NetClassification(str, Enum):
    """Classification of net purpose in the circuit."""

    POWER = "POWER"
    GROUND = "GROUND"
    SIGNAL = "SIGNAL"
    CONTROL = "CONTROL"
    FEEDBACK = "FEEDBACK"
    CLOCK = "CLOCK"
    # Gate-specific additions for schematic intent completeness (Phase 86-02)
    HIGH_CURRENT = "HIGH_CURRENT"
    DIFFERENTIAL_PAIR = "DIFFERENTIAL_PAIR"
    ANALOG = "ANALOG"
    DIGITAL = "DIGITAL"
    UNKNOWN = "UNKNOWN"


class PinRole(str, Enum):
    """Role of a pin in signal flow."""

    INPUT = "INPUT"
    OUTPUT = "OUTPUT"
    POWER = "POWER"
    BIDIRECTIONAL = "BIDIRECTIONAL"
    CONTROL = "CONTROL"
    UNKNOWN = "UNKNOWN"
