"""Five constraint extractors for constraint propagation.

Each extractor is a plain function:
    (topology, subcircuits, intent, rule_report, config) -> list[PCBConstraint]

Extractors:
1. extract_diff_pair_constraints -- differential pair detection from net names
2. extract_power_constraints -- IC decoupling + power net clearance
3. extract_impedance_constraints -- high-speed/clock impedance control
4. extract_thermal_constraints -- high-pin-count IC thermal management
5. extract_signal_flow_constraints -- subcircuit placement grouping

CP-01, CP-05: Constraint propagation from circuit analysis.
"""
from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING

from volta.analysis.types import NetClassification
from volta.constraints.table import lookup_params
from volta.constraints.types import (
    ClearanceConstraint,
    DecouplingConstraint,
    DifferentialPairConstraint,
    ImpedanceConstraint,
    PCBConstraint,
    ThermalConstraint,
)

if TYPE_CHECKING:
    from volta.analysis.design_rules import DesignRuleReport
    from volta.analysis.intent_schemas import DesignIntent
    from volta.analysis.subcircuit_detector import Subcircuit
    from volta.analysis.topology_graph import CircuitTopology, TopologyEdge, TopologyNode

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Helper utilities (private, module-level)
# ---------------------------------------------------------------------------


def _build_net_to_edges(
    edges: "tuple[TopologyEdge, ...]",
) -> dict[str, list["TopologyEdge"]]:
    """Index edges by net_name."""
    result: dict[str, list[TopologyEdge]] = {}
    for edge in edges:
        result.setdefault(edge.net_name, []).append(edge)
    return result


def _build_ref_to_node(
    nodes: "tuple[TopologyNode, ...]",
) -> dict[str, "TopologyNode"]:
    """Index nodes by ref."""
    return {n.ref: n for n in nodes}


# Diff pair net name patterns (ordered by specificity)
_DIFF_PAIR_PATTERNS: list[tuple[re.Pattern[str], re.Pattern[str]]] = [
    # Exact +/- suffix: "D+" / "D-", "CLK+" / "CLK-"
    (re.compile(r"^(.+)\+$"), re.compile(r"^(.+)\-$")),
    # _P / _N suffix: "DATA_P" / "DATA_N"
    (re.compile(r"^(.+)_P$"), re.compile(r"^(.+)_N$")),
    # _POS / _NEG suffix: "DATA_POS" / "DATA_NEG"
    (re.compile(r"^(.+)_POS$"), re.compile(r"^(.+)_NEG$")),
]


def _is_diff_pair_name(name: str) -> str | None:
    """Check if name is part of a differential pair. Returns paired net name if match."""
    for pos_pattern, neg_pattern in _DIFF_PAIR_PATTERNS:
        pos_match = pos_pattern.match(name)
        if pos_match:
            base = pos_match.group(1)
            # Return the negative counterpart
            # Reconstruct from the same pattern type
            if "_POS" in name:
                return f"{base}_NEG"
            if "+" in name:
                return f"{base}-"
            if "_P" in name:
                return f"{base}_N"
            return None

        neg_match = neg_pattern.match(name)
        if neg_match:
            base = neg_match.group(1)
            if "_NEG" in name:
                return f"{base}_POS"
            if "-" in name and not name.startswith("-"):
                return f"{base}+"
            if "_N" in name:
                return f"{base}_P"
            return None
    return None


def _get_net_importance(edge: "TopologyEdge") -> "NetImportance":
    """Derive importance from classification."""
    from volta.analysis.net_classifier import NetImportance

    importance_map: dict[NetClassification, NetImportance] = {
        NetClassification.POWER: NetImportance.CRITICAL,
        NetClassification.GROUND: NetImportance.CRITICAL,
        NetClassification.CLOCK: NetImportance.HIGH,
        NetClassification.FEEDBACK: NetImportance.HIGH,
        NetClassification.CONTROL: NetImportance.HIGH,
        NetClassification.SIGNAL: NetImportance.MEDIUM,
    }
    return importance_map.get(edge.classification, NetImportance.LOW)


def _get_signal_integrity(edge: "TopologyEdge") -> "SignalIntegrity":
    """Derive signal integrity from classification and net name patterns."""
    from volta.analysis.net_classifier import SignalIntegrity

    if edge.classification == NetClassification.CLOCK:
        return SignalIntegrity.HIGH_SPEED
    if edge.classification in (NetClassification.POWER, NetClassification.GROUND):
        return SignalIntegrity.POWER_INTEGRITY
    # Check for high-speed digital patterns in net name
    name_upper = edge.net_name.upper()
    if any(p in name_upper for p in ("SPI", "I2C", "UART", "USB", "SDIO", "MOSI", "MISO", "SCK")):
        return SignalIntegrity.HIGH_SPEED
    return SignalIntegrity.UNKNOWN


