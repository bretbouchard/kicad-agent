"""Built-in design rules for analog circuit review.

DOMAIN-04: 8 domain-specific design rules that go beyond
KiCad's built-in ERC/DRC checks.

Rules:
  BYPASS_CAP_01: Decoupling caps on IC power nets
  FEEDBACK_01: Op-amp feedback loop compensation capacitor
  IMPEDANCE_01: High-speed nets with controlled impedance
  THERMAL_01: Power components with thermal consideration
  GROUND_01: Star ground topology for audio circuits
  POWER_01: Power supply filtering adequacy
  SIGNAL_01: Input protection on externally-connected nets
  LAYOUT_01: Critical signal paths with excessive connections

Uses topology edges (not pin_nets) for net connectivity since
TopologyNode has no pin_nets field. Adapts Phase 47's
_build_net_to_nodes/_build_node_to_nets pattern.

Usage:
    from kicad_agent.analysis.builtin_rules import get_builtin_rules

    rules = get_builtin_rules()
    engine = DesignRuleEngine(rules=rules)
    report = engine.run(topology)
"""
from __future__ import annotations

import logging
from typing import Any

from kicad_agent.analysis.design_rules import (
    DesignRule,
    DesignRuleViolation,
    RuleCategory,
    RuleSeverity,
)
from kicad_agent.analysis.topology_graph import CircuitTopology, TopologyNode

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Shared helpers (adapted from design_review.py Phase 47)
# ---------------------------------------------------------------------------

_IC_LIB_PATTERNS = (
    "NE5532", "TL072", "LM358", "THAT4301", "CD4066", "CD4060",
    "RP2040", "PT2399", "LM7812", "LM7912", "LM7805", "OP07",
    "OPA2134", "RC4558", "JRC4558", "BA6110", "LM13700", "LF353",
)

_OPAMP_LIB_PATTERNS = (
    "NE5532", "TL072", "LM358", "OP07", "OPA2134", "RC4558",
    "JRC4558", "LF353", "BA6110", "LM13700",
)

_CAP_LIB_PATTERNS = ("Device:C", "Device:C_Small", "Device:CP", "Device:CP_Small")

_POWER_NET_PREFIXES = (
    "+9V", "-9V", "+12V", "-12V", "+15V", "-15V",
    "+3V3", "+5V", "-5V", "VCC", "VDD", "VEE",
)

_HIGH_SPEED_NET_PATTERNS = (
    "SPI", "SCLK", "MOSI", "MISO", "SS", "CS",
    "I2C", "SDA", "SCL", "UART", "TX", "RX",
    "USB", "DP", "DM", "MIDI",
)

_POWER_IC_PATTERNS = (
    "LM78", "LM79", "LM317", "LM337", "7805", "7812", "7912",
)

_GROUND_NAMES = ("GND", "GNDA", "AGND", "PGND", "CHASSIS", "EARTH")


def _build_net_to_nodes(topology: CircuitTopology) -> dict[str, list[TopologyNode]]:
    """Build mapping from net name to connected TopologyNode list."""
    net_map: dict[str, list[TopologyNode]] = {}
    node_map = {n.ref: n for n in topology.nodes}

    for edge in topology.edges:
        src_node = node_map.get(edge.source_ref)
        if src_node:
            net_map.setdefault(edge.net_name, [])
            if src_node not in net_map[edge.net_name]:
                net_map[edge.net_name].append(src_node)
        tgt_node = node_map.get(edge.target_ref)
        if tgt_node:
            net_map.setdefault(edge.net_name, [])
            if tgt_node not in net_map[edge.net_name]:
                net_map[edge.net_name].append(tgt_node)

    return net_map


def _build_node_to_nets(topology: CircuitTopology) -> dict[str, list[str]]:
    """Build mapping from node ref to connected net names."""
    node_nets: dict[str, list[str]] = {}
    for edge in topology.edges:
        for ref in (edge.source_ref, edge.target_ref):
            node_nets.setdefault(ref, [])
            if edge.net_name not in node_nets[ref]:
                node_nets[ref].append(edge.net_name)
    return node_nets


