"""Design review engine -- identifies improvement opportunities in schematics.

DOMAIN-03: Template-based design review combining inferred intent with
circuit topology to produce actionable findings.

Review categories:
  - missing_bypass_caps: IC power pins without decoupling capacitors
  - feedback_compensation: Op-amp feedback loops without compensation caps
  - power_decoupling: Power rails without adequate filtering
  - signal_integrity: Input/output protection, impedance matching
  - component_value_optimization: Suboptimal component values
  - thermal: Power components without thermal consideration

All suggestions are template-based (no LLM needed).

Security:
  T-47-05: findings list capped at 200 per review (DoS prevention).
  T-47-06: suggestion text max 1000 chars.

Usage:
    from kicad_agent.analysis.design_review import DesignReviewer

    reviewer = DesignReviewer()
    review = reviewer.review(topology, intent=result.intent)
    for finding in review.findings:
        print(f"[{finding.severity}] {finding.category}: {finding.description}")
"""
from __future__ import annotations

import logging
from collections.abc import Callable
from enum import Enum

from pydantic import BaseModel, Field, field_validator

from kicad_agent.analysis.intent_schemas import DesignGoal, DesignIntent
from kicad_agent.analysis.topology_graph import CircuitTopology, TopologyNode

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Schemas
# ---------------------------------------------------------------------------


class ReviewSeverity(str, Enum):
    """Finding severity levels."""

    INFO = "INFO"  # Nice to know, optional improvement
    SUGGESTION = "SUGGESTION"  # Recommended improvement
    WARNING = "WARNING"  # Could cause issues, should fix
    CRITICAL = "CRITICAL"  # Will cause problems, must fix


class ReviewCategory(str, Enum):
    """Finding category for grouping and filtering."""

    MISSING_BYPASS_CAPS = "missing_bypass_caps"
    FEEDBACK_COMPENSATION = "feedback_compensation"
    POWER_DECOUPLING = "power_decoupling"
    SIGNAL_INTEGRITY = "signal_integrity"
    COMPONENT_VALUE_OPTIMIZATION = "component_value_optimization"
    THERMAL = "thermal"


class DesignFinding(BaseModel):
    """A single design review finding.

    Attributes:
        category: Review category.
        severity: Finding severity level.
        description: What was found and why it matters.
        location: Where in the schematic (component ref or net name).
        suggestion: Concrete improvement recommendation.
        affected_components: Component refs involved in this finding.
    """

    category: ReviewCategory
    severity: ReviewSeverity
    description: str = Field(min_length=1, max_length=2000)
    location: str = Field(min_length=1, max_length=512)
    suggestion: str = Field(default="", max_length=1000)
    affected_components: tuple[str, ...] = Field(default_factory=tuple)

    @field_validator("description")
    @classmethod
    def _description_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("description must not be empty or whitespace")
        return v


class DesignReview(BaseModel):
    """Complete design review result.

    Attributes:
        findings: List of design findings.
        schematic_path: Path to the reviewed schematic.
        summary: Auto-computed severity counts.
    """

    findings: tuple[DesignFinding, ...] = Field(default_factory=tuple, max_length=200)
    schematic_path: str = Field(default="")
    summary: dict[str, int] = Field(default_factory=dict)

    def model_post_init(self, __context) -> None:
        """Compute summary from findings."""
        counts = {s.value: 0 for s in ReviewSeverity}
        for f in self.findings:
            counts[f.severity.value] += 1
        self.summary = counts


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------

_IC_LIB_PATTERNS = (
    "NE5532", "TL072", "LM358", "THAT4301", "CD4066", "CD4060",
    "RP2040", "PT2399", "LM7812", "LM7912", "LM7805", "OP07",
    "OPA2134", "RC4558", "JRC4558", "BA6110", "LM13700",
)

_OPAMP_LIB_PATTERNS = (
    "NE5532", "TL072", "LM358", "OP07", "OPA2134", "RC4558",
    "JRC4558", "BA6110", "LM13700",
)

_CAP_LIB_PATTERNS = ("Device:C", "Device:C_Small", "Device:CP", "Device:CP_Small")

_POWER_NET_PREFIXES = (
    "+9V", "-9V", "+12V", "-12V", "+15V", "-15V",
    "+3V3", "+5V", "-5V", "GNDA",
)

def _find_ics(topology: CircuitTopology) -> list[TopologyNode]:
    """Find all IC components in topology."""
    return [
        n for n in topology.nodes
        if any(pat.upper() in n.lib_id.upper() for pat in _IC_LIB_PATTERNS)
    ]


def _find_opamps(topology: CircuitTopology) -> list[TopologyNode]:
    """Find all op-amp components in topology."""
    return [
        n for n in topology.nodes
        if any(pat.upper() in n.lib_id.upper() for pat in _OPAMP_LIB_PATTERNS)
    ]


