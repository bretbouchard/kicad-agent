"""Library reference propagation for schematic symbols and PCB footprints.

XFILE-02/XFILE-03: When a symbol or footprint library reference changes,
all instances across schematic and PCB files update to match.

Purpose: When a user renames a symbol in a library or moves a footprint to
a different library, every schematic component and PCB footprint referencing
the old name must be updated. Without propagation, broken references cause
ERC/DRC errors.

Security:
- T-06-06: Validates old/new strings are non-empty, rejects null bytes
- T-06-07: Exact string match only -- no regex or glob
- T-06-09: Max field length 256 for DoS mitigation
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from volta.ir.pcb_ir import PcbIR
from volta.ir.schematic_ir import SchematicIR

logger = logging.getLogger(__name__)

_MAX_REF_LENGTH = 256


def _validate_ref(value: str, param_name: str) -> None:
    """Validate a library reference string.

    Args:
        value: The string to validate.
        param_name: Parameter name for error messages.

    Raises:
        ValueError: If string is empty, contains null bytes, or exceeds max length.
    """
    if not value:
        raise ValueError(f"{param_name} must be a non-empty string")
    if "\x00" in value:
        raise ValueError(f"{param_name} contains null bytes")
    if len(value) > _MAX_REF_LENGTH:
        raise ValueError(
            f"{param_name} exceeds maximum length of {_MAX_REF_LENGTH} characters"
        )


@dataclass(frozen=True)
class PropagationResult:
    """Result of a library reference propagation operation.

    Attributes:
        updated_count: Number of instances actually modified.
        matched_count: Number of instances matching the old reference.
        file_path: Path to the file that was modified.
    """

    updated_count: int
    matched_count: int
    file_path: Path


def propagate_symbol_ref(
    schematic_ir: SchematicIR,
    old_lib_id: str,
    new_lib_id: str,
) -> PropagationResult:
    """Propagate a symbol library reference change to all matching schematic components.

    Finds all components in the SchematicIR whose libId matches old_lib_id and
    updates them to new_lib_id.

    Args:
        schematic_ir: The SchematicIR containing components to update.
        old_lib_id: Current library ID to match (e.g. "Device:R_Small_US").
        new_lib_id: New library ID to set (e.g. "MyLib:R_Small_US").

    Returns:
        PropagationResult with counts of matched and updated components.

    Raises:
        ValueError: If old_lib_id or new_lib_id is empty or contains null bytes.
    """
    _validate_ref(old_lib_id, "old_lib_id")
    _validate_ref(new_lib_id, "new_lib_id")

    # No-op when old and new are identical
    if old_lib_id == new_lib_id:
        return PropagationResult(
            updated_count=0,
            matched_count=0,
            file_path=Path(schematic_ir.file_path),
        )

    matched_count = 0
    for comp in schematic_ir.components:
        if comp.libId == old_lib_id:
            comp.libId = new_lib_id
            matched_count += 1

    if matched_count > 0:
        schematic_ir._record_mutation(
            "propagate_symbol_ref",
            {
                "old_lib_id": old_lib_id,
                "new_lib_id": new_lib_id,
                "updated_count": matched_count,
            },
        )

    return PropagationResult(
        updated_count=matched_count,
        matched_count=matched_count,
        file_path=Path(schematic_ir.file_path),
    )


def propagate_footprint_ref(
    pcb_ir: PcbIR,
    old_lib_ref: str,
    new_lib_ref: str,
) -> PropagationResult:
    """Propagate a footprint library reference change to all matching PCB footprints.

    Finds all footprints in the PcbIR whose libraryNickname:entryName matches
    old_lib_ref and updates them to new_lib_ref.

    Args:
        pcb_ir: The PcbIR containing footprints to update.
        old_lib_ref: Current library reference (e.g. "Resistor_SMD:R_0402").
        new_lib_ref: New library reference (e.g. "MyLib:R_0402").

    Returns:
        PropagationResult with counts of matched and updated footprints.

    Raises:
        ValueError: If old_lib_ref or new_lib_ref is empty or contains null bytes.
    """
    _validate_ref(old_lib_ref, "old_lib_ref")
    _validate_ref(new_lib_ref, "new_lib_ref")

    # No-op when old and new are identical
    if old_lib_ref == new_lib_ref:
        return PropagationResult(
            updated_count=0,
            matched_count=0,
            file_path=Path(pcb_ir.file_path),
        )

    # Parse new reference into nickname and entry name
    if ":" not in new_lib_ref:
        raise ValueError(
            f"new_lib_ref must contain ':' separator (format: Library:Footprint), got: {new_lib_ref!r}"
        )
    new_nickname, new_entry_name = new_lib_ref.split(":", 1)

    matched_count = 0
    for fp in pcb_ir.footprints:
        combined = f"{fp.libraryNickname}:{fp.entryName}"
        if combined == old_lib_ref:
            fp.libraryNickname = new_nickname
            fp.entryName = new_entry_name
            matched_count += 1

    if matched_count > 0:
        pcb_ir._record_mutation(
            "propagate_footprint_ref",
            {
                "old_lib_ref": old_lib_ref,
                "new_lib_ref": new_lib_ref,
                "updated_count": matched_count,
            },
        )

    return PropagationResult(
        updated_count=matched_count,
        matched_count=matched_count,
        file_path=Path(pcb_ir.file_path),
    )