def _is_ic(lib_id: str) -> bool:
    return any(p.upper() in lib_id.upper() for p in _IC_LIB_PATTERNS)


def _is_opamp(lib_id: str) -> bool:
    return any(p.upper() in lib_id.upper() for p in _OPAMP_LIB_PATTERNS)


def _is_cap(lib_id: str) -> bool:
    return any(pat in lib_id for pat in _CAP_LIB_PATTERNS)


def _is_resistor(lib_id: str) -> bool:
    return lib_id.startswith("Device:R")


def _is_diode(lib_id: str) -> bool:
    return lib_id.startswith("Device:D") or lib_id.startswith("Device:LED")


def _is_power_net(net_name: str) -> bool:
    return any(net_name.upper().startswith(p.upper()) for p in _POWER_NET_PREFIXES)


def _is_high_speed_net(net_name: str) -> bool:
    return any(p in net_name.upper() for p in _HIGH_SPEED_NET_PATTERNS)


def _is_ground_net(net_name: str) -> bool:
    return any(g == net_name.upper() for g in _GROUND_NAMES)


# ---------------------------------------------------------------------------
# Built-in rules
# ---------------------------------------------------------------------------


class BypassCapRule(DesignRule):
    """BYPASS_CAP_01: ICs must have decoupling capacitors on power nets.

    Uses topology edges to find ICs, then checks if any capacitor shares
    a power net with the IC. Uses power_nets from CircuitTopology for
    power net identification, supplemented by prefix pattern matching.
    """

    name = "BYPASS_CAP_01"
    category = RuleCategory.BYPASS_CAPS
    default_severity = RuleSeverity.WARNING
    description = "ICs must have decoupling capacitors on power pins"

    def check(self, topology: Any, config: dict[str, Any] | None = None) -> list[DesignRuleViolation]:
        config = config or {}
        violations: list[DesignRuleViolation] = []

        net_to_nodes = _build_net_to_nodes(topology)
        node_nets = _build_node_to_nets(topology)

        for node in topology.nodes:
            if not _is_ic(node.lib_id):
                continue
            if not node.power_pins:
                continue

            ic_nets = node_nets.get(node.ref, [])

            for net_name in ic_nets:
                is_power = (
                    net_name in topology.power_nets
                    or _is_power_net(net_name)
                    or _is_ground_net(net_name)
                )
                if not is_power:
                    continue

                # Skip ground nets for bypass cap check
                if _is_ground_net(net_name):
                    continue

                # Check if any capacitor is on this same net
                nodes_on_net = net_to_nodes.get(net_name, [])
                has_bypass = any(
                    _is_cap(n.lib_id) and n.ref != node.ref
                    for n in nodes_on_net
                )

                if not has_bypass:
                    violations.append(DesignRuleViolation(
                        rule_id=self.name,
                        description=f"{node.ref} ({node.lib_id}) power pin on {net_name} "
                                    f"has no bypass capacitor",
                        severity=self.default_severity,
                        location=node.ref,
                        suggestion=f"Add 100nF ceramic cap between {net_name} and GND near {node.ref}",
                        affected_components=(node.ref,),
                        details={"power_net": net_name, "ic_lib_id": node.lib_id},
                    ))

        return violations


