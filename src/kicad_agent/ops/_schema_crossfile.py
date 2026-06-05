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
