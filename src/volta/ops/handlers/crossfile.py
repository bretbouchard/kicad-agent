"""Cross-file handler implementations -- operations spanning multiple files.

Handlers receive (op, ir_map, base_dir) and return a result dict.
"""

import logging
from pathlib import Path
from typing import Any, Callable

logger = logging.getLogger(__name__)

_CROSSFILE_HANDLERS: dict[str, Callable] = {}


def register_crossfile(op_type: str) -> Callable:
    """Decorator to register a cross-file operation handler."""
    def decorator(fn: Callable) -> Callable:
        _CROSSFILE_HANDLERS[op_type] = fn
        return fn
    return decorator


@register_crossfile("propagate_symbol_change")
def _handle_propagate_symbol_change(
    op: Any, ir_map: dict[Path, Any], base_dir: Path
) -> dict[str, Any]:
    from volta.crossfile.propagation import (
        propagate_footprint_ref,
        propagate_symbol_ref,
    )
    from volta.ir.pcb_ir import PcbIR
    from volta.ir.schematic_ir import SchematicIR

    results = []
    for file_path, ir in ir_map.items():
        if isinstance(ir, SchematicIR):
            result = propagate_symbol_ref(ir, op.old_lib_id, op.new_lib_id)
            results.append({"file": str(file_path.name), "type": "schematic", "updated": result.updated_count})
        elif isinstance(ir, PcbIR):
            result = propagate_footprint_ref(ir, op.old_lib_id, op.new_lib_id)
            results.append({"file": str(file_path.name), "type": "pcb", "updated": result.updated_count})
    return {"files_modified": results, "total_updated": sum(r["updated"] for r in results)}


@register_crossfile("update_pcb_from_schematic")
def _handle_update_pcb_from_schematic(
    op: Any, ir_map: dict[Path, Any], base_dir: Path
) -> dict[str, Any]:
    """Sync PCB footprints and netlist from schematic source of truth.

    Uses kicad-cli to export a netlist from the schematic, parses it,
    and updates the PCB's pad-to-net assignments via raw S-expression
    manipulation (avoids kiutils serialization corruption).
    """
    from dataclasses import replace

    from volta.crossfile.schematic_sync import sync_pcb_from_netlist
    from volta.ir.pcb_ir import PcbIR
    from volta.ir.schematic_ir import SchematicIR

    # Identify schematic and PCB IRs by file extension
    sch_ir: SchematicIR | None = None
    pcb_ir: PcbIR | None = None
    sch_path: Path | None = None

    for file_path, ir in ir_map.items():
        if isinstance(ir, SchematicIR):
            sch_ir = ir
            sch_path = file_path
        elif isinstance(ir, PcbIR):
            pcb_ir = ir

    if sch_ir is None or pcb_ir is None:
        raise ValueError(
            "update_pcb_from_schematic requires both a schematic IR and a PCB IR"
        )
    if sch_path is None:
        raise ValueError("Schematic file path not found in ir_map")

    pcb_raw = pcb_ir._parse_result.raw_content

    new_raw, sync_result = sync_pcb_from_netlist(
        pcb_raw=pcb_raw,
        schematic_path=sch_path,
        base_dir=base_dir,
        sync_netlist=op.sync_netlist,
        sync_footprints=op.sync_footprints,
        add_new_components=op.add_new_components,
        remove_orphans=op.remove_orphans,
    )

    # Write modified content if changes were made
    if sync_result.has_changes:
        pcb_ir.commit_raw_content(new_raw)
        pcb_ir.mark_dirty("update_pcb_from_schematic")

    return {
        "added_footprints": sync_result.added_footprints,
        "updated_nets": sync_result.updated_nets,
        "removed_orphans": sync_result.removed_orphans,
        "added_net_defs": sync_result.added_net_defs,
        "footprint_ref_updates": sync_result.footprint_ref_updates,
        "pad_net_updates": sync_result.pad_net_updates,
        "has_changes": sync_result.has_changes,
    }