class FeedbackCompRule(DesignRule):
    """FEEDBACK_01: Op-amp feedback loops should have compensation capacitors.

    Checks that op-amps with feedback networks include a small capacitor
    across the feedback resistor to prevent oscillation.

    Algorithm:
    1. Find op-amps
    2. Look for feedback edges (signal_direction="feedback")
    3. Check if capacitor shares feedback nets with the op-amp
    4. No cap -> SUGGESTION
    """

    name = "FEEDBACK_01"
    category = RuleCategory.FEEDBACK
    default_severity = RuleSeverity.SUGGESTION
    description = "Op-amp feedback loops should have compensation capacitors"

    def check(self, topology: Any, config: dict[str, Any] | None = None) -> list[DesignRuleViolation]:
        violations: list[DesignRuleViolation] = []

        node_nets = _build_node_to_nets(topology)

        for node in topology.nodes:
            if not _is_opamp(node.lib_id):
                continue

            # Check for feedback edges involving this op-amp
            has_feedback = False
            feedback_nets: set[str] = set()
            for edge in topology.edges:
                if edge.signal_direction == "feedback":
                    if edge.source_ref == node.ref or edge.target_ref == node.ref:
                        has_feedback = True
                        feedback_nets.add(edge.net_name)

            # Also check: resistor shares 2+ nets with opamp (classic feedback)
            opamp_nets = set(node_nets.get(node.ref, []))
            if not has_feedback:
                for other in topology.nodes:
                    if not _is_resistor(other.lib_id):
                        continue
                    other_nets = set(node_nets.get(other.ref, []))
                    shared = other_nets & opamp_nets
                    if len(shared) >= 2:
                        has_feedback = True
                        feedback_nets.update(shared)

            if not has_feedback:
                continue

            # Check if a capacitor also shares feedback nets
            has_comp_cap = False
            for other in topology.nodes:
                if not _is_cap(other.lib_id):
                    continue
                other_nets = set(node_nets.get(other.ref, []))
                # Cap on any feedback net is sufficient -- in real circuits
                # the comp cap bridges the same nets as the feedback resistor.
                # With single-net feedback (common in topology graph), cap just
                # needs to be on that feedback net.
                if other_nets & feedback_nets:
                    has_comp_cap = True
                    break

            if not has_comp_cap:
                violations.append(DesignRuleViolation(
                    rule_id=self.name,
                    description=f"{node.ref} ({node.lib_id}) has feedback network "
                                f"but no compensation capacitor",
                    severity=self.default_severity,
                    location=node.ref,
                    suggestion=f"Add 10-22pF capacitor across feedback resistor "
                               f"on {node.ref} to prevent oscillation",
                    affected_components=(node.ref,),
                ))

        return violations


class ImpedanceRule(DesignRule):
    """IMPEDANCE_01: High-speed nets should have controlled impedance.

    Flags nets with high-speed protocol names (SPI, I2C, UART, USB, MIDI)
    that don't have series termination resistors.

    Severity: WARNING for SPI/USB, INFO for others.
    """

    name = "IMPEDANCE_01"
    category = RuleCategory.IMPEDANCE
    default_severity = RuleSeverity.INFO
    description = "High-speed nets should have controlled impedance"

    def check(self, topology: Any, config: dict[str, Any] | None = None) -> list[DesignRuleViolation]:
        violations: list[DesignRuleViolation] = []

        net_to_nodes = _build_net_to_nodes(topology)

        # Collect unique net names from edges
        net_names = {e.net_name for e in topology.edges}

        for net_name in net_names:
            if not _is_high_speed_net(net_name):
                continue

            # Skip power nets
            if net_name in topology.power_nets or _is_power_net(net_name):
                continue

            # Check if any resistor is on this net (series termination)
            nodes_on_net = net_to_nodes.get(net_name, [])
            has_termination = any(_is_resistor(n.lib_id) for n in nodes_on_net)

            if not has_termination:
                upper = net_name.upper()
                severity = RuleSeverity.WARNING if (
                    "SPI" in upper or "USB" in upper
                ) else RuleSeverity.INFO

                affected = tuple(n.ref for n in nodes_on_net)
                violations.append(DesignRuleViolation(
                    rule_id=self.name,
                    description=f"High-speed net {net_name} has no series termination resistor",
                    severity=severity,
                    location=net_name,
                    suggestion=f"Add 22-33 ohm series termination resistor on {net_name} "
                               f"for impedance matching",
                    affected_components=affected,
                ))

        return violations


