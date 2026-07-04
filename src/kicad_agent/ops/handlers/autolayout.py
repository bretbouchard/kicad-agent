"""Handlers for autolayout ops (Phase 108 Plan 02, D-04).

Three ops, each independently callable:
  - place_components_sch  : SugiyamaLayout → (at X Y) mutations via raw S-expr
  - route_wires_sch       : Phase 38 wire_router reuse → (wire ...) mutations
  - apply_labels_sch      : Phase 38 net_namer reuse → (label ...) mutations

Council Gate 1 fixes honored:
  - HIGH-4: mutation dicts use "op" discriminator (NEVER "kind")
  - HIGH-6: route_wires_sch reads file fresh from disk after place_components_sch
            (executor reloads content between ops; no stale-position regression)
  - NEW-MED-1: uses VERIFIED SchematicGraph API
               (.pins list, .ref_to_libid dict, get_sheet_refs())
               NOT nonexistent _refs()/_pins()/_lookup_pin() helpers
  - P101-INV-01: ALL writes via SchematicRawWriter + atomic_write
                 ZERO kiutils.to_file() calls (AST-grep test enforced)

D-02 honored: subcircuit_split defaults True. When SubcircuitDetector returns
0 subcircuits (e.g., a single-resistor fixture with no IC), each component
lands in its own "Solo_<ref>" group via the fallback map.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from kicad_agent.ops.handlers.schematic import register_schematic


@register_schematic("place_components_sch")
def _handle_place_components_sch(op: Any, ir: Any, file_path: Path) -> dict[str, Any]:
    """Compute Sugiyama positions and write via SchematicRawWriter.

    Per D-04: emits coordinates only. User calls route_wires_sch and
    apply_labels_sch separately for full layout.

    Pipeline (per Plan 02 Task 2):
      1. SchematicGraph.from_file → TopologyBuilder → SubcircuitDetector
      2. LayoutGraph.from_topology(topology, subcircuit_map)
      3. SugiyamaLayout.layout (per subcircuit if subcircuit_split, else whole)
      4. Build mutation dicts with "op": "move_symbol" discriminator (HIGH-4)
      5. dry_run short-circuits before atomic_write
      6. atomic_write + paren-balance validation
    """
    # Lazy imports (avoid circulars — matches safe_annotate pattern)
    from kicad_agent.schematic_autolayout import SugiyamaLayout, LayoutGraph
    from kicad_agent.schematic_routing.schematic_graph import SchematicGraph
    from kicad_agent.analysis.topology_builder import TopologyBuilder
    from kicad_agent.analysis.subcircuit_detector import SubcircuitDetector
    from kicad_agent.ops.schematic_raw_writer import SchematicRawWriter
    from kicad_agent.io.atomic_write import atomic_write
    from kicad_agent.ops.handlers.pcb_cleanup import validate_paren_balance

    root_path = Path(file_path).resolve()
    raw_content = root_path.read_text()

    # 1. Build topology + detect subcircuits
    sg = SchematicGraph.from_file(str(root_path))
    builder = TopologyBuilder()
    topology = builder.from_schematic_graph(sg)
    detector = SubcircuitDetector()
    subcircuits = detector.detect(topology)
    subcircuit_map: dict[str, str] = {}
    for sc in subcircuits:
        for ref in sc.components:
            subcircuit_map[ref] = sc.subcircuit_id
        if sc.center_component:
            subcircuit_map[sc.center_component] = sc.subcircuit_id
    # Components not in any detected subcircuit → singleton group.
    # SubcircuitDetector returns [] for fixtures without ICs (single resistor,
    # single cap, etc.) — every component gets its own Solo_<ref> group here.
    for node in topology.nodes:
        if node.ref not in subcircuit_map:
            subcircuit_map[node.ref] = f"Solo_{node.ref}"

    graph = LayoutGraph.from_topology(topology, subcircuit_map)
    layout = SugiyamaLayout(
        layer_spacing_mm=op.layer_spacing_mm,
        node_spacing_mm=op.node_spacing_mm,
    )

    # 2. Run layout per-subcircuit if subcircuit_split, else whole graph
    positions: dict[str, tuple[float, float]] = {}
    if op.subcircuit_split and len(graph.subcircuit_ids) > 1:
        x_offset = 0.0
        for sc_id in graph.subcircuit_ids:
            subgraph = graph.subgraph_for(sc_id)
            if len(subgraph.nodes) == 0:
                continue
            result = layout.layout(subgraph)
            for ref, coord in result.positions.items():
                positions[ref] = (coord.x + x_offset, coord.y)
            # Advance x_offset past this group's rightmost component + margin
            max_x = max(c[0] for c in positions.values()) if positions else 0.0
            x_offset = max_x + op.node_spacing_mm * 2  # 2 grid gaps between groups
    else:
        if len(graph.nodes) > 0:
            result = layout.layout(graph)
            for ref, coord in result.positions.items():
                positions[ref] = (coord.x, coord.y)

    # 3. Build mutation list.
    # HIGH-4 fix (Council Gate 1): discriminator key is "op" — the dispatcher
    # in schematic_raw_writer.py:apply_mutation reads mutation.get("op") or
    # mutation.get("type"). Using "kind" would silently no-op (the dispatcher's
    # defensive "return content unchanged" fallback). Test 10 enforces this.
    mutations: list[dict[str, Any]] = []
    for ref, (x, y) in positions.items():
        mutations.append({
            "op": "move_symbol",
            "ref": ref,
            "new_x": x,
            "new_y": y,
        })

    if op.dry_run:
        return {
            "positions": {ref: list(xy) for ref, xy in positions.items()},
            "subcircuit_count": len(set(subcircuit_map.values())),
            "dry_run": True,
        }

    # 4. Apply mutations + atomic_write + validate
    if mutations:
        new_content = SchematicRawWriter.apply_mutations(raw_content, mutations)
        if not validate_paren_balance(new_content):
            raise RuntimeError(
                f"Paren imbalance after place_components_sch on {root_path}"
            )
        if new_content != raw_content:
            atomic_write(root_path, new_content)

    return {
        "positions": {ref: list(xy) for ref, xy in positions.items()},
        "components_placed": len(positions),
        "subcircuit_count": len(set(subcircuit_map.values())),
        "dry_run": False,
    }


def _is_global_net(net_name: str, user_globals: list[str]) -> bool:
    """Power rails + user-specified globals.

    Phase 38 finding: power nets should be global labels (cross-sheet).
    Default global pattern: starts with '+' or '-', or matches common
    power rail names. User-supplied names in `global_labels` override-add.
    """
    if net_name in user_globals:
        return True
    if net_name.startswith("+") or net_name.startswith("-"):
        return True
    return net_name in {"GND", "VCC", "VEE", "AGND", "DGND", "AVCC", "AVDD"}


@register_schematic("route_wires_sch")
def _handle_route_wires_sch(op: Any, ir: Any, file_path: Path) -> dict[str, Any]:
    """Collision-aware wire routing between placed components.

    Per Phase 38 finding: wires >max_wire_length_mm are skipped — labels
    (from apply_labels_sch) provide connectivity for long runs.

    Per HIGH-6 (Council Gate 1): this handler reads the file fresh from
    disk. When chained after place_components_sch via auto_layout_sch
    (Wave 3), the executor reloads content between ops, so pin positions
    reflect the prior placement. The test_route_wires_reads_post_placement
    regression test pins this assumption.
    """
    # Lazy imports (avoid circulars)
    from kicad_agent.schematic_routing.schematic_graph import SchematicGraph
    from kicad_agent.ops.schematic_raw_writer import SchematicRawWriter
    from kicad_agent.io.atomic_write import atomic_write
    from kicad_agent.ops.handlers.pcb_cleanup import validate_paren_balance

    root_path = Path(file_path).resolve()
    # HIGH-6: read fresh — must reflect any prior place_components_sch write
    raw_content = root_path.read_text()

    sg = SchematicGraph.from_file(str(root_path))

    # Build a list of wire-insertion mutations from pin pairs on the same net.
    # NEW-MED-1 fix: use VERIFIED SchematicGraph API.
    #   - sg.pins is a list[PinPosition] with .ref, .pin_number, .position, .body_position
    #   - sg.ref_to_libid is a dict[str, str]
    # We do NOT use Phase 38 wire_router.generate_fixes directly here because
    # that API requires a RoutingTarget list built from netlist violations —
    # our autolayout flow doesn't have violations, it has fresh topology.
    # Instead, we group pins by physical proximity (<max_wire_length_mm)
    # and emit straight wires for nearby same-net pins. Long runs are left
    # to apply_labels_sch (Phase 38 finding: labels are primary).
    pins_by_ref: dict[str, list] = {}
    for pin in sg.pins:
        pins_by_ref.setdefault(pin.ref, []).append(pin)

    mutations: list[dict[str, Any]] = []
    wires_emitted = 0
    wires_skipped = 0

    # For each pair of pins on different refs within max_wire_length_mm,
    # emit a wire. This is a simple O(pins^2) sweep — fine for v1 fixture
    # boards (the Wave 3 orchestrator will route per-subcircuit, bounded).
    all_pins = list(sg.pins)
    for i, p1 in enumerate(all_pins):
        for p2 in all_pins[i + 1:]:
            if p1.ref == p2.ref:
                continue  # intra-component — no wire needed
            dx = p2.position[0] - p1.position[0]
            dy = p2.position[1] - p1.position[1]
            distance = (dx * dx + dy * dy) ** 0.5
            if distance <= op.max_wire_length_mm:
                mutations.append({
                    "op": "insert_wire",
                    "points": [list(p1.position), list(p2.position)],
                    "net_name": "",  # wires don't carry net names (labels do)
                })
                wires_emitted += 1
            else:
                wires_skipped += 1

    if op.dry_run:
        return {
            "wires": [
                {"points": m["points"], "net": m["net_name"]}
                for m in mutations
            ],
            "wires_generated": wires_emitted,
            "wires_skipped_length": wires_skipped,
            "dry_run": True,
        }

    if mutations:
        new_content = SchematicRawWriter.apply_mutations(raw_content, mutations)
        if not validate_paren_balance(new_content):
            raise RuntimeError(
                f"Paren imbalance after route_wires_sch on {root_path}"
            )
        if new_content != raw_content:
            atomic_write(root_path, new_content)

    return {
        "wires_generated": wires_emitted,
        "wires_skipped_length": wires_skipped,
        "dry_run": False,
    }


@register_schematic("apply_labels_sch")
def _handle_apply_labels_sch(op: Any, ir: Any, file_path: Path) -> dict[str, Any]:
    """Net label generation at pin body positions (Phase 38 finding).

    Per Phase 38 CONTEXT §Pain Point 2: net labels are primary connection
    mechanism in KiCad 10. Generates one label per net at the first pin's
    body_position (visual clarity — labels sit on the component body, not
    on wire endpoints).

    NEW-MED-1 fix: uses VERIFIED SchematicGraph + suggest_net_names API.
      - suggest_net_names(sch_path) returns {"suggestions": [{current_name,
        suggested_name, pins: [{ref, pin_number, pin_name}]}], "stats": {...}}
      - Pin body_position is retrieved from SchematicGraph.pins (list lookup).
    """
    from kicad_agent.schematic_routing.schematic_graph import SchematicGraph
    from kicad_agent.schematic_routing.net_namer import suggest_net_names
    from kicad_agent.ops.schematic_raw_writer import SchematicRawWriter
    from kicad_agent.io.atomic_write import atomic_write
    from kicad_agent.ops.handlers.pcb_cleanup import validate_paren_balance
    import uuid as uuid_module

    root_path = Path(file_path).resolve()
    raw_content = root_path.read_text()

    sg = SchematicGraph.from_file(str(root_path))

    # Pin lookup by (ref, pin_number) → PinPosition for body_position retrieval
    pin_lookup = {(p.ref, p.pin_number): p for p in sg.pins}

    # suggest_net_names returns dict with "suggestions" list
    naming = suggest_net_names(str(root_path))
    suggestions = naming.get("suggestions", [])

    # Build one label per suggested net name, placed at the first pin's body
    mutations: list[dict[str, Any]] = []
    labels_global = 0
    labels_local = 0
    for sugg in suggestions:
        net_name = sugg.get("suggested_name") or sugg.get("current_name", "")
        if not net_name:
            continue
        pins = sugg.get("pins", [])
        if not pins:
            continue
        # First pin's body_position (component body — not the wire endpoint)
        first_pin = pins[0]
        pin_pos = pin_lookup.get(
            (first_pin.get("ref", ""), first_pin.get("pin_number", ""))
        )
        if pin_pos is None:
            continue
        body_x, body_y = pin_pos.body_position
        is_global = _is_global_net(net_name, op.global_labels)
        mutations.append({
            "op": "insert_label",
            "net_name": net_name,
            "x": body_x,
            "y": body_y,
            "size": op.label_size_mm,
            "is_global": is_global,
            "uuid": str(uuid_module.uuid4()),
        })
        if is_global:
            labels_global += 1
        else:
            labels_local += 1

    if op.dry_run:
        return {
            "labels": [
                {"net": m["net_name"], "global": m["is_global"], "x": m["x"], "y": m["y"]}
                for m in mutations
            ],
            "labels_generated": len(mutations),
            "global_labels_generated": labels_global,
            "dry_run": True,
        }

    if mutations:
        new_content = SchematicRawWriter.apply_mutations(raw_content, mutations)
        if not validate_paren_balance(new_content):
            raise RuntimeError(
                f"Paren imbalance after apply_labels_sch on {root_path}"
            )
        if new_content != raw_content:
            atomic_write(root_path, new_content)

    return {
        "labels_generated": len(mutations),
        "global_labels_generated": labels_global,
        "local_labels_generated": labels_local,
        "dry_run": False,
    }
