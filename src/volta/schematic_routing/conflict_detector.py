"""Detect net naming conflicts in a .kicad_sch file without running ERC.

Runs four independent checks on a schematic:
  1. Shorted nets -- two different-named labels at the same position (error)
  2. Case variants -- same net name with different case (e.g. VCC vs vcc) (warning)
  3. Mixed label types -- same name used as both global and local (warning)
  4. Unlabeled junctions -- junction with 3+ wire endpoints and no label (warning)

Each check can be enabled/disabled via boolean flags. Returns a structured
conflict list with severity, positions, descriptions, and the conflicting items.

Usage:
    from volta.schematic_routing.conflict_detector import detect_net_conflicts

    result = detect_net_conflicts(sch_path="board.kicad_sch")
    # result = {"conflicts": [...], "stats": {"total_conflicts", "errors", "warnings"}}
"""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any

from volta.schematic_routing.schematic_graph import (
    Label,
    SchematicGraph,
    _round_pos,
)


def detect_net_conflicts(
    sch_path: Path | str,
    check_case_variants: bool = True,
    check_mixed_labels: bool = True,
    check_unlabeled_junctions: bool = True,
) -> dict[str, Any]:
    """Detect net naming conflicts in a schematic file.

    Args:
        sch_path: Path to the .kicad_sch file.
        check_case_variants: Detect case-variant net names (default True).
        check_mixed_labels: Detect mixed label types on same net (default True).
        check_unlabeled_junctions: Detect junctions merging unnamed nets (default True).

    Returns:
        Dict with "conflicts" and "stats" keys:
        - conflicts: list of conflict dicts, each with conflict_type, severity,
          description, positions, items.
        - stats: {"total_conflicts", "errors", "warnings"}.
    """
    graph = SchematicGraph.from_file(sch_path)

    conflicts: list[dict[str, Any]] = []

    # Check 1: Shorted nets (always on)
    conflicts.extend(_check_shorted_nets(graph))

    # Check 2: Case variants
    if check_case_variants:
        conflicts.extend(_check_case_variants(graph))

    # Check 3: Mixed label types
    if check_mixed_labels:
        conflicts.extend(_check_mixed_labels(graph))

    # Check 4: Unlabeled junctions
    if check_unlabeled_junctions:
        conflicts.extend(_check_unlabeled_junctions(graph))

    errors = sum(1 for c in conflicts if c["severity"] == "error")
    warnings = sum(1 for c in conflicts if c["severity"] == "warning")

    return {
        "conflicts": conflicts,
        "stats": {
            "total_conflicts": len(conflicts),
            "errors": errors,
            "warnings": warnings,
        },
    }


def _check_shorted_nets(graph: SchematicGraph) -> list[dict[str, Any]]:
    """Detect multiple different-named labels at the same position.

    Two labels with different names sharing a position means the nets
    are shorted at that point -- an error.
    """
    # Group labels by rounded position
    pos_labels: dict[tuple[float, float], list[Label]] = defaultdict(list)
    for label in graph.labels:
        key = _round_pos(label.position)
        pos_labels[key].append(label)

    conflicts: list[dict[str, Any]] = []
    for pos, labels in pos_labels.items():
        # Get unique names at this position
        names_at_pos = {label.name for label in labels}
        if len(names_at_pos) > 1:
            items = [
                {
                    "name": label.name,
                    "label_type": label.label_type,
                    "position": list(label.position),
                }
                for label in labels
            ]
            name_list = ", ".join(sorted(names_at_pos))
            conflicts.append({
                "conflict_type": "shorted_nets",
                "severity": "error",
                "description": f"Labels {name_list} share position ({pos[0]}, {pos[1]})",
                "positions": [list(pos)],
                "items": items,
            })

    return conflicts


