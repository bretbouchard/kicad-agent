"""Unified operation registry with metadata and query functions.

Provides a central catalog of all 98 KiCad operations with rich metadata
including category, file types, read-only status, scope, and dependencies.
Used by MCP server, LLM tool selection, and validation gates.

The registry is validated against the Operation discriminated union in
schema.py to catch drift between registered operations and schema definitions.
"""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel


class OpMeta(BaseModel):
    """Metadata for a single KiCad operation type.

    Attributes:
        op_type: Unique operation identifier (matches schema op_type discriminator).
        category: Functional category for grouping (e.g. 'component', 'wire', 'pcb').
        description: Human-readable description of what the operation does.
        file_types: List of file suffixes or names this operation targets.
        is_readonly: True if the operation never modifies files.
        scope: Execution scope -- single_point, single_file, or multi_file.
        requires: List of prerequisite op_types that must run first.
        conflicts: List of op_types that conflict with this one.
    """

    op_type: str
    category: str
    description: str
    file_types: list[str]
    is_readonly: bool
    scope: Literal["single_point", "single_file", "multi_file"]
    requires: list[str]
    conflicts: list[str]


# ---------------------------------------------------------------------------
# Registry population from catalog data
# ---------------------------------------------------------------------------

_RAW_CATALOG: dict[str, dict] = {
    "add_component": {
        "category": "component",
        "description": "Add a component to a schematic or PCB file",
        "file_types": [".kicad_sch", ".kicad_pcb"],
        "is_readonly": False,
        "scope": "single_point",
        "requires": [],
        "conflicts": [],
    },
    "remove_component": {
        "category": "component",
        "description": "Remove a component by reference designator",
        "file_types": [".kicad_sch"],
        "is_readonly": False,
        "scope": "single_point",
        "requires": [],
        "conflicts": [],
    },
    "move_component": {
        "category": "component",
        "description": "Move a component to a new position",
        "file_types": [".kicad_sch"],
        "is_readonly": False,
        "scope": "single_point",
        "requires": [],
        "conflicts": [],
    },
    "modify_property": {
        "category": "component",
        "description": "Modify a component property (value, footprint, reference, custom field)",
        "file_types": [".kicad_sch"],
        "is_readonly": False,
        "scope": "single_point",
        "requires": [],
        "conflicts": [],
    },
    "duplicate_component": {
        "category": "component",
        "description": "Duplicate a component with fresh UUID and incremented reference",
        "file_types": [".kicad_sch"],
        "is_readonly": False,
        "scope": "single_point",
        "requires": [],
        "conflicts": [],
    },
    "array_replicate": {
        "category": "component",
        "description": "Replicate a component in a linear, circular, or matrix array pattern",
        "file_types": [".kicad_sch"],
        "is_readonly": False,
        "scope": "multi_file",
        "requires": [],
        "conflicts": [],
    },
    "add_net": {
        "category": "net",
        "description": "Add a net to a PCB",
        "file_types": [".kicad_pcb"],
        "is_readonly": False,
        "scope": "single_file",
        "requires": [],
        "conflicts": [],
    },
    "remove_net": {
        "category": "net",
        "description": "Remove a net from a PCB, disconnecting all pads",
        "file_types": [".kicad_pcb"],
        "is_readonly": False,
        "scope": "single_file",
        "requires": [],
        "conflicts": [],
    },
    "rename_net": {
        "category": "net",
        "description": "Rename a net, propagating to all connected pads",
        "file_types": [".kicad_pcb"],
        "is_readonly": False,
        "scope": "single_file",
        "requires": [],
        "conflicts": [],
    },
    "renumber_refs": {
        "category": "reference",
        "description": "Renumber component references with configurable prefix and sequencing",
        "file_types": [".kicad_sch"],
        "is_readonly": False,
        "scope": "single_file",
        "requires": [],
        "conflicts": [],
    },
    "validate_refs": {
        "category": "reference",
        "description": "Validate that all component references are unique",
        "file_types": [".kicad_sch"],
        "is_readonly": True,
        "scope": "single_file",
        "requires": [],
        "conflicts": [],
    },
    "annotate": {
        "category": "reference",
        "description": "Auto-assign references to unannotated components (refs ending in '?')",
        "file_types": [".kicad_sch"],
        "is_readonly": False,
        "scope": "single_file",
        "requires": [],
        "conflicts": [],
    },
    "cross_ref_check": {
        "category": "reference",
        "description": "Verify all symbol libIds resolve to entries in the embedded libSymbols",
        "file_types": [".kicad_sch"],
        "is_readonly": True,
        "scope": "single_file",
        "requires": [],
        "conflicts": [],
    },
    "assign_footprint": {
        "category": "footprint",
        "description": "Assign a footprint to a schematic component",
        "file_types": [".kicad_sch"],
        "is_readonly": False,
        "scope": "single_point",
        "requires": [],
        "conflicts": [],
    },
    "swap_footprint": {
        "category": "footprint",
        "description": "Swap a PCB footprint while preserving pad-to-net connections",
        "file_types": [".kicad_pcb"],
        "is_readonly": False,
        "scope": "single_point",
        "requires": [],
        "conflicts": [],
    },
    "validate_footprint": {
        "category": "footprint",
        "description": "Validate that a footprint exists in the available libraries",
        "file_types": [".kicad_sch", ".kicad_pcb"],
        "is_readonly": True,
        "scope": "single_point",
        "requires": [],
        "conflicts": [],
    },
    "verify_pin_map": {
        "category": "footprint",
        "description": "Verify that symbol pin numbers match footprint pad numbers",
        "file_types": [".kicad_sch", ".kicad_pcb"],
        "is_readonly": True,
        "scope": "single_point",
        "requires": [],
        "conflicts": [],
    },
    "update_footprint_from_library": {
        "category": "footprint",
        "description": "Reload a PCB footprint's geometry from the library, preserving placement",
        "file_types": [".kicad_pcb"],
        "is_readonly": False,
        "scope": "single_point",
        "requires": [],
        "conflicts": [],
    },
    "add_wire": {
        "category": "wire",
        "description": "Add a wire segment between two points in a schematic",
        "file_types": [".kicad_sch"],
        "is_readonly": False,
        "scope": "single_point",
        "requires": [],
        "conflicts": [],
    },
    "add_label": {
        "category": "wire",
        "description": "Add a net label to a schematic (local, global, or hierarchical)",
        "file_types": [".kicad_sch"],
        "is_readonly": False,
        "scope": "single_point",
        "requires": [],
        "conflicts": [],
    },
    "add_power": {
        "category": "wire",
        "description": "Add a power symbol to a schematic (e.g. +5V, GND, +3V3)",
        "file_types": [".kicad_sch"],
        "is_readonly": False,
        "scope": "single_point",
        "requires": [],
        "conflicts": [],
    },
    "add_no_connect": {
        "category": "wire",
        "description": "Add a no-connect flag to a schematic pin",
        "file_types": [".kicad_sch"],
        "is_readonly": False,
        "scope": "single_point",
        "requires": [],
        "conflicts": [],
    },
    "add_junction": {
        "category": "wire",
        "description": "Add a junction dot at a wire intersection in a schematic",
        "file_types": [".kicad_sch"],
        "is_readonly": False,
        "scope": "single_point",
        "requires": [],
        "conflicts": [],
    },
    "remove_wire": {
        "category": "remove",
        "description": "Remove a wire segment by UUID",
        "file_types": [".kicad_sch"],
        "is_readonly": False,
        "scope": "single_point",
        "requires": [],
        "conflicts": [],
    },
    "remove_label": {
        "category": "remove",
        "description": "Remove a net label by UUID",
        "file_types": [".kicad_sch"],
        "is_readonly": False,
        "scope": "single_point",
        "requires": [],
        "conflicts": [],
    },
    "remove_labels": {
        "category": "remove",
        "description": "Batch remove labels by type and/or name",
        "file_types": [".kicad_sch"],
        "is_readonly": False,
        "scope": "single_file",
        "requires": [],
        "conflicts": [],
    },
    "remove_junction": {
        "category": "remove",
        "description": "Remove a junction dot by UUID",
        "file_types": [".kicad_sch"],
        "is_readonly": False,
        "scope": "single_point",
        "requires": [],
        "conflicts": [],
    },
    "remove_no_connect": {
        "category": "remove",
        "description": "Remove a no-connect flag by UUID",
        "file_types": [".kicad_sch"],
        "is_readonly": False,
        "scope": "single_point",
        "requires": [],
        "conflicts": [],
    },
    "query_connectivity": {
        "category": "query",
        "description": "Query PCB connectivity via NetGraph",
        "file_types": [".kicad_pcb"],
        "is_readonly": True,
        "scope": "single_file",
        "requires": [],
        "conflicts": [],
    },
    "add_lib_entry": {
        "category": "library",
        "description": "Add a library entry to sym-lib-table or fp-lib-table",
        "file_types": ["sym-lib-table", "fp-lib-table"],
        "is_readonly": False,
        "scope": "single_file",
        "requires": [],
        "conflicts": [],
    },
    "remove_lib_entry": {
        "category": "library",
        "description": "Remove a library entry from sym-lib-table or fp-lib-table",
        "file_types": ["sym-lib-table", "fp-lib-table"],
        "is_readonly": False,
        "scope": "single_file",
        "requires": [],
        "conflicts": [],
    },
    "list_lib_entries": {
        "category": "library",
        "description": "List all library entries in a sym-lib-table or fp-lib-table",
        "file_types": ["sym-lib-table", "fp-lib-table"],
        "is_readonly": True,
        "scope": "single_file",
        "requires": [],
        "conflicts": [],
    },
    "add_net_class": {
        "category": "pcb",
        "description": "Add a net class with track/via/clearance dimensions",
        "file_types": [".kicad_dru"],
        "is_readonly": False,
        "scope": "single_file",
        "requires": [],
        "conflicts": [],
    },
    "add_design_rule": {
        "category": "pcb",
        "description": "Add a custom DRC rule to .kicad_dru",
        "file_types": [".kicad_dru"],
        "is_readonly": False,
        "scope": "single_file",
        "requires": [],
        "conflicts": [],
    },
    "add_copper_zone": {
        "category": "pcb",
        "description": "Add a copper zone/ground pour to a PCB",
        "file_types": [".kicad_pcb"],
        "is_readonly": False,
        "scope": "single_point",
        "requires": [],
        "conflicts": [],
    },
    "set_board_outline": {
        "category": "pcb",
        "description": "Define PCB board shape as a rectangle on Edge.Cuts",
        "file_types": [".kicad_pcb"],
        "is_readonly": False,
        "scope": "single_file",
        "requires": [],
        "conflicts": [],
    },
    "assign_net_class": {
        "category": "pcb",
        "description": "Assign a net class to a specific net in the PCB",
        "file_types": [".kicad_pcb"],
        "is_readonly": False,
        "scope": "single_point",
        "requires": [],
        "conflicts": [],
    },
    "move_footprint": {
        "category": "pcb",
        "description": "Move a footprint to a new position on the PCB",
        "file_types": [".kicad_pcb"],
        "is_readonly": False,
        "scope": "single_point",
        "requires": [],
        "conflicts": [],
    },
    "batch_expand_footprints": {
        "category": "pcb",
        "description": "Expand all synthetic (geometry-less) footprints from their libraries, loading full pad/courtyard/silkscreen data",
        "file_types": [".kicad_pcb"],
        "is_readonly": False,
        "scope": "single_file",
        "requires": [],
        "conflicts": [],
    },
    "auto_route": {
        "category": "pcb",
        "description": "Auto-route nets on a PCB using A* pathfinding",
        "file_types": [".kicad_pcb"],
        "is_readonly": False,
        "scope": "single_file",
        "requires": [],
        "conflicts": [],
    },
    "import_ses": {
        "category": "pcb",
        "description": "Import a Freerouting SES routing result into a KiCad PCB",
        "file_types": [".kicad_pcb"],
        "is_readonly": False,
        "scope": "single_file",
        "requires": [],
        "conflicts": [],
    },
    "auto_route_manhattan": {
        "category": "pcb",
        "description": "Generate Manhattan-style L-shaped routing segments for a PCB",
        "file_types": [".kicad_pcb"],
        "is_readonly": False,
        "scope": "single_file",
        "requires": [],
        "conflicts": [],
    },
    "auto_place": {
        "category": "pcb",
        "description": "Auto-place components on a PCB with overlap-free guarantee",
        "file_types": [".kicad_pcb"],
        "is_readonly": False,
        "scope": "single_file",
        "requires": [],
        "conflicts": ["move_component"],
    },
    "auto_place_zoned": {
        "category": "pcb",
        "description": "Auto-place components on a PCB with zone-aware packing",
        "file_types": [".kicad_pcb"],
        "is_readonly": False,
        "scope": "single_file",
        "requires": [],
        "conflicts": ["move_component", "auto_place"],
    },
    "export_positions": {
        "category": "pcb",
        "description": "Export footprint positions from a PCB to a JSON file",
        "file_types": [".kicad_pcb"],
        "is_readonly": True,
        "scope": "single_file",
        "requires": [],
        "conflicts": [],
    },
    "import_positions": {
        "category": "pcb",
        "description": "Import footprint positions from a JSON file and apply to a PCB",
        "file_types": [".kicad_pcb"],
        "is_readonly": False,
        "scope": "single_file",
        "requires": [],
        "conflicts": ["move_component", "auto_place"],
    },
    "route_diff_pair": {
        "category": "pcb",
        "description": "Route a differential pair with impedance-controlled spacing and length matching",
        "file_types": [".kicad_pcb"],
        "is_readonly": False,
        "scope": "single_file",
        "requires": [],
        "conflicts": [],
    },
    "match_lengths": {
        "category": "pcb",
        "description": "Match route lengths between net pairs via serpentine tuning",
        "file_types": [".kicad_pcb"],
        "is_readonly": False,
        "scope": "single_file",
        "requires": [],
        "conflicts": [],
    },
    "analyze_split_plane": {
        "category": "pcb",
        "description": "Analyze split power/ground planes for boundary crossings",
        "file_types": [".kicad_pcb"],
        "is_readonly": True,
        "scope": "single_file",
        "requires": [],
        "conflicts": [],
    },
    "fix_silkscreen_over_copper": {
        "category": "pcb",
        "description": "Detect and optionally relocate silkscreen text overlapping copper",
        "file_types": [".kicad_pcb"],
        "is_readonly": False,
        "scope": "single_file",
        "requires": [],
        "conflicts": [],
    },
    "modify_net_class": {
        "category": "pcb",
        "description": "Modify an existing net class in .kicad_dru",
        "file_types": [".kicad_dru"],
        "is_readonly": False,
        "scope": "single_file",
        "requires": [],
        "conflicts": [],
    },
    "remove_net_class": {
        "category": "pcb",
        "description": "Remove a net class from .kicad_dru",
        "file_types": [".kicad_dru"],
        "is_readonly": False,
        "scope": "single_file",
        "requires": [],
        "conflicts": [],
    },
    "list_net_classes": {
        "category": "pcb",
        "description": "List all net classes in a .kicad_dru file",
        "file_types": [".kicad_dru"],
        "is_readonly": True,
        "scope": "single_file",
        "requires": [],
        "conflicts": [],
    },
    "modify_design_rule": {
        "category": "pcb",
        "description": "Modify an existing custom DRC rule in .kicad_dru",
        "file_types": [".kicad_dru"],
        "is_readonly": False,
        "scope": "single_file",
        "requires": [],
        "conflicts": [],
    },
    "remove_design_rule": {
        "category": "pcb",
        "description": "Remove a custom DRC rule from .kicad_dru",
        "file_types": [".kicad_dru"],
        "is_readonly": False,
        "scope": "single_file",
        "requires": [],
        "conflicts": [],
    },
    "list_design_rules": {
        "category": "pcb",
        "description": "List all custom DRC rules in a .kicad_dru file",
        "file_types": [".kicad_dru"],
        "is_readonly": True,
        "scope": "single_file",
        "requires": [],
        "conflicts": [],
    },
    "modify_project_settings": {
        "category": "pcb",
        "description": "Modify settings in a .kicad_pro project file",
        "file_types": [".kicad_pro"],
        "is_readonly": False,
        "scope": "single_file",
        "requires": [],
        "conflicts": [],
    },
    "modify_copper_zone": {
        "category": "pcb",
        "description": "Modify an existing copper zone on a PCB",
        "file_types": [".kicad_pcb"],
        "is_readonly": False,
        "scope": "single_point",
        "requires": [],
        "conflicts": [],
    },
    "remove_copper_zone": {
        "category": "pcb",
        "description": "Remove a copper zone from a PCB",
        "file_types": [".kicad_pcb"],
        "is_readonly": False,
        "scope": "single_point",
        "requires": [],
        "conflicts": [],
    },
    "delete_copper_zone": {
        "category": "pcb",
        "description": "Delete a copper zone by UUID (Phase 101-06 alias of remove_copper_zone)",
        "file_types": [".kicad_pcb"],
        "is_readonly": False,
        "scope": "single_point",
        "requires": [],
        "conflicts": [],
    },
    "refill_copper_zone": {
        "category": "pcb",
        "description": "Strip filled polygon data from a zone so KiCad refills it",
        "file_types": [".kicad_pcb"],
        "is_readonly": False,
        "scope": "single_point",
        "requires": [],
        "conflicts": [],
    },
    "modify_zone_polygon": {
        "category": "pcb",
        "description": "Replace the outline polygon of an existing copper zone",
        "file_types": [".kicad_pcb"],
        "is_readonly": False,
        "scope": "single_point",
        "requires": [],
        "conflicts": [],
    },
    "add_keepout_area": {
        "category": "pcb",
        "description": "Add a keepout area to a PCB",
        "file_types": [".kicad_pcb"],
        "is_readonly": False,
        "scope": "single_point",
        "requires": [],
        "conflicts": [],
    },
    "add_zone_keepout": {
        "category": "pcb",
        "description": "Add a zone keepout with optional (rule (clearance N)) wrapper (Phase 101-06)",
        "file_types": [".kicad_pcb"],
        "is_readonly": False,
        "scope": "single_point",
        "requires": [],
        "conflicts": [],
    },
    "remove_keepout_area": {
        "category": "pcb",
        "description": "Remove a keepout area from a PCB",
        "file_types": [".kicad_pcb"],
        "is_readonly": False,
        "scope": "single_point",
        "requires": [],
        "conflicts": [],
    },
    "validate_power_nets": {
        "category": "erc",
        "description": "Check all power pins have connected power symbols",
        "file_types": [".kicad_sch"],
        "is_readonly": True,
        "scope": "single_file",
        "requires": [],
        "conflicts": [],
    },
    "validate_schematic": {
        "category": "erc",
        "description": "Comprehensive schematic validation combining multiple checks",
        "file_types": [".kicad_sch"],
        "is_readonly": True,
        "scope": "single_file",
        "requires": [],
        "conflicts": [],
    },
    "pre_pcb_schematic_gate": {
        "category": "erc",
        "description": "Hard schematic readiness gate before PCB layout or transfer",
        "file_types": [".kicad_sch"],
        "is_readonly": True,
        "scope": "single_file",
        "requires": [],
        "conflicts": [],
    },
    "analyze_gaps": {
        "category": "gap",
        "description": "Analyze a PCB for routing gaps, DRC violations, and naming issues",
        "file_types": [".kicad_pcb"],
        "is_readonly": True,
        "scope": "single_file",
        "requires": [],
        "conflicts": [],
    },
    "fill_gaps": {
        "category": "gap",
        "description": "Run the gap-filling engine on a PCB",
        "file_types": [".kicad_pcb"],
        "is_readonly": False,
        "scope": "single_file",
        "requires": ["analyze_gaps"],
        "conflicts": [],
    },
    "fill_zones": {
        "category": "pcb",
        "description": "Fill copper zones on PCB using KiCad pcbnew API",
        "file_types": [".kicad_pcb"],
        "is_readonly": False,
        "scope": "single_file",
        "requires": [],
        "conflicts": [],
    },
    "strip_shorts": {
        "category": "pcb",
        "description": "Remove shorting track segments identified by DRC",
        "file_types": [".kicad_pcb"],
        "is_readonly": False,
        "scope": "single_file",
        "requires": [],
        "conflicts": [],
    },
    "remove_dangling_tracks": {
        "category": "pcb",
        "description": "Iteratively remove dangling tracks and vias from PCB",
        "file_types": [".kicad_pcb"],
        "is_readonly": False,
        "scope": "single_file",
        "requires": [],
        "conflicts": [],
    },
    "auto_route_freerouting": {
        "category": "pcb",
        "description": "Full auto-route pipeline: DSN export -> Freerouting -> SES import -> cleanup",
        "file_types": [".kicad_pcb"],
        "is_readonly": False,
        "scope": "single_file",
        "requires": [],
        "conflicts": ["auto_route"],
    },
    "parse_erc": {
        "category": "erc",
        "description": "Parse ERC results for a schematic file",
        "file_types": [".kicad_sch"],
        "is_readonly": True,
        "scope": "single_file",
        "requires": [],
        "conflicts": [],
    },
    "extract_violation_positions": {
        "category": "erc",
        "description": "Extract positions for a specific ERC violation type",
        "file_types": [".kicad_sch"],
        "is_readonly": True,
        "scope": "single_file",
        "requires": [],
        "conflicts": [],
    },
    "validate_hlabels": {
        "category": "erc",
        "description": "Validate hierarchical labels in a schematic",
        "file_types": [".kicad_sch"],
        "is_readonly": True,
        "scope": "single_file",
        "requires": [],
        "conflicts": [],
    },
    "create_schematic": {
        "category": "create",
        "description": "Create a new empty .kicad_sch file",
        "file_types": [".kicad_sch"],
        "is_readonly": False,
        "scope": "single_file",
        "requires": [],
        "conflicts": [],
    },
    "create_pcb": {
        "category": "create",
        "description": "Create a new empty .kicad_pcb file",
        "file_types": [".kicad_pcb"],
        "is_readonly": False,
        "scope": "single_file",
        "requires": [],
        "conflicts": [],
    },
    "create_project": {
        "category": "create",
        "description": "Create a new empty .kicad_pro project file",
        "file_types": [".kicad_pro"],
        "is_readonly": False,
        "scope": "single_file",
        "requires": [],
        "conflicts": [],
    },
    "create_symbol": {
        "category": "create",
        "description": "Create a new symbol definition in a .kicad_sym library file",
        "file_types": [".kicad_sym"],
        "is_readonly": False,
        "scope": "single_file",
        "requires": [],
        "conflicts": [],
    },
    "embed_symbol": {
        "category": "create",
        "description": "Embed a symbol definition from a .kicad_sym library into a schematic's lib_symbols",
        "file_types": [".kicad_sch"],
        "is_readonly": False,
        "scope": "single_point",
        "requires": [],
        "conflicts": [],
    },
    "create_footprint": {
        "category": "create",
        "description": "Create a new footprint definition in a .kicad_mod file",
        "file_types": [".kicad_mod"],
        "is_readonly": False,
        "scope": "single_file",
        "requires": [],
        "conflicts": [],
    },
    "repair_schematic": {
        "category": "repair",
        "description": "Auto-repair common ERC errors in a schematic",
        "file_types": [".kicad_sch"],
        "is_readonly": False,
        "scope": "single_file",
        "requires": ["parse_erc"],
        "conflicts": ["remove_component"],
    },
    "convert_kicad6_to_10": {
        "category": "create",
        "description": "Convert a KiCad 5/6 format schematic to KiCad 10 format",
        "file_types": [".kicad_sch"],
        "is_readonly": False,
        "scope": "single_file",
        "requires": [],
        "conflicts": [],
    },
    "snap_to_grid": {
        "category": "repair",
        "description": "Snap off-grid wire endpoints to the nearest grid point",
        "file_types": [".kicad_sch"],
        "is_readonly": False,
        "scope": "single_file",
        "requires": [],
        "conflicts": [],
    },
    "snap_components_to_grid": {
        "category": "component",
        "description": "Snap all or filtered components to grid-aligned positions",
        "file_types": [".kicad_sch"],
        "is_readonly": False,
        "scope": "single_file",
        "requires": [],
        "conflicts": [],
    },
    "add_power_flag": {
        "category": "wire",
        "description": "Place PWR_FLAG symbols at power_pin_not_driven ERC violation positions",
        "file_types": [".kicad_sch"],
        "is_readonly": False,
        "scope": "single_file",
        "requires": [],
        "conflicts": [],
    },
    "rebuild_root_sheet": {
        "category": "sheet",
        "description": "Rebuild root schematic sheet pins from sub-sheet hierarchical labels",
        "file_types": [".kicad_sch"],
        "is_readonly": False,
        "scope": "single_file",
        "requires": [],
        "conflicts": [],
    },
    "swap_symbol": {
        "category": "component",
        "description": "Swap a component's symbol (lib_id) in-place, preserving position and properties",
        "file_types": [".kicad_sch"],
        "is_readonly": False,
        "scope": "single_point",
        "requires": [],
        "conflicts": [],
    },
    "update_symbols_from_library": {
        "category": "library",
        "description": "Re-embed all mismatched symbols from their libraries",
        "file_types": [".kicad_sch"],
        "is_readonly": False,
        "scope": "single_file",
        "requires": [],
        "conflicts": [],
    },
    "fix_shorted_nets": {
        "category": "repair",
        "description": "Fix positions where multiple net names connect to the same items",
        "file_types": [".kicad_sch"],
        "is_readonly": False,
        "scope": "single_file",
        "requires": ["parse_erc"],
        "conflicts": [],
    },
    "fix_pin_type_mismatches": {
        "category": "repair",
        "description": "Fix pin electrical type mismatches in embedded lib_symbols",
        "file_types": [".kicad_sch"],
        "is_readonly": False,
        "scope": "single_file",
        "requires": [],
        "conflicts": [],
    },
    "place_missing_units": {
        "category": "repair",
        "description": "Place all unplaced units of multi-unit symbols",
        "file_types": [".kicad_sch"],
        "is_readonly": False,
        "scope": "single_file",
        "requires": [],
        "conflicts": [],
    },
    "remove_dangling_wires": {
        "category": "repair",
        "description": "Remove wire segments with unconnected endpoints",
        "file_types": [".kicad_sch"],
        "is_readonly": False,
        "scope": "single_file",
        "requires": [],
        "conflicts": [],
    },
    "break_wire_shorts": {
        "category": "repair",
        "description": "Break wire segments that short different nets together",
        "file_types": [".kicad_sch"],
        "is_readonly": False,
        "scope": "single_file",
        "requires": [],
        "conflicts": [],
    },
    "resolve_shorted_nets": {
        "category": "repair",
        "description": "Atomically resolve shorted nets with wire breaking and label fixing",
        "file_types": [".kicad_sch"],
        "is_readonly": False,
        "scope": "single_file",
        "requires": ["parse_erc"],
        "conflicts": [],
    },
    "place_net_labels": {
        "category": "routing",
        "description": "Place net labels on IC pins based on a pin-to-net mapping",
        "file_types": [".kicad_sch"],
        "is_readonly": False,
        "scope": "single_file",
        "requires": [],
        "conflicts": [],
    },
    "fix_net_short": {
        "category": "repair",
        "description": "Fix a shorted net by breaking wires and re-labeling affected segments",
        "file_types": [".kicad_sch"],
        "is_readonly": False,
        "scope": "single_file",
        "requires": [],
        "conflicts": [],
    },
    "rename_net_label": {
        "category": "repair",
        "description": "Rename a net label across a schematic with cross-sheet consistency",
        "file_types": [".kicad_sch"],
        "is_readonly": False,
        "scope": "single_file",
        "requires": [],
        "conflicts": [],
    },
    "add_sheet": {
        "category": "sheet",
        "description": "Add a hierarchical sheet to a schematic",
        "file_types": [".kicad_sch"],
        "is_readonly": False,
        "scope": "single_point",
        "requires": [],
        "conflicts": [],
    },
    "add_sheet_pin": {
        "category": "sheet",
        "description": "Add a pin to a hierarchical sheet",
        "file_types": [".kicad_sch"],
        "is_readonly": False,
        "scope": "single_point",
        "requires": [],
        "conflicts": [],
    },
    "navigate_hierarchy": {
        "category": "sheet",
        "description": "Navigate hierarchical schematic sheets",
        "file_types": [".kicad_sch"],
        "is_readonly": True,
        "scope": "single_file",
        "requires": [],
        "conflicts": [],
    },
    "propagate_symbol_change": {
        "category": "crossfile",
        "description": "Propagate a symbol/footprint library reference change across multiple files atomically",
        "file_types": [".kicad_sch", ".kicad_pcb"],
        "is_readonly": False,
        "scope": "multi_file",
        "requires": [],
        "conflicts": [],
    },
    "update_pcb_from_schematic": {
        "category": "crossfile",
        "description": "Synchronize PCB footprints and netlist from schematic source of truth via kicad-cli netlist export",
        "file_types": [".kicad_sch", ".kicad_pcb"],
        "is_readonly": False,
        "scope": "multi_file",
        "requires": ["kicad-cli"],
        "conflicts": [],
    },
    "repopulate_pcb_from_schematic": {
        "category": "crossfile",
        "description": "Re-populate a PCB with footprints from schematic netlist, auto-place, and assign nets",
        "file_types": [".kicad_sch", ".kicad_pcb"],
        "is_readonly": False,
        "scope": "multi_file",
        "requires": ["kicad-cli"],
        "conflicts": [],
    },
    "rebuild_pcb_nets": {
        "category": "crossfile",
        "description": "Rebuild PCB net table and pad net assignments from schematic netlist",
        "file_types": [".kicad_sch", ".kicad_pcb"],
        "is_readonly": False,
        "scope": "multi_file",
        "requires": ["kicad-cli"],
        "conflicts": [],
    },
    "resolve_pin_positions": {
        "category": "routing",
        "description": "Resolve absolute pin positions for schematic components",
        "file_types": [".kicad_sch"],
        "is_readonly": True,
        "scope": "single_file",
        "requires": [],
        "conflicts": [],
    },
    "detect_routing_collisions": {
        "category": "routing",
        "description": "Detect collision zones in a schematic where wires would short pins",
        "file_types": [".kicad_sch"],
        "is_readonly": True,
        "scope": "single_file",
        "requires": [],
        "conflicts": [],
    },
    "detect_pin_overlaps": {
        "category": "routing",
        "description": "Detect pins from different nets at the exact same position",
        "file_types": [".kicad_sch"],
        "is_readonly": True,
        "scope": "single_file",
        "requires": [],
        "conflicts": [],
    },
    "connect_pins": {
        "category": "routing",
        "description": "Connect pins into a net with wire/label generation",
        "file_types": [".kicad_sch"],
        "is_readonly": False,
        "scope": "single_file",
        "requires": ["resolve_pin_positions"],
        "conflicts": [],
    },
    "batch_connect": {
        "category": "routing",
        "description": "Batch-connect multiple nets in a single call",
        "file_types": [".kicad_sch"],
        "is_readonly": False,
        "scope": "single_file",
        "requires": ["resolve_pin_positions", "detect_routing_collisions"],
        "conflicts": [],
    },
    "regenerate_wiring": {
        "category": "routing",
        "description": "Strip all wires/labels/no_connects and regenerate from netlist definition",
        "file_types": [".kicad_sch"],
        "is_readonly": False,
        "scope": "single_file",
        "requires": ["resolve_pin_positions"],
        "conflicts": [],
    },
    "extract_nets": {
        "category": "schematic_intel",
        "description": "Extract complete net topology from a schematic file",
        "file_types": [".kicad_sch"],
        "is_readonly": True,
        "scope": "single_file",
        "requires": [],
        "conflicts": [],
    },
    "infer_connectivity": {
        "category": "schematic_intel",
        "description": "Infer net connectivity from partial wiring with confidence scoring",
        "file_types": [".kicad_sch"],
        "is_readonly": True,
        "scope": "single_file",
        "requires": [],
        "conflicts": [],
    },
    "detect_net_conflicts": {
        "category": "schematic_intel",
        "description": "Detect net naming conflicts in a schematic file",
        "file_types": [".kicad_sch"],
        "is_readonly": True,
        "scope": "single_file",
        "requires": [],
        "conflicts": [],
    },
    "suggest_net_names": {
        "category": "schematic_intel",
        "description": "Suggest canonical net names based on labels and topology",
        "file_types": [".kicad_sch"],
        "is_readonly": True,
        "scope": "single_file",
        "requires": [],
        "conflicts": [],
    },
    "detect_net_shorts": {
        "category": "schematic_intel",
        "description": "Detect shorted nets via union-find connectivity analysis",
        "file_types": [".kicad_sch"],
        "is_readonly": True,
        "scope": "single_file",
        "requires": [],
        "conflicts": [],
    },
    "analyze_ground_topology": {
        "category": "schematic_intel",
        "description": "Analyze ground net merging/splitting for mixed-signal designs",
        "file_types": [".kicad_sch"],
        "is_readonly": True,
        "scope": "single_file",
        "requires": [],
        "conflicts": [],
    },
    "trace_net_from_label": {
        "category": "schematic_intel",
        "description": "Trace all pins reachable from a label through schematic graph",
        "file_types": [".kicad_sch"],
        "is_readonly": True,
        "scope": "single_file",
        "requires": [],
        "conflicts": [],
    },
    "classify_violations": {
        "category": "erc_smart",
        "description": "Classify ERC violations into actionable categories",
        "file_types": [".kicad_sch"],
        "is_readonly": True,
        "scope": "single_file",
        "requires": [],
        "conflicts": [],
    },
    "diagnose_violations": {
        "category": "erc_smart",
        "description": "Diagnose root causes for fixable ERC violations and propose targeted fixes",
        "file_types": [".kicad_sch"],
        "is_readonly": True,
        "scope": "single_file",
        "requires": ["classify_violations"],
        "conflicts": [],
    },
    "erc_auto_fix": {
        "category": "erc_smart",
        "description": "Meta-operation: run ERC, dispatch repairs by violation type, iterate",
        "file_types": [".kicad_sch"],
        "is_readonly": False,
        "scope": "single_file",
        "requires": ["parse_erc"],
        "conflicts": [],
    },
    "erc_auto_fix_hierarchical": {
        "category": "erc_smart",
        "description": "Run ERC auto-fix across all sheets in a hierarchical schematic",
        "file_types": [".kicad_sch"],
        "is_readonly": False,
        "scope": "multi_file",
        "requires": ["parse_erc"],
        "conflicts": [],
    },
    # review_schematic was missing from the original catalog but exists in schema
    "review_schematic": {
        "category": "readability",
        "description": "Review schematic readability and generate SRS report with suggestions",
        "file_types": [".kicad_sch"],
        "is_readonly": True,
        "scope": "single_file",
        "requires": [],
        "conflicts": [],
    },
    "run_gate_check": {
        "category": "gate",
        "description": "Run a named design stage gate check (read-only, no side effects)",
        "file_types": [".kicad_sch", ".kicad_pcb"],
        "is_readonly": True,
        "scope": "multi_file",
        "requires": [],
        "conflicts": [],
    },
    "gate_status": {
        "category": "gate",
        "description": "Query current design stage and registered gate states",
        "file_types": [".kicad_sch", ".kicad_pcb"],
        "is_readonly": True,
        "scope": "multi_file",
        "requires": [],
        "conflicts": [],
    },
    "update_from_schematic": {
        "category": "pcb",
        "description": "Transfer schematic intent to PCB: validate contract, assign pad nets",
        "file_types": [".kicad_sch", ".kicad_pcb"],
        "is_readonly": False,
        "scope": "multi_file",
        "requires": ["parse_schematic"],
        "conflicts": [],
    },
    "set_constraints": {
        "category": "constraint",
        "description": "Set design constraints and propagate to .kicad_dru and sidecar file",
        "file_types": [".kicad_dru"],
        "is_readonly": False,
        "scope": "single_file",
        "requires": [],
        "conflicts": [],
    },
    "get_constraints": {
        "category": "constraint",
        "description": "Get current design constraints from sidecar file",
        "file_types": [".kicad_dru"],
        "is_readonly": True,
        "scope": "single_file",
        "requires": [],
        "conflicts": [],
    },
    "generate_bom": {
        "category": "manufacturing",
        "description": "Generate BOM with LCSC/JLCPCB part numbers from schematic",
        "file_types": [".kicad_sch"],
        "is_readonly": True,
        "scope": "single_file",
        "requires": [],
        "conflicts": [],
    },
    "add_track": {
        "category": "pcb",
        "description": "Add a single straight track segment to a PCB (KiCad 10 net format)",
        "file_types": [".kicad_pcb"],
        "is_readonly": False,
        "scope": "single_point",
        "requires": [],
        "conflicts": [],
    },
    "add_arc_track": {
        "category": "pcb",
        "description": "Add a single arc track segment to a PCB (KiCad 10 net format)",
        "file_types": [".kicad_pcb"],
        "is_readonly": False,
        "scope": "single_point",
        "requires": [],
        "conflicts": [],
    },
    "add_via": {
        "category": "pcb",
        "description": "Add a single via to a PCB (KiCad 10 net format, JLC 4-layer defaults)",
        "file_types": [".kicad_pcb"],
        "is_readonly": False,
        "scope": "single_point",
        "requires": [],
        "conflicts": [],
    },
    "delete_track": {
        "category": "pcb",
        "description": "Delete a straight track segment from a PCB by UUID",
        "file_types": [".kicad_pcb"],
        "is_readonly": False,
        "scope": "single_point",
        "requires": [],
        "conflicts": [],
    },
    "delete_via": {
        "category": "pcb",
        "description": "Delete a via from a PCB by UUID",
        "file_types": [".kicad_pcb"],
        "is_readonly": False,
        "scope": "single_point",
        "requires": [],
        "conflicts": [],
    },
    "move_track_endpoint": {
        "category": "pcb",
        "description": "Move the start or end point of a track segment by UUID",
        "file_types": [".kicad_pcb"],
        "is_readonly": False,
        "scope": "single_point",
        "requires": [],
        "conflicts": [],
    },
    "lock_track": {
        "category": "pcb",
        "description": "Lock a straight track segment by UUID (inject (locked) token)",
        "file_types": [".kicad_pcb"],
        "is_readonly": False,
        "scope": "single_point",
        "requires": [],
        "conflicts": [],
    },
    "lock_via": {
        "category": "pcb",
        "description": "Lock a via by UUID (inject (locked) token)",
        "file_types": [".kicad_pcb"],
        "is_readonly": False,
        "scope": "single_point",
        "requires": [],
        "conflicts": [],
    },
    "add_stitching_via_pattern": {
        "category": "pcb",
        "description": "Add a grid of stitching vias bounded by a region",
        "file_types": [".kicad_pcb"],
        "is_readonly": False,
        "scope": "single_point",
        "requires": [],
        "conflicts": [],
    },
    "place_component": {
        "category": "pcb",
        "description": "Place a component (footprint) on a PCB -- parametric SMD library for 0402/0603/0805 caps and resistors",
        "file_types": [".kicad_pcb"],
        "is_readonly": False,
        "scope": "single_point",
        "requires": [],
        "conflicts": [],
    },
}

