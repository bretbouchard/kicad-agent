"""Schematic mutation handlers -- operations that modify schematic files.

Handlers receive (op, SchematicIR, file_path) and return a result dict.
Each handler is registered via @register_schematic(op_type) and looked up
by the executor's _dispatch method.
"""

import dataclasses
import logging
from pathlib import Path
from typing import Any, Callable

from kicad_agent.ir.schematic_ir import SchematicIR

logger = logging.getLogger(__name__)

_SCHEMATIC_HANDLERS: dict[str, Callable] = {}


def register_schematic(op_type: str) -> Callable:
    """Decorator to register a schematic operation handler."""
    def decorator(fn: Callable) -> Callable:
        _SCHEMATIC_HANDLERS[op_type] = fn
        return fn
    return decorator


@register_schematic("add_component")
def _handle_add_component(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.add_component import add_component
    return add_component(op, ir, file_path)


@register_schematic("remove_component")
def _handle_remove_component(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.remove_component import remove_component
    return remove_component(op, ir)


@register_schematic("duplicate_component")
def _handle_duplicate_component(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.duplicate_component import duplicate_component
    return duplicate_component(op, ir)


@register_schematic("array_replicate")
def _handle_array_replicate(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.array_replicate import array_replicate
    return array_replicate(op, ir)


@register_schematic("move_component")
def _handle_move_component(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.move_component import move_component
    return move_component(op, ir, file_type=ir.file_type)


@register_schematic("snap_components_to_grid")
def _handle_snap_components_to_grid(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    """Snap component positions to the nearest grid point."""
    grid = op.grid_size

    def _snap(value: float) -> float:
        nearest = int(value / grid + 0.5)
        return round(nearest * grid, 2)

    sch = ir._parse_result.kiutils_obj
    snapped = 0
    skipped = 0
    moves: list[dict] = []

    for sym in sch.schematicSymbols:
        ref = getattr(sym, 'libId', '')  # fallback
        # Get reference from properties
        for prop in getattr(sym, 'properties', []):
            if prop.key == "Reference":
                ref = prop.value
                break

        # Apply prefix filter
        if op.prefix_filter and not ref.startswith(op.prefix_filter):
            skipped += 1
            continue

        old_x = sym.position.X
        old_y = sym.position.Y
        new_x = _snap(old_x)
        new_y = _snap(old_y)

        if new_x == old_x and new_y == old_y:
            skipped += 1
            continue

        moves.append({
            "reference": ref,
            "from": [old_x, old_y],
            "to": [new_x, new_y],
        })

        if not op.dry_run:
            sym.position.X = new_x
            sym.position.Y = new_y
            ir._record_mutation("snap_component", {
                "reference": ref,
                "from": [old_x, old_y],
                "to": [new_x, new_y],
                "grid": grid,
            })

        snapped += 1

    return {
        "snapped": snapped,
        "skipped": skipped,
        "dry_run": op.dry_run,
        "grid_size": grid,
        "moves": moves,
    }


@register_schematic("modify_property")
def _handle_modify_property(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.modify_property import modify_property
    return modify_property(op, ir)


@register_schematic("add_net")
def _handle_sch_add_net(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    net = ir.add_net(net_name=op.net_name, net_number=op.net_number)
    return {"net_name": net.name, "net_number": net.number}


@register_schematic("remove_net")
def _handle_sch_remove_net(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    ir.remove_net(net_name=op.net_name)
    return {"removed_net": op.net_name}


@register_schematic("rename_net")
def _handle_sch_rename_net(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    ir.rename_net(old_name=op.old_name, new_name=op.new_name)
    return {"old_name": op.old_name, "new_name": op.new_name}


@register_schematic("renumber_refs")
def _handle_renumber_refs(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    changes = ir.renumber_references(
        prefix=op.prefix, start_index=op.start_index, step=op.step
    )
    return {"changes": [{"old": o, "new": n} for o, n in changes]}


@register_schematic("annotate")
def _handle_annotate(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    changes = ir.annotate_components(prefix_filter=op.prefix_filter)
    return {"annotated": [{"old": o, "new": n} for o, n in changes]}


@register_schematic("assign_footprint")
def _handle_assign_footprint(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    ir.assign_footprint(reference=op.reference, footprint_lib_id=op.footprint_lib_id)
    return {"reference": op.reference, "footprint": op.footprint_lib_id}


@register_schematic("swap_footprint")
def _handle_sch_swap_footprint(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    return ir.swap_footprint(reference=op.reference, new_footprint_lib_id=op.new_footprint_lib_id)


@register_schematic("add_wire")
def _handle_add_wire(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    return ir.add_wire(
        start_x=op.start_x, start_y=op.start_y,
        end_x=op.end_x, end_y=op.end_y,
    )


@register_schematic("add_label")
def _handle_add_label(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    return ir.add_label(
        name=op.name,
        label_type=op.label_type,
        x=op.position.x, y=op.position.y,
        angle=op.position.angle,
        shape=op.shape,
    )


@register_schematic("add_power")
def _handle_add_power(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    return ir.add_power_symbol(
        name=op.name,
        x=op.position.x, y=op.position.y,
        angle=op.position.angle,
    )


@register_schematic("add_no_connect")
def _handle_add_no_connect(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    return ir.add_no_connect(x=op.position.x, y=op.position.y)


@register_schematic("add_junction")
def _handle_add_junction(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    return ir.add_junction(x=op.position.x, y=op.position.y)


@register_schematic("repair_schematic")
def _handle_repair_schematic(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.repair_erc import (
        place_no_connects,
        remove_orphaned_labels,
    )
    from kicad_agent.ops.repair_wires import (
        repair_wire_snapping,
        snap_to_grid,
    )
    details: dict[str, Any] = {}
    if op.snap_wires:
        details["wire_snapping"] = repair_wire_snapping(ir, file_path)
    if op.remove_orphans:
        details["orphan_removal"] = remove_orphaned_labels(ir)
    if op.place_no_connects:
        details["no_connects"] = place_no_connects(ir)
    if op.snap_to_grid:
        details["snap_to_grid"] = snap_to_grid(ir, grid_mm=0.01)
    return details


@register_schematic("convert_kicad6_to_10")
def _handle_convert_kicad6_to_10(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.format_convert import convert_kicad6_to_10
    content = file_path.read_text(encoding="utf-8")
    converted = convert_kicad6_to_10(content)
    file_path.write_text(converted, encoding="utf-8")
    return {"converted": True, "file_path": str(file_path)}


@register_schematic("snap_to_grid")
def _handle_snap_to_grid(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.repair_wires import snap_to_grid
    return snap_to_grid(ir, grid_mm=op.grid_mm)


@register_schematic("add_power_flag")
def _handle_add_power_flag(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.repair_erc import add_power_flags
    return add_power_flags(ir, file_path)


@register_schematic("rebuild_root_sheet")
def _handle_rebuild_root_sheet(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.root_sheet import rebuild_root_sheet
    results = rebuild_root_sheet(file_path)
    return {
        "sheets_processed": len(results),
        "details": [dataclasses.asdict(r) for r in results],
    }


@register_schematic("embed_symbol")
def _handle_embed_symbol(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.swap_symbol import embed_symbol
    return embed_symbol(op, ir, file_path)


@register_schematic("swap_symbol")
def _handle_swap_symbol(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.swap_symbol import swap_symbol
    return swap_symbol(op, ir, file_path)


@register_schematic("remove_wire")
def _handle_remove_wire(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.remove_ops import remove_wire
    return remove_wire(op, ir, file_path, file_path.parent)


@register_schematic("remove_label")
def _handle_remove_label(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.remove_ops import remove_label
    return remove_label(op, ir, file_path, file_path.parent)


@register_schematic("remove_labels")
def _handle_remove_labels(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    """Batch remove labels by type and/or name."""
    sch = ir._parse_result.kiutils_obj

    # Safety: require remove_all=True when no names filter
    if not op.names and not op.remove_all:
        raise ValueError(
            "remove_labels requires either 'names' filter or remove_all=True"
        )

    name_set = set(op.names) if op.names else None
    removed_count = 0
    removed_details: list[dict] = []

    def _remove_from_list(label_list: list, label_type: str) -> int:
        nonlocal removed_count
        to_remove = []
        for lbl in label_list:
            if name_set is not None and lbl.text not in name_set:
                continue
            to_remove.append(lbl)
        for lbl in to_remove:
            label_list.remove(lbl)
            removed_count += 1
            removed_details.append({
                "name": lbl.text, "label_type": label_type,
                "position": [lbl.position.X, lbl.position.Y],
            })
        return len(to_remove)

    if op.label_type is None or op.label_type == "global":
        _remove_from_list(sch.globalLabels, "global")
    if op.label_type is None or op.label_type == "local":
        _remove_from_list(sch.labels, "local")
    if op.label_type is None or op.label_type == "hierarchical":
        _remove_from_list(sch.hierarchicalLabels, "hierarchical")

    ir._record_mutation("remove_labels", {
        "label_type": op.label_type,
        "names": op.names,
        "removed_count": removed_count,
    })

    return {
        "removed_count": removed_count,
        "removed": removed_details,
    }


@register_schematic("remove_junction")
def _handle_remove_junction(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.remove_ops import remove_junction
    return remove_junction(op, ir, file_path, file_path.parent)


@register_schematic("remove_no_connect")
def _handle_remove_no_connect(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.remove_ops import remove_no_connect
    return remove_no_connect(op, ir, file_path, file_path.parent)


@register_schematic("add_sheet")
def _handle_add_sheet(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.sheet_ops import add_sheet
    return add_sheet(op, ir, file_path)


@register_schematic("add_sheet_pin")
def _handle_add_sheet_pin(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.sheet_ops import add_sheet_pin
    return add_sheet_pin(op, ir, file_path)


@register_schematic("update_symbols_from_library")
def _handle_update_symbols_from_library(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.repair_components import update_symbols_from_library
    return update_symbols_from_library(
        ir, file_path,
        references=op.references,
        dry_run=op.dry_run,
    )


@register_schematic("fix_shorted_nets")
def _handle_fix_shorted_nets(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.repair_nets import fix_shorted_nets
    return fix_shorted_nets(
        ir, file_path,
        strategy=op.strategy,
        keep_nets=op.keep_nets,
        dry_run=op.dry_run,
    )


@register_schematic("fix_pin_type_mismatches")
def _handle_fix_pin_type_mismatches(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.repair_components import fix_pin_type_mismatches
    return fix_pin_type_mismatches(
        ir, file_path,
        pin_type_map=op.pin_type_map,
        dry_run=op.dry_run,
    )


@register_schematic("place_missing_units")
def _handle_place_missing_units(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.repair_components import place_missing_units
    return place_missing_units(
        ir, file_path,
        references=op.references,
        offset_x=op.offset_x,
        offset_y=op.offset_y,
        dry_run=op.dry_run,
    )


@register_schematic("remove_dangling_wires")
def _handle_remove_dangling_wires(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.repair_wires import remove_dangling_wires
    return remove_dangling_wires(
        ir, file_path,
        max_length_mm=op.max_length_mm,
        dry_run=op.dry_run,
    )


@register_schematic("break_wire_shorts")
def _handle_break_wire_shorts(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.repair_wires import break_wire_shorts
    return break_wire_shorts(
        ir, file_path,
        net_pairs=op.net_pairs,
        strategy=op.strategy,
        dry_run=op.dry_run,
    )


@register_schematic("resolve_shorted_nets")
def _handle_resolve_shorted_nets(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.repair_nets import resolve_shorted_nets
    return resolve_shorted_nets(
        ir, file_path,
        strategy=op.strategy,
        keep_nets=op.keep_nets,
        dry_run=op.dry_run,
    )


@register_schematic("fix_net_short")
def _handle_fix_net_short(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.net_short_fixer import fix_net_short
    return fix_net_short(
        ir, file_path,
        net_a=op.net_a,
        net_b=op.net_b,
        dry_run=op.dry_run,
        remove_strategy=op.remove_strategy,
    )


@register_schematic("place_net_labels")
def _handle_place_net_labels(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.net_label_placer import place_net_labels
    return place_net_labels(
        ir, file_path,
        pin_map=op.pin_map,
        references=op.references,
        dry_run=op.dry_run,
    )


@register_schematic("erc_auto_fix")
def _handle_erc_auto_fix(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.ops.erc_auto_fix import erc_auto_fix
    return erc_auto_fix(
        ir, file_path,
        max_iterations=op.max_iterations,
        mode=op.mode,
        fix_classes=op.fix_classes,
        sheet_filter=op.sheet_filter,
    )


@register_schematic("erc_auto_fix_hierarchical")
def _handle_erc_auto_fix_hierarchical(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    # ir unused: hierarchical creates per-sheet IRs internally
    from kicad_agent.ops.erc_auto_fix import erc_auto_fix_hierarchical
    return erc_auto_fix_hierarchical(
        file_path,
        max_iterations=op.max_iterations,
        mode=op.mode,
    )


@register_schematic("connect_pins")
def _handle_connect_pins(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.schematic_routing.net_connector import NetConnector
    connector = NetConnector(file_path)
    result = connector.connect_pins(
        net_name=op.net_name,
        pins=[{"ref": p.ref, "pin": p.pin} for p in op.pins],
        strategy=op.strategy,
        collision_zones=[z.model_dump() for z in op.collision_zones],
        max_wire_length=op.max_wire_length,
    )
    # Apply generated wires and labels to the IR
    for wire in result.get("wires", []):
        ir.add_wire(
            start_x=wire["start"][0], start_y=wire["start"][1],
            end_x=wire["end"][0], end_y=wire["end"][1],
        )
    for label in result.get("labels", []):
        ir.add_label(
            name=op.net_name,
            label_type="local",
            x=label["position"][0], y=label["position"][1],
            angle=0, shape="input",
        )
    return {
        "net_name": op.net_name,
        "wires_generated": result["wires_generated"],
        "labels_generated": result["labels_generated"],
        "collisions_avoided": result["collisions_avoided"],
        "notes": result.get("notes", []),
    }


@register_schematic("batch_connect")
def _handle_batch_connect(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.schematic_routing.batch_wiring import BatchWiring
    wiring = BatchWiring(file_path)
    result = wiring.batch_connect(
        nets=[{"name": n.name, "pins": [{"ref": p.ref, "pin": p.pin} for p in n.pins]} for n in op.nets],
        global_labels=[{"name": g.name, "position": (g.position.x, g.position.y), "shape": g.shape} for g in op.global_labels],
        strategy=op.strategy,
        collision_zones=[z.model_dump() for z in op.collision_zones],
        auto_detect_collisions=op.auto_detect_collisions,
        max_wire_length=op.max_wire_length,
    )
    # Apply generated wires to IR
    for wire in result.get("wires", []):
        ir.add_wire(start_x=wire["start"][0], start_y=wire["start"][1],
                    end_x=wire["end"][0], end_y=wire["end"][1])
    # Apply generated labels to IR
    for label in result.get("labels", []):
        # Use net_name from label data, falling back to first net name,
        # then to "unnamed_net" as a last resort (never empty string).
        default_name = op.nets[0].name if op.nets else "unnamed_net"
        ir.add_label(name=label.get("net_name") or default_name,
                     label_type="local",
                     x=label["position"][0], y=label["position"][1],
                     angle=0, shape="input")
    # Apply global labels to IR
    for gl in result.get("global_labels", []):
        ir.add_label(name=gl["name"], label_type="global",
                     x=gl["position"][0], y=gl["position"][1],
                     angle=0, shape=gl.get("shape", "bidirectional"))
    return {
        "nets_processed": result["nets_processed"],
        "wires_generated": result["wires_generated"],
        "labels_generated": result["labels_generated"],
        "global_labels_generated": result["global_labels_generated"],
        "collisions_detected": result["collisions_detected"],
        "notes": result.get("notes", []),
    }


@register_schematic("regenerate_wiring")
def _handle_regenerate_wiring(op: Any, ir: SchematicIR, file_path: Path) -> dict[str, Any]:
    from kicad_agent.schematic_routing.batch_wiring import BatchWiring
    wiring = BatchWiring(file_path)
    result = wiring.regenerate_wiring(
        nets=[{"name": n.name, "pins": [{"ref": p.ref, "pin": p.pin} for p in n.pins]} for n in op.nets],
        global_labels=[{"name": g.name, "position": (g.position.x, g.position.y), "shape": g.shape} for g in op.global_labels],
        no_connect_positions=[{"x": p.x, "y": p.y} for p in op.no_connect_positions],
        strategy=op.strategy,
        collision_zones=[z.model_dump() for z in op.collision_zones],
        auto_detect_collisions=op.auto_detect_collisions,
        max_wire_length=op.max_wire_length,
    )
    # The regenerate_wiring method strips and reconnects via kiutils directly.
    # Mark IR as dirty so the executor's Transaction block re-serializes.
    ir.mark_dirty("regenerate_wiring")
    return {
        "removed": result["removed"],
        "generated": result["generated"],
        "notes": result.get("notes", []),
    }
