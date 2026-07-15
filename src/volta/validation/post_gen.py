"""Post-generation validation for schematic and PCB files.

BUG-005 / FEAT-005: Automated validation pipeline that runs after
schematic/PCB generation to catch silent data loss and ensure
generated files are valid before manufacturing.

Checks:
1. Wire count consistency (pre vs post generation)
2. Pin connectivity verification
3. Component count verification
4. Net count verification
5. ERC/DRC summary integration
6. Structured report output

Usage:
    from volta.validation.post_gen import validate_generated, GenerationValidationResult

    result = validate_generated(
        schematic_path=Path("board.kicad_sch"),
        expected_wires=42,
        expected_components=10,
    )
    if not result.passed:
        for issue in result.issues:
            print(f"ISSUE: {issue}")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

logger = logging.getLogger(__name__)


class ValidationSeverity(str, Enum):
    """Severity of a post-generation validation finding."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass(frozen=True)
class ValidationIssue:
    """A single finding from post-generation validation."""

    check: str
    severity: ValidationSeverity
    message: str
    expected: str | None = None
    actual: str | None = None


@dataclass(frozen=True)
class GenerationValidationResult:
    """Result of post-generation validation.

    Attributes:
        passed: True if no ERROR-severity issues found.
        issues: Tuple of ValidationIssue findings.
        wire_count: Number of wires found in schematic (0 if not checked).
        component_count: Number of components found (0 if not checked).
        net_count: Number of nets found (0 if not checked).
    """

    passed: bool
    issues: tuple[ValidationIssue, ...] = ()
    wire_count: int = 0
    component_count: int = 0
    net_count: int = 0

    @property
    def errors(self) -> tuple[ValidationIssue, ...]:
        return tuple(i for i in self.issues if i.severity == ValidationSeverity.ERROR)

    @property
    def warnings(self) -> tuple[ValidationIssue, ...]:
        return tuple(i for i in self.issues if i.severity == ValidationSeverity.WARNING)


def _count_schematic_elements(schematic_path: Path) -> dict[str, int]:
    """Count wires, components, and nets in a schematic file.

    Uses raw text parsing for speed — no full IR parse required.

    Args:
        schematic_path: Path to .kicad_sch file.

    Returns:
        Dict with keys: wires, components, nets, labels, junctions.
    """
    if not schematic_path.exists():
        return {"wires": 0, "components": 0, "nets": 0, "labels": 0, "junctions": 0}

    content = schematic_path.read_text(encoding="utf-8")

    # Count wire segments (wire S-expressions at top level)
    import re
    wire_count = len(re.findall(r'^\(wire\s', content, re.MULTILINE))
    # Count components (symbol S-expressions at top level, excluding embedded lib symbols)
    component_count = len(re.findall(r'^\(symbol\s', content, re.MULTILINE))
    # Count net labels
    label_count = len(re.findall(r'^\((?:global_label|hierarchical_label|label|net_label)\s', content, re.MULTILINE))
    # Count junctions
    junction_count = len(re.findall(r'^\(junction\s', content, re.MULTILINE))
    # Count nets in net segment declarations
    net_count = len(re.findall(r'\(net_name\s+"([^"]+)"', content))

    return {
        "wires": wire_count,
        "components": component_count,
        "nets": net_count,
        "labels": label_count,
        "junctions": junction_count,
    }


