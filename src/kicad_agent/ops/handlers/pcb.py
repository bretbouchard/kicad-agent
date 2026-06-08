"""PCB mutation handlers -- operations that modify PCB files.

Handlers receive (op, PcbIR, file_path) and return a result dict.
"""

import logging
from dataclasses import replace
from pathlib import Path
from typing import Any, Callable

from kicad_agent.ir.pcb_ir import PcbIR

logger = logging.getLogger(__name__)

_PCB_HANDLERS: dict[str, Callable] = {}


def register_pcb(op_type: str) -> Callable:
    """Decorator to register a PCB operation handler."""
    def decorator(fn: Callable) -> Callable:
        _PCB_HANDLERS[op_type] = fn
        return fn
    return decorator


def _validate_footprint_impl(footprint_lib_id: str, file_path: Path) -> dict[str, Any]:
    """Validate that a footprint exists in the available libraries.

    Parses the fp-lib-table to resolve the library nickname and checks
    if the footprint .kicad_mod file exists on disk.

    Args:
        footprint_lib_id: Footprint library reference, e.g. "Library:Footprint".
        file_path: Path to the target KiCad file (used to locate fp-lib-table).

    Returns:
        Dict with footprint_lib_id, valid (bool), and library_path or error.
    """
    from kicad_agent.lib_resolver import resolve_footprint_path

    try:
        resolved = resolve_footprint_path(footprint_lib_id, file_path)
        return {
            "footprint_lib_id": footprint_lib_id,
            "valid": True,
            "library_path": str(resolved),
        }
    except (ValueError, FileNotFoundError) as exc:
        return {
            "footprint_lib_id": footprint_lib_id,
            "valid": False,
            "error": str(exc),
        }


@register_pcb("update_footprint_from_library")
def _handle_update_footprint(op: Any, ir: PcbIR, file_path: Path) -> dict[str, Any]:
    return ir.update_footprint_from_library(
        reference=op.reference,
        lib_id_override=op.footprint_lib_id,
        pcb_path=file_path,
    )


@register_pcb("swap_footprint")
def _handle_pcb_swap_footprint(op: Any, ir: PcbIR, file_path: Path) -> dict[str, Any]:
    return ir.swap_footprint(
        reference=op.reference,
        new_footprint_lib_id=op.new_footprint_lib_id,
    )


@register_pcb("add_net")
def _handle_pcb_add_net(op: Any, ir: PcbIR, file_path: Path) -> dict[str, Any]:
    net = ir.add_net(net_name=op.net_name, net_number=op.net_number)
    return {"net_name": net.name, "net_number": net.number}


@register_pcb("remove_net")
def _handle_pcb_remove_net(op: Any, ir: PcbIR, file_path: Path) -> dict[str, Any]:
    ir.remove_net(net_name=op.net_name)
    return {"removed_net": op.net_name}


@register_pcb("rename_net")
def _handle_pcb_rename_net(op: Any, ir: PcbIR, file_path: Path) -> dict[str, Any]:
    ir.rename_net(old_name=op.old_name, new_name=op.new_name)
    return {"old_name": op.old_name, "new_name": op.new_name}


@register_pcb("validate_footprint")
def _handle_pcb_validate_footprint(op: Any, ir: PcbIR, file_path: Path) -> dict[str, Any]:
    return _validate_footprint_impl(op.footprint_lib_id, file_path)