@register_crossfile("repopulate_pcb_from_schematic")
def _handle_repopulate_pcb(
    op: Any, ir_map: dict[Path, Any], base_dir: Path
) -> dict[str, Any]:
    """Full PCB repopulation from schematic netlist."""
    from volta.crossfile.schematic_sync import repopulate_pcb_from_schematic
    from volta.ir.pcb_ir import PcbIR
    from volta.ir.schematic_ir import SchematicIR

    sch_ir: SchematicIR | None = None
    pcb_ir: PcbIR | None = None
    sch_path: Path | None = None

    for file_path, ir in ir_map.items():
        if isinstance(ir, SchematicIR):
            sch_ir = ir
            sch_path = file_path
        elif isinstance(ir, PcbIR):
            pcb_ir = ir

    if sch_ir is None or pcb_ir is None:
        raise ValueError("repopulate_pcb_from_schematic requires both schematic and PCB IRs")
    if sch_path is None:
        raise ValueError("Schematic file path not found in ir_map")

    pcb_raw = pcb_ir._parse_result.raw_content

    new_raw, result = repopulate_pcb_from_schematic(
        pcb_raw=pcb_raw,
        schematic_path=sch_path,
        base_dir=base_dir,
        strip_routing=op.strip_routing,
        strip_zones=op.strip_zones,
        remove_orphans=op.remove_orphans,
        auto_place=op.auto_place,
        assign_nets=op.assign_nets,
        placement_clearance=op.placement_clearance,
        board_width=op.board_width,
        board_height=op.board_height,
    )

    pcb_ir.commit_raw_content(new_raw)
    pcb_ir.mark_dirty("repopulate_pcb_from_schematic")

    return result


@register_crossfile("rebuild_pcb_nets")
def _handle_rebuild_pcb_nets(
    op: Any, ir_map: dict[Path, Any], base_dir: Path
) -> dict[str, Any]:
    """Rebuild PCB net table and pad assignments from schematic."""
    from volta.crossfile.schematic_sync import rebuild_pcb_nets
    from volta.ir.pcb_ir import PcbIR
    from volta.ir.schematic_ir import SchematicIR

    sch_ir: SchematicIR | None = None
    pcb_ir: PcbIR | None = None
    sch_path: Path | None = None

    for file_path, ir in ir_map.items():
        if isinstance(ir, SchematicIR):
            sch_ir = ir
            sch_path = file_path
        elif isinstance(ir, PcbIR):
            pcb_ir = ir

    if sch_ir is None or pcb_ir is None:
        raise ValueError("rebuild_pcb_nets requires both schematic and PCB IRs")
    if sch_path is None:
        raise ValueError("Schematic file path not found in ir_map")

    pcb_raw = pcb_ir._parse_result.raw_content

    new_raw, result = rebuild_pcb_nets(
        pcb_raw=pcb_raw,
        schematic_path=sch_path,
        base_dir=base_dir,
        strip_routing=op.strip_routing,
        ghost_refs=op.ghost_refs,
        remove_all_orphans=op.remove_all_orphans,
    )

    pcb_ir.commit_raw_content(new_raw)
    pcb_ir.mark_dirty("rebuild_pcb_nets")

    return result