# ---------------------------------------------------------------------------
# Extractor 1: Differential Pair
# ---------------------------------------------------------------------------


def extract_diff_pair_constraints(
    topology: "CircuitTopology",
    subcircuits: "list[Subcircuit]",
    intent: "DesignIntent | None",
    rule_report: "DesignRuleReport | None",
    config: dict,
) -> list[PCBConstraint]:
    """Extract differential pair constraints from net name patterns.

    Scans topology.edges for net_name pairs matching diff pair patterns:
    ends with +/-, _P/_N, _POS/_NEG.

    Args:
        topology: Circuit topology graph.
        subcircuits: Detected functional blocks (unused by this extractor).
        intent: Design intent (unused by this extractor).
        rule_report: Design rule report (unused by this extractor).
        config: Optional per-extractor configuration overrides.

    Returns:
        List of DifferentialPairConstraint instances.
    """
    from volta.analysis.net_classifier import NetImportance, SignalIntegrity

    if not topology.edges:
        return []

    net_to_edges = _build_net_to_edges(topology.edges)
    all_net_names = set(net_to_edges.keys())

    # Find diff pair net name pairs
    paired: set[frozenset[str]] = set()
    for net_name in all_net_names:
        counterpart = _is_diff_pair_name(net_name)
        if counterpart and counterpart in all_net_names:
            pair = frozenset((net_name, counterpart))
            paired.add(pair)

    if not paired:
        return []

    constraints: list[PCBConstraint] = []

    for pair in sorted(paired, key=lambda p: sorted(p)):
        pair_nets = tuple(sorted(pair))
        # Get edges for both nets to find shared components
        edges_a = net_to_edges.get(pair_nets[0], [])
        edges_b = net_to_edges.get(pair_nets[1], [])

        # Determine signal integrity from the first edge
        si = SignalIntegrity.UNKNOWN
        importance = NetImportance.MEDIUM
        if edges_a:
            si = _get_signal_integrity(edges_a[0])
            importance = _get_net_importance(edges_a[0])
        elif edges_b:
            si = _get_signal_integrity(edges_b[0])
            importance = _get_net_importance(edges_b[0])

        params = lookup_params(si, importance)

        # Collect component refs from both nets
        refs: set[str] = set()
        for edge in edges_a + edges_b:
            refs.add(edge.source_ref)
            refs.add(edge.target_ref)

        # Confidence: 0.9 for explicit +/- pairs, 0.6 for pattern matches
        net_str = "".join(pair_nets)
        confidence = 0.9 if ("+" in net_str and "-" in net_str) else 0.6

        constraints.append(DifferentialPairConstraint(
            net_names=pair_nets,
            source_rule="diff_pair_extractor",
            confidence=confidence,
            component_refs=tuple(sorted(refs)),
            rationale=f"Differential pair: {pair_nets[0]} / {pair_nets[1]}",
            gap_mm=config.get("diff_pair_gap_mm", params.diff_pair_gap_mm),
            width_mm=config.get("diff_pair_width_mm", params.trace_width_mm),
        ))

    return constraints


# ---------------------------------------------------------------------------
# Extractor 2: Power
# ---------------------------------------------------------------------------


