"""Native ERC engine — pure Python, no kicad-cli dependency.

Implements the core Electrical Rules Check (ERC) checks that KiCad's C++
engine performs, but entirely in Python using the parsed schematic graph
and circuit topology.

This module replaces kicad-cli's `sch erc` command for App Store sandboxed
builds where external process execution is blocked.

Checks implemented:
    1. Pin-type conflict detection (11x11 compatibility matrix)
    2. Power net validation (unconnected power pins)
    3. No-connect validation (missing/incorrect NC flags)
    4. Dangling wires

Usage::

    from kicad_agent.validation.native_erc import run_native_erc, NativeErcResult

    result = run_native_erc(Path("board.kicad_sch"))
    if result.error_count > 0:
        for v in result.violations:
            print(f"{v.severity}: {v.description}")
"""

from __future__ import annotations

import logging
import re
from collections import defaultdict
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class ERCSeverity(str, Enum):
    """ERC violation severity matching KiCad's levels."""
    ERROR = "error"
    WARNING = "warning"
    INFO = "info"
    EXCLUSION = "exclusion"


@dataclass(frozen=True)
class ERCViolation:
    """A single ERC violation."""
    severity: ERCSeverity
    check_id: str
    description: str
    ref: str = ""
    pin: str = ""
    net: str = ""
    position: tuple[float, float] | None = None

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {
            "severity": self.severity.value,
            "check_id": self.check_id,
            "description": self.description,
        }
        if self.ref: d["ref"] = self.ref
        if self.pin: d["pin"] = self.pin
        if self.net: d["net"] = self.net
        if self.position: d["position"] = list(self.position)
        return d


@dataclass(frozen=True)
class NativeErcResult:
    """Result of running native ERC checks."""
    violations: tuple[ERCViolation, ...] = ()
    checks_run: tuple[str, ...] = ()
    checks_skipped: tuple[str, ...] = ()

    @property
    def error_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == ERCSeverity.ERROR)

    @property
    def warning_count(self) -> int:
        return sum(1 for v in self.violations if v.severity == ERCSeverity.WARNING)

    @property
    def passed(self) -> bool:
        return self.error_count == 0

    def to_dict(self) -> dict[str, Any]:
        return {
            "clean": self.passed,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "violations": [v.to_dict() for v in self.violations],
            "checks_run": list(self.checks_run),
            "checks_skipped": list(self.checks_skipped),
        }


# ============================================================================
# Check 1: Pin-Type Conflict Detection
# ============================================================================

_PIN_TYPE_ORDER = [
    "input", "output", "bidirectional", "tri_state", "passive",
    "unspecified", "power_input", "power_output", "open_collector",
    "open_emitter", "free",
]

# KiCad ERC electrical rules matrix (default configuration).
# Values: "ok" = compatible, "err" = error, "warn" = warning.
# Transcribed from KiCad's publicly documented ERC matrix.
_PIN_COMPAT_MATRIX: dict[str, dict[str, str]] = {
    "input":          {"input": "ok",   "output": "ok",   "bidirectional": "ok",   "tri_state": "ok",   "passive": "ok", "unspecified": "warn", "power_input": "ok",   "power_output": "ok",   "open_collector": "ok",   "open_emitter": "ok",   "free": "warn"},
    "output":         {"input": "ok",   "output": "err",  "bidirectional": "warn", "tri_state": "err",  "passive": "ok", "unspecified": "warn", "power_input": "err",  "power_output": "err",  "open_collector": "warn","open_emitter": "warn","free": "warn"},
    "bidirectional":  {"input": "ok",   "output": "warn", "bidirectional": "warn", "tri_state": "warn", "passive": "ok", "unspecified": "warn", "power_input": "warn", "power_output": "warn", "open_collector": "warn","open_emitter": "warn","free": "warn"},
    "tri_state":      {"input": "ok",   "output": "err",  "bidirectional": "warn", "tri_state": "err",  "passive": "ok", "unspecified": "warn", "power_input": "err",  "power_output": "err",  "open_collector": "warn","open_emitter": "warn","free": "warn"},
    "passive":        {"input": "ok",   "output": "ok",   "bidirectional": "ok",   "tri_state": "ok",   "passive": "ok", "unspecified": "warn", "power_input": "ok",   "power_output": "ok",   "open_collector": "ok",   "open_emitter": "ok",   "free": "warn"},
    "unspecified":    {"input": "warn", "output": "warn", "bidirectional": "warn", "tri_state": "warn", "passive": "warn","unspecified": "warn", "power_input": "warn", "power_output": "warn", "open_collector": "warn","open_emitter": "warn","free": "warn"},
    "power_input":    {"input": "ok",   "output": "err",  "bidirectional": "warn", "tri_state": "err",  "passive": "ok", "unspecified": "warn", "power_input": "ok",   "power_output": "err",  "open_collector": "ok",   "open_emitter": "ok",   "free": "warn"},
    "power_output":   {"input": "ok",   "output": "err",  "bidirectional": "warn", "tri_state": "err",  "passive": "ok", "unspecified": "warn", "power_input": "err",  "power_output": "warn", "open_collector": "ok",   "open_emitter": "ok",   "free": "warn"},
    "open_collector": {"input": "ok",   "output": "warn", "bidirectional": "warn", "tri_state": "warn", "passive": "ok", "unspecified": "warn", "power_input": "ok",   "power_output": "ok",   "open_collector": "warn","open_emitter": "warn","free": "warn"},
    "open_emitter":   {"input": "ok",   "output": "warn", "bidirectional": "warn", "tri_state": "warn", "passive": "ok", "unspecified": "warn", "power_input": "ok",   "power_output": "ok",   "open_collector": "warn","open_emitter": "warn","free": "warn"},
    "free":           {"input": "warn", "output": "warn", "bidirectional": "warn", "tri_state": "warn", "passive": "warn","unspecified": "warn", "power_input": "warn", "power_output": "warn", "open_collector": "warn","open_emitter": "warn","free": "warn"},
}


