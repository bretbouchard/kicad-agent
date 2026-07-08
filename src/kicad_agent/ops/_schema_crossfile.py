"""Cross-file operation schemas -- atomic multi-file mutations.

XFILE-07: Cross-file operations coordinate mutations across multiple KiCad files
in a single atomic transaction. If any file fails, all files roll back.

D-03 is relaxed for cross-file operations: target_file is required for execute()
routing, while target_files lists all files to mutate atomically.
"""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, Field, field_validator

from kicad_agent.ops.schema import TargetFile, _validate_safe_identifier


class PropagateSymbolChangeOp(BaseModel):
    """Propagate a symbol/footprint library reference change across multiple files atomically.

    Attributes:
        op_type: Discriminator literal ``"propagate_symbol_change"``.
        target_file: Primary file path (used by execute() routing, must be first in target_files).
        target_files: List of relative file paths to mutate (schematic and/or PCB files).
        old_lib_id: Current library ID to match, e.g. "Device:R_Small_US".
        new_lib_id: Replacement library ID, e.g. "MyLib:R_Small_US".
    """

    op_type: Literal["propagate_symbol_change"] = "propagate_symbol_change"
    target_file: TargetFile = Field(
        description="Primary file for execute() routing (first entry in target_files)",
    )
    target_files: list[TargetFile] = Field(
        min_length=1,
        max_length=20,
        description="List of files to update atomically",
    )
    old_lib_id: str = Field(
        min_length=1,
        max_length=256,
        description="Current library ID to match",
    )
    new_lib_id: str = Field(
        min_length=1,
        max_length=256,
        description="Replacement library ID",
    )

    @field_validator("old_lib_id")
    @classmethod
    def _validate_old_lib_id(cls, v: str) -> str:
        return _validate_safe_identifier(v, "old_lib_id")

    @field_validator("new_lib_id")
    @classmethod
    def _validate_new_lib_id(cls, v: str) -> str:
        return _validate_safe_identifier(v, "new_lib_id")


class UpdatePcbFromSchematicOp(BaseModel):
    """Synchronize PCB footprints and netlist from schematic source of truth.

    Exports a netlist from the schematic via kicad-cli, parses component
    references + net assignments, and updates the PCB accordingly.

    Attributes:
        op_type: Discriminator literal ``"update_pcb_from_schematic"``.
        target_file: Primary file (.kicad_pcb) for execute() routing.
        target_files: List of files to parse atomically: [pcb_file, schematic_file].
            Exactly one .kicad_pcb and one .kicad_sch required.
        sync_netlist: Update pad-to-net assignments on existing PCB footprints.
        sync_footprints: Update footprint lib_id references to match schematic.
        add_new_components: Add PCB footprints for schematic components not yet in PCB.
            Requires footprint library to be resolvable from the project.
        remove_orphans: Remove PCB footprints with no matching schematic component.
    """

    op_type: Literal["update_pcb_from_schematic"] = "update_pcb_from_schematic"
    target_file: TargetFile = Field(
        description="Primary .kicad_pcb file for execute() routing",
    )
    target_files: list[TargetFile] = Field(
        min_length=2,
        max_length=2,
        description="[pcb_file, schematic_file] -- exactly one of each type",
    )
    sync_netlist: bool = Field(
        default=True,
        description="Update pad-to-net assignments from schematic netlist",
    )
    sync_footprints: bool = Field(
        default=True,
        description="Update footprint lib_id references to match schematic",
    )
    add_new_components: bool = Field(
        default=True,
        description="Add new PCB footprints for components in schematic but missing from PCB",
    )
    remove_orphans: bool = Field(
        default=False,
        description="Remove PCB footprints with no schematic counterpart",
    )

    @field_validator("target_files")
    @classmethod
    def _validate_target_files(cls, v: list[str]) -> list[str]:
        extensions = [Path(f).suffix for f in v]
        if ".kicad_pcb" not in extensions:
            raise ValueError("target_files must include exactly one .kicad_pcb file")
        if ".kicad_sch" not in extensions:
            raise ValueError("target_files must include exactly one .kicad_sch file")
        if extensions.count(".kicad_pcb") > 1:
            raise ValueError("target_files must include exactly one .kicad_pcb file")
        if extensions.count(".kicad_sch") > 1:
            raise ValueError("target_files must include exactly one .kicad_sch file")
        return v