def _is_capacitor(node: TopologyNode) -> bool:
    """Check if a node is a capacitor."""
    return any(pat in node.lib_id for pat in _CAP_LIB_PATTERNS)


def _is_resistor(node: TopologyNode) -> bool:
    """Check if a node is a resistor."""
    return node.lib_id.startswith("Device:R")


def _is_diode(node: TopologyNode) -> bool:
    """Check if a node is a diode."""
    return node.lib_id.startswith("Device:D") or node.lib_id.startswith("Device:LED")


def _build_net_to_nodes(topology: CircuitTopology) -> dict[str, list[TopologyNode]]:
    """Build a mapping from net name to connected nodes.

    Uses topology edges to determine which nodes share nets.
    """
    net_map: dict[str, list[TopologyNode]] = {}
    node_map = {n.ref: n for n in topology.nodes}

    for edge in topology.edges:
        # Add source node to net
        src_node = node_map.get(edge.source_ref)
        if src_node:
            net_map.setdefault(edge.net_name, [])
            if src_node not in net_map[edge.net_name]:
                net_map[edge.net_name].append(src_node)
        # Add target node to net
        tgt_node = node_map.get(edge.target_ref)
        if tgt_node:
            net_map.setdefault(edge.net_name, [])
            if tgt_node not in net_map[edge.net_name]:
                net_map[edge.net_name].append(tgt_node)

    return net_map


def _build_node_to_nets(topology: CircuitTopology) -> dict[str, list[str]]:
    """Build a mapping from node ref to connected net names."""
    node_nets: dict[str, list[str]] = {}
    for edge in topology.edges:
        node_nets.setdefault(edge.source_ref, [])
        if edge.net_name not in node_nets[edge.source_ref]:
            node_nets[edge.source_ref].append(edge.net_name)
        node_nets.setdefault(edge.target_ref, [])
        if edge.net_name not in node_nets[edge.target_ref]:
            node_nets[edge.target_ref].append(edge.net_name)
    return node_nets


def _has_cap_on_power_net(
    ic: TopologyNode,
    topology: CircuitTopology,
    net_to_nodes: dict[str, list[TopologyNode]] | None = None,
    node_nets: dict[str, list[str]] | None = None,
) -> bool:
    """Check if any capacitor shares a power net with the IC."""
    net_to_nodes = net_to_nodes or _build_net_to_nodes(topology)
    node_nets = node_nets or _build_node_to_nets(topology)

    # Get nets connected to the IC
    ic_nets = node_nets.get(ic.ref, [])

    # Check power nets
    for net_name in ic_nets:
        # Is this a power net?
        is_power = (
            net_name in topology.power_nets
            or any(net_name.upper().startswith(p.upper()) for p in ("+9V", "-9V", "+12V", "-12V", "+15V", "-15V", "+3V3", "+5V", "-5V"))
            or "GND" in net_name.upper()
        )
        if not is_power:
            continue

        # Check if any capacitor is on this same net
        nodes_on_net = net_to_nodes.get(net_name, [])
        for node in nodes_on_net:
            if _is_capacitor(node) and node.ref != ic.ref:
                return True
    return False


def _has_feedback_cap(
    opamp: TopologyNode,
    topology: CircuitTopology,
    net_to_nodes: dict[str, list[TopologyNode]] | None = None,
    node_nets: dict[str, list[str]] | None = None,
) -> bool:
    """Check if an op-amp has a capacitor in its feedback path.

    Feedback path: inverting input (-) and output (OUT) share a net
    through a resistor, and there is a capacitor bridging the same nets.
    """
    node_nets = node_nets or _build_node_to_nets(topology)
    net_to_nodes = net_to_nodes or _build_net_to_nodes(topology)

    # Find feedback edges: edges with signal_direction="feedback"
    # that involve this op-amp
    opamp_nets = set(node_nets.get(opamp.ref, []))

    # Look for capacitor that shares two nets with the op-amp
    # (i.e. cap is in parallel with the feedback resistor)
    for node in topology.nodes:
        if not _is_capacitor(node):
            continue
        cap_nets = set(node_nets.get(node.ref, []))
        # Cap shares nets with opamp
        shared_nets = cap_nets & opamp_nets
        if len(shared_nets) >= 2:
            return True

    return False