@register_crossfile("safe_sync_pcb_from_schematic")
def _handle_safe_sync_pcb_from_schematic(
    op: Any, ir_map: dict[Path, Any], base_dir: Path
) -> dict[str, Any]:
    """NON-DESTRUCTIVE PCB sync — preserves routing, zones, placement by default.

    ae-26: Bridges the gap between update_pcb_from_schematic (which mutates
    pad nets + lib_ids but lacks explicit preserve flags + dry_run) and
    repopulate_pcb_from_schematic (which strips routing). This handler wraps
    sync_pcb_from_netlist with explicit safety flags + dry_run support.

    Uses raw S-expression manipulation via sync_pcb_from_netlist (no kiutils
    to_file — prevents KiCad 10 corruption per Phase 101 P0-003 lesson).
    """
    from volta.crossfile.schematic_sync import sync_pcb_from_netlist
    from volta.ir.pcb_ir import PcbIR
    from volta.ir.schematic_ir import SchematicIR

    sch_ir: SchematicIR | None = None
    pcb_ir: PcbIR | None = None
    sch_path: Path | None = None

    for file_path, ir in ir_map.items():
        if isinstance(ir, SchematicIR):
            sch_ir = ir
            sch_path = file_path
        elif isinstance(ir, PcbIR):
            pcb_ir = ir

    if sch_ir is None or pcb_ir is None:
        raise ValueError(
            "safe_sync_pcb_from_schematic requires both a schematic IR and a PCB IR"
        )
    if sch_path is None:
        raise ValueError("Schematic file path not found in ir_map")

    # Enforce preserve_* guarantees — these are the op's reason for existence.
    # If the user disabled any, warn but still proceed (the underlying
    # sync_pcb_from_netlist never touches routing/zones/placement anyway).
    if not op.preserve_routing:
        logger.warning(
            "safe_sync_pcb_from_schematic: preserve_routing=False has no effect — "
            "this op NEVER modifies (segment ...) or (via ...) blocks"
        )
    if not op.preserve_zones:
        logger.warning(
            "safe_sync_pcb_from_schematic: preserve_zones=False has no effect — "
            "this op NEVER modifies (zone ...) blocks"
        )
    if not op.preserve_placement:
        logger.warning(
            "safe_sync_pcb_from_schematic: preserve_placement=False has no effect — "
            "this op NEVER modifies (at X Y) in existing (footprint ...) blocks"
        )

    # update_references (REF** → real refs) requires timestamp matching between
    # netlist and PCB footprint paths. NetlistComponent doesn't yet extract
    # timestamps. Tracked as a follow-up enhancement.
    if op.update_references:
        logger.warning(
            "safe_sync_pcb_from_schematic: update_references=True is not yet "
            "implemented (requires netlist timestamp extraction). "
            "Reference designator updates (REF** → R1) will come in a follow-up. "
            "All other sync operations (pad nets, lib_ids, net defs) are functional."
        )

    pcb_raw = pcb_ir._parse_result.raw_content

    # Snapshot routing/zones before mutation for preserve_* verification
    segment_count_before = pcb_raw.count("(segment")
    via_count_before = pcb_raw.count("(via ")
    zone_count_before = pcb_raw.count("(zone")

    new_raw, sync_result = sync_pcb_from_netlist(
        pcb_raw=pcb_raw,
        schematic_path=sch_path,
        base_dir=base_dir,
        sync_netlist=op.update_pad_nets,
        sync_footprints=op.update_footprint_lib_ids,
        add_new_components=op.add_missing_footprints,
        remove_orphans=op.remove_orphans,
    )

    # Verify preserve_* invariants — defensive check
    segment_count_after = new_raw.count("(segment")
    via_count_after = new_raw.count("(via ")
    zone_count_after = new_raw.count("(zone")
    assert segment_count_after == segment_count_before, (
        f"PRESERVE ROUTING VIOLATION: segments changed {segment_count_before} → {segment_count_after}"
    )
    assert via_count_after == via_count_before, (
        f"PRESERVE ROUTING VIOLATION: vias changed {via_count_before} → {via_count_after}"
    )
    assert zone_count_after == zone_count_before, (
        f"PRESERVE ZONES VIOLATION: zones changed {zone_count_before} → {zone_count_after}"
    )

    if op.dry_run:
        return {
            "dry_run": True,
            "has_changes": sync_result.has_changes,
            "added_footprints": sync_result.added_footprints,
            "updated_nets": sync_result.updated_nets,
            "removed_orphans": sync_result.removed_orphans,
            "added_net_defs": sync_result.added_net_defs,
            "footprint_ref_updates": sync_result.footprint_ref_updates,
            "pad_net_updates": sync_result.pad_net_updates,
            "net_token_rewrites": sync_result.net_token_rewrites,
            "references_updated": 0,
            "footprint_lib_ids_updated": len(sync_result.footprint_ref_updates),
            "message": "Dry run — no file mutation. Reference designator updates not yet implemented.",
        }

    if sync_result.has_changes:
        pcb_ir.commit_raw_content(new_raw)
        pcb_ir.mark_dirty("safe_sync_pcb_from_schematic")

    return {
        "dry_run": False,
        "has_changes": sync_result.has_changes,
        "added_footprints": sync_result.added_footprints,
        "updated_nets": sync_result.updated_nets,
        "removed_orphans": sync_result.removed_orphans,
        "added_net_defs": sync_result.added_net_defs,
        "footprint_ref_updates": sync_result.footprint_ref_updates,
        "pad_net_updates": sync_result.pad_net_updates,
        "net_token_rewrites": sync_result.net_token_rewrites,
        "references_updated": 0,
        "footprint_lib_ids_updated": len(sync_result.footprint_ref_updates),
        "routing_preserved": segment_count_before == segment_count_after,
        "zones_preserved": zone_count_before == zone_count_after,
    }