def _validate_pcb_sch_pair(v: list[str]) -> list[str]:
    """Validator for target_files that must be [pcb, schematic] pair."""
    extensions = [Path(f).suffix for f in v]
    if ".kicad_pcb" not in extensions:
        raise ValueError("target_files must include exactly one .kicad_pcb file")
    if ".kicad_sch" not in extensions:
        raise ValueError("target_files must include exactly one .kicad_sch file")
    if extensions.count(".kicad_pcb") > 1:
        raise ValueError("target_files must include exactly one .kicad_pcb file")
    if extensions.count(".kicad_sch") > 1:
        raise ValueError("target_files must include exactly one .kicad_sch file")
    return v


class RepopulatePcbFromSchematicOp(BaseModel):
    """Re-populate a PCB with footprints from the schematic netlist.

    Strips routing and optionally zones, removes orphan footprints, adds
    missing footprints via template cloning, auto-places with clearance
    awareness, assigns nets from schematic, and rebuilds net declarations.

    Attributes:
        op_type: Discriminator literal ``"repopulate_pcb_from_schematic"``.
        target_file: Primary .kicad_pcb file for execute() routing.
        target_files: List of files: [pcb_file, schematic_file].
        strip_routing: Remove all segments and vias before re-population.
        strip_zones: Remove all copper zones before re-population.
        remove_orphans: Remove footprints not in schematic.
        auto_place: Auto-place missing footprints with clearance awareness.
        assign_nets: Assign pad nets from schematic netlist.
        placement_clearance: Min clearance between footprints in mm.
        board_width: Board width in mm (0 = auto-detect from Edge.Cuts).
        board_height: Board height in mm (0 = auto-detect from Edge.Cuts).
    """

    op_type: Literal["repopulate_pcb_from_schematic"] = "repopulate_pcb_from_schematic"
    target_file: TargetFile = Field(
        description="Primary .kicad_pcb file for execute() routing",
    )
    target_files: list[TargetFile] = Field(
        min_length=2,
        max_length=2,
        description="[pcb_file, schematic_file]",
    )
    strip_routing: bool = Field(default=True)
    strip_zones: bool = Field(default=False)
    remove_orphans: bool = Field(default=True)
    auto_place: bool = Field(default=True)
    assign_nets: bool = Field(default=True)
    placement_clearance: float = Field(default=4.0, gt=0)
    board_width: float = Field(default=0.0, ge=0, description="Board width mm (0=auto)")
    board_height: float = Field(default=0.0, ge=0, description="Board height mm (0=auto)")

    @field_validator("target_files")
    @classmethod
    def _validate_target_files(cls, v: list[str]) -> list[str]:
        return _validate_pcb_sch_pair(v)