def _normalize_pin_type(raw: str) -> str:
    """Normalize KiCad pin type strings to canonical form."""
    t = raw.lower().strip()
    aliases = {
        "power_in": "power_input",
        "power_out": "power_output",
        "opencollector": "open_collector",
        "openemitter": "open_emitter",
        "tristate": "tri_state",
        "no_connect": "passive",
    }
    return aliases.get(t, t)


def check_pin_type_conflicts(
    pins: list, pin_nets: dict[tuple[str, str], str]
) -> list[ERCViolation]:
    """Check 1: Detect pin-type conflicts on shared nets."""
    violations: list[ERCViolation] = []
    net_pins: dict[str, list] = defaultdict(list)

    for pin in pins:
        net = pin_nets.get((pin.ref, pin.pin_number))
        if net is None: continue
        net_pins[net].append(pin)

    for net, pins_on_net in net_pins.items():
        if len(pins_on_net) < 2: continue
        for i in range(len(pins_on_net)):
            for j in range(i + 1, len(pins_on_net)):
                pa, pb = pins_on_net[i], pins_on_net[j]
                ta = _normalize_pin_type(pa.electrical_type)
                tb = _normalize_pin_type(pb.electrical_type)
                compat = _PIN_COMPAT_MATRIX.get(ta, {}).get(tb, "warn")
                if compat == "ok": continue
                sev = ERCSeverity.ERROR if compat == "err" else ERCSeverity.WARNING
                violations.append(ERCViolation(
                    severity=sev, check_id="ERC_PIN_CONFLICT",
                    description=(
                        f"Pin type conflict: {pa.ref}.{pa.pin_number} ({ta}) "
                        f"connected to {pb.ref}.{pb.pin_number} ({tb}) on net '{net}'"
                    ),
                    ref=f"{pa.ref}/{pb.ref}",
                    pin=f"{pa.pin_number}/{pb.pin_number}", net=net,
                    position=pa.position,
                ))
    return violations


# ============================================================================
# Check 2: Power Net Validation
# ============================================================================

_POWER_NAMES = {"VCC", "GND", "VDD", "VSS", "VEE", "AGND", "DGND", "PGND", "Earth"}
_VOLTAGE_RE = re.compile(r"^[+V]\d|[-+]\d+\s*V|_?\d+[Vv]\d?", re.IGNORECASE)


def _is_power_net(net_name: str) -> bool:
    """Check if a net name looks like a power net."""
    upper = net_name.upper()
    if upper in _POWER_NAMES: return True
    if any(upper.startswith(p) for p in ("+", "V", "PWR")):
        if _VOLTAGE_RE.search(upper): return True
    return False


def check_power_nets(
    pins: list, pin_nets: dict[tuple[str, str], str]
) -> list[ERCViolation]:
    """Check 2: Verify power nets have at least one power_output driver."""
    violations: list[ERCViolation] = []
    net_pins: dict[str, list] = defaultdict(list)

    for pin in pins:
        net = pin_nets.get((pin.ref, pin.pin_number))
        if net is None: continue
        net_pins[net].append(pin)

    for net, pins_on_net in net_pins.items():
        if not _is_power_net(net): continue
        has_driver = any(
            _normalize_pin_type(p.electrical_type) == "power_output"
            for p in pins_on_net
        )
        has_power_input = any(
            _normalize_pin_type(p.electrical_type) == "power_input"
            for p in pins_on_net
        )
        if has_power_input and not has_driver:
            violations.append(ERCViolation(
                severity=ERCSeverity.WARNING,
                check_id="ERC_POWER_NOT_DRIVEN",
                description=(
                    f"Power net '{net}' has power_input pins but no power_output driver. "
                    f"Add a power symbol (VCC, GND) or regulator output."
                ),
                net=net,
            ))
    return violations


# ============================================================================
# Check 3: No-Connect Validation
# ============================================================================


