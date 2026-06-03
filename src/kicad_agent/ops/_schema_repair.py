"""Repair operation schemas -- repair, snap, fix shorted nets, fix pin type mismatches,
place missing units, remove dangling wires, break wire shorts, resolve shorted nets.

Six ops were reorganized to their correct category files (Plan 74-02):
- SwapSymbolOp -> _schema_component.py
- UpdateSymbolsFromLibraryOp -> _schema_library.py
- ConvertKicad6To10Op -> _schema_create.py
- AddPowerFlagOp -> _schema_wire.py
- RebuildRootSheetOp -> _schema_sheet.py
- PlaceNetLabelsOp -> _schema_schematic_routing.py
"""

from typing import Literal, Optional

from pydantic import BaseModel, Field

from kicad_agent.ops.schema import (
    TargetFile,
)


class RepairSchematicOp(BaseModel):
    """Auto-repair common ERC errors in a schematic.

    Runs wire snapping, orphaned label removal, and no-connect placement
    based on the enabled flags.

    Attributes:
        op_type: Discriminator literal ``"repair_schematic"``.
        target_file: Relative path to the target KiCad schematic file (H-01 validated).
        snap_wires: Snap wire endpoints to nearest pin positions (default True).
        remove_orphans: Remove labels not connected to any wire or pin (default True).
        place_no_connects: Place no-connect markers on unconnected pins (default True).
        snap_to_grid: Snap off-grid wire endpoints to nearest grid point (default False).
    """

    op_type: Literal["repair_schematic"] = "repair_schematic"
    target_file: TargetFile
    snap_wires: bool = Field(default=True, description="Snap wire endpoints to pins")
    remove_orphans: bool = Field(default=True, description="Remove orphaned labels")
    place_no_connects: bool = Field(default=True, description="Place no-connect markers")
    snap_to_grid: bool = Field(default=False, description="Snap off-grid wire endpoints to grid")


class SnapToGridOp(BaseModel):
    """Snap off-grid wire endpoints to the nearest grid point.

    SCHREPAIR-05: Grid-snapping with connectivity preservation.

    Attributes:
        op_type: Discriminator literal ``"snap_to_grid"``.
        target_file: Relative path to the target KiCad schematic file (H-01 validated).
        grid_mm: Grid spacing in mm. Default 0.01mm for KiCad 8+.
    """

    op_type: Literal["snap_to_grid"] = "snap_to_grid"
    target_file: TargetFile
    grid_mm: float = Field(
        default=0.01, gt=0, le=100,
        description="Grid spacing in mm. Default 0.01mm for KiCad 8+.",
    )


class FixShortedNetsOp(BaseModel):
    """Fix positions where multiple net names connect to the same items.

    Detects short circuits where wires from different named nets overlap,
    then removes the "losing" label based on the chosen strategy.

    Attributes:
        op_type: Discriminator literal ``"fix_shorted_nets"``.
        target_file: Relative path to the .kicad_sch file.
        strategy: Which label to keep. "keep_first" keeps the first alphabetically,
            "keep_last" keeps the last, "manual" uses keep_nets list.
        keep_nets: For "manual" strategy, which net names to keep.
        dry_run: If True, report shorts without modifying the file.
    """

    op_type: Literal["fix_shorted_nets"] = "fix_shorted_nets"
    target_file: TargetFile
    strategy: Literal["keep_first", "keep_last", "keep_majority", "manual"] = Field(
        default="keep_first",
        description="Which label to keep at short positions. "
        "'keep_majority' keeps the net with most connections, with power-net protection.",
    )
    keep_nets: Optional[list[str]] = Field(
        default=None,
        description="For manual strategy, which net names to keep",
    )
    dry_run: bool = Field(
        default=False,
        description="Report shorts without modifying the file",
    )


class FixPinTypeMismatchesOp(BaseModel):
    """Fix pin electrical type mismatches in embedded lib_symbols.

    Updates pin electrical types in the embedded symbol definitions to resolve
    pin_to_pin ERC violations. Common fix: change "Unspecified" to "Passive"
    for analog switch pins connected to passive components.

    Attributes:
        op_type: Discriminator literal ``"fix_pin_type_mismatches"``.
        target_file: Relative path to the .kicad_sch file.
        pin_type_map: Override map from old type to new type. Defaults to {"unspecified": "passive"}.
        dry_run: If True, report what would change without modifying the file.
    """

    op_type: Literal["fix_pin_type_mismatches"] = "fix_pin_type_mismatches"
    target_file: TargetFile
    pin_type_map: Optional[dict[str, str]] = Field(
        default=None,
        description='Map from old type to new type, e.g. {"unspecified": "passive"}',
    )
    dry_run: bool = Field(
        default=False,
        description="Report mismatches without modifying the file",
    )