OPERATION_REGISTRY: dict[str, OpMeta] = {
    op_type: OpMeta(op_type=op_type, **data)
    for op_type, data in _RAW_CATALOG.items()
}

# Known valid categories (derived from catalog)
VALID_CATEGORIES: frozenset[str] = frozenset(
    data["category"] for data in _RAW_CATALOG.values()
)


# ---------------------------------------------------------------------------
# Query functions
# ---------------------------------------------------------------------------


def get_operations_for_file_type(suffix: str) -> list[OpMeta]:
    """Return all operations that target a specific file type.

    Args:
        suffix: File extension (e.g. '.kicad_sch') or name (e.g. 'sym-lib-table').

    Returns:
        List of OpMeta for operations that support this file type.
    """
    return [
        meta for meta in OPERATION_REGISTRY.values()
        if suffix in meta.file_types
    ]


def get_readonly_operations() -> list[OpMeta]:
    """Return all read-only operations."""
    return [
        meta for meta in OPERATION_REGISTRY.values()
        if meta.is_readonly
    ]


def get_operation_dependencies(op_type: str) -> list[str]:
    """Return required prerequisite operations for a given op.

    Args:
        op_type: The operation type to query.

    Returns:
        List of prerequisite op_type strings.

    Raises:
        KeyError: If op_type is not in the registry.
    """
    meta = OPERATION_REGISTRY.get(op_type)
    if meta is None:
        raise KeyError(f"Unknown op_type: {op_type!r}")
    return list(meta.requires)


