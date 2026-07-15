"""Net label tracer -- trace per-label pin connectivity through schematic graph.

When two nets are shorted, the netlist merges them and per-label pin data is lost.
This operation uses schematic graph traversal (union-find over wire/pin/label positions)
with label-boundary heuristics to assign pins to their nearest label.

Usage:
    from volta.ops.net_tracer import trace_net_from_label

    result = trace_net_from_label(Path("board.kicad_sch"), label_name="GNDA")
    for pin in result["reachable_pins"]:
        print(f"  {pin['ref']}.{pin['pin_number']} at ({pin['position'][0]}, {pin['position'][1]})")
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from volta.schematic_routing.net_extractor import (
    _build_union_find_components,
    _resolve_net_names,
)
from volta.schematic_routing.schematic_graph import (
    Label,
    PinPosition,
    SchematicGraph,
    _round_pos,
)

logger = __import__("logging").getLogger(__name__)


# ---------------------------------------------------------------------------
# Empty result helper
# ---------------------------------------------------------------------------

def _empty_trace_result(label_name: str) -> dict[str, Any]:
    """Return the canonical empty trace result."""
    return {
        "label": label_name,
        "reachable_pins": [],
        "pin_count": 0,
        "refs": [],
        "sheets": [],
        "domain": "unknown",
        "blocked_by": [],
        "far_pins": [],
        "far_pin_count": 0,
    }


def _merge_trace_results(results: list[dict[str, Any]]) -> dict[str, Any]:
    """Merge trace results from multiple sheets into one.

    Deduplicates pins by (ref, pin_number). Unions refs, far_pins,
    blocked_by, and sheets. Re-classifies domain on merged pin set.
    """
    if not results:
        return _empty_trace_result("")
    if len(results) == 1:
        return results[0]

    merged = _empty_trace_result(results[0]["label"])
    seen_pins: set[tuple[str, str]] = set()

    for r in results:
        for p in r.get("reachable_pins", []):
            key = (p["ref"], p["pin_number"])
            if key not in seen_pins:
                seen_pins.add(key)
                merged["reachable_pins"].append(p)
        for p in r.get("far_pins", []):
            key = (p["ref"], p["pin_number"])
            if key not in seen_pins:
                seen_pins.add(key)
                merged["far_pins"].append(p)
        for name in r.get("blocked_by", []):
            if name not in merged["blocked_by"]:
                merged["blocked_by"].append(name)
        merged["sheets"].extend(r.get("sheets", []))

    merged["pin_count"] = len(merged["reachable_pins"])
    merged["refs"] = sorted({p["ref"] for p in merged["reachable_pins"]})

    pin_set = {(p["ref"], p["pin_number"]) for p in merged["reachable_pins"]}
    if pin_set:
        from volta.ops.ground_topology import _classify_ground_domain
        merged["domain"] = _classify_ground_domain(merged["label"], pin_set)

    merged["far_pin_count"] = len(merged["far_pins"])
    return merged


def _trace_single_graph(
    graph: SchematicGraph,
    *,
    label_name: str,
    label_type: str = "all",
    stop_at_labels: bool = True,
    sheet_name: str = "",
) -> dict[str, Any]:
    """Trace pins reachable from a label within a single SchematicGraph.

    This is the core tracing logic, extracted so it can be called per-sheet
    in hierarchical designs and results merged.
    """
    uf, all_positions, pin_pos_map, label_pos_map = _build_union_find_components(graph)

    # Find all positions in the component containing our target label
    target_positions: set[tuple[float, float]] = set()
    for pos, label in label_pos_map.items():
        if label.name == label_name:
            if label_type != "all" and label.label_type != label_type:
                continue
            root = uf.find(pos)
            for p in all_positions:
                if uf.find(p) == root:
                    target_positions.add(p)

    if not target_positions:
        return _empty_trace_result(label_name)

    # Supplement: labels placed at pin body positions (not wire-ends) are
    # orphaned in the tight union-find. Scan pin body positions within
    # KiCad grid tolerance and add matching pins to the result.
    _KICAD_GRID_MM = 2.54
    has_pins = any(pos in pin_pos_map for pos in target_positions)
    if not has_pins:
        # Snapshot positions to avoid mutation during iteration
        label_positions_snapshot = list(target_positions)
        for label_pos in label_positions_snapshot:
            for pin in graph.pins:
                bp = pin.body_position
                dist = ((label_pos[0] - bp[0]) ** 2 + (label_pos[1] - bp[1]) ** 2) ** 0.5
                if dist <= _KICAD_GRID_MM:
                    # Add this pin's wire-end position to the target set
                    wp = _round_pos(pin.position)
                    target_positions.add(wp)

    # Find all label names in this component
    blocked_labels: list[str] = []
    for pos, label in label_pos_map.items():
        if pos in target_positions and label.name != label_name:
            if label.name not in blocked_labels:
                blocked_labels.append(label.name)

    if stop_at_labels and len(blocked_labels) > 0:
        label_pins, assign_far_pins = _assign_pins_to_labels(
            pin_pos_map, label_pos_map, target_positions,
            target_label=label_name,
            label_type_filter=label_type,
        )
        pins = label_pins.get(label_name, [])
        far_pins = list(assign_far_pins)
        for other_label, other_pins in label_pins.items():
            if other_label != label_name:
                far_pins.extend(other_pins)
    else:
        pins = []
        for pos, pin_list in pin_pos_map.items():
            if pos in target_positions:
                for pin in pin_list:
                    pins.append({
                        "ref": pin.ref,
                        "pin_number": pin.pin_number,
                        "pin_name": pin.pin_name,
                        "position": [pin.position[0], pin.position[1]],
                        "electrical_type": pin.electrical_type,
                    })
        far_pins = []

    refs = sorted({p["ref"] for p in pins})

    from volta.ops.ground_topology import _classify_ground_domain
    pin_set = {(p["ref"], p["pin_number"]) for p in pins}
    domain = _classify_ground_domain(label_name, pin_set) if pins else "unknown"

    return {
        "label": label_name,
        "reachable_pins": pins,
        "pin_count": len(pins),
        "refs": refs,
        "sheets": [sheet_name] if sheet_name else [],
        "domain": domain,
        "blocked_by": blocked_labels,
        "far_pins": far_pins,
        "far_pin_count": len(far_pins),
    }

# Maximum distance (mm) from a pin to the nearest label before we consider
# it "far" and don't assign it. 25.4mm = 1 inch. In a well-designed schematic,
# pins are physically close to the label that names their net.
_MAX_LABEL_DISTANCE_MM = 25.4


# ---------------------------------------------------------------------------
# Pin-to-label assignment
# ---------------------------------------------------------------------------

def _assign_pins_to_labels(
    pin_pos_map: dict[tuple[float, float], list[PinPosition]],
    label_pos_map: dict[tuple[float, float], Label],
    component_positions: set[tuple[float, float]],
    target_label: str,
    label_type_filter: str = "all",
) -> tuple[dict[str, list[dict[str, Any]]], list[dict[str, Any]]]:
    """Assign pins to labels based on nearest-label proximity.

    For each pin position in the union-find component, find the nearest
    named label and assign the pin to that label. This allows per-label
    pin tracing even when labels are shorted together.

    Args:
        pin_pos_map: Rounded position -> list of PinPosition objects.
        label_pos_map: Rounded position -> Label objects.
        component_positions: All positions in the union-find component.
        target_label: Label name to trace.
        label_type_filter: "label", "global", "hierarchical", or "all".

    Returns:
        Tuple of (label_pins dict, far_pins list).
    """
    # Filter labels by type
    labels_in_component: list[tuple[tuple[float, float], Label]] = []
    for pos, label in label_pos_map.items():
        if pos not in component_positions:
            continue
        if label_type_filter != "all" and label.label_type != label_type_filter:
            continue
        labels_in_component.append((pos, label))

    if not labels_in_component:
        return {}, []

    # Collect all pin positions in this component
    pin_entries: list[tuple[tuple[float, float], PinPosition]] = []
    for pos, pins in pin_pos_map.items():
        if pos in component_positions:
            for pin in pins:
                pin_entries.append((pos, pin))

    # Assign each pin to its nearest label
    label_pins: dict[str, list[dict[str, Any]]] = {}
    far_pins: list[dict[str, Any]] = []

    for pos, pin in pin_entries:
        nearest_label: str | None = None
        nearest_dist: float = float("inf")

        for label_pos, label in labels_in_component:
            dx = pos[0] - label_pos[0]
            dy = pos[1] - label_pos[1]
            dist = math.sqrt(dx * dx + dy * dy)
            if dist < nearest_dist:
                nearest_dist = dist
                nearest_label = label.name

        pin_dict = {
            "ref": pin.ref,
            "pin_number": pin.pin_number,
            "pin_name": pin.pin_name,
            "position": [pin.position[0], pin.position[1]],
            "electrical_type": pin.electrical_type,
            "nearest_label": nearest_label,
            "nearest_distance": round(nearest_dist, 2),
        }

        if nearest_label is not None and nearest_dist <= _MAX_LABEL_DISTANCE_MM:
            label_pins.setdefault(nearest_label, []).append(pin_dict)
        else:
            far_pins.append(pin_dict)

    return label_pins, far_pins


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def trace_net_from_label(
    sch_path: Path,
    *,
    label_name: str,
    label_type: str = "all",
    stop_at_labels: bool = True,
) -> dict[str, Any]:
    """Trace all pins reachable from a label through the schematic graph.

    Uses union-find over wire/pin/label positions to build connectivity,
    then assigns pins to labels by proximity. When labels are shorted,
    each pin is assigned to its nearest label, enabling independent
    per-label analysis.

    For hierarchical schematics, traces the label in each sub-sheet
    independently and merges results. Global labels with the same name
    across sheets are electrically connected.

    Args:
        sch_path: Path to a .kicad_sch file.
        label_name: Label text to trace.
        label_type: Filter by label type: "label", "global", "hierarchical", "all".
        stop_at_labels: If True, assign pins by nearest-label proximity
            (default). If False, return all pins in the union-find component.

    Returns:
        Dict with reachable pins, pin count, refs, domain, and blocked labels.
    """
    # Try hierarchical parsing
    try:
        from volta.schematic_routing.schematic_graph import (
            HierarchicalSchematic,
        )
        hier = SchematicGraph.from_hierarchy(sch_path)
    except Exception:
        hier = None

    if hier and hier.sheet_refs:
        # Multi-sheet: trace in root + each child, merge results
        results: list[dict[str, Any]] = []
        results.append(_trace_single_graph(
            hier.graph, label_name=label_name, label_type=label_type,
            stop_at_labels=stop_at_labels, sheet_name="root",
        ))
        for child in hier.children:
            sheet_name = Path(child.filepath).stem
            results.append(_trace_single_graph(
                child.graph, label_name=label_name, label_type=label_type,
                stop_at_labels=stop_at_labels, sheet_name=sheet_name,
            ))
        return _merge_trace_results(results)

    # Single-sheet fallback (unchanged behavior)
    return _trace_single_graph(
        SchematicGraph.from_file(str(sch_path)),
        label_name=label_name,
        label_type=label_type,
        stop_at_labels=stop_at_labels,
    )
