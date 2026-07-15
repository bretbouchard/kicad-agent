"""Project context renderer for summarizing KiCad project state.

Given any directory containing KiCad files, discovers file types, counts
components and nets, and produces a human-readable summary suitable for
AI context injection.

Threat model mitigations:
- T-07-10: Recursive glob on KiCad projects (typically small directories)
- T-07-11: Parse errors caught and skipped (try/except + logging.warning)
"""

from __future__ import annotations

import logging
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from volta.ir import SchematicIR, PcbIR
from volta.parser import parse_schematic, parse_pcb
from volta.parser.uuid_extractor import extract_uuids

logger = logging.getLogger(__name__)

# KiCad file extensions mapped to their category
_KICAD_GLOB_PATTERNS: dict[str, str] = {
    "schematic_files": "**/*.kicad_sch",
    "pcb_files": "**/*.kicad_pcb",
    "symbol_lib_files": "**/*.kicad_sym",
    "footprint_files": "**/*.kicad_mod",
}


@dataclass(frozen=True)
class ProjectSummary:
    """Immutable snapshot of a KiCad project's file structure with counts.

    Attributes:
        project_dir: Absolute path to the project directory.
        schematic_files: Relative paths to .kicad_sch files.
        pcb_files: Relative paths to .kicad_pcb files.
        symbol_lib_files: Relative paths to .kicad_sym files.
        footprint_files: Relative paths to .kicad_mod files.
        component_count: Total components across all schematics.
        net_count: Total nets across all PCBs.
        footprint_count: Total footprints placed on PCBs.
    """

    project_dir: Path
    schematic_files: tuple[str, ...]
    pcb_files: tuple[str, ...]
    symbol_lib_files: tuple[str, ...]
    footprint_files: tuple[str, ...]
    component_count: int = 0
    net_count: int = 0
    footprint_count: int = 0

    @property
    def has_kicad_files(self) -> bool:
        """True if any KiCad files were found."""
        return self.total_files > 0

    @property
    def total_files(self) -> int:
        """Total count of all KiCad files found."""
        return (
            len(self.schematic_files)
            + len(self.pcb_files)
            + len(self.symbol_lib_files)
            + len(self.footprint_files)
        )


def discover_kicad_files(project_dir: Path) -> ProjectSummary:
    """Discover all KiCad files in a project directory.

    Recursively globs for all four KiCad file extensions and returns
    a ProjectSummary with file lists and zero counts (no enrichment).

    Args:
        project_dir: Path to the directory to scan.

    Returns:
        ProjectSummary with discovered files and zero counts.

    Raises:
        FileNotFoundError: If project_dir does not exist or is not a directory.
    """
    resolved = project_dir.resolve()

    if not resolved.is_dir():
        raise FileNotFoundError(
            f"Path does not exist or is not a directory: {project_dir}"
        )

    file_lists: dict[str, tuple[str, ...]] = {}
    for attr_name, pattern in _KICAD_GLOB_PATTERNS.items():
        found = sorted(resolved.glob(pattern))
        file_lists[attr_name] = tuple(
            str(f.relative_to(resolved)) for f in found
        )

    return ProjectSummary(
        project_dir=resolved,
        schematic_files=file_lists["schematic_files"],
        pcb_files=file_lists["pcb_files"],
        symbol_lib_files=file_lists["symbol_lib_files"],
        footprint_files=file_lists["footprint_files"],
    )