def extract_power_constraints(
    topology: "CircuitTopology",
    subcircuits: "list[Subcircuit]",
    intent: "DesignIntent | None",
    rule_report: "DesignRuleReport | None",
    config: dict,
) -> list[PCBConstraint]:
    """Extract power constraints: decoupling proximity and power net clearance.

    Identifies IC-to-capacitor pairs on power nets and creates
    DecouplingConstraint for proximity and ClearanceConstraint for
    power net clearance.

    Args:
        topology: Circuit topology graph.
        subcircuits: Detected functional blocks.
        intent: Design intent.
        rule_report: Design rule report.
        config: Optional per-extractor configuration overrides.

    Returns:
        List of DecouplingConstraint and ClearanceConstraint instances.
    """
    from volta.analysis.net_classifier import NetImportance, SignalIntegrity

    if not topology.edges:
        return []

    ref_to_node = _build_ref_to_node(topology.nodes)
    net_to_edges = _build_net_to_edges(topology.edges)

    # Filter power/ground edges
    power_edges = [
        e for e in topology.edges
        if e.classification in (NetClassification.POWER, NetClassification.GROUND)
    ]

    if not power_edges:
        return []

    constraints: list[PCBConstraint] = []

    # Build IC-to-cap mapping on power nets
    # For each power net, find ICs and capacitors connected to it
    power_nets = {e.net_name for e in power_edges}

    for net_name in power_nets:
        edges = net_to_edges.get(net_name, [])
        ic_refs: set[str] = set()
        cap_refs: set[str] = set()

        for edge in edges:
            src_node = ref_to_node.get(edge.source_ref)
            tgt_node = ref_to_node.get(edge.target_ref)

            if src_node and src_node.component_type == "ic":
                ic_refs.add(edge.source_ref)
            elif src_node and src_node.component_type == "capacitor":
                cap_refs.add(edge.source_ref)

            if tgt_node and tgt_node.component_type == "ic":
                ic_refs.add(edge.target_ref)
            elif tgt_node and tgt_node.component_type == "capacitor":
                cap_refs.add(edge.target_ref)

        # Create decoupling constraints for IC-cap pairs
        max_distance = config.get("decoupling_max_distance_mm", 5.0)
        for ic_ref in sorted(ic_refs):
            for cap_ref in sorted(cap_refs):
                if ic_ref == cap_ref:
                    continue

                # Determine priority from net importance
                net_importance = NetImportance.CRITICAL
                if edges:
                    net_importance = _get_net_importance(edges[0])

                priority = "normal"
                if net_importance == NetImportance.CRITICAL:
                    priority = "critical"
                elif net_importance == NetImportance.HIGH:
                    priority = "high"

                constraints.append(DecouplingConstraint(
                    net_names=(net_name,),
                    source_rule="power_extractor",
                    confidence=0.85,
                    component_refs=(ic_ref, cap_ref),
                    rationale=f"Decoupling cap {cap_ref} for IC {ic_ref} on {net_name}",
                    ic_ref=ic_ref,
                    cap_ref=cap_ref,
                    max_distance_mm=max_distance,
                    priority=priority,
                ))

        # Create clearance constraint for power net
        power_params = lookup_params(
            SignalIntegrity.POWER_INTEGRITY,
            NetImportance.CRITICAL,
        )
        constraints.append(ClearanceConstraint(
            net_names=(net_name,),
            source_rule="power_extractor",
            confidence=0.7,
            component_refs=tuple(sorted(ic_refs | cap_refs)),
            rationale=f"Power net clearance for {net_name}",
            min_clearance_mm=config.get("power_clearance_mm", power_params.clearance_mm),
            net_class_name=f"power_{net_name}",
        ))

    return constraints


# ---------------------------------------------------------------------------
# Extractor 3: Impedance
# ---------------------------------------------------------------------------


def extract_impedance_constraints(
    topology: "CircuitTopology",
    subcircuits: "list[Subcircuit]",
    intent: "DesignIntent | None",
    rule_report: "DesignRuleReport | None",
    config: dict,
) -> list[PCBConstraint]:
    """Extract impedance constraints for high-speed and clock nets.

    Targets nets classified as CLOCK or with HIGH_SPEED signal integrity.
    Uses lookup-based defaults for trace width (closed-form impedance
    deferred to Phase 52).

    Args:
        topology: Circuit topology graph.
        subcircuits: Detected functional blocks.
        intent: Design intent.
        rule_report: Design rule report.
        config: Optional per-extractor configuration overrides.

    Returns:
        List of ImpedanceConstraint instances.
    """
    from volta.analysis.net_classifier import NetImportance, SignalIntegrity

    if not topology.edges:
        return []

    constraints: list[PCBConstraint] = []

    # Find high-speed/clock nets
    high_speed_nets: set[str] = set()
    for edge in topology.edges:
        if edge.classification == NetClassification.CLOCK:
            high_speed_nets.add(edge.net_name)
        elif _get_signal_integrity(edge) == SignalIntegrity.HIGH_SPEED:
            high_speed_nets.add(edge.net_name)

    if not high_speed_nets:
        return []

    net_to_edges = _build_net_to_edges(topology.edges)

    for net_name in sorted(high_speed_nets):
        edges = net_to_edges.get(net_name, [])
        if not edges:
            continue

        first_edge = edges[0]
        si = _get_signal_integrity(first_edge)
        importance = _get_net_importance(first_edge)
        params = lookup_params(si, importance)

        # Collect component refs
        refs: set[str] = set()
        for edge in edges:
            refs.add(edge.source_ref)
            refs.add(edge.target_ref)

        # Confidence: 0.8 for clock nets, 0.7 for other high-speed
        is_clock = first_edge.classification == NetClassification.CLOCK
        confidence = 0.8 if is_clock else 0.7

        target_impedance = config.get("target_impedance_ohm", 50.0)

        constraints.append(ImpedanceConstraint(
            net_names=(net_name,),
            source_rule="impedance_extractor",
            confidence=confidence,
            component_refs=tuple(sorted(refs)),
            rationale=f"Controlled impedance for {'clock' if is_clock else 'high-speed'} net {net_name}",
            target_impedance_ohm=target_impedance,
            trace_width_mm=config.get("impedance_trace_width_mm", params.trace_width_mm),
        ))

    return constraints


