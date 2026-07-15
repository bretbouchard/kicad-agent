"""ConstraintPropagator: orchestrates constraint extraction from circuit analysis.

CP-01: Translates schematic intent into PCB design constraints.

Runs all five extractors against the circuit topology, subcircuits,
design intent, and design rule report. Concatenates results into
a single list of PCBConstraint instances.

Propagation is strictly unidirectional: schematic -> PCB.
No feedback path from PCB to schematic (D-V3-01).

Usage:
    from volta.constraints.propagator import ConstraintPropagator

    propagator = ConstraintPropagator(config={"decoupling_max_distance_mm": 3.0})
    constraints = propagator.propagate(topology, subcircuits, intent, rule_report)
"""
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from volta.constraints.extractors import (
    extract_diff_pair_constraints,
    extract_impedance_constraints,
    extract_power_constraints,
    extract_signal_flow_constraints,
    extract_thermal_constraints,
)
from volta.constraints.types import PCBConstraint

if TYPE_CHECKING:
    from volta.analysis.design_rules import DesignRuleReport
    from volta.analysis.intent_schemas import DesignIntent
    from volta.analysis.subcircuit_detector import Subcircuit
    from volta.analysis.topology_graph import CircuitTopology

logger = logging.getLogger(__name__)


# Extractor registry: ordered list of (name, function) tuples.
# Deterministic ordering -- extractors run in this sequence.
_EXTRACTORS: list[tuple[str, ...]] = [
    ("diff_pair", "extract_diff_pair_constraints"),
    ("power", "extract_power_constraints"),
    ("impedance", "extract_impedance_constraints"),
    ("thermal", "extract_thermal_constraints"),
    ("signal_flow", "extract_signal_flow_constraints"),
]


class ConstraintPropagator:
    """Orchestrates constraint extraction from circuit analysis.

    Runs all five extractors against the circuit topology, subcircuits,
    design intent, and design rule report. Concatenates results into
    a single list of PCBConstraint instances.

    Follows the same orchestration pattern as DesignRuleEngine:
    iterate over registered functions, collect results, handle errors
    gracefully. Key differences:
    - Extractors are plain functions, not class instances
    - Error handling: log and continue (one broken extractor does
      not kill propagation)
    - Deterministic ordering: extractors run in registration order

    Attributes:
        _config: Per-extractor configuration overrides.
        _extractors: Ordered list of (name, extractor_fn) tuples.
    """

    def __init__(self, config: dict | None = None) -> None:
        """Initialize propagator with optional config overrides.

        Args:
            config: Dict of configuration overrides passed to each
                    extractor. Keys are extractor-specific (e.g.
                    "decoupling_max_distance_mm").
        """
        self._config = config or {}
        self._extractors: list[tuple[str, object]] = [
            ("diff_pair", extract_diff_pair_constraints),
            ("power", extract_power_constraints),
            ("impedance", extract_impedance_constraints),
            ("thermal", extract_thermal_constraints),
            ("signal_flow", extract_signal_flow_constraints),
        ]

    def propagate(
        self,
        topology: "CircuitTopology",
        subcircuits: "list[Subcircuit] | None" = None,
        intent: "DesignIntent | None" = None,
        rule_report: "DesignRuleReport | None" = None,
    ) -> list[PCBConstraint]:
        """Run all extractors and return concatenated constraints.

        Propagation is strictly unidirectional: schematic -> PCB.
        The result contains no back-references to PCB state.

        Args:
            topology: Circuit topology graph with nodes and edges.
            subcircuits: Detected functional blocks (may be None or empty).
            intent: Inferred design intent (may be None).
            rule_report: Design rule check results (may be None).

        Returns:
            List of PCBConstraint instances from all extractors.
            Empty list if no constraints derivable.
        """
        constraints: list[PCBConstraint] = []
        subcircuits_list = subcircuits or []

        for name, extractor in self._extractors:
            try:
                result = extractor(
                    topology, subcircuits_list, intent, rule_report, self._config,
                )
                constraints.extend(result)
            except Exception as e:
                logger.warning(
                    "Extractor '%s' failed: %s", name, e,
                )
                continue

        return constraints
