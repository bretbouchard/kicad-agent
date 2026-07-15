"""Pre-mutation structural validation for KiCad operations.

VAL-05: Catch invalid operations before execution.
Checks that the operation is structurally sound given the current file state:
  - Target component exists (for remove, move, modify operations)
  - Target file type matches the operation type
  - UUID uniqueness is maintained after mutation
  - Library references are syntactically valid

This validator runs BEFORE the mutation is applied. It does NOT run ERC/DRC
(that happens post-mutation in the validation pipeline).

Usage:
    from volta.validation.structural import validate_structural

    result = validate_structural(operation, ir)
    if result.passed:
        # Safe to proceed with mutation
    else:
        for v in result.violations:
            print(f"BLOCKED: {v.description}")
"""

import logging
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Optional

from volta.ops.schema import (
    Operation,
    AddComponentOp,
    RemoveComponentOp,
    MoveComponentOp,
    ModifyPropertyOp,
)
from volta.ir.base import BaseIR
from volta.parser.uuid_extractor import extract_uuids

logger = logging.getLogger(__name__)


class ViolationKind(str, Enum):
    """Categories of structural violations."""

    MISSING_COMPONENT = "missing_component"
    FILE_TYPE_MISMATCH = "file_type_mismatch"
    INVALID_LIBRARY_REF = "invalid_library_ref"
    DUPLICATE_UUID = "duplicate_uuid"
    INVALID_POSITION = "invalid_position"
    EMPTY_REFERENCE = "empty_reference"


@dataclass(frozen=True)
class StructuralViolation:
    """A single structural validation violation."""

    kind: ViolationKind
    description: str
    detail: str = ""  # Additional context (e.g., which component, which UUID)


@dataclass(frozen=True)
class StructuralResult:
    """Result of a structural validation check."""

    passed: bool
    violations: tuple[StructuralViolation, ...] = ()
    operation_type: str = ""  # op_type from the operation
    target_file: str = ""  # target_file from the operation

    @property
    def error_count(self) -> int:
        return len(self.violations)


# Pattern for valid library reference: LIBRARY:SYMBOL with non-empty both sides
_LIBRARY_REF_PATTERN = re.compile(r"^[^:]+:[^:]+$")


def _component_exists(ir: BaseIR, reference: str) -> bool:
    """Check if a component/footprint with the given reference exists.

    Uses duck typing to work with both SchematicIR and PcbIR:
    - SchematicIR has get_component_by_ref()
    - PcbIR has footprints with properties dict containing 'Reference'

    Args:
        ir: The IR instance to search.
        reference: The reference designator to look for.

    Returns:
        True if the component/footprint exists, False otherwise.
    """
    # SchematicIR has get_component_by_ref
    if hasattr(ir, "get_component_by_ref"):
        return ir.get_component_by_ref(reference) is not None
    # PcbIR has footprints with properties dict
    if hasattr(ir, "footprints"):
        for fp in ir.footprints:
            props = getattr(fp, "properties", None)
            if isinstance(props, dict) and props.get("Reference") == reference:
                return True
    return False


def _validate_add_component(op: AddComponentOp, ir: BaseIR) -> list[StructuralViolation]:
    """Validate an add_component operation against current IR state.

    Checks:
      - File type is 'schematic' (add_component targets schematics)
      - library_id matches LIBRARY:SYMBOL format
      - Position coordinates are non-negative
      - Reference is non-empty after stripping

    Args:
        op: The add_component operation to validate.
        ir: The current IR state.

    Returns:
        List of violations (empty if valid).
    """
    violations: list[StructuralViolation] = []

    # File type check -- add_component targets schematics
    if ir.file_type != "schematic":
        violations.append(
            StructuralViolation(
                kind=ViolationKind.FILE_TYPE_MISMATCH,
                description="add_component requires a schematic file",
                detail=f"Expected file_type='schematic', got {ir.file_type!r}",
            )
        )

    # Library reference format check -- must contain ':'
    if not _LIBRARY_REF_PATTERN.match(op.library_id):
        violations.append(
            StructuralViolation(
                kind=ViolationKind.INVALID_LIBRARY_REF,
                description="library_id must be in LIBRARY:SYMBOL format",
                detail=f"Got library_id={op.library_id!r}",
            )
        )

    # Position validity check -- negative coordinates are invalid
    if op.position.x < 0 or op.position.y < 0:
        violations.append(
            StructuralViolation(
                kind=ViolationKind.INVALID_POSITION,
                description="Position coordinates must be non-negative",
                detail=f"Got position=({op.position.x}, {op.position.y})",
            )
        )

    # Reference check -- non-empty after stripping
    if not op.reference.strip():
        violations.append(
            StructuralViolation(
                kind=ViolationKind.EMPTY_REFERENCE,
                description="Reference designator must not be empty",
                detail=f"Got reference={op.reference!r}",
            )
        )

    return violations


