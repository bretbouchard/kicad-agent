"""Net label tracer -- trace per-label pin connectivity through schematic graph.

When two nets are shorted, the netlist merges them and per-label pin data is lost.
This operation uses schematic graph traversal (union-find over wire/pin/label positions)
with label-boundary heuristics to assign pins to their nearest label.

Usage:
    from kicad_agent.ops.net_tracer import trace_net_from_label

    result = trace_net_from_label(Path("board.kicad_sch"), label_name="GNDA")
    for pin in result["reachable_pins"]:
        print(f"  {pin['ref']}.{pin['pin_number']} at ({pin['position'][0]}, {pin['position'][1]})")
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import Any

from kicad_agent.schematic_routing.net_extractor import (
    _build_union_find_components,
    _resolve_net_names,
)
from kicad_agent.schematic_routing.schematic_graph import (
    Label,
    PinPosition,
    SchematicGraph,
    _round_pos,
)

logger = __import__("logging").getLogger(__name__)

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

    Args:
        sch_path: Path to a .kicad_sch file.
        label_name: Label text to trace.
        label_type: Filter by label type: "label", "global", "hierarchical", "all".
        stop_at_labels: If True, assign pins by nearest-label proximity
            (default). If False, return all pins in the union-find component.

    Returns:
        Dict with reachable pins, pin count, refs, domain, and blocked labels.
    """
    graph = SchematicGraph.from_file(str(sch_path))

    # Build union-find components
    uf, all_positions, pin_pos_map, label_pos_map = _build_union_find_components(graph)

    # Find all positions in the component containing our target label
    target_positions: set[tuple[float, float]] = set()
    for pos, label in label_pos_map.items():
        if label.name == label_name:
            if label_type != "all" and label.label_type != label_type:
                continue
            # Find the union-find root for this label position
            root = uf.find(pos)
            # Collect all positions in this component
            for p in all_positions:
                if uf.find(p) == root:
                    target_positions.add(p)

    if not target_positions:
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

    # Find all label names in this component
    blocked_labels: list[str] = []
    for pos, label in label_pos_map.items():
        if pos in target_positions and label.name != label_name:
            if label.name not in blocked_labels:
                blocked_labels.append(label.name)

    if stop_at_labels and len(blocked_labels) > 0:
        # Assign pins to nearest label
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
        # Return ALL pins in the component (no label boundary)
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

    # Extract refs and classify domain
    refs = sorted({p["ref"] for p in pins})

    from kicad_agent.ops.ground_topology import _classify_ground_domain
    pin_set = {(p["ref"], p["pin_number"]) for p in pins}
    domain = _classify_ground_domain(label_name, pin_set) if pins else "unknown"

    return {
        "label": label_name,
        "reachable_pins": pins,
        "pin_count": len(pins),
        "refs": refs,
        "domain": domain,
        "blocked_by": blocked_labels,
        "far_pins": far_pins,
        "far_pin_count": len(far_pins),
    }