def enrich_summary(summary: ProjectSummary) -> ProjectSummary:
    """Enrich a ProjectSummary with component, net, and footprint counts.

    Parses each schematic and PCB file to extract counts. Files that
    fail to parse are skipped with a warning log.

    Args:
        summary: A ProjectSummary from discover_kicad_files.

    Returns:
        New ProjectSummary with enriched counts.
    """
    component_count = 0
    net_count = 0
    footprint_count = 0

    # Count components from schematics
    for rel_path in summary.schematic_files:
        abs_path = summary.project_dir / rel_path
        try:
            result = parse_schematic(abs_path)
            ir = SchematicIR(_parse_result=result)
            component_count += len(ir.components)
        except Exception as exc:
            logger.warning("Failed to parse schematic %s: %s", rel_path, exc)

    # Count footprints and nets from PCBs
    for rel_path in summary.pcb_files:
        abs_path = summary.project_dir / rel_path
        try:
            result = parse_pcb(abs_path)
            uuid_map = extract_uuids(result.raw_content, "pcb")
            ir = PcbIR(_parse_result=result, _uuid_map=uuid_map)
            footprint_count += len(ir.footprints)
            net_count += len(ir.nets)
        except Exception as exc:
            logger.warning("Failed to parse PCB %s: %s", rel_path, exc)

    return ProjectSummary(
        project_dir=summary.project_dir,
        schematic_files=summary.schematic_files,
        pcb_files=summary.pcb_files,
        symbol_lib_files=summary.symbol_lib_files,
        footprint_files=summary.footprint_files,
        component_count=component_count,
        net_count=net_count,
        footprint_count=footprint_count,
    )


def render_project_context(project_dir: Path, enrich: bool = True) -> str:
    """Render a human-readable summary of a KiCad project directory.

    Discovers KiCad files, optionally enriches with component/net counts,
    and produces formatted text suitable for AI context injection.

    Args:
        project_dir: Path to the directory to summarize.
        enrich: If True, parse files to count components and nets.

    Returns:
        Formatted text summary of the project.
    """
    summary = discover_kicad_files(project_dir)

    if not summary.has_kicad_files:
        return f"No KiCad files found in {project_dir}"

    if enrich:
        summary = enrich_summary(summary)

    lines: list[str] = []
    lines.append(f"KiCad Project: {summary.project_dir.name}")
    lines.append(f"Location: {summary.project_dir}")
    lines.append(
        f"Files: {summary.total_files} total "
        f"({len(summary.schematic_files)} schematics, "
        f"{len(summary.pcb_files)} PCBs, "
        f"{len(summary.symbol_lib_files)} symbol libs, "
        f"{len(summary.footprint_files)} footprint libs)"
    )
    lines.append("")
    lines.append(f"Components: {summary.component_count} across all schematics")
    lines.append(f"Nets: {summary.net_count} across all PCBs")
    lines.append(f"Footprints: {summary.footprint_count} placed on PCBs")
    lines.append("")
    lines.append("Files:")

    if summary.schematic_files:
        lines.append("  Schematics:")
        for f in summary.schematic_files:
            lines.append(f"    - {f}")

    if summary.pcb_files:
        lines.append("  PCBs:")
        for f in summary.pcb_files:
            lines.append(f"    - {f}")

    if summary.symbol_lib_files:
        lines.append("  Symbol Libraries:")
        for f in summary.symbol_lib_files:
            lines.append(f"    - {f}")

    if summary.footprint_files:
        lines.append("  Footprint Libraries:")
        for f in summary.footprint_files:
            lines.append(f"    - {f}")

    return "\n".join(lines)