def get_operations_by_category(category: str) -> list[OpMeta]:
    """Return all operations in a given category.

    Args:
        category: Category name (e.g. 'component', 'wire', 'pcb').

    Returns:
        List of OpMeta for operations in this category.
    """
    return [
        meta for meta in OPERATION_REGISTRY.values()
        if meta.category == category
    ]


def validate_registry_completeness() -> dict:
    """Cross-validate registry against the Operation discriminated union.

    Compares the registry's op_types against the schema's discriminated union
    members to find any drift.

    Returns:
        Dict with:
            registry_count: Number of ops in the registry.
            schema_count: Number of ops in the schema.
            missing_from_registry: Op types in schema but not registry.
            extra_in_registry: Op types in registry but not schema.
    """
    import kicad_agent.ops.schema as schema_module

    schema_types: set[str] = set()
    for name in dir(schema_module):
        obj = getattr(schema_module, name)
        if hasattr(obj, "model_fields") and "op_type" in obj.model_fields:
            field = obj.model_fields["op_type"]
            if field.default is not None:
                schema_types.add(field.default)

    registry_types = set(OPERATION_REGISTRY.keys())

    return {
        "registry_count": len(registry_types),
        "schema_count": len(schema_types),
        "missing_from_registry": sorted(schema_types - registry_types),
        "extra_in_registry": sorted(registry_types - schema_types),
    }