class ThermalRule(DesignRule):
    """THERMAL_01: Power components should have thermal consideration.

    Flags voltage regulators and power transistors that don't have
    thermal pads or heatsink provisions.

    Since TopologyNode lacks thermal pad data, all power ICs are
    flagged as INFO-level informational warnings.

    Severity: INFO (informational -- no thermal data in topology).
    """

    name = "THERMAL_01"
    category = RuleCategory.THERMAL
    default_severity = RuleSeverity.INFO
    description = "Power components should have thermal consideration"

    def check(self, topology: Any, config: dict[str, Any] | None = None) -> list[DesignRuleViolation]:
        violations: list[DesignRuleViolation] = []

        for node in topology.nodes:
            if not any(p.upper() in node.lib_id.upper() for p in _POWER_IC_PATTERNS):
                continue

            violations.append(DesignRuleViolation(
                rule_id=self.name,
                description=f"Power component {node.ref} ({node.lib_id}) "
                            f"may need thermal pad or heatsink",
                severity=self.default_severity,
                location=node.ref,
                suggestion=f"Verify thermal pad connection or heatsink provision for {node.ref}",
                affected_components=(node.ref,),
            ))

        return violations


class GroundRule(DesignRule):
    """GROUND_01: Audio circuits should use star ground topology.

    Checks that circuits with multiple ground nets (GND, GNDA, AGND, etc.)
    have those nets connected through components (star ground point).

    Algorithm:
    1. Find all ground nets from edges
    2. If multiple ground nets, check if any component bridges them
    3. Unconnected ground pairs -> WARNING
    """

    name = "GROUND_01"
    category = RuleCategory.GROUND
    default_severity = RuleSeverity.WARNING
    description = "Audio circuits should use star ground topology"

    def check(self, topology: Any, config: dict[str, Any] | None = None) -> list[DesignRuleViolation]:
        violations: list[DesignRuleViolation] = []

        # Collect ground nets from edges
        ground_nets: set[str] = set()
        for edge in topology.edges:
            if _is_ground_net(edge.net_name):
                ground_nets.add(edge.net_name)

        if len(ground_nets) <= 1:
            return violations

        # Check if ground nets connect through any component
        node_nets = _build_node_to_nets(topology)
        connected_pairs: set[tuple[str, str]] = set()

        for node in topology.nodes:
            comp_nets = set(node_nets.get(node.ref, []))
            gnd_in_comp = comp_nets & ground_nets
            if len(gnd_in_comp) >= 2:
                # This component bridges two ground nets
                for a in gnd_in_comp:
                    for b in gnd_in_comp:
                        if a != b:
                            connected_pairs.add(tuple(sorted((a, b))))

        # Any unconnected ground pairs?
        all_pairs = {
            tuple(sorted((a, b)))
            for a in ground_nets for b in ground_nets if a != b
        }
        unconnected = all_pairs - connected_pairs

        for pair in sorted(unconnected):
            violations.append(DesignRuleViolation(
                rule_id=self.name,
                description=f"Ground nets {pair[0]} and {pair[1]} are not connected "
                            f"-- consider star ground topology",
                severity=self.default_severity,
                location=f"{pair[0]} / {pair[1]}",
                suggestion=f"Connect {pair[0]} and {pair[1]} at a single star ground point "
                           f"to avoid ground loops",
            ))

        return violations


class PowerFilterRule(DesignRule):
    """POWER_01: Power supply filtering should be adequate for IC current draw.

    Checks that power rails have capacitors for filtering.

    Algorithm:
    1. Find all power nets
    2. For each power net, check if any capacitor is on it
    3. No cap -> WARNING
    """

    name = "POWER_01"
    category = RuleCategory.POWER
    default_severity = RuleSeverity.WARNING
    description = "Power supply filtering should be adequate for IC current draw"

    def check(self, topology: Any, config: dict[str, Any] | None = None) -> list[DesignRuleViolation]:
        violations: list[DesignRuleViolation] = []

        net_to_nodes = _build_net_to_nodes(topology)

        # Check power_nets from topology
        for power_net in topology.power_nets:
            # Skip ground nets
            if _is_ground_net(power_net):
                continue

            nodes_on_net = net_to_nodes.get(power_net, [])
            has_cap = any(_is_cap(n.lib_id) for n in nodes_on_net)

            if not has_cap:
                affected = tuple(n.ref for n in nodes_on_net)
                violations.append(DesignRuleViolation(
                    rule_id=self.name,
                    description=f"Power net {power_net} has no decoupling capacitor",
                    severity=self.default_severity,
                    location=power_net,
                    suggestion=f"Add 10uF electrolytic capacitor on {power_net} "
                               f"for bulk decoupling, plus 100nF ceramic per IC",
                    affected_components=affected,
                ))

        return violations