def render_component_intelligence(project_dir: Path) -> str:
    """Render component-level intelligence for AI context injection.

    Goes beyond file-level stats to provide per-component intelligence:
    pinouts, pin types, net memberships, and connectivity state. This is
    what the pre-analysis gate and callers need to make informed decisions.

    Args:
        project_dir: Path to the project directory.

    Returns:
        Formatted text with component intelligence, or empty string if
        no schematics found.
    """
    summary = discover_kicad_files(project_dir)
    if not summary.schematic_files:
        return ""

    lines: list[str] = ["## Component Intelligence"]

    for rel_path in summary.schematic_files:
        abs_path = summary.project_dir / rel_path
        try:
            result = parse_schematic(abs_path)
            ir = SchematicIR(_parse_result=result)
        except Exception as exc:
            logger.warning("Failed to parse %s: %s", rel_path, exc)
            continue

        lines.append(f"\n### {rel_path}")

        # Component list with pin summaries
        pin_positions = ir.get_pin_positions()
        wire_endpoints = ir.get_wire_endpoints()
        label_positions = ir.get_label_positions()

        # Build set of connected pin positions for fast lookup
        connected_positions: set[tuple[float, float]] = set()
        for we in wire_endpoints:
            connected_positions.add((round(we["start_x"], 2), round(we["start_y"], 2)))
            connected_positions.add((round(we["end_x"], 2), round(we["end_y"], 2)))

        # Group pins by reference
        pins_by_ref: dict[str, list[dict[str, Any]]] = {}
        for pin in pin_positions:
            ref = pin["reference"]
            pins_by_ref.setdefault(ref, []).append(pin)

        # Count pins per electrical type across all components
        pin_type_counts: Counter[str] = Counter()
        for pin in pin_positions:
            pin_type_counts[pin["electrical_type"]] += 1

        # Component summaries
        for sym in ir.components:
            ref = ""
            value = ""
            lib_id = getattr(sym, "libId", "")
            for prop in sym.properties:
                if prop.key == "Reference":
                    ref = prop.value
                elif prop.key == "Value":
                    value = prop.value
            if not ref:
                continue

            pins = pins_by_ref.get(ref, [])
            connected_count = sum(
                1 for p in pins
                if (round(p["x"], 2), round(p["y"], 2)) in connected_positions
            )

            pin_types = Counter(p["electrical_type"] for p in pins)
            type_summary = ", ".join(
                f"{count} {ptype}" for ptype, count in sorted(pin_types.items())
            ) if pins else "no pins"

            lines.append(f"  {ref} ({lib_id})")
            if value:
                lines.append(f"    Value: {value}")
            lines.append(f"    Pins: {len(pins)} total ({type_summary})")
            lines.append(
                f"    Connected: {connected_count}/{len(pins)}"
                if pins else "    Connected: N/A"
            )

            # Show pin details for ICs (more than 4 pins suggests an IC)
            if len(pins) > 4:
                for pin in sorted(pins, key=lambda p: p["pin_number"]):
                    is_connected = (
                        round(pin["x"], 2), round(pin["y"], 2)
                    ) in connected_positions
                    conn_marker = "*" if is_connected else " "
                    lines.append(
                        f"    {conn_marker} Pin {pin['pin_number']}: "
                        f"{pin['pin_name']} ({pin['electrical_type']}) "
                        f"@ ({pin['x']:.1f}, {pin['y']:.1f})"
                    )

        # Net label inventory
        net_labels = [lp for lp in label_positions if lp["label_type"] != "local"]
        if net_labels:
            lines.append("\n  Net Labels:")
            for lp in sorted(net_labels, key=lambda l: l["name"]):
                lines.append(
                    f"    {lp['name']} ({lp['label_type']}) "
                    f"@ ({lp['x']:.1f}, {lp['y']:.1f})"
                )

        # Power nets
        power_nets: list[str] = []
        for sym in ir.components:
            if getattr(sym, "libId", "").startswith("power:"):
                net_name = sym.libId.split(":", 1)[1]
                for prop in sym.properties:
                    if prop.key == "Value":
                        net_name = prop.value
                        break
                power_nets.append(net_name)
        if power_nets:
            lines.append(f"\n  Power Nets: {', '.join(sorted(set(power_nets)))}")

        # Connectivity summary
        total_pins = len(pin_positions)
        total_connected = sum(1 for p in pin_positions if (round(p["x"], 2), round(p["y"], 2)) in connected_positions)
        if total_pins > 0:
            lines.append(
                f"\n  Connectivity: {total_connected}/{total_pins} pins connected "
                f"({100 * total_connected // max(total_pins, 1)}%)"
            )

    return "\n".join(lines)