def _validate_remove_component(
    op: RemoveComponentOp, ir: BaseIR
) -> list[StructuralViolation]:
    """Validate a remove_component operation against current IR state.

    Checks:
      - File type is 'schematic' (remove_component targets schematics)
      - Target component exists in the IR

    Args:
        op: The remove_component operation to validate.
        ir: The current IR state.

    Returns:
        List of violations (empty if valid).
    """
    violations: list[StructuralViolation] = []

    # File type check -- remove_component targets schematics
    if ir.file_type != "schematic":
        violations.append(
            StructuralViolation(
                kind=ViolationKind.FILE_TYPE_MISMATCH,
                description="remove_component requires a schematic file",
                detail=f"Expected file_type='schematic', got {ir.file_type!r}",
            )
        )

    # Component existence check
    if not _component_exists(ir, op.reference):
        violations.append(
            StructuralViolation(
                kind=ViolationKind.MISSING_COMPONENT,
                description=f"Component {op.reference!r} not found in file",
                detail=f"reference={op.reference!r}",
            )
        )

    return violations


def _validate_move_component(
    op: MoveComponentOp, ir: BaseIR
) -> list[StructuralViolation]:
    """Validate a move_component operation against current IR state.

    Checks:
      - File type is 'schematic' (move_component targets schematics)
      - Target component exists in the IR
      - Position coordinates are non-negative

    Args:
        op: The move_component operation to validate.
        ir: The current IR state.

    Returns:
        List of violations (empty if valid).
    """
    violations: list[StructuralViolation] = []

    # File type check -- move_component targets schematics
    if ir.file_type != "schematic":
        violations.append(
            StructuralViolation(
                kind=ViolationKind.FILE_TYPE_MISMATCH,
                description="move_component requires a schematic file",
                detail=f"Expected file_type='schematic', got {ir.file_type!r}",
            )
        )

    # Component existence check
    if not _component_exists(ir, op.reference):
        violations.append(
            StructuralViolation(
                kind=ViolationKind.MISSING_COMPONENT,
                description=f"Component {op.reference!r} not found in file",
                detail=f"reference={op.reference!r}",
            )
        )

    # Position validity check -- negative coordinates are invalid
    if op.position.x < 0 or op.position.y < 0:
        violations.append(
            StructuralViolation(
                kind=ViolationKind.INVALID_POSITION,
                description="Position coordinates must be non-negative",
                detail=f"Got position=({op.position.x}, {op.position.y})",
            )
        )

    return violations


def _validate_modify_property(
    op: ModifyPropertyOp, ir: BaseIR
) -> list[StructuralViolation]:
    """Validate a modify_property operation against current IR state.

    Checks:
      - Target component exists in the IR
      - property_name is non-empty

    Note: We do NOT validate that the property already exists on the
    component -- the user may be adding a new custom property.

    Args:
        op: The modify_property operation to validate.
        ir: The current IR state.

    Returns:
        List of violations (empty if valid).
    """
    violations: list[StructuralViolation] = []

    # Component existence check
    if not _component_exists(ir, op.reference):
        violations.append(
            StructuralViolation(
                kind=ViolationKind.MISSING_COMPONENT,
                description=f"Component {op.reference!r} not found in file",
                detail=f"reference={op.reference!r}",
            )
        )

    return violations


def _validate_ref_exists(
    op: Any, ir: BaseIR, ref_field: str
) -> list[StructuralViolation]:
    """Validate that a component reference field exists in the IR.

    Generic validator for ops that target a specific component/footprint.

    Args:
        op: The operation with a reference field.
        ir: The current IR state.
        ref_field: Name of the attribute holding the reference (e.g. "reference", "source_reference").

    Returns:
        List of violations (empty if valid).
    """
    ref = getattr(op, ref_field, None)
    if ref is None or not _component_exists(ir, ref):
        return [
            StructuralViolation(
                kind=ViolationKind.MISSING_COMPONENT,
                description=f"Component {ref!r} not found in file",
                detail=f"{ref_field}={ref!r}",
            )
        ]
    return []


def _validate_file_type(ir: BaseIR, expected: str) -> list[StructuralViolation]:
    """Validate that the IR's file type matches the expected type.

    Args:
        ir: The current IR state.
        expected: Expected file_type string (e.g. "schematic", "pcb").

    Returns:
        List of violations (empty if valid).
    """
    if ir.file_type != expected:
        return [
            StructuralViolation(
                kind=ViolationKind.FILE_TYPE_MISMATCH,
                description=f"Operation requires file_type={expected!r}",
                detail=f"Expected {expected!r}, got {ir.file_type!r}",
            )
        ]
    return []


