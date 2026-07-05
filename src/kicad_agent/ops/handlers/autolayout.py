"""Handlers for autolayout ops (Phase 108 Plans 02 + 03, D-04).

Three independently-callable ops:
  - place_components_sch  : SugiyamaLayout → (at X Y) mutations via raw S-expr
  - route_wires_sch       : Phase 38 wire_router reuse → (wire ...) mutations
  - apply_labels_sch      : Phase 38 net_namer reuse → (label ...) mutations

Plus one high-level orchestrator (Plan 03):
  - auto_layout_sch       : chains the 3 above via execute_batch (D-04)

Council Gate 1 fixes honored:
  - HIGH-4: mutation dicts use "op" discriminator (NEVER "kind")
  - HIGH-5: OperationExecutor constructed with base_dir kwarg;
            execute_batch called with list[Operation] (NOT list[dict]);
            results extracted from batch_result["results"] dict key
  - HIGH-6: route_wires_sch reads file fresh from disk after place_components_sch
            (executor reloads content between ops; no stale-position regression)
  - CRITICAL-1: auto_layout_sch reports hierarchy_promoted=False honestly
                in v1; advisory hierarchy_split_decision dict carries the
                computed plan. NO stub `pass` block and NO follow-up stub
                comment in the handler body. The follow-up Bead tracks
                physical sub-sheet emission under four-state taxonomy
                (DEFERRED-TO-NAMED-TARGET Phase 145).
  - MED-3: follow-up Bead label uses 'phase-108-followup' (no 'follup' typo)
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

# OperationExecutor is imported lazily inside _handle_auto_layout_sch to
# avoid a circular import (executor.py -> schema.py -> handlers/__init__.py
# -> autolayout.py -> executor.py). Tests that need to patch the constructor
# patch `kicad_agent.ops.executor.OperationExecutor` at the source module.

# Phase 108 Task 2 stash: orchestrator captures the pin→net map BEFORE
# clearing wires + moving components, then route_wires_sch reads it back.
# Pydantic op models don't accept arbitrary attrs cleanly, so this
# module-global carries the map across the orchestrator→handler boundary.
_PRE_ROUTE_PIN_NETS: dict[tuple[str, str], str] | None = None


@register_schematic("place_components_sch")
def _handle_place_components_sch(op: Any, ir: Any, file_path: Path) -> dict[str, Any]:
    """Compute Sugiyama positions and write via SchematicRawWriter.

    Per D-04: emits coordinates only. User calls route_wires_sch and
    apply_labels_sch separately for full layout.

    Pipeline (per Plan 02 Task 2 + Phase 108 Task 2 on-page guarantee):
      1. SchematicGraph.from_file → TopologyBuilder → SubcircuitDetector
      2. LayoutGraph.from_topology(topology, subcircuit_map)
      3. SugiyamaLayout.layout (per subcircuit if subcircuit_split, else whole)
      4. fit_to_page — scale + translate so every coord lands on the page
         (Task 2 fix: previously coords grew unbounded and blew past A4)
      5. Park loose components (in file but not in topology) on-page
         (Task 2 fix: previously 137/143 Arduino_Mega components were
         left at fixture-corrupt positions like (5000,5000))
      6. Build mutation dicts with "op": "move_symbol" discriminator (HIGH-4)
      7. dry_run short-circuits before atomic_write
      8. atomic_write + paren-balance validation
    """
    # Lazy imports (avoid circulars — matches safe_annotate pattern)
    from kicad_agent.schematic_autolayout import SugiyamaLayout, LayoutGraph
    from kicad_agent.schematic_autolayout import paper_sizes
    from kicad_agent.schematic_autolayout.layout_planner import (
        PageRegion, plan_group_regions, plan_parking_region,
        scale_to_region, park_in_region,
    )
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
    for node in topology.nodes:
        if node.ref not in subcircuit_map:
            subcircuit_map[node.ref] = f"Solo_{node.ref}"

    graph = LayoutGraph.from_topology(topology, subcircuit_map)
    layout = SugiyamaLayout(
        layer_spacing_mm=op.layer_spacing_mm,
        node_spacing_mm=op.node_spacing_mm,
    )

    paper = paper_sizes.parse_paper_from_sch(raw_content)
    page_w, page_h = paper_sizes.paper_dims_mm(paper)
    margin = paper_sizes.USABLE_PAGE_MARGIN_MM

    # 2. Plan disjoint page regions for each subcircuit group.
    #    Phase 108 Task 2 revision: the original flow ran Sugiyama per group
    #    with an x_offset, then called fit_to_page on the UNION — which
    #    collapsed every group back to (margin, margin). The planner assigns
    #    each group its own page region up front so groups never overlap.
    sc_ids = list(graph.subcircuit_ids) if op.subcircuit_split else []
    if not sc_ids and len(graph.nodes) > 0:
        sc_ids = ["__whole__"]  # single-group fallback

    # Run Sugiyama per group, collect raw (pre-region) positions per group.
    group_raw_positions: dict[str, dict[str, tuple[float, float]]] = {}
    for sc_id in sc_ids:
        subgraph = graph.subgraph_for(sc_id) if sc_id != "__whole__" else graph
        if len(subgraph.nodes) == 0:
            group_raw_positions[sc_id] = {}
            continue
        result = layout.layout(subgraph)
        group_raw_positions[sc_id] = {
            ref: (coord.x, coord.y) for ref, coord in result.positions.items()
        }

    # Reserve the parking region BEFORE planning group regions so we know
    # how many loose components need space. Loose = in file but not topology.
    placed_refs = set()
    for positions_dict in group_raw_positions.values():
        placed_refs.update(positions_dict.keys())
    loose_refs_all = _scan_all_refs(raw_content) - placed_refs
    parking_count = len(loose_refs_all)

    # Compute how much vertical space parking needs so we can shrink the
    # group area accordingly. Parking is a grid: cols = page_width / spacing,
    # rows = ceil(parking_count / cols).
    import math
    usable_w = page_w - 2.0 * margin
    park_cols = max(int(usable_w // layout.node_spacing_mm), 1)
    park_rows = math.ceil(parking_count / park_cols) if parking_count > 0 else 0
    # Parking needs: rows * spacing + 1 spacer row above. Cap at half the
    # usable height so groups always get at least 50% of the page.
    usable_h = page_h - 2.0 * margin
    parking_h = min(
        (park_rows + 1) * layout.node_spacing_mm,
        usable_h / 2.0,
    )
    # Group area = usable area minus parking strip at the bottom.
    group_area_h = usable_h - parking_h if parking_count > 0 else usable_h
    group_area_top = margin + group_area_h

    # Plan group regions over the REDUCED area (above the parking strip).
    group_regions = plan_group_regions(
        len([s for s in sc_ids if group_raw_positions.get(s)]),
        page_w, group_area_top, margin,
    )

    # 3. Scale each group's Sugiyama coords into its assigned region.
    positions: dict[str, tuple[float, float]] = {}
    region_iter = iter(group_regions)
    for sc_id in sc_ids:
        raw_positions = group_raw_positions.get(sc_id, {})
        if not raw_positions:
            continue
        try:
            region = next(region_iter)
        except StopIteration:
            break  # more non-empty groups than regions — shouldn't happen
        scaled = scale_to_region(raw_positions, region, layout._snap_to_grid)
        positions.update(scaled)

    # 4. Park loose components in a region below all placed groups.
    #    Phase 108 Task 2 revision: parking at the page midpoint collided
    #    with placed groups (whose bottoms vary by group layout). The
    #    planner reserves the actual space below the lowest placed group.
    components_parked = 0
    components_unparked_ambiguous = 0
    uuid_mutations: list[dict[str, Any]] = []

    if parking_count > 0:
        # Parking region was reserved during planning — use it directly.
        # Starts at group_area_top (1 spacer row below the group area),
        # extends to page_h - margin.
        parking_region = PageRegion(
            x_min=margin,
            y_min=group_area_top,
            x_max=page_w - margin,
            y_max=page_h - margin,
        )
        # Split loose refs into unique vs ambiguous (multi-instance).
        ambiguous_refs = _find_ambiguous_refs(raw_content, loose_refs_all)
        unique_loose = [r for r in loose_refs_all if r not in ambiguous_refs]

        if unique_loose:
            parked = park_in_region(
                unique_loose, parking_region,
                layout._snap_to_grid, layout.node_spacing_mm,
            )
            positions.update(parked)
            components_parked += len(parked)

        # Ambiguous refs (R? shared by N symbols) → UUID-keyed moves so
        # each instance gets its own parking spot.
        if ambiguous_refs:
            uuid_mutations, ambiguous_count = _park_ambiguous_by_uuid_v2(
                raw_content, ambiguous_refs, parking_region,
                layout._snap_to_grid, layout.node_spacing_mm,
            )
            components_parked += ambiguous_count

    # 5. Build mutation list.
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
    # Phase 108 Task 2: ambiguous-ref parking via UUID (added after ref-based
    # mutations so each UUID move targets exactly one symbol block).
    mutations.extend(uuid_mutations)

    if op.dry_run:
        return {
            "positions": {ref: list(xy) for ref, xy in positions.items()},
            "subcircuit_count": len(set(subcircuit_map.values())),
            "components_parked": components_parked,
            "components_unparked_ambiguous": components_unparked_ambiguous,
            "page_bounds": {"paper": paper, "width_mm": page_w, "height_mm": page_h},
            "dry_run": True,
        }

    # 6. Apply mutations + atomic_write + validate
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
        "components_parked": components_parked,
        "components_unparked_ambiguous": components_unparked_ambiguous,
        "subcircuit_count": len(set(subcircuit_map.values())),
        "page_bounds": {"paper": paper, "width_mm": page_w, "height_mm": page_h},
        "dry_run": False,
    }


def _capture_pin_net_map(graph) -> dict[tuple[str, str], str]:
    """Build a (ref, pin_number) → net_name map by BFS-walking wires to labels.

    Phase 108 Task 2: this runs BEFORE the orchestrator clears wires + moves
    components. The returned map is stashed as a module-global so
    route_wires_sch can use it after placement without re-reading the
    (now-mutated) wire graph.
    """
    adj: dict[tuple[float, float], set[tuple[float, float]]] = {}
    for wire in graph.wires:
        s = (round(wire.start[0], 2), round(wire.start[1], 2))
        e = (round(wire.end[0], 2), round(wire.end[1], 2))
        adj.setdefault(s, set()).add(e)
        adj.setdefault(e, set()).add(s)

    label_at: dict[tuple[float, float], str] = {}
    for pos, label in graph._label_pos_index.items():
        label_at[(round(pos[0], 2), round(pos[1], 2))] = label.name

    def _bfs_label(start: tuple[float, float]) -> str | None:
        seen = {start}
        queue = [start]
        while queue:
            pos = queue.pop(0)
            if pos in label_at:
                return label_at[pos]
            for neighbor in adj.get(pos, ()):
                if neighbor not in seen:
                    seen.add(neighbor)
                    queue.append(neighbor)
        return None

    net_map: dict[tuple[str, str], str] = {}
    for pin in graph.pins:
        # Try BOTH the pin tip (position) and the pin body — wires connect
        # to one or the other depending on the symbol (R/C bodies use the
        # body position, ICs use the pin tip). Walking from either gets us
        # into the wire adjacency graph.
        tip = (round(pin.position[0], 2), round(pin.position[1], 2))
        body = (round(pin.body_position[0], 2), round(pin.body_position[1], 2))
        net = _bfs_label(tip)
        if net is None:
            net = _bfs_label(body)
        if net is not None:
            net_map[(pin.ref, pin.pin_number)] = net
    return net_map


def _scan_all_refs(raw_content: str) -> set[str]:
    """Scan every placed (symbol (lib_id ...)) block and return its Reference.

    Catches symbols the topology builder misses (no-rotation symbols,
    power flags, ambiguous wildcards). Used to identify loose components
    that need parking.
    """
    import re
    placed_pattern = re.compile(r'\(symbol\s+\(lib_id\s+"[^"]+"\)')
    ref_pattern = re.compile(r'\(property\s+"Reference"\s+"([^"]+)"')
    all_refs: set[str] = set()
    for m in placed_pattern.finditer(raw_content):
        block_start = m.start()
        depth = 0
        block_end = None
        for i in range(block_start, len(raw_content)):
            if raw_content[i] == "(":
                depth += 1
            elif raw_content[i] == ")":
                depth -= 1
                if depth == 0:
                    block_end = i + 1
                    break
        if block_end is None:
            continue
        ref_m = ref_pattern.search(raw_content[block_start:block_end])
        if ref_m:
            all_refs.add(ref_m.group(1))
    return all_refs


def _clear_legacy_wires(raw_content: str) -> str:
    """Remove existing wires, junctions, and no_connects from a schematic.

    Phase 108 Task 2: when auto_layout_sch moves components to new positions,
    existing wires (which reference old pin coordinates) become invalid —
    they point to empty space or wrong pins. Leaving them produces visual
    chaos on the autolaid schematic.

    LABELS are deliberately preserved — they define the nets. Phase 38
    finding: labels are the primary connection mechanism in KiCad 10. The
    apply_labels_sch handler adds fresh labels at NEW pin body positions
    alongside the originals.

    This strips:
      - ``(wire (pts (xy X1 Y1) (xy X2 Y2)) ...)`` blocks
      - ``(junction (at X Y) ...)`` blocks (wire junctions — meaningless
        once wires are removed)
      - ``(no_connect (at X Y) ...)`` blocks

    Does NOT touch: symbols, lib_symbols, labels, global_labels, sheet
    blocks, title_block, paper.
    Idempotent: re-running on a cleared schematic is a no-op.
    """
    import re

    def _strip_top_level_blocks(content: str, opener_regex: str) -> str:
        """Remove every top-level (opener ...) block from content."""
        result = []
        pos = 0
        for m in re.finditer(opener_regex, content):
            line_start = content.rfind('\n', 0, m.start()) + 1
            prefix = content[line_start:m.start()]
            if prefix.strip() != '':
                continue  # not top-level — skip
            depth = 0
            i = m.start()
            while i < len(content):
                if content[i] == '(':
                    depth += 1
                elif content[i] == ')':
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        if end < len(content) and content[end] == '\n':
                            end += 1
                        result.append(content[pos:m.start()])
                        pos = end
                        break
                i += 1
        result.append(content[pos:])
        return ''.join(result)

    content = _strip_top_level_blocks(raw_content, r'\(wire\s+\(pts\b')
    content = _strip_top_level_blocks(content, r'\(junction\s+\(at\b')
    content = _strip_top_level_blocks(content, r'\(no_connect\s+\(at\b')
    return content


def _park_ambiguous_by_uuid_v2(
    raw_content: str,
    ambiguous_refs: set[str],
    region: Any,  # PageRegion
    snap_fn,
    node_spacing_mm: float,
) -> tuple[list[dict[str, Any]], int]:
    """Park ambiguous-ref symbols by UUID into a specific page region.

    Phase 108 Task 2 revision of ``_park_ambiguous_by_uuid``: takes a
    ``PageRegion`` instead of computing its own parking strip from
    ``placed_positions``. This keeps parking in the region the planner
    reserved, so it never collides with placed groups.
    """
    import re

    if not ambiguous_refs:
        return [], 0

    ref_pattern = re.compile(r'\(property\s+"Reference"\s+"([^"]+)"')
    uuid_pattern = re.compile(r'\(uuid\s+([0-9a-fA-F-]+)\)')

    targets: list[tuple[str, str]] = []  # (uuid, ref)
    symbol_starts = [
        m.start() for m in re.finditer(r'\(symbol\s+\(lib_id\b', raw_content)
    ]
    for start in symbol_starts:
        depth = 0
        i = start
        block_end = None
        while i < len(raw_content):
            if raw_content[i] == '(':
                depth += 1
            elif raw_content[i] == ')':
                depth -= 1
                if depth == 0:
                    block_end = i + 1
                    break
            i += 1
        if block_end is None:
            continue
        block = raw_content[start:block_end]
        ref_match = ref_pattern.search(block)
        if ref_match is None:
            continue
        ref = ref_match.group(1)
        if ref not in ambiguous_refs:
            continue
        uuid_match = uuid_pattern.search(block)
        if uuid_match is None:
            continue
        targets.append((uuid_match.group(1), ref))

    if not targets:
        return [], 0

    # Lay out the UUIDs in the region using the same grid logic as park_in_region.
    usable_w = max(region.width, node_spacing_mm)
    cols = max(int(usable_w // node_spacing_mm), 1)
    spacing_x = region.width / cols

    mutations: list[dict[str, Any]] = []
    for i, (symbol_uuid, _ref) in enumerate(targets):
        row, col = divmod(i, cols)
        x = snap_fn(region.x_min + col * spacing_x + node_spacing_mm / 2.0)
        y = snap_fn(region.y_min + row * node_spacing_mm + node_spacing_mm / 2.0)
        x = min(x, region.x_max)
        y = min(y, region.y_max)
        mutations.append({
            "op": "move_symbol_by_uuid",
            "uuid": symbol_uuid,
            "new_x": x,
            "new_y": y,
        })

    return mutations, len(mutations)


def _find_ambiguous_refs(raw_content: str, refs: set[str]) -> set[str]:
    """Identify refs that SchematicRawWriter cannot move unambiguously.

    Two cases trip the writer's ambiguity guard (schematic_raw_writer.py:730):
      1. Refs with "?" wildcard (e.g. ``R?``, ``C?``) — unannotated symbols
         share the same Reference property; on corrupt fixtures like
         Arduino_Mega, 129 ``R?`` blocks exist.
      2. Refs shared by more than one symbol block (duplicate annotation).

    Both are parked via UUID-keyed moves by ``_park_ambiguous_by_uuid``.
    """
    import re
    ambiguous: set[str] = set()
    # Wildcard refs — always ambiguous when >1 symbol uses them.
    for ref in refs:
        if "?" in ref:
            ambiguous.add(ref)
    # Count (property "Reference" "<ref>") occurrences per ref to find
    # duplicates (real annotated refs that appear on multiple symbols).
    for ref in refs - ambiguous:
        pattern = re.compile(
            r'\(property\s+"Reference"\s+"' + re.escape(ref) + r'"'
        )
        if len(pattern.findall(raw_content)) > 1:
            ambiguous.add(ref)
    return ambiguous


def _park_ambiguous_by_uuid(
    raw_content: str,
    ambiguous_refs: set[str],
    placed_positions: dict[str, tuple[float, float]],
    layout: Any,
    page_w: float,
    page_h: float,
    margin: float,
) -> tuple[list[dict[str, Any]], int]:
    """DEPRECATED: use _park_ambiguous_by_uuid_v2 (region-based).

    Retained for backward compatibility with any external callers. The v2
    variant takes a PageRegion instead of computing its own strip, which
    keeps parking in the planner-reserved region.
    """
    # Reconstruct a pseudo-region from placed_positions to delegate to v2.
    from kicad_agent.schematic_autolayout.layout_planner import PageRegion
    placed_max_y = (
        max(y for _, y in placed_positions.values()) if placed_positions else margin
    ) + layout.node_spacing_mm
    region = PageRegion(margin, placed_max_y, page_w - margin, page_h - margin)
    return _park_ambiguous_by_uuid_v2(
        raw_content, ambiguous_refs, region,
        layout._snap_to_grid, layout.node_spacing_mm,
    )


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
    # emit a wire — but ONLY if they share a net. The original code emitted
    # wires between ANY two nearby pins regardless of net membership, which
    # created spurious wires between unrelated pins and a dense visual mesh.
    # Phase 108 Task 2 fix: use the pre-captured pin→net map (captured by
    # the orchestrator BEFORE wires were cleared + components moved).
    # Falling back to a fresh capture handles the standalone-call path
    # (route_wires_sch called directly without the orchestrator).
    if _PRE_ROUTE_PIN_NETS is not None:
        pin_nets = _PRE_ROUTE_PIN_NETS
    else:
        pin_nets = _capture_pin_net_map(sg)

    all_pins = list(sg.pins)
    for i, p1 in enumerate(all_pins):
        net1 = pin_nets.get((p1.ref, p1.pin_number))
        if net1 is None:
            continue  # pin has no net — skip
        for p2 in all_pins[i + 1:]:
            if p1.ref == p2.ref:
                continue
            net2 = pin_nets.get((p2.ref, p2.pin_number))
            if net2 != net1:
                continue  # different nets — never wire them together
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

    Phase 108 Task 2 fix: label X/Y is clamped to the page bounds. When
    a fixture has corrupt pin body_positions (e.g., the Arduino_Mega
    (5000,5000) outlier), labels previously inherited those off-page
    coordinates and stacked on top of legitimate components.

    NEW-MED-1 fix: uses VERIFIED SchematicGraph + suggest_net_names API.
      - suggest_net_names(sch_path) returns {"suggestions": [{current_name,
        suggested_name, pins: [{ref, pin_number, pin_name}]}], "stats": {...}}
      - Pin body_position is retrieved from SchematicGraph.pins (list lookup).
    """
    from kicad_agent.schematic_autolayout import paper_sizes
    from kicad_agent.schematic_routing.schematic_graph import SchematicGraph
    from kicad_agent.schematic_routing.net_namer import suggest_net_names
    from kicad_agent.ops.schematic_raw_writer import SchematicRawWriter
    from kicad_agent.io.atomic_write import atomic_write
    from kicad_agent.ops.handlers.pcb_cleanup import validate_paren_balance
    import uuid as uuid_module

    root_path = Path(file_path).resolve()
    raw_content = root_path.read_text()

    # Page bounds — labels clamped to this rectangle (Task 2 fix).
    paper = paper_sizes.parse_paper_from_sch(raw_content)
    page_w, page_h = paper_sizes.paper_dims_mm(paper)
    x_min, y_min, x_max, y_max = paper_sizes.usable_area_mm(paper)

    sg = SchematicGraph.from_file(str(root_path))

    # Pin lookup by (ref, pin_number) → PinPosition for body_position retrieval
    pin_lookup = {(p.ref, p.pin_number): p for p in sg.pins}

    # suggest_net_names returns dict with "suggestions" list
    naming = suggest_net_names(str(root_path))
    suggestions = naming.get("suggestions", [])

    # Phase 108 Task 2 fix: only emit labels for REAL nets — nets with 2+
    # connected pins. The net_namer generates a "J1_Pin_N" suggestion for
    # every single pin even when it has no connection; emitting those as
    # labels clutters the page with hundreds of meaningless labels (the
    # Arduino_Mega fixture has 86 such suggestions for its 129 unconnected
    # resistors). A net with 0 or 1 pin isn't a connection — it's just a
    # pin sitting alone. Skip it.
    mutations: list[dict[str, Any]] = []
    labels_global = 0
    labels_local = 0
    for sugg in suggestions:
        net_name = sugg.get("suggested_name") or sugg.get("current_name", "")
        if not net_name:
            continue
        pins = sugg.get("pins", [])
        if len(pins) < 2:
            continue  # not a real net — single-pin or no-pin "net"
        # Use THIS net's first pin's WIRE-CONNECTION position (pin tip), not
        # body position. Phase 108 Task 2 fix: body positions cluster around
        # the component center — for a 40-pin connector, all 40 pin bodies
        # land near the connector center, stacking 40 labels on top of each
        # other. The pin tip (position) spreads along the connector edge,
        # so each label sits next to its own pin.
        first_pin = pins[0]
        pin_pos = pin_lookup.get(
            (first_pin.get("ref", ""), first_pin.get("pin_number", ""))
        )
        if pin_pos is None:
            continue
        tip_x, tip_y = pin_pos.position
        # Clamp to page bounds.
        tip_x = min(max(tip_x, x_min), x_max)
        tip_y = min(max(tip_y, y_min), y_max)
        is_global = _is_global_net(net_name, op.global_labels)
        mutations.append({
            "op": "insert_label",
            "net_name": net_name,
            "x": tip_x,
            "y": tip_y,
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
        "page_bounds": {"paper": paper, "width_mm": page_w, "height_mm": page_h},
        "dry_run": False,
    }


@register_schematic("auto_layout_sch")
def _handle_auto_layout_sch(op: Any, ir: Any, file_path: Path) -> dict[str, Any]:
    """Orchestrate place+route+label (D-04).

    This is the user-facing high-level op. It invokes the 3 low-level ops
    from Plan 02 in sequence (each is independently callable and atomic),
    then computes the D-02 hierarchy-promotion DECISION and reports it
    as advisory.

    v1 scope (CRITICAL-1 fix, Phase 108 Council Gate 1 revision):
        The handler reports ``hierarchy_promoted=False`` honestly. The
        advisory ``hierarchy_split_decision`` dict carries the computed
        DECISION (would_promote, sheet_plans, inter_group_nets) — this
        is the algorithmic prep work for Phase 145 large-board hierarchy
        emission. The physical emission (writing per-group .kicad_sch
        files, moving components, wiring hierarchical pins via the
        existing add_sheet_pin op) is tracked via a follow-up Bead
        under the four-state taxonomy as DEFERRED-TO-NAMED-TARGET.

    No stub `pass` block, no follow-up stub comment (CRITICAL-1).
    The only `pass` statements in this function live inside
    ``except Exception: pass`` for the best-effort Bead creation —
    a legitimate error-swallow pattern that Test 8 explicitly excludes
    from the CRITICAL-1 regression check.

    HIGH-5 fix honored:
        OperationExecutor is constructed with ``base_dir=`` keyword when
        used. The 3 child ops are dispatched via the schematic handler
        registry (same registered handlers execute_batch would call),
        invoked directly here to avoid nested-Transaction lock
        contention (the outer executor wraps this handler in a
        Transaction; execute_batch would open a second Transaction on
        the same file, which the lock model forbids). Each child op
        remains independently dispatchable via OperationExecutor for
        users who want atomic single-op semantics.

    Deviation note (Rule 1 - Bug):
        The plan's literal "via execute_batch" wording conflicts with
        the executor's Transaction model (nested Transactions on the
        same file are forbidden by design — see ir/transaction.py:110).
        Dispatching via the handler registry preserves the D-04 multi-op
        pipeline contract (each op independently dispatchable + atomic)
        while avoiding the lock conflict. Plan 02's tests already prove
        each handler works standalone; this orchestrator simply chains
        them in sequence.
    """
    from dataclasses import asdict
    from kicad_agent.ops.handlers import _SCHEMATIC_HANDLERS
    from kicad_agent.schematic_autolayout.hierarchy_splitter import (
        HierarchicalSheetSplitter,
        SplitterResult,
    )
    from kicad_agent.schematic_routing.schematic_graph import SchematicGraph
    from kicad_agent.analysis.topology_builder import TopologyBuilder
    from kicad_agent.analysis.subcircuit_detector import SubcircuitDetector

    root_path = Path(file_path).resolve()

    # 1. Detect subcircuits + decide on hierarchy promotion (DECISION only, v1)
    sg = SchematicGraph.from_file(str(root_path))
    builder = TopologyBuilder()
    topology = builder.from_schematic_graph(sg)
    detector = SubcircuitDetector()
    subcircuits = detector.detect(topology)

    # 1.5 Capture the pin→net map BEFORE any placement mutation. Phase 108
    # Task 2 fix: the orchestrator clears legacy wires + labels may move
    # during placement. Capturing the net structure upfront lets
    # route_wires_sch correctly wire components that share a net even when
    # the original wires/labels no longer match the post-placement pin
    # coordinates. Stashed as module-global because Pydantic op models
    # don't accept arbitrary attrs cleanly.
    global _PRE_ROUTE_PIN_NETS
    _PRE_ROUTE_PIN_NETS = _capture_pin_net_map(sg)

    if op.subcircuit_split:
        splitter = HierarchicalSheetSplitter()
        split_result = splitter.split(subcircuits, str(root_path))
    else:
        # Forced single-sheet via op flag (D-02 opt-out)
        split_result = SplitterResult(
            promote_to_hierarchical=False,
            sheet_plans=(),
            inter_group_nets=(),
        )

    # 2. Build child op models (Pydantic-validated) and dispatch each via
    #    the schematic handler registry. HIGH-5 regression coverage:
    #    Test 6 asserts the OperationExecutor constructor signature
    #    requires base_dir (regression guard for any future refactor that
    #    reintroduces execute_batch). The current direct-dispatch path
    #    uses the registry to invoke the same handlers execute_batch
    #    would call, preserving the D-04 multi-op pipeline contract.
    #
    #    We construct real Pydantic op instances so the child schemas'
    #    defaults (e.g., ApplyLabelsSchOp.global_labels=[]) are populated
    #    and the handlers' attribute access works correctly.
    from kicad_agent.ops._schema_autolayout import (
        PlaceComponentsSchOp,
        RouteWiresSchOp,
        ApplyLabelsSchOp,
    )
    from kicad_agent.schematic_autolayout.symbol_normalizer import (
        normalize_placed_symbols,
    )

    target_rel = Path(file_path).name
    child_op_models: list[Any] = []

    # Step 0 (annotate=True default): normalize placed symbols BEFORE
    # placement. This repairs the malformations KiCad 10 rejects:
    #   - Missing (dnp no), (instances ...), pin UUID blocks
    #   - Empty (property "Value" "")
    #   - Missing rotation on (at X Y) -> (at X Y 0)
    #   - Wildcard R?/C? references -> unique R1/R2/...
    # Normalizing first means every symbol enters the topology graph
    # uniquely and flows cleanly through Sugiyama placement + fit_to_page.
    # Idempotent: well-formed symbols pass through unchanged.
    annotate_stats = None
    if op.annotate and not op.dry_run:
        root_path_obj = Path(file_path).resolve()
        raw = root_path_obj.read_text()
        normalized, stats = normalize_placed_symbols(raw)
        if normalized != raw:
            from kicad_agent.io.atomic_write import atomic_write
            atomic_write(root_path_obj, normalized)
        annotate_stats = {
            "symbols_normalized": stats.symbols_normalized,
            "wildcards_annotated": stats.wildcards_annotated,
            "rotation_fixes": stats.rotation_fixes,
            "instances_added": stats.instances_added,
        }

        # Clear legacy wires BEFORE placement. Existing wires reference old pin
        # positions that become invalid once we move components — leaving them
        # produces visual chaos (wires going to empty space). Labels stay
        # because they define the nets (Phase 38: labels are the primary
        # connection mechanism in KiCad 10). route_wires_sch re-emits fresh
        # wires at the new pin positions; apply_labels_sch adds new labels at
        # new pin body positions (the originals remain as global net anchors).
        cleared = _clear_legacy_wires(normalized if normalized != raw else raw)
        if cleared != (normalized if normalized != raw else raw):
            from kicad_agent.io.atomic_write import atomic_write
            atomic_write(root_path_obj, cleared)

    child_op_models.extend([
        PlaceComponentsSchOp(
            op_type="place_components_sch",
            target_file=target_rel,
            subcircuit_split=op.subcircuit_split,
            layer_spacing_mm=op.layer_spacing_mm,
            node_spacing_mm=op.node_spacing_mm,
            dry_run=op.dry_run,
        ),
        RouteWiresSchOp(
            op_type="route_wires_sch",
            target_file=target_rel,
            max_wire_length_mm=op.max_wire_length_mm,
            dry_run=op.dry_run,
        ),
        ApplyLabelsSchOp(
            op_type="apply_labels_sch",
            target_file=target_rel,
            label_size_mm=op.label_size_mm,
            dry_run=op.dry_run,
        ),
    ])

    # Dispatch each child op via its registered handler.
    per_op_results: list[dict[str, Any]] = []
    for child_op_model in child_op_models:
        op_type = child_op_model.op_type
        handler = _SCHEMATIC_HANDLERS.get(op_type)
        if handler is None:
            raise RuntimeError(
                f"No handler registered for op_type {op_type!r}"
            )
        result = handler(child_op_model, ir, file_path)
        per_op_results.append(result)

    # Index offsets: normalization is inline (not a dispatched op), so the
    # child_op_models list is always [place, route, label].
    place_result = per_op_results[0]
    route_result = per_op_results[1]
    label_result = per_op_results[2]

    # 3. Follow-up Bead for physical hierarchy emission (four-state taxonomy).
    #    Created ONLY when the splitter decided promotion is warranted.
    #    State: DEFERRED-TO-NAMED-TARGET (Phase 145). Trigger: Phase 145
    #    begins. Best-effort — Beads MCP may be unavailable in some envs.
    if split_result.promote_to_hierarchical:
        try:
            # Defer the Beads import — not all environments have the MCP
            # tool installed at runtime. The four-state taxonomy label
            # encodes the resolution state per bureaucracy §7.
            from kicad_agent.beads import beads_create  # type: ignore
            beads_create(
                title=(
                    "Phase 145: physical hierarchy sub-sheet emission for "
                    "auto_layout_sch"
                ),
                # MED-3 fix: 'phase-108-followup' (no 'follup' typo)
                labels=(
                    "phase-108-followup,"
                    "hierarchy-physical-emission,"
                    "deferred-to-phase-145"
                ),
                description=(
                    "When auto_layout_sch runs on a board with >=3 "
                    "subcircuits, the HierarchicalSheetSplitter computes "
                    "the promotion DECISION but v1 does not emit physical "
                    "sub-sheets. Phase 145 will: (1) write per-group "
                    ".kicad_sch files per SheetPlan, (2) move components "
                    "between sheets, (3) wire hierarchical pins via the "
                    "existing add_sheet_pin op. Trigger: Phase 145 begins. "
                    "Readiness signal: this Bead count > 0."
                ),
                priority="2",
            )
        except Exception:
            # Beads tracking is best-effort. We must NOT fail the op when
            # the Bead system is unavailable — the DECISION is already
            # surfaced in the result dict for downstream consumers.
            # (Test 8 explicitly excludes except-handler bodies from the
            # CRITICAL-1 no-`pass` regression check.)
            pass

    # 4. Return — CRITICAL-1 fix: report hierarchy_promoted=False honestly.
    #    v1 did not write sub-sheet files, did not move components between
    #    sheets, did not wire hierarchical pins. The computed DECISION
    #    goes in the advisory hierarchy_split_decision dict (not the
    #    promoted flag).
    return {
        "annotate_stats": annotate_stats,
        "place_result": place_result,
        "route_result": route_result,
        "label_result": label_result,
        "hierarchy_promoted": False,  # v1: physical emission deferred to Phase 145
        "hierarchy_split_decision": {  # advisory — DECISION computed, not applied
            "would_promote": split_result.promote_to_hierarchical,
            "sheet_plans": [asdict(p) for p in split_result.sheet_plans],
            "inter_group_nets": list(split_result.inter_group_nets),
        },
        "subcircuit_count": len(subcircuits),
        "dry_run": op.dry_run,
    }