def check_no_connects(
    graph, pin_nets: dict[tuple[str, str], str]
) -> list[ERCViolation]:
    """Check 3: Validate no-connect flags on pins."""
    violations: list[ERCViolation] = []
    nc_positions: set[tuple[float, float]] = set()
    for nc_pos in graph.no_connects:
        nc_positions.add((round(nc_pos[0], 2), round(nc_pos[1], 2)))

    for pin in graph.pins:
        if pin.ref.startswith("#"): continue
        pin_pos = (round(pin.position[0], 2), round(pin.position[1], 2))
        is_connected = pin_nets.get((pin.ref, pin.pin_number)) is not None
        has_nc = pin_pos in nc_positions

        if is_connected and has_nc:
            violations.append(ERCViolation(
                severity=ERCSeverity.WARNING, check_id="ERC_NC_CONNECTED",
                description=f"Pin {pin.ref}.{pin.pin_number} has NC flag but is connected",
                ref=pin.ref, pin=pin.pin_number, position=pin.position,
            ))
        elif not is_connected and not has_nc:
            ptype = _normalize_pin_type(pin.electrical_type)
            if ptype in ("passive", "free", "unspecified"): continue
            violations.append(ERCViolation(
                severity=ERCSeverity.ERROR, check_id="ERC_UNCONNECTED_PIN",
                description=(
                    f"Pin {pin.ref}.{pin.pin_number} ({ptype}) is not connected. "
                    f"Add a wire or no-connect flag."
                ),
                ref=pin.ref, pin=pin.pin_number, position=pin.position,
            ))
    return violations


# ============================================================================
# Check 4: Dangling Wires
# ============================================================================


def check_dangling_wires(graph) -> list[ERCViolation]:
    """Check 4: Detect wire endpoints that don't connect to anything."""
    violations: list[ERCViolation] = []
    connection_points: set[tuple[float, float]] = set()

    for pin in graph.pins:
        connection_points.add((round(pin.position[0], 2), round(pin.position[1], 2)))
    for label in graph.labels:
        connection_points.add((round(label.position[0], 2), round(label.position[1], 2)))

    wire_endpoints: dict[tuple[float, float], int] = defaultdict(int)
    for wire in graph.wires:
        s = (round(wire.start[0], 2), round(wire.start[1], 2))
        e = (round(wire.end[0], 2), round(wire.end[1], 2))
        wire_endpoints[s] += 1
        wire_endpoints[e] += 1

    for wire in graph.wires:
        for endpoint in [wire.start, wire.end]:
            pos = (round(endpoint[0], 2), round(endpoint[1], 2))
            if pos in connection_points: continue
            if wire_endpoints.get(pos, 0) >= 2: continue
            violations.append(ERCViolation(
                severity=ERCSeverity.WARNING, check_id="ERC_WIRE_DANGLING",
                description=f"Wire endpoint at ({pos[0]:.2f}, {pos[1]:.2f}) not connected",
                position=pos,
            ))
    return violations


# ============================================================================
# Main Entry Point
# ============================================================================


def run_native_erc(schematic_path: Path) -> NativeErcResult:
    """Run all native ERC checks on a schematic file.

    Pure Python — no kicad-cli dependency.
    """
    checks_run: list[str] = []
    checks_skipped: list[str] = []
    all_violations: list[ERCViolation] = []

    try:
        from kicad_agent.analysis.topology_builder import TopologyBuilder
        from kicad_agent.schematic_routing.schematic_graph import SchematicGraph
    except ImportError:
        logger.error("Cannot import topology/graph modules")
        return NativeErcResult(checks_skipped=("all",))

    try:
        graph = SchematicGraph.from_file(schematic_path)
        checks_run.append("schematic_graph")

        builder = TopologyBuilder()
        pin_nets = builder._resolve_pin_nets(graph)
        checks_run.append("topology_resolution")
    except Exception as e:
        logger.error(f"Failed to parse schematic: {e}")
        return NativeErcResult(
            violations=(ERCViolation(
                severity=ERCSeverity.ERROR, check_id="ERC_PARSE_ERROR",
                description=f"Failed to parse schematic: {e}",
            ),),
            checks_skipped=("pin_conflicts", "power_nets", "no_connects", "dangling_wires"),
        )

    all_pins = list(graph.pins)

    for check_name, check_fn, args in [
        ("pin_type_conflicts", check_pin_type_conflicts, (all_pins, pin_nets)),
        ("power_net_validation", check_power_nets, (all_pins, pin_nets)),
        ("no_connect_validation", check_no_connects, (graph, pin_nets)),
        ("dangling_wires", check_dangling_wires, (graph,)),
    ]:
        try:
            all_violations.extend(check_fn(*args))
            checks_run.append(check_name)
        except Exception as e:
            logger.warning(f"{check_name} failed: {e}")
            checks_skipped.append(check_name)

    return NativeErcResult(
        violations=tuple(all_violations),
        checks_run=tuple(checks_run),
        checks_skipped=tuple(checks_skipped),
    )
