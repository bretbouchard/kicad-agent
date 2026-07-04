"""Phase 156 Wave 4: Hierarchical sheet flattener.

Recursively flattens hierarchical sub-sheets into one flat circuit.
SKIDL has no native hierarchy — everything is a flat netlist. Sheet pins
↔ sub-sheet labels must connect to the same Net.

Uses the proven extract_nets path which already resolves hierarchical
connectivity via the net extractor's union-find over wire segments.
"""
from __future__ import annotations

import logging
from pathlib import Path

from kicad_agent.circuit_ir.types import (
    CircuitIR,
    NetDescriptor,
    PartDescriptor,
    PinRef,
)

logger = logging.getLogger(__name__)


def flatten_hierarchy(
    root_sch_path: Path | str,
) -> tuple[list[PartDescriptor], list[NetDescriptor], list[str]]:
    """Flatten a hierarchical schematic into flat parts + nets.

    Delegates to extract_nets which already handles hierarchical sheets
    via the KiCad netlist resolution (sheet pins ↔ hierarchical labels).
    This function wraps it with the PartDescriptor/NetDescriptor types.

    Args:
        root_sch_path: Path to the root .kicad_sch file.

    Returns:
        Tuple of (parts, nets, diagnostics).
    """
    from kicad_agent.circuit_ir.skidl_circuit import _extract_components
    from kicad_agent.schematic_routing.net_extractor import extract_nets

    root_sch_path = Path(root_sch_path)
    content = root_sch_path.read_text(encoding="utf-8")

    # Extract all components (handles all sheets via the flat content).
    components = _extract_components(content)

    # Separate power and real parts.
    parts: list[PartDescriptor] = []
    power_net_names: set[str] = set()

    for comp in components:
        if comp.is_power:
            power_net_names.add(comp.value)
        else:
            # Tag with root sheet.
            parts.append(PartDescriptor(
                lib_id=comp.lib_id,
                reference=comp.reference,
                value=comp.value,
                footprint=comp.footprint,
                unit=comp.unit,
                is_power=False,
                pins=comp.pins,
                sheet=str(root_sch_path.parent),
            ))

    # Extract nets — extract_nets handles hierarchy via netlist resolution.
    nets_result = extract_nets(root_sch_path, include_positions=False)
    nets_data = nets_result.get("nets", {})

    diagnostics: list[str] = []

    net_descriptors: list[NetDescriptor] = []
    for net_name, pins in nets_data.items():
        is_power = net_name in power_net_names or _is_power_name(net_name)
        pin_refs = tuple(
            PinRef(
                reference=p.get("ref", ""),
                pin_number=str(p.get("pin_number", "")),
                pin_name=p.get("pin_name", ""),
            )
            for p in pins
        )
        net_descriptors.append(NetDescriptor(
            name=net_name,
            pins=pin_refs,
            is_power=is_power,
        ))

    logger.info(
        "Flattened %s: %d parts, %d nets",
        root_sch_path.name, len(parts), len(net_descriptors),
    )

    return parts, net_descriptors, diagnostics


def flatten_to_circuit_ir(
    root_sch_path: Path | str,
) -> CircuitIR:
    """Flatten a hierarchical schematic directly to a CircuitIR.

    Convenience function — calls flatten_hierarchy and wraps in CircuitIR.
    """
    parts, nets, diagnostics = flatten_hierarchy(root_sch_path)
    return CircuitIR(
        parts=tuple(parts),
        nets=tuple(nets),
        diagnostics=tuple(diagnostics),
        source_file=str(root_sch_path),
    )


def _is_power_name(name: str) -> bool:
    """Check if a net name looks like a power rail."""
    power_patterns = (
        "GND", "VCC", "VDD", "VSS", "VEE", "+3V3", "+5V",
        "+12V", "-12V", "+1V8", "+9V", "AVDD", "AVCC", "AGND",
        "DGND", "GNDA", "GNDD", "VBUS", "VBAT",
    )
    name_upper = name.upper()
    return (
        name_upper in {p.upper() for p in power_patterns}
        or name.startswith("+")
        or name.startswith("-")
    )