def _has_feedback_path(
    opamp: TopologyNode,
    topology: CircuitTopology,
    net_to_nodes: dict[str, list[TopologyNode]] | None = None,
    node_nets: dict[str, list[str]] | None = None,
) -> bool:
    """Check if an op-amp has a feedback path (resistor from output to inverting input)."""
    node_nets = node_nets or _build_node_to_nets(topology)
    net_to_nodes = net_to_nodes or _build_net_to_nodes(topology)

    opamp_nets = set(node_nets.get(opamp.ref, []))

    # Look for a resistor that shares nets with the op-amp
    for node in topology.nodes:
        if not _is_resistor(node):
            continue
        res_nets = set(node_nets.get(node.ref, []))
        shared = res_nets & opamp_nets
        # Resistor is in feedback if it connects to at least 2 of the opamp's nets
        if len(shared) >= 2:
            return True

    # Also check for feedback edges involving this opamp
    for edge in topology.edges:
        if edge.signal_direction == "feedback":
            if edge.source_ref == opamp.ref or edge.target_ref == opamp.ref:
                return True

    return False


# ---------------------------------------------------------------------------
# Review checks (each is a callable)
# ---------------------------------------------------------------------------


def _check_bypass_caps(
    topology: CircuitTopology,
    intent: DesignIntent | None,
) -> list[DesignFinding]:
    """Check for missing bypass/decoupling capacitors on IC power pins.

    Algorithm:
    1. Find all ICs (lib_id matches known IC patterns)
    2. For each IC, check if any capacitor shares power nets
    3. If no cap found -> WARNING for general ICs, CRITICAL for audio processing ICs

    Severity logic:
    - CRITICAL if intent is AUDIO_PROCESSING and IC is in signal chain
    - WARNING otherwise
    """
    findings: list[DesignFinding] = []
    net_to_nodes = _build_net_to_nodes(topology)
    node_nets = _build_node_to_nets(topology)
    ics = _find_ics(topology)

    for ic in ics:
        # Only flag ICs that have power pins
        if not ic.power_pins:
            continue

        if _has_cap_on_power_net(ic, topology, net_to_nodes, node_nets):
            continue

        is_audio = intent and DesignGoal.AUDIO_PROCESSING in intent.design_goals
        severity = ReviewSeverity.CRITICAL if is_audio else ReviewSeverity.WARNING

        power_pin_str = ", ".join(ic.power_pins)
        findings.append(DesignFinding(
            category=ReviewCategory.MISSING_BYPASS_CAPS,
            severity=severity,
            description=f"{ic.ref} ({ic.lib_id}) has power pins ({power_pin_str}) "
                        f"but no bypass capacitor found on connected power nets",
            location=ic.ref,
            suggestion=f"Add 100nF ceramic capacitor between power and GND "
                       f"near {ic.ref}, placed within 5mm",
            affected_components=(ic.ref,),
        ))

    return findings


def _check_feedback_compensation(
    topology: CircuitTopology,
    intent: DesignIntent | None,
) -> list[DesignFinding]:
    """Check op-amp feedback loops for compensation capacitors.

    Algorithm:
    1. Find all op-amps
    2. For each op-amp, check if there is a feedback path
    3. If feedback exists, check if a cap is in the feedback path
    4. No cap -> SUGGESTION to add compensation
    """
    findings: list[DesignFinding] = []
    net_to_nodes = _build_net_to_nodes(topology)
    node_nets = _build_node_to_nets(topology)
    opamps = _find_opamps(topology)

    for opamp in opamps:
        if not _has_feedback_path(opamp, topology, net_to_nodes, node_nets):
            continue

        if _has_feedback_cap(opamp, topology, net_to_nodes, node_nets):
            continue

        findings.append(DesignFinding(
            category=ReviewCategory.FEEDBACK_COMPENSATION,
            severity=ReviewSeverity.SUGGESTION,
            description=f"{opamp.ref} ({opamp.lib_id}) has feedback network "
                        f"but no compensation capacitor in feedback path",
            location=opamp.ref,
            suggestion=f"Add 10-22pF compensation capacitor across feedback resistor "
                       f"on {opamp.ref} to prevent oscillation",
            affected_components=(opamp.ref,),
        ))

    return findings


def _check_power_decoupling(
    topology: CircuitTopology,
    intent: DesignIntent | None,
) -> list[DesignFinding]:
    """Check power rails for adequate filtering.

    Algorithm:
    1. For each power net in topology, check if any capacitor is on it
    2. If power net has no capacitor -> WARNING
    """
    findings: list[DesignFinding] = []
    net_to_nodes = _build_net_to_nodes(topology)

    for power_net in topology.power_nets:
        # Skip ground nets
        if "GND" in power_net.upper():
            continue

        nodes_on_net = net_to_nodes.get(power_net, [])
        has_cap = any(_is_capacitor(n) for n in nodes_on_net)

        if not has_cap:
            findings.append(DesignFinding(
                category=ReviewCategory.POWER_DECOUPLING,
                severity=ReviewSeverity.WARNING,
                description=f"Power rail {power_net} has no decoupling capacitor",
                location=power_net,
                suggestion=f"Add 10uF electrolytic capacitor on {power_net} "
                           f"for bulk decoupling, plus 100nF ceramic per IC",
                affected_components=(),
            ))

    return findings