# ---------------------------------------------------------------------------
# Extractor 4: Thermal
# ---------------------------------------------------------------------------


def extract_thermal_constraints(
    topology: "CircuitTopology",
    subcircuits: "list[Subcircuit]",
    intent: "DesignIntent | None",
    rule_report: "DesignRuleReport | None",
    config: dict,
) -> list[PCBConstraint]:
    """Extract thermal constraints for high-pin-count ICs.

    Identifies ICs with pin_count >= 16 or >= 8 power pins.
    Uses heuristic thermal resistance (typical DIP/SOIC) and heat
    dissipation estimated from power pin count.

    Args:
        topology: Circuit topology graph.
        subcircuits: Detected functional blocks.
        intent: Design intent.
        rule_report: Design rule report -- thermal violations adjust confidence.
        config: Optional per-extractor configuration overrides.

    Returns:
        List of ThermalConstraint instances.
    """
    if not topology.nodes:
        return []

    constraints: list[PCBConstraint] = []

    # Default thermal parameters (configurable)
    default_thermal_resistance = config.get("thermal_resistance_c_per_w", 50.0)
    max_junction_temp = config.get("max_junction_temp_c", 125.0)
    heat_per_power_pin = config.get("heat_per_power_pin_w", 0.5)

    # Check for thermal violations in rule_report
    has_thermal_violation = False
    if rule_report is not None:
        for violation in rule_report.violations:
            if hasattr(violation, "category") and violation.category.value == "thermal":
                has_thermal_violation = True
                break

    for node in topology.nodes:
        if node.component_type != "ic":
            continue

        # Trigger: high pin count or many power pins
        is_high_pin = node.pin_count >= 16
        has_many_power_pins = len(node.power_pins) >= 8

        if not is_high_pin and not has_many_power_pins:
            continue

        # Estimate heat dissipation from power pin count
        heat_dissipation = len(node.power_pins) * heat_per_power_pin

        # Adjust confidence if thermal violations detected
        confidence = 0.6
        if has_thermal_violation:
            confidence = 0.8

        constraints.append(ThermalConstraint(
            net_names=(),
            source_rule="thermal_extractor",
            confidence=confidence,
            component_refs=(node.ref,),
            rationale=f"Thermal management for high-pin IC {node.ref} "
                      f"({node.pin_count} pins, {len(node.power_pins)} power pins)",
            max_junction_temp_c=max_junction_temp,
            thermal_resistance_c_per_w=default_thermal_resistance,
            heat_dissipation_w=heat_dissipation,
        ))

    return constraints


# ---------------------------------------------------------------------------
# Extractor 5: Signal Flow
# ---------------------------------------------------------------------------


def extract_signal_flow_constraints(
    topology: "CircuitTopology",
    subcircuits: "list[Subcircuit]",
    intent: "DesignIntent | None",
    rule_report: "DesignRuleReport | None",
    config: dict,
) -> list[PCBConstraint]:
    """Extract signal flow constraints from subcircuit placement groups.

    Uses subcircuits to define placement groups: components in the same
    subcircuit should be placed contiguously. If intent is provided,
    subcircuit_intents ordering is used for priority.

    Args:
        topology: Circuit topology graph.
        subcircuits: Detected functional blocks.
        intent: Design intent with subcircuit ordering.
        rule_report: Design rule report (unused by this extractor).
        config: Optional per-extractor configuration overrides.

    Returns:
        List of ClearanceConstraint instances for placement groups.
    """
    if not subcircuits:
        return []

    # Order subcircuits by intent if available
    ordered_subcircuits = list(subcircuits)

    if intent is not None and intent.subcircuit_intents:
        # Build intent component set -> subcircuit mapping
        intent_components: dict[str, int] = {}
        for i, sci in enumerate(intent.subcircuit_intents):
            for ref in sci.component_refs:
                intent_components[ref] = i

        # Sort subcircuits by their intent ordering (earliest intent component wins)
        def _intent_order(sc: "Subcircuit") -> int:
            for ref in sc.components:
                if ref in intent_components:
                    return intent_components[ref]
            return len(intent.subcircuit_intents)  # unmapped go last

        ordered_subcircuits.sort(key=_intent_order)

    constraints: list[PCBConstraint] = []

    intra_clearance = config.get("signal_flow_intra_clearance_mm", 2.0)

    for sc in ordered_subcircuits:
        constraints.append(ClearanceConstraint(
            net_names=sc.nets,
            source_rule="signal_flow_extractor",
            confidence=sc.confidence,
            component_refs=sc.components,
            rationale=f"Placement group {sc.subcircuit_id} "
                      f"({sc.subcircuit_type.value}): keep {', '.join(sc.components)} contiguous",
            min_clearance_mm=intra_clearance,
        ))

    return constraints