class InputProtectionRule(DesignRule):
    """SIGNAL_01: Input nets should have protection components.

    Flags externally-connected input nets that don't have series resistors,
    clamp diodes, or other protection.

    Algorithm:
    1. Find input nets from topology
    2. Check if input nets have series resistor or diode
    3. No protection -> SUGGESTION
    """

    name = "SIGNAL_01"
    category = RuleCategory.SIGNAL
    default_severity = RuleSeverity.SUGGESTION
    description = "Input nets should have protection components"

    def check(self, topology: Any, config: dict[str, Any] | None = None) -> list[DesignRuleViolation]:
        violations: list[DesignRuleViolation] = []
        net_to_nodes = _build_net_to_nodes(topology)

        for input_net in topology.input_nets:
            nodes_on_input = net_to_nodes.get(input_net, [])

            has_protection = False
            has_ic = False

            for node in nodes_on_input:
                if node.component_type == "ic":
                    has_ic = True
                if _is_resistor(node.lib_id) or _is_diode(node.lib_id):
                    has_protection = True

            if has_ic and not has_protection:
                affected = tuple(n.ref for n in nodes_on_input if n.component_type == "ic")
                violations.append(DesignRuleViolation(
                    rule_id=self.name,
                    description=f"Input net {input_net} connects directly to IC "
                                f"without series resistor or ESD protection",
                    severity=self.default_severity,
                    location=input_net,
                    suggestion=f"Consider adding ESD protection diode or series resistor "
                               f"on {input_net} to protect against overvoltage",
                    affected_components=affected,
                ))

        return violations


class LayoutRule(DesignRule):
    """LAYOUT_01: Critical signal paths should minimize via count.

    Flags signal nets with many connected components (>5 by default) that
    may have routing complexity issues. Informational only -- actual
    via count requires PCB data.

    Severity: INFO.
    """

    name = "LAYOUT_01"
    category = RuleCategory.LAYOUT
    default_severity = RuleSeverity.INFO
    description = "Critical signal paths should minimize via count"

    def check(self, topology: Any, config: dict[str, Any] | None = None) -> list[DesignRuleViolation]:
        config = config or {}
        max_components = config.get("max_components_per_net", 5)
        violations: list[DesignRuleViolation] = []

        net_to_nodes = _build_net_to_nodes(topology)

        for net_name, nodes_on_net in net_to_nodes.items():
            if net_name in topology.power_nets or _is_power_net(net_name):
                continue
            if _is_ground_net(net_name):
                continue

            if len(nodes_on_net) > max_components:
                affected = tuple(n.ref for n in nodes_on_net)
                violations.append(DesignRuleViolation(
                    rule_id=self.name,
                    description=f"Net {net_name} has {len(nodes_on_net)} connections "
                                f"(threshold: {max_components}) -- verify routing quality",
                    severity=self.default_severity,
                    location=net_name,
                    suggestion=f"Review routing of {net_name} -- high fan-out may need "
                               f"buffering or star routing",
                    affected_components=affected,
                ))

        return violations


# ---------------------------------------------------------------------------
# Factory
# ---------------------------------------------------------------------------


def get_builtin_rules() -> list[DesignRule]:
    """Return all built-in design rules."""
    return [
        BypassCapRule(),
        FeedbackCompRule(),
        ImpedanceRule(),
        ThermalRule(),
        GroundRule(),
        PowerFilterRule(),
        InputProtectionRule(),
        LayoutRule(),
    ]