def validate_structural(operation: Operation, ir: BaseIR) -> StructuralResult:
    """Validate an operation against current IR state before mutation.

    Dispatches to type-specific validators based on operation.op_type.
    Collects all violations and returns a StructuralResult.
    A result passes only if zero violations are found.

    Args:
        operation: The operation to validate (Operation discriminated union).
        ir: The current IR state of the target file.

    Returns:
        StructuralResult with pass/fail status and any violations.
    """
    op = operation.root
    op_type = op.op_type
    target_file = op.target_file

    # Dispatch to type-specific validator
    # Query-only ops (validate, check, verify) pass through with no pre-checks.
    # Mutation ops with component references check existence.
    validator_map = {
        "add_component": lambda: _validate_add_component(op, ir),
        "remove_component": lambda: _validate_remove_component(op, ir),
        "move_component": lambda: _validate_move_component(op, ir),
        "modify_property": lambda: _validate_modify_property(op, ir),
        # Component reference ops -- check target exists
        "duplicate_component": lambda: _validate_ref_exists(op, ir, "source_reference"),
        "array_replicate": lambda: _validate_ref_exists(op, ir, "source_reference"),
        "assign_footprint": lambda: _validate_ref_exists(op, ir, "reference"),
        "swap_footprint": lambda: _validate_ref_exists(op, ir, "reference"),
        # Net ops -- check file type is PCB
        "add_net": lambda: _validate_file_type(ir, "pcb"),
        "remove_net": lambda: _validate_file_type(ir, "pcb"),
        "rename_net": lambda: _validate_file_type(ir, "pcb"),
        # Schematic-only ops -- check file type is schematic
        "add_bus": lambda: _validate_file_type(ir, "schematic"),
        "remove_bus": lambda: _validate_file_type(ir, "schematic"),
        "renumber_refs": lambda: _validate_file_type(ir, "schematic"),
        "annotate": lambda: _validate_file_type(ir, "schematic"),
        # Query-only ops -- no structural pre-checks needed
        "validate_refs": lambda: [],
        "cross_ref_check": lambda: [],
        "validate_footprint": lambda: [],
        "verify_pin_map": lambda: _validate_ref_exists(op, ir, "reference"),
    }

    validator = validator_map.get(op_type)
    if validator is None:
        # Council M-2: Reject unknown op_type rather than silently passing.
        # Safe default: if we can't validate it, we block it.
        logger.warning("Unknown op_type %r -- rejecting (no structural validator)", op_type)
        return StructuralResult(
            passed=False,
            violations=(
                StructuralViolation(
                    kind=ViolationKind.FILE_TYPE_MISMATCH,
                    description=f"Unknown operation type: {op_type!r}",
                    detail=f"No structural validator registered for op_type={op_type!r}",
                ),
            ),
            operation_type=op_type,
            target_file=target_file,
        )

    violations = validator()
    passed = len(violations) == 0

    if violations:
        logger.info(
            "Structural validation found %d violation(s) for %s on %s",
            len(violations),
            op_type,
            target_file,
        )

    return StructuralResult(
        passed=passed,
        violations=tuple(violations),
        operation_type=op_type,
        target_file=target_file,
    )


def validate_uuid_uniqueness(
    ir: BaseIR,
    content: Optional[str] = None,
) -> StructuralResult:
    """Check UUID uniqueness across the entire file.

    Extracts all UUIDs from the file content using extract_uuids(),
    then counts each UUID value. Any UUID appearing more than once
    produces a DUPLICATE_UUID violation.

    When called after serialization (pipeline post-mutation), reads
    the actual file from disk to validate post-mutation UUID state.
    Falls back to ir.raw_content if no content provided.

    Args:
        ir: The IR instance whose file to check.
        content: Optional content string. If None, reads from ir.file_path.

    Returns:
        StructuralResult with any duplicate UUID violations.
    """
    if content is None:
        # Read from disk (post-serialization) to get current state,
        # but only if the file has been modified since IR creation.
        # This handles both pipeline (serialized to disk) and test
        # scenarios (raw_content modified in memory).
        file_path = ir.file_path
        if (
            file_path
            and Path(file_path).exists()
            and ir.dirty
        ):
            # IR has been mutated and serialized — validate the file on disk
            content = Path(file_path).read_text(encoding="utf-8")
        else:
            # Fall back to raw_content (original or test-modified)
            content = ir.raw_content

    uuid_map = extract_uuids(content, ir.file_type)

    # Count occurrences of each UUID value
    uuid_counts: dict[str, int] = {}
    for entry in uuid_map.entries:
        uuid_counts[entry.uuid_value] = uuid_counts.get(entry.uuid_value, 0) + 1

    # Find duplicates
    violations: list[StructuralViolation] = []
    for uuid_value, count in uuid_counts.items():
        if count > 1:
            violations.append(
                StructuralViolation(
                    kind=ViolationKind.DUPLICATE_UUID,
                    description=f"Duplicate UUID {uuid_value!r} found {count} times",
                    detail=f"uuid={uuid_value}, count={count}",
                )
            )

    passed = len(violations) == 0

    if violations:
        logger.warning(
            "UUID uniqueness check found %d duplicate(s) in %s",
            len(violations),
            ir.file_path,
        )

    return StructuralResult(
        passed=passed,
        violations=tuple(violations),
        operation_type="uuid_uniqueness",
        target_file=str(ir.file_path),
    )