class PlaceMissingUnitsOp(BaseModel):
    """Place all unplaced units of multi-unit symbols.

    For multi-unit symbols like CD4066BE (quad bilateral switch), places all
    units that KiCad ERC reports as missing. Units are placed adjacent to the
    existing unit with configurable spacing.

    Attributes:
        op_type: Discriminator literal ``"place_missing_units"``.
        target_file: Relative path to the .kicad_sch file.
        references: Optional list of specific references. If None, fixes all.
        offset_x: Horizontal spacing between units in mm (default 25.4 = 1 inch).
        offset_y: Vertical spacing between units in mm.
        dry_run: If True, report what would be placed without modifying.
    """

    op_type: Literal["place_missing_units"] = "place_missing_units"
    target_file: TargetFile
    references: Optional[list[str]] = Field(
        default=None,
        description="Specific references to fix, or None for all",
    )
    offset_x: float = Field(
        default=25.4, gt=0, le=254,
        description="Horizontal spacing between units in mm",
    )
    offset_y: float = Field(
        default=0.0, ge=0, le=254,
        description="Vertical spacing between units in mm",
    )
    dry_run: bool = Field(
        default=False,
        description="Report placements without modifying the file",
    )


class RemoveDanglingWiresOp(BaseModel):
    """Remove wire segments with unconnected endpoints.

    Identifies and removes wires where at least one endpoint is not connected
    to any pin, label, junction, or other wire intersection.

    Attributes:
        op_type: Discriminator literal ``"remove_dangling_wires"``.
        target_file: Relative path to the .kicad_sch file.
        max_length_mm: Only remove wires shorter than this (safety). None = no limit.
        dry_run: If True, report what would be removed without modifying.
    """

    op_type: Literal["remove_dangling_wires"] = "remove_dangling_wires"
    target_file: TargetFile
    max_length_mm: Optional[float] = Field(
        default=None, gt=0, le=1000,
        description="Only remove wires shorter than this (mm). None = no limit.",
    )
    dry_run: bool = Field(
        default=False,
        description="Report removals without modifying the file",
    )


class BreakWireShortsOp(BaseModel):
    """Break wire segments that short different nets together.

    Detects wire-level shorts where a physical wire segment connects two nets
    that shouldn't be connected (e.g. ADC_IN_1 shorted to GND via a crossing
    wire). Uses BFS to find the bridge wire(s) on the path between shorted
    net labels and removes them.

    Attributes:
        op_type: Discriminator literal ``"break_wire_shorts"``.
        target_file: Relative path to the .kicad_sch file.
        net_pairs: Optional list of specific net pairs to break, e.g.
            ``[("ADC_IN_1", "GND")]``. If None, breaks all detected shorts.
        strategy: ``"shortest_path"`` removes the single wire on the shortest
            path between shorted nets. ``"all_bridges"`` removes all wires
            connecting the two nets.
        dry_run: If True, report what would be removed without modifying.
    """

    op_type: Literal["break_wire_shorts"] = "break_wire_shorts"
    target_file: TargetFile
    net_pairs: Optional[list[list[str]]] = Field(
        default=None,
        description='Specific net pairs to break, e.g. [["ADC_IN_1", "GND"]]. None = all shorts.',
    )
    strategy: Literal["shortest_path", "all_bridges"] = Field(
        default="shortest_path",
        description="shortest_path: remove one bridge wire. all_bridges: remove all connecting wires.",
    )
    dry_run: bool = Field(
        default=False,
        description="Report bridge wires without modifying the file",
    )


class ResolveShortedNetsOp(BaseModel):
    """Atomically resolve shorted nets with wire breaking and label fixing.

    Phase 67: Combines break_wire_shorts + fix_shorted_nets into one atomic
    operation with proper ordering, clean-break verification, and power-net
    protection. The "smart" strategy (default) tries wire break first, then
    falls back to label removal if no clean break is possible.

    Single-sheet schematics only. Cross-sheet shorts require project-level
    netlist analysis.

    Attributes:
        op_type: Discriminator literal ``"resolve_shorted_nets"``.
        target_file: Relative path to the .kicad_sch file.
        strategy: Resolution strategy:
            - ``"smart"``: try wire break, fall back to label fix (default)
            - ``"break_only"``: only attempt wire breaking
            - ``"fix_labels_only"``: only fix labels (no wire removal)
            - ``"manual"``: report only, no changes
        keep_nets: For "manual" strategy, which net names to keep.
        dry_run: If True, report what would change without modifying.
    """

    op_type: Literal["resolve_shorted_nets"] = "resolve_shorted_nets"
    target_file: TargetFile
    strategy: Literal["smart", "break_only", "fix_labels_only", "manual"] = Field(
        default="smart",
        description="Resolution strategy: smart (default), break_only, fix_labels_only, manual",
    )
    keep_nets: Optional[list[str]] = Field(
        default=None,
        description='For manual strategy, which net names to keep',
    )
    dry_run: bool = Field(
        default=False,
        description="Report without modifying the file",
    )


# ErcAutoFixOp has been migrated to _schema_erc_smart.py (Council H-02:
# two classes with the same op_type discriminator cannot coexist in the
# Operation union). Import from there if needed directly.