def _check_case_variants(graph: SchematicGraph) -> list[dict[str, Any]]:
    """Detect case-variant net names (e.g. VCC vs vcc).

    Groups labels by lowercased name. If a lowercase group has 2+ different
    original names, those labels are case-variant conflicts.
    """
    # Group by lowercased name -> original names
    lower_to_labels: dict[str, list[Label]] = defaultdict(list)
    for label in graph.labels:
        lower_to_labels[label.name.lower()].append(label)

    conflicts: list[dict[str, Any]] = []
    for lower_name, labels in lower_to_labels.items():
        # Get distinct original names (case-sensitive)
        original_names = {label.name for label in labels}
        if len(original_names) > 1:
            items = [
                {
                    "name": label.name,
                    "label_type": label.label_type,
                    "position": list(label.position),
                }
                for label in labels
            ]
            positions = [list(label.position) for label in labels]
            name_list = ", ".join(sorted(original_names))
            conflicts.append({
                "conflict_type": "case_variant",
                "severity": "warning",
                "description": f"Case-variant net names: {name_list}",
                "positions": positions,
                "items": items,
            })

    return conflicts


def _check_mixed_labels(graph: SchematicGraph) -> list[dict[str, Any]]:
    """Detect same net name used with different label types (global + local).

    Groups labels by exact name. If a name has labels with 2+ different
    label_types, that is a mixed_label_types conflict.
    """
    # Group by exact name
    name_to_labels: dict[str, list[Label]] = defaultdict(list)
    for label in graph.labels:
        name_to_labels[label.name].append(label)

    conflicts: list[dict[str, Any]] = []
    for name, labels in name_to_labels.items():
        label_types = {label.label_type for label in labels}
        if len(label_types) > 1:
            items = [
                {
                    "name": label.name,
                    "label_type": label.label_type,
                    "position": list(label.position),
                }
                for label in labels
            ]
            positions = [list(label.position) for label in labels]
            type_list = ", ".join(sorted(label_types))
            conflicts.append({
                "conflict_type": "mixed_label_types",
                "severity": "warning",
                "description": f"Net '{name}' uses mixed label types: {type_list}",
                "positions": positions,
                "items": items,
            })

    return conflicts


def _check_unlabeled_junctions(graph: SchematicGraph) -> list[dict[str, Any]]:
    """Detect junctions connecting 3+ wire endpoints with no label nearby.

    An unlabeled junction that merges multiple wires creates an unnamed net,
    which is ambiguous and can cause connectivity issues.
    """
    # Build a map of how many wire endpoints are at each position
    endpoint_count: dict[tuple[float, float], int] = defaultdict(int)
    for wire in graph.wires:
        start = _round_pos(wire.start)
        end = _round_pos(wire.end)
        endpoint_count[start] += 1
        endpoint_count[end] += 1

    # Build label position set (rounded)
    label_positions: set[tuple[float, float]] = set()
    for label in graph.labels:
        label_positions.add(_round_pos(label.position))

    # Check each junction
    tolerance = 1.27  # mm, same as SchematicGraph proximity matching
    conflicts: list[dict[str, Any]] = []

    for junc in graph.junctions:
        junc_key = _round_pos(junc)

        # Check if any label is within tolerance of this junction
        has_label = junc_key in label_positions
        if not has_label:
            # Check proximity (within tolerance)
            for lp in label_positions:
                dist = ((lp[0] - junc_key[0]) ** 2 + (lp[1] - junc_key[1]) ** 2) ** 0.5
                if dist <= tolerance:
                    has_label = True
                    break

        if has_label:
            continue

        # Count wire endpoints at this junction position
        count = endpoint_count.get(junc_key, 0)

        if count >= 3:
            conflicts.append({
                "conflict_type": "unlabeled_junction",
                "severity": "warning",
                "description": (
                    f"Unlabeled junction at ({junc_key[0]}, {junc_key[1]}) "
                    f"merges {count} wire endpoints"
                ),
                "positions": [list(junc_key)],
                "items": [
                    {
                        "type": "junction",
                        "position": list(junc_key),
                        "wire_endpoint_count": count,
                    }
                ],
            })

    return conflicts