def validate_dependencies(op_types: list[str]) -> list[str]:
    """Validate that all prerequisites are satisfied for a sequence of operations.

    Walks the op_types in execution order, tracking which ops have been "seen".
    For each op, checks that all its declared ``requires`` are in the seen set.
    Returns a list of missing prerequisite op_types.

    Args:
        op_types: List of op_type strings in planned execution order.

    Returns:
        List of missing prerequisite op_type strings. Empty if all deps satisfied.
    """
    seen: set[str] = set()
    missing: list[str] = []
    for op_type in op_types:
        meta = OPERATION_REGISTRY.get(op_type)
        if meta is None:
            # Unknown op -- skip (not our job to validate existence here)
            seen.add(op_type)
            continue
        for req in meta.requires:
            if req not in seen:
                missing.append(req)
        seen.add(op_type)
    return missing


def get_destructive_operations() -> list[OpMeta]:
    """Return all destructive operations (remove_* types and cross-file changes).

    Destructive operations permanently remove data. The canonical set includes
    all remove_* op_types and propagate_symbol_change (which overwrites refs).
    """
    return [
        meta for meta in OPERATION_REGISTRY.values()
        if meta.op_type.startswith("remove_") or meta.op_type == "propagate_symbol_change"
    ]


def validate_conflicts(op_types: list[str]) -> list[str]:
    """Validate that no conflicting operations appear in the same sequence.

    Walks the op_types in execution order, tracking which ops have been "seen".
    For each op, checks that none of its declared ``conflicts`` are in the seen set.
    Returns a list of conflict descriptions.

    Args:
        op_types: List of op_type strings in planned execution order.

    Returns:
        List of conflict description strings. Empty if no conflicts detected.
    """
    seen: set[str] = set()
    conflict_list: list[str] = []
    for op_type in op_types:
        meta = OPERATION_REGISTRY.get(op_type)
        if meta is not None:
            for conflict in meta.conflicts:
                if conflict in seen:
                    conflict_list.append(
                        f"{op_type!r} conflicts with {conflict!r}"
                    )
        seen.add(op_type)
    return conflict_list
