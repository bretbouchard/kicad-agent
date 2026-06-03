"""PCB mutation handlers -- operations that modify PCB files.

Handlers receive (op, PcbIR, file_path) and return a result dict.
"""

import logging
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


@register_pcb("auto_route")
def _handle_auto_route(op: Any, ir: PcbIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.routing.bridge import (
        TrackSegment,
        ViaSegment,
        route_to_segments,
        route_to_segments_multilayer,
        segments_to_sexpr,
    )
    from kicad_agent.routing.constraints import RoutingConstraints
    from kicad_agent.routing.pathfinder import RouteResult, build_routing_graph, route_all_nets

    # Determine active layers.
    active_layers = op.layers if op.layers else [op.layer]
    is_multilayer = len(active_layers) > 1

    # Build base constraints with stackup parameters.
    constraints = RoutingConstraints(
        dielectric_constant=4.5,
        dielectric_height_mm=0.2,
        copper_thickness_mm=0.035,
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

    bounds = ir.get_board_bounds()
    if bounds is None:
        raise ValueError("Cannot auto-route: board outline not set")

    netlist = ir.extract_netlist()
    if not netlist:
        return {"routed_nets": 0, "segments": 0, "message": "No nets to route"}

    if op.nets:
        netlist = {n: pins for n, pins in netlist.items() if n in op.nets}

    # Build routing graph with layers support.
    routing_graph = build_routing_graph(
        bounds,
        constraints=constraints,
        layers=active_layers if is_multilayer else None,
    )
    results = route_all_nets(routing_graph, netlist)

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
        segments = route_to_segments_multilayer(results, constraints)
    else:
        segments = route_to_segments(results, constraints, layer=op.layer)
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
        "failed_nets": [
            n for n in netlist
            if n not in results or not results[n].success
        ],
        "impedance": (
            {"target_z0": impedance_result.target_z0,
             "achieved_z0": impedance_result.achieved_z0,
             "trace_width_mm": impedance_result.trace_width_mm}
            if impedance_result else None
        ),
        "length_matching": matched_pairs if matched_pairs else None,
    }