class SafeSyncPcbFromSchematicOp(BaseModel):
    """NON-DESTRUCTIVE PCB sync from schematic (KiCad GUI "Update PCB from Schematic").

    Bridges the gap between ``update_pcb_from_schematic`` (contract-only,
    never mutates) and ``repopulate_pcb_from_schematic`` (mutates but strips
    routing). This op performs real mutations while preserving routing,
    zones, and existing footprint placement by default.

    All PCB modifications use raw S-expression manipulation via
    ``atomic_write`` (kiutils ``Board.to_file()`` is forbidden -- it
    corrupts KiCad 10 PCBs per project memory kiutils-root-sheet-danger.md
    and Phase 101 P0-003 lesson).

    Attributes:
        op_type: Discriminator literal ``"safe_sync_pcb_from_schematic"``.
        target_file: Primary .kicad_pcb file for execute() routing.
        target_files: List of files: [pcb_file, schematic_file] -- exactly one of each.
        update_references: Update REF** placeholders with real refs from schematic.
        update_footprint_lib_ids: Update footprint lib_id from schematic.
        update_pad_nets: Update pad-to-net assignments from schematic netlist.
        add_missing_footprints: Add PCB footprints for components in schematic but
            missing from PCB (cloned from existing footprint template, auto-placed
            in free space; never moves existing footprints).
        remove_orphans: Remove PCB footprints not in schematic. Default False --
            the op is non-destructive by design.
        preserve_routing: CRITICAL: never touch (segment ...) or (via ...) blocks.
        preserve_zones: CRITICAL: never touch (zone ...) blocks.
        preserve_placement: CRITICAL: never touch (at X Y) in existing (footprint ...)
            blocks. Only new footprints get auto-placed positions.
        dry_run: If True, return the change contract without writing to disk.
    """

    op_type: Literal["safe_sync_pcb_from_schematic"] = "safe_sync_pcb_from_schematic"
    target_file: TargetFile = Field(
        description="Primary .kicad_pcb file for execute() routing",
    )
    target_files: list[TargetFile] = Field(
        min_length=2,
        max_length=2,
        description="[pcb_file, schematic_file] -- exactly one of each type",
    )
    update_references: bool = Field(
        default=True,
        description="Update REF** placeholders with real reference designators",
    )
    update_footprint_lib_ids: bool = Field(
        default=True,
        description="Update footprint lib_id references from schematic",
    )
    update_pad_nets: bool = Field(
        default=True,
        description="Update pad-to-net assignments from schematic netlist",
    )
    add_missing_footprints: bool = Field(
        default=True,
        description="Add PCB footprints for components in schematic but missing from PCB",
    )
    remove_orphans: bool = Field(
        default=False,
        description="Remove PCB footprints with no schematic counterpart (default False)",
    )
    preserve_routing: bool = Field(
        default=True,
        description="CRITICAL: never touch (segment ...) or (via ...) blocks",
    )
    preserve_zones: bool = Field(
        default=True,
        description="CRITICAL: never touch (zone ...) blocks",
    )
    preserve_placement: bool = Field(
        default=True,
        description="CRITICAL: never touch (at X Y) in existing footprint blocks",
    )
    dry_run: bool = Field(
        default=False,
        description="Return change contract without writing to disk",
    )

    @field_validator("target_files")
    @classmethod
    def _validate_target_files(cls, v: list[str]) -> list[str]:
        return _validate_pcb_sch_pair(v)


class RebuildPcbNetsOp(BaseModel):
    """Rebuild PCB net table and pad net assignments from schematic netlist.

    More aggressive than update_pcb_from_schematic: strips all routing,
    optionally removes ghost footprints, reassigns every pad net from
    scratch, and rebuilds net declarations with sequential renumbering.

    Attributes:
        op_type: Discriminator literal ``"rebuild_pcb_nets"``.
        target_file: Primary .kicad_pcb file for execute() routing.
        target_files: List of files: [pcb_file, schematic_file].
        strip_routing: Remove all segments and vias before net rebuild.
        ghost_refs: Specific footprint refs to remove as ghosts.
        remove_all_orphans: Remove ALL footprints not in schematic.
    """

    op_type: Literal["rebuild_pcb_nets"] = "rebuild_pcb_nets"
    target_file: TargetFile = Field(
        description="Primary .kicad_pcb file for execute() routing",
    )
    target_files: list[TargetFile] = Field(
        min_length=2,
        max_length=2,
        description="[pcb_file, schematic_file]",
    )
    strip_routing: bool = Field(default=True)
    ghost_refs: list[str] = Field(
        default_factory=list,
        description="Footprint refs to remove as ghosts",
    )
    remove_all_orphans: bool = Field(default=False)

    @field_validator("target_files")
    @classmethod
    def _validate_target_files(cls, v: list[str]) -> list[str]:
        return _validate_pcb_sch_pair(v)