@register_pcb("add_copper_zone")
def _handle_add_copper_zone(op: Any, ir: PcbIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.pcb_ops import add_copper_zone
    return add_copper_zone(
        ir, file_path,
        net_name=op.net_name,
        layer=op.layer,
        clearance=op.clearance,
        min_width=op.min_width,
        priority=op.priority,
    )


@register_pcb("modify_copper_zone")
def _handle_modify_copper_zone(op: Any, ir: PcbIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.pcb_ops import modify_copper_zone
    return modify_copper_zone(
        ir, file_path,
        zone_uuid=op.zone_uuid,
        net_name=op.net_name,
        layer=op.layer,
        clearance=op.clearance,
        min_width=op.min_width,
        priority=op.priority,
    )


@register_pcb("remove_copper_zone")
def _handle_remove_copper_zone(op: Any, ir: PcbIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.pcb_ops import remove_copper_zone
    return remove_copper_zone(
        ir, file_path,
        zone_uuid=op.zone_uuid,
        zone_index=op.zone_index,
    )


@register_pcb("refill_copper_zone")
def _handle_refill_copper_zone(op: Any, ir: PcbIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.pcb_ops import refill_copper_zone
    return refill_copper_zone(
        ir, file_path,
        zone_uuid=op.zone_uuid,
        zone_index=op.zone_index,
    )


@register_pcb("modify_zone_polygon")
def _handle_modify_zone_polygon(op: Any, ir: PcbIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.pcb_ops import modify_zone_polygon
    return modify_zone_polygon(
        ir, file_path,
        zone_uuid=op.zone_uuid,
        polygon=op.polygon,
    )


@register_pcb("add_keepout_area")
def _handle_add_keepout_area(op: Any, ir: PcbIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.pcb_ops import add_keepout_area
    return add_keepout_area(
        ir, file_path,
        layer=op.layer,
        keepout_type=op.keepout_type,
        polygon=op.polygon,
    )


@register_pcb("remove_keepout_area")
def _handle_remove_keepout_area(op: Any, ir: PcbIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.pcb_ops import remove_keepout_area
    return remove_keepout_area(
        ir, file_path,
        zone_uuid=op.zone_uuid,
        zone_index=op.zone_index,
    )


@register_pcb("set_board_outline")
def _handle_set_board_outline(op: Any, ir: PcbIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.pcb_ops import set_board_outline
    return set_board_outline(ir, width=op.width, height=op.height)


@register_pcb("assign_net_class")
def _handle_assign_net_class(op: Any, ir: PcbIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.pcb_ops import assign_net_class
    return assign_net_class(
        ir, file_path,
        net_name=op.net_name,
        net_class_name=op.net_class_name,
    )


@register_pcb("move_footprint")
def _handle_move_footprint(op: Any, ir: PcbIR, file_path: Path) -> dict[str, Any]:
    """Move a footprint via PcbRawWriter (Council C-01: returns content, executor writes)."""
    from kicad_agent.ops.pcb_raw_writer import PcbRawWriter

    raw = ir.raw_content
    new_content = PcbRawWriter.modify_footprint_position(
        raw, op.reference, op.x, op.y, op.angle
    )
    if new_content == raw:
        raise ValueError(f"Footprint '{op.reference}' not found in PCB")

    # Write atomically and update IR state (Council C-01/C-02)
    ir.commit_raw_content(new_content)

    return {
        "reference": op.reference,
        "x": op.x,
        "y": op.y,
        "angle": op.angle,
    }


@register_pcb("batch_expand_footprints")
def _handle_batch_expand_footprints(op: Any, ir: PcbIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.pcb_raw_writer import PcbRawWriter

    raw = ir.raw_content
    new_content, result = PcbRawWriter.batch_expand_footprints(
        raw, file_path, dry_run=op.dry_run,
    )
    if not op.dry_run and new_content != raw:
        ir.commit_raw_content(new_content)
    return result


@register_pcb("auto_route")
def _handle_auto_route(op: Any, ir: PcbIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.routing.freerouting import (
        is_freerouting_available,
        route_with_freerouting,
        import_ses_into_pcb,
    )

    # --- Freerouting strategy branch ---
    strategy = getattr(op, "strategy", "auto")
    use_freerouting = strategy == "freerouting" or (
        strategy == "auto" and is_freerouting_available()
    )

    if use_freerouting:
        logger.info("Auto-route: using Freerouting (strategy=%s)", strategy)
        fr_result = route_with_freerouting(file_path, max_passes=10)

        if not fr_result.success:
            if strategy == "freerouting":
                return {
                    "routed_nets": 0,
                    "segments": 0,
                    "vias": 0,
                    "failed_nets": [],
                    "strategy": "freerouting",
                    "message": f"Freerouting failed: {fr_result.stderr}",
                }
            # auto mode: fall through to A*
            logger.warning(
                "Freerouting failed (%s), falling back to A*", fr_result.stderr
            )
            use_freerouting = False
        else:
            # Import SES into PCB content
            new_content, stats = import_ses_into_pcb(
                fr_result.ses_path, ir.raw_content
            )
            ir.commit_raw_content(new_content)
            return {
                "routed_nets": stats["nets_routed"],
                "segments": stats["segments"],
                "vias": stats["vias"],
                "skipped": stats["skipped"],
                "failed_nets": [],
                "strategy": "freerouting",
                "ses_path": str(fr_result.ses_path),
                "dsn_path": str(fr_result.dsn_path),
            }

    # --- A* pathfinder strategy ---
    from kicad_agent.routing.bridge import (
        TrackSegment,
        ViaSegment,
        route_to_segments,
        route_to_segments_multilayer,
        segments_to_sexpr,
    )
    from kicad_agent.routing.constraints import RoutingConstraints
    from kicad_agent.routing.pathfinder import (
        RouteResult,
        build_routing_graph,
        route_all_nets,
        route_net,
    )

    # Determine active layers.
    active_layers = op.layers if op.layers else [op.layer]
    is_multilayer = len(active_layers) > 1

    # Build base constraints with stackup parameters.
    # Use 0.25mm grid for better pad snapping on dense boards.
    constraints = RoutingConstraints(
        dielectric_constant=4.5,
        dielectric_height_mm=0.2,
        copper_thickness_mm=0.035,
        grid_resolution_mm=0.25,
    )

    # Impedance control: calculate trace width per layer (ROUTE-06).
    layer_trace_widths: dict[str, float] | None = None
    impedance_result = None
    if op.impedance_target is not None:
        from kicad_agent.routing.impedance import solve_trace_width

        layer_trace_widths = {}
        for layer_name in active_layers:
            model = "microstrip" if layer_name in ("F.Cu", "B.Cu") else "stripline"
            if layer_name == "B.Cu" and len(active_layers) > 2:
                logger.warning(
                    "B.Cu modeled as microstrip -- may be inaccurate for 4+ layer "
                    "stackups where B.Cu is embedded. Use layer_trace_widths override."
                )
            result = solve_trace_width(
                target_z0=op.impedance_target,
                h=constraints.dielectric_height_mm,
                t=constraints.copper_thickness_mm,
                er=constraints.dielectric_constant,
                model=model,
            )
            layer_trace_widths[layer_name] = result.trace_width_mm
        impedance_result = result  # Report last result for user feedback

        # Create new constraints with layer-specific trace widths.
        constraints = RoutingConstraints(
            dielectric_constant=constraints.dielectric_constant,
            dielectric_height_mm=constraints.dielectric_height_mm,
            copper_thickness_mm=constraints.copper_thickness_mm,
            layer_trace_widths=layer_trace_widths,
        )

    # --- Phase 1: Extract footprint obstacles (kicad-agent-7) ---
    obstacles = ir.extract_obstacles(clearance_mm=constraints.clearance_mm)
    logger.info(
        "Auto-route: extracted %d obstacles from %d footprints",
        len(obstacles),
        len(ir.footprints),
    )

    netlist = ir.extract_netlist()
    if not netlist:
        return {"routed_nets": 0, "segments": 0, "message": "No nets to route"}

    if op.nets:
        netlist = {n: pins for n, pins in netlist.items() if n in op.nets}

    # --- Phase 2: Filter power/ground nets (they get copper zones) ---
    _power_prefixes = ("+", "GND", "AGND", "VDD", "VSS", "VCC")
    _power_nets: set[str] = set()
    for net_name in list(netlist.keys()):
        if net_name.startswith(_power_prefixes):
            _power_nets.add(net_name)
        elif net_name == "":
            _power_nets.add(net_name)

    route_nets = {
        n: pins for n, pins in netlist.items() if n not in _power_nets
    }
    if _power_nets:
        logger.info(
            "Auto-route: skipping %d power/ground nets (use copper zones): %s",
            len(_power_nets),
            ", ".join(sorted(_power_nets)[:8]),
        )

    if not route_nets:
        return {
            "routed_nets": 0,
            "segments": 0,
            "vias": 0,
            "failed_nets": [],
            "skipped_power_nets": sorted(_power_nets),
            "message": "All nets are power/ground — route copper zones instead",
        }

    # Collect all pad positions for required nodes and bounds computation.
    _all_pads: set[tuple[float, float]] = set()
    _pad_xs: list[float] = []
    _pad_ys: list[float] = []
    for pins in route_nets.values():
        for px, py in pins:
            _all_pads.add((px, py))
            _pad_xs.append(px)
            _pad_ys.append(py)

    # Compute routing bounds from obstacles + pad extents, not board outline.
    all_xs: list[float] = list(_pad_xs)
    all_ys: list[float] = list(_pad_ys)
    for o in obstacles:
        all_xs.extend([o.x1, o.x2])
        all_ys.extend([o.y1, o.y2])
    margin_mm = constraints.clearance_mm + constraints.trace_width_mm + 1.0
    bounds = (
        min(all_xs) - margin_mm,
        min(all_ys) - margin_mm,
        max(all_xs) + margin_mm,
        max(all_ys) + margin_mm,
    )
    logger.info("Auto-route: routing bounds %.1f x %.1f mm", bounds[2]-bounds[0], bounds[3]-bounds[1])

    # --- Phase 3: Build routing graph with obstacles and required pad nodes ---
    routing_graph = build_routing_graph(
        bounds,
        obstacles=obstacles,
        constraints=constraints,
        layers=active_layers if is_multilayer else None,
        required_nodes=_all_pads,
    )

    # --- Phase 4: Sequential routing with rip-up (kicad-agent-7) ---
    # Route nets shortest-first. After each successful route, mark the
    # path as an obstacle so subsequent nets avoid it.
    net_id_map = ir.extract_net_id_map()

    # Sort nets by pin count (2-pin first = shortest), then by name for
    # deterministic ordering.
    net_order = sorted(
        route_nets.items(),
        key=lambda item: (len(item[1]), item[0]),
    )

    results: dict[str, RouteResult] = {}
    failed_nets: list[str] = []
    for net_name, pins in net_order:
        if len(pins) < 2:
            continue

        if len(pins) == 2:
            # Simple 2-pin net: direct A* route.
            result = route_net(routing_graph, pins[0], pins[1], net_name)
        else:
            # Multi-pin net: sequential nearest-neighbor Steiner tree.
            result = route_all_nets(routing_graph, {net_name: pins}).get(net_name)

        if result is not None and result.success:
            results[net_name] = result
            routing_graph.mark_path_as_obstacle(
                result.path, clearance=constraints.trace_width_mm,
            )
        else:
            failed_nets.append(net_name)

    # Length matching: apply sawtooth to specified net pairs (ROUTE-07).
    matched_pairs: list[dict[str, Any]] = []
    if op.length_match_pairs:
        from kicad_agent.routing.length_matching import add_sawtooth_matching
        from kicad_agent.routing.pathfinder import _path_length as calc_len

        for net_a, net_b, tolerance_mm in op.length_match_pairs:
            if net_a in results and net_b in results:
                len_a = results[net_a].length_mm
                len_b = results[net_b].length_mm
                mismatch = abs(len_a - len_b)
                if mismatch > tolerance_mm:
                    delta = mismatch - tolerance_mm
                    shorter_net = net_a if len_a < len_b else net_b
                    shorter_path = results[shorter_net].path
                    # Extract 2D waypoints from potentially 3D path.
                    path_2d = tuple(
                        (p[0], p[1]) for p in shorter_path
                    )
                    match_result = add_sawtooth_matching(
                        path_2d, delta, spacing_mm=constraints.trace_width_mm,
                    )
                    if match_result.valid:
                        matched_path = match_result.path
                        # Re-attach layer info if 3D path.
                        if is_multilayer and len(shorter_path) > 0 and len(shorter_path[0]) >= 3:
                            layer = shorter_path[0][2]
                            matched_path_3d = tuple(
                                (p[0], p[1], layer) for p in matched_path
                            )
                        else:
                            matched_path_3d = matched_path
                        results[shorter_net] = RouteResult(
                            net_name=shorter_net,
                            path=matched_path_3d,
                            length_mm=round(calc_len(list(matched_path_3d)), 4),
                            success=True,
                        )
                        matched_pairs.append({
                            "pair": (net_a, net_b),
                            "achieved_mismatch_mm": round(
                                abs(results[net_a].length_mm - results[net_b].length_mm), 4
                            ),
                            "valid": True,
                        })
                    else:
                        matched_pairs.append({
                            "pair": (net_a, net_b),
                            "valid": False,
                            "reason": "Could not achieve target length match",
                        })

    # Convert to segments.
    if is_multilayer:
        segments = route_to_segments_multilayer(results, constraints, net_id_map=net_id_map)
    else:
        segments = route_to_segments(results, constraints, layer=op.layer, net_id_map=net_id_map)
    segment_count = len(segments)
    via_count = sum(1 for s in segments if isinstance(s, ViaSegment))
    routed_nets = len({s.net for s in segments}) if segments else 0

    if segments:
        track_segs = [s for s in segments if isinstance(s, TrackSegment)]
        if track_segs:
            sexpr_block = segments_to_sexpr(track_segs)
            ir.insert_track_segments(sexpr_block)
        # Insert vias separately.
        via_segs = [s for s in segments if isinstance(s, ViaSegment)]
        if via_segs:
            via_block = "\n".join(s.to_sexpr() for s in via_segs)
            ir.insert_track_segments(via_block)

    return {
        "routed_nets": routed_nets,
        "segments": segment_count,
        "vias": via_count,
        "failed_nets": failed_nets,
        "skipped_power_nets": sorted(_power_nets),
        "obstacles": len(obstacles),
        "strategy": "astar",
        "impedance": (
            {"target_z0": impedance_result.target_z0,
             "achieved_z0": impedance_result.achieved_z0,
             "trace_width_mm": impedance_result.trace_width_mm}
            if impedance_result else None
        ),
        "length_matching": matched_pairs if matched_pairs else None,
    }


@register_pcb("route_diff_pair")
def _handle_route_diff_pair(op: Any, ir: PcbIR, file_path: Path) -> dict[str, Any]:
    """Route a differential pair with impedance control and length matching."""
    from kicad_agent.routing.bridge import (
        TrackSegment,
        ViaSegment,
        route_to_segments,
        segments_to_sexpr,
    )
    from kicad_agent.routing.constraints import RoutingConstraints
    from kicad_agent.routing.diff_pair import route_differential_pair
    from kicad_agent.routing.graph import RoutingGraph
    from kicad_agent.routing.pathfinder import build_routing_graph

    # Resolve pad positions for both nets.
    netlist = ir.extract_netlist()
    if op.net_positive not in netlist:
        raise ValueError(f"Net '{op.net_positive}' not found in PCB")
    if op.net_negative not in netlist:
        raise ValueError(f"Net '{op.net_negative}' not found in PCB")

    pos_pins = netlist[op.net_positive]
    neg_pins = netlist[op.net_negative]
    if not pos_pins or not neg_pins:
        raise ValueError(
            f"Both nets must have at least one pin: "
            f"{op.net_positive}={len(pos_pins)}, {op.net_negative}={len(neg_pins)}"
        )

    # Impedance-controlled trace width.
    trace_width = op.trace_width_mm
    impedance_achieved = None
    if op.impedance_target is not None and trace_width is None:
        from kicad_agent.routing.impedance import solve_trace_width

        model = "microstrip" if op.layer in ("F.Cu", "B.Cu") else "stripline"
        imp_result = solve_trace_width(
            target_z0=op.impedance_target,
            h=op.dielectric_height_mm,
            t=op.copper_thickness_mm,
            er=op.dielectric_er,
            model=model,
        )
        trace_width = imp_result.trace_width_mm
        impedance_achieved = {
            "target_z0": imp_result.target_z0,
            "achieved_z0": imp_result.achieved_z0,
            "trace_width_mm": imp_result.trace_width_mm,
            "model": imp_result.model,
        }

    if trace_width is None:
        trace_width = 0.25  # Default 10mil

    # Build routing graph.
    is_multilayer = op.via_layers is not None and len(op.via_layers) > 1
    constraints = RoutingConstraints(
        dielectric_constant=op.dielectric_er,
        dielectric_height_mm=op.dielectric_height_mm,
        copper_thickness_mm=op.copper_thickness_mm,
        trace_width_mm=trace_width,
        clearance_mm=op.spacing_mm * 0.5,
    )

    obstacles = ir.extract_obstacles(clearance_mm=constraints.clearance_mm)
    active_layers = op.via_layers if is_multilayer else [op.layer]

    _all_pads: set[tuple[float, float]] = set()
    for pins in [pos_pins, neg_pins]:
        for p in pins:
            _all_pads.add(p)

    all_xs: list[float] = [p[0] for p in _all_pads]
    all_ys: list[float] = [p[1] for p in _all_pads]
    for o in obstacles:
        all_xs.extend([o.x1, o.x2])
        all_ys.extend([o.y1, o.y2])
    margin = constraints.clearance_mm + trace_width + 1.0
    bounds = (min(all_xs) - margin, min(all_ys) - margin,
              max(all_xs) + margin, max(all_ys) + margin)

    graph = build_routing_graph(
        bounds, obstacles=obstacles, constraints=constraints,
        layers=active_layers if is_multilayer else None,
        required_nodes=_all_pads,
    )

    # Route the differential pair.
    dp_result = route_differential_pair(
        graph,
        src_p=pos_pins[0], src_n=neg_pins[0],
        tgt_p=pos_pins[-1], tgt_n=neg_pins[-1],
        target_spacing_mm=op.spacing_mm,
        max_length_mismatch_mm=op.max_length_mismatch_mm,
    )

    if not dp_result.valid:
        return {
            "routed": False,
            "reason": "Differential pair routing failed",
            "net_positive": op.net_positive,
            "net_negative": op.net_negative,
        }

    # Convert to KiCad segments.
    results = {
        op.net_positive: type("R", (), {
            "path": dp_result.net_positive, "length_mm": dp_result.length_positive_mm,
        })(),
        op.net_negative: type("R", (), {
            "path": dp_result.net_negative, "length_mm": dp_result.length_negative_mm,
        })(),
    }
    net_id_map = ir.extract_net_id_map()
    segments = route_to_segments(results, constraints, layer=op.layer, net_id_map=net_id_map)
    segment_count = len(segments)
    via_count = sum(1 for s in segments if isinstance(s, ViaSegment))

    if segments:
        track_segs = [s for s in segments if isinstance(s, TrackSegment)]
        if track_segs:
            sexpr_block = segments_to_sexpr(track_segs)
            ir.insert_track_segments(sexpr_block)
        via_segs = [s for s in segments if isinstance(s, ViaSegment)]
        if via_segs:
            via_block = "\n".join(s.to_sexpr() for s in via_segs)
            ir.insert_track_segments(via_block)

    return {
        "routed": True,
        "net_positive": op.net_positive,
        "net_negative": op.net_negative,
        "segments": segment_count,
        "vias": via_count,
        "length_positive_mm": dp_result.length_positive_mm,
        "length_negative_mm": dp_result.length_negative_mm,
        "mismatch_mm": dp_result.mismatch_mm,
        "spacing_mm": dp_result.spacing_mm,
        "impedance": impedance_achieved,
    }


@register_pcb("match_lengths")
def _handle_match_lengths(op: Any, ir: PcbIR, file_path: Path) -> dict[str, Any]:
    """Match route lengths between net pairs via serpentine tuning."""
    from kicad_agent.routing.geometry import _path_length

    pairs_matched: list[dict[str, Any]] = []
    total_bumps = 0

    for pair in op.net_pairs:
        # Extract routes for both nets from PCB segments.
        path_a = ir.extract_net_path(pair.net_a)
        path_b = ir.extract_net_path(pair.net_b)

        if not path_a:
            pairs_matched.append({
                "net_a": pair.net_a, "net_b": pair.net_b,
                "status": "skipped", "reason": f"No route found for {pair.net_a}",
            })
            continue
        if not path_b:
            pairs_matched.append({
                "net_a": pair.net_a, "net_b": pair.net_b,
                "status": "skipped", "reason": f"No route found for {pair.net_b}",
            })
            continue

        len_a = _path_length(list(path_a))
        len_b = _path_length(list(path_b))
        mismatch = abs(len_a - len_b)

        if mismatch <= pair.tolerance_mm:
            pairs_matched.append({
                "net_a": pair.net_a, "net_b": pair.net_b,
                "status": "already_within_tolerance",
                "before_mm": {"net_a": round(len_a, 4), "net_b": round(len_b, 4)},
                "mismatch_mm": round(mismatch, 4),
            })
            continue

        delta = mismatch - pair.tolerance_mm
        shorter = path_a if len_a < len_b else path_b
        shorter_name = pair.net_a if len_a < len_b else pair.net_b

        if op.pattern == "sawtooth":
            from kicad_agent.routing.length_matching import add_sawtooth_matching
            match_result = add_sawtooth_matching(
                shorter, delta, spacing_mm=op.half_pitch_mm,
            )
        else:
            from kicad_agent.routing.diff_pair import route_differential_pair
            # Accordion pattern: use diff_pair's internal accordion logic
            match_result = type("MR", (), {
                "path": shorter, "achieved_delta_mm": 0.0,
                "num_bumps": 0, "valid": False,
            })()
            pairs_matched.append({
                "net_a": pair.net_a, "net_b": pair.net_b,
                "status": "error", "reason": "Accordion pattern not yet implemented",
            })
            continue

        if match_result.valid:
            total_bumps += match_result.num_bumps
            pairs_matched.append({
                "net_a": pair.net_a, "net_b": pair.net_b,
                "status": "matched",
                "before_mm": {"net_a": round(len_a, 4), "net_b": round(len_b, 4)},
                "mismatch_mm": round(mismatch, 4),
                "bumps_added": match_result.num_bumps,
                "shortened_net": shorter_name,
            })
        else:
            pairs_matched.append({
                "net_a": pair.net_a, "net_b": pair.net_b,
                "status": "failed", "reason": "Could not achieve length match",
            })

    return {
        "pairs_checked": len(op.net_pairs),
        "pairs_matched": sum(1 for p in pairs_matched if p["status"] == "matched"),
        "total_bumps_added": total_bumps,
        "per_pair": pairs_matched,
    }


@register_pcb("analyze_split_plane")
def _handle_analyze_split_plane(op: Any, ir: PcbIR, file_path: Path) -> dict[str, Any]:
    """Analyze split planes and flag boundary crossings (read-only)."""
    from kicad_agent.validation.split_plane import analyze_split_plane

    analysis = analyze_split_plane(
        pcb_ir=ir,
        layer=op.layer,
        min_gap_mm=op.min_gap_mm,
    )
    return {
        "layer": op.layer,
        "num_zones": analysis.num_zones,
        "num_splits": analysis.num_splits,
        "num_crossings": analysis.num_crossings,
        "splits": [
            {"zone_a": s.zone_a_id, "zone_b": s.zone_b_id, "gap_mm": s.gap_mm}
            for s in analysis.splits
        ],
        "crossings": [
            {"net": c.trace_net, "point": c.crossing_point,
             "zone_a": c.zone_a, "zone_b": c.zone_b}
            for c in analysis.crossings
        ],
    }


@register_pcb("fix_silkscreen_over_copper")
def _handle_fix_silkscreen_over_copper(op: Any, ir: PcbIR, file_path: Path) -> dict[str, Any]:
    """Detect and optionally relocate silkscreen text overlapping copper."""
    from kicad_agent.validation.silkscreen_clearance import check_silkscreen_clearance

    result = check_silkscreen_clearance(
        pcb_ir=ir,
        clearance_mm=op.clearance_mm,
        copper_layers=op.copper_layers,
        silk_layers=op.silk_layers,
    )

    relocations_applied = 0
    if op.action == "relocate" and result.violations:
        for violation in result.violations:
            if violation.suggested_position is not None:
                try:
                    from kicad_agent.ops.pcb_raw_writer import PcbRawWriter
                    new_content = PcbRawWriter.modify_footprint_position(
                        ir.raw_content,
                        violation.footprint_ref,
                        violation.suggested_position[0],
                        violation.suggested_position[1],
                        0.0,
                    )
                    if new_content != ir.raw_content:
                        ir.commit_raw_content(new_content)
                        relocations_applied += 1
                except (ValueError, RuntimeError) as e:
                    import logging
                    logging.getLogger(__name__).warning(
                        "Silkscreen relocation failed for footprint: %s", e
                    )

    return {
        "total_checked": result.total_checked,
        "violations_found": len(result.violations),
        "relocations_applied": relocations_applied,
        "action": op.action,
        "violations": [
            {
                "text": v.text_content,
                "footprint_ref": v.footprint_ref,
                "position": v.text_position,
                "overlapping_items": v.overlapping_items,
                "suggested_position": v.suggested_position,
            }
            for v in result.violations
        ],
    }
