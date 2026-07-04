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