def _check_input_protection(
    topology: CircuitTopology,
    intent: DesignIntent | None,
) -> list[DesignFinding]:
    """Check externally-connected nets for input protection.

    Algorithm:
    1. Find input nets from topology
    2. Check if input nets have series resistor or clamp diodes between
       the external source and the IC
    3. No protection -> SUGGESTION
    """
    findings: list[DesignFinding] = []
    node_nets = _build_node_to_nets(topology)

    for input_net in topology.input_nets:
        # Find all nodes on this input net
        nodes_on_input = []
        for node in topology.nodes:
            if input_net in node_nets.get(node.ref, []):
                nodes_on_input.append(node)

        # Check if there's a series resistor or diode between the external
        # connector and any IC on this net
        has_protection = False
        has_ic = False

        for node in nodes_on_input:
            if node.component_type == "ic":
                has_ic = True
            if _is_resistor(node) or _is_diode(node):
                has_protection = True

        if has_ic and not has_protection:
            findings.append(DesignFinding(
                category=ReviewCategory.SIGNAL_INTEGRITY,
                severity=ReviewSeverity.SUGGESTION,
                description=f"Input net {input_net} connects directly to IC "
                            f"without series resistor or ESD protection",
                location=input_net,
                suggestion=f"Consider adding ESD protection diode or series resistor "
                           f"on {input_net} to protect against overvoltage",
                affected_components=tuple(
                    n.ref for n in nodes_on_input if n.component_type == "ic"
                ),
            ))

    return findings


def _check_component_values(
    topology: CircuitTopology,
    intent: DesignIntent | None,
) -> list[DesignFinding]:
    """Check for suboptimal component values in signal path.

    Note: Value information is not available in TopologyNode (only ref, lib_id,
    component_type, pin_count, pins). This check is a placeholder that does
    surface-level checks based on topology structure. Future integration with
    the schematic parser could provide actual component values.
    """
    # No value data in TopologyNode -- skip for now.
    # This check is available for future extension when values are accessible.
    return []


# ---------------------------------------------------------------------------
# Default check list
# ---------------------------------------------------------------------------

_DEFAULT_CHECKS: list[Callable[
    [CircuitTopology, DesignIntent | None],
    list[DesignFinding],
]] = [
    _check_bypass_caps,
    _check_feedback_compensation,
    _check_power_decoupling,
    _check_input_protection,
    # _check_component_values excluded: TopologyNode lacks value data.
    # Available for future integration when component values are accessible.
]


# ---------------------------------------------------------------------------
# DesignReviewer
# ---------------------------------------------------------------------------


class DesignReviewer:
    """Rule-based design review engine.

    Applies a series of review checks to a circuit topology, optionally
    informed by inferred design intent. All checks are deterministic
    and template-based (no LLM calls).

    Usage:
        reviewer = DesignReviewer()
        review = reviewer.review(topology, intent=result.intent)
    """

    def __init__(
        self,
        checks: list[Callable[[CircuitTopology, DesignIntent | None], list[DesignFinding]]] | None = None,
    ):
        """Initialize with optional custom checks.

        Args:
            checks: List of check callables. Each takes (topology, intent)
                    and returns a list of DesignFinding. Defaults to all checks.
        """
        self._checks = checks or _DEFAULT_CHECKS

    def review(
        self,
        topology: CircuitTopology,
        intent: DesignIntent | None = None,
    ) -> DesignReview:
        """Run all enabled checks against the circuit topology.

        Algorithm:
        1. For each check, evaluate against topology + intent
        2. Collect all findings
        3. Sort by severity (CRITICAL first)
        4. Return DesignReview with findings and summary

        Args:
            topology: CircuitTopology to review.
            intent: Optional DesignIntent for context-aware review.

        Returns:
            DesignReview with findings sorted by severity.
        """
        findings: list[DesignFinding] = []
        for check in self._checks:
            findings.extend(check(topology, intent))

        # Sort: CRITICAL > WARNING > SUGGESTION > INFO
        severity_order = {
            ReviewSeverity.CRITICAL: 0,
            ReviewSeverity.WARNING: 1,
            ReviewSeverity.SUGGESTION: 2,
            ReviewSeverity.INFO: 3,
        }
        findings.sort(key=lambda f: severity_order[f.severity])

        return DesignReview(
            findings=tuple(findings),
            schematic_path=getattr(topology, "schematic_path", ""),
        )