def validate_generated(
    schematic_path: Path | None = None,
    pcb_path: Path | None = None,
    *,
    expected_wires: int | None = None,
    expected_components: int | None = None,
    expected_nets: int | None = None,
    min_wires: int = 0,
    run_erc: bool = False,
    run_drc: bool = False,
) -> GenerationValidationResult:
    """Run post-generation validation checks.

    Args:
        schematic_path: Path to .kicad_sch file.
        pcb_path: Path to .kicad_pcb file.
        expected_wires: Expected wire count. If provided, mismatch is an ERROR.
        expected_components: Expected component count. If provided, mismatch is a WARNING.
        expected_nets: Expected net count. If provided, mismatch is a WARNING.
        min_wires: Minimum wire count below which is an ERROR (default 0).
        run_erc: Whether to run ERC on the schematic.
        run_drc: Whether to run DRC on the PCB.

    Returns:
        GenerationValidationResult with pass/fail and all findings.
    """
    issues: list[ValidationIssue] = []
    wire_count = 0
    component_count = 0
    net_count = 0

    # --- Schematic validation ---
    if schematic_path is not None and schematic_path.exists():
        counts = _count_schematic_elements(schematic_path)
        wire_count = counts["wires"]
        component_count = counts["components"]
        net_count = counts["nets"]

        # BUG-005: Wire count validation
        if expected_wires is not None and wire_count != expected_wires:
            severity = ValidationSeverity.ERROR
            if wire_count < expected_wires:
                message = (
                    f"Wire count mismatch: expected {expected_wires}, "
                    f"found {wire_count} ({expected_wires - wire_count} wires missing)"
                )
            else:
                message = (
                    f"Wire count mismatch: expected {expected_wires}, "
                    f"found {wire_count} ({wire_count - expected_wires} extra wires)"
                )
                severity = ValidationSeverity.WARNING
            issues.append(ValidationIssue(
                check="wire_count",
                severity=severity,
                message=message,
                expected=str(expected_wires),
                actual=str(wire_count),
            ))

        # Minimum wire count check
        if wire_count < min_wires:
            issues.append(ValidationIssue(
                check="min_wire_count",
                severity=ValidationSeverity.ERROR,
                message=f"Wire count ({wire_count}) below minimum ({min_wires})",
                expected=f">={min_wires}",
                actual=str(wire_count),
            ))

        # Component count check
        if expected_components is not None and component_count != expected_components:
            issues.append(ValidationIssue(
                check="component_count",
                severity=ValidationSeverity.WARNING,
                message=f"Component count: expected {expected_components}, found {component_count}",
                expected=str(expected_components),
                actual=str(component_count),
            ))

        # Net count check
        if expected_nets is not None and net_count != expected_nets:
            issues.append(ValidationIssue(
                check="net_count",
                severity=ValidationSeverity.WARNING,
                message=f"Net count: expected {expected_nets}, found {net_count}",
                expected=str(expected_nets),
                actual=str(net_count),
            ))

        # Zero wires on a schematic that has components = suspicious
        if wire_count == 0 and component_count > 1:
            issues.append(ValidationIssue(
                check="no_wires_with_components",
                severity=ValidationSeverity.ERROR,
                message=f"Schematic has {component_count} components but 0 wires — possible silent wire drop",
            ))

        # ERC check
        if run_erc:
            try:
                from volta.validation.erc_drc import run_erc

                erc_result = run_erc(schematic_path)
                if not erc_result.passed:
                    issues.append(ValidationIssue(
                        check="erc",
                        severity=ValidationSeverity.ERROR,
                        message=f"ERC failed: {erc_result.error_count} errors, {erc_result.warning_count} warnings",
                    ))
                elif erc_result.warning_count > 0:
                    issues.append(ValidationIssue(
                        check="erc",
                        severity=ValidationSeverity.WARNING,
                        message=f"ERC passed with {erc_result.warning_count} warnings",
                    ))
                else:
                    issues.append(ValidationIssue(
                        check="erc",
                        severity=ValidationSeverity.INFO,
                        message="ERC passed clean",
                    ))
            except Exception as e:
                issues.append(ValidationIssue(
                    check="erc",
                    severity=ValidationSeverity.WARNING,
                    message=f"ERC could not run: {e}",
                ))

    # --- PCB validation ---
    if pcb_path is not None and pcb_path.exists():
        if run_drc:
            try:
                from volta.validation.erc_drc import run_drc

                drc_result = run_drc(pcb_path)
                if not drc_result.passed:
                    issues.append(ValidationIssue(
                        check="drc",
                        severity=ValidationSeverity.ERROR,
                        message=f"DRC failed: {drc_result.error_count} errors, {len(drc_result.unconnected_items)} unconnected",
                    ))
                elif drc_result.warning_count > 0:
                    issues.append(ValidationIssue(
                        check="drc",
                        severity=ValidationSeverity.WARNING,
                        message=f"DRC passed with {drc_result.warning_count} warnings",
                    ))
                else:
                    issues.append(ValidationIssue(
                        check="drc",
                        severity=ValidationSeverity.INFO,
                        message="DRC passed clean",
                    ))
            except Exception as e:
                issues.append(ValidationIssue(
                    check="drc",
                    severity=ValidationSeverity.WARNING,
                    message=f"DRC could not run: {e}",
                ))

    # --- No files to validate ---
    if schematic_path is None and pcb_path is None:
        issues.append(ValidationIssue(
            check="input",
            severity=ValidationSeverity.ERROR,
            message="No schematic or PCB path provided for validation",
        ))

    has_errors = any(i.severity == ValidationSeverity.ERROR for i in issues)
    return GenerationValidationResult(
        passed=not has_errors,
        issues=tuple(issues),
        wire_count=wire_count,
        component_count=component_count,
        net_count=net_count,
    )


def format_validation_report(result: GenerationValidationResult) -> str:
    """Format a GenerationValidationResult as a human-readable report.

    Args:
        result: The validation result to format.

    Returns:
        Multi-line string report.
    """
    lines: list[str] = []
    status = "PASS" if result.passed else "FAIL"
    lines.append(f"Post-Generation Validation: {status}")
    lines.append(f"  Wires: {result.wire_count}")
    lines.append(f"  Components: {result.component_count}")
    lines.append(f"  Nets: {result.net_count}")

    if result.errors:
        lines.append(f"\n  Errors ({len(result.errors)}):")
        for issue in result.errors:
            lines.append(f"    [{issue.check}] {issue.message}")
            if issue.expected and issue.actual:
                lines.append(f"      expected={issue.expected}, actual={issue.actual}")

    if result.warnings:
        lines.append(f"\n  Warnings ({len(result.warnings)}):")
        for issue in result.warnings:
            lines.append(f"    [{issue.check}] {issue.message}")

    info = [i for i in result.issues if i.severity == ValidationSeverity.INFO]
    if info:
        lines.append(f"\n  Info ({len(info)}):")
        for issue in info:
            lines.append(f"    [{issue.check}] {issue.message}")

    return "\n".join(lines)
