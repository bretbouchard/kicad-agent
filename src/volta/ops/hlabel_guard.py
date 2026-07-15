"""Hierarchical label validation guard.

SCHREPAIR-03: Validates that hierarchical labels in a sub-sheet match the
expected set. Used before and after mutation operations to ensure label
integrity is preserved.

Usage:
    from volta.ops.hlabel_guard import validate_hlabels

    result = validate_hlabels(ir, expected_labels={"SDA", "SCL", "VCC"})
    if not result.passed:
        print(f"Missing labels: {result.missing}")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass

from volta.ir.schematic_ir import SchematicIR

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class HlabelValidationResult:
    """Result of validating hierarchical labels against an expected set.

    Attributes:
        passed: True if validation passed (no missing labels).
        expected_count: Number of expected labels (0 if snapshot mode).
        actual_count: Number of hierarchical labels found in the schematic.
        missing: Labels expected but not found.
        extra: Labels found but not expected.
    """

    passed: bool
    expected_count: int
    actual_count: int
    missing: tuple[str, ...]
    extra: tuple[str, ...]


def validate_hlabels(
    ir: SchematicIR,
    expected_labels: set[str] | None = None,
) -> HlabelValidationResult:
    """Validate hierarchical labels against an expected set.

    If expected_labels is provided, compares actual vs expected and reports
    discrepancies. If None, reports the current label count in snapshot mode
    (always passes).

    Args:
        ir: SchematicIR for the target schematic.
        expected_labels: Set of expected hierarchical label text strings.
            None means snapshot mode (count only, no comparison).

    Returns:
        HlabelValidationResult with counts and discrepancies.
    """
    # Extract actual hierarchical label names
    actual_labels: set[str] = set()
    for label in ir.schematic.hierarchicalLabels:
        if label.text:
            actual_labels.add(label.text)

    actual_count = len(actual_labels)

    # Snapshot mode: no expected set to compare against
    if expected_labels is None:
        return HlabelValidationResult(
            passed=True,
            expected_count=0,
            actual_count=actual_count,
            missing=(),
            extra=(),
        )

    # Comparison mode
    missing = tuple(sorted(expected_labels - actual_labels))
    extra = tuple(sorted(actual_labels - expected_labels))
    passed = len(missing) == 0

    return HlabelValidationResult(
        passed=passed,
        expected_count=len(expected_labels),
        actual_count=actual_count,
        missing=missing,
        extra=extra,
    )
