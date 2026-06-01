"""ERC report parser and violation position extractor.

Wraps the existing run_erc() from erc_drc.py to provide structured violation
data and position-based filtering for ERC-driven repair workflows.

SCHREPAIR-01: parse_erc returns structured violation list.
SCHREPAIR-02: extract_violation_positions filters by type with (x,y) positions.

Usage:
    from kicad_agent.ops.erc_parser import parse_erc, extract_violation_positions

    violations = parse_erc(Path("schematic.kicad_sch"))
    positions = extract_violation_positions(Path("schematic.kicad_sch"), "pin_not_connected")
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ErcViolation:
    """A single ERC violation with position data extracted from items.

    Attributes:
        sheet: Sheet path where the violation occurs (e.g. "/").
        type: Violation type string (e.g. "pin_not_connected").
        severity: Severity level ("error", "warning", "exclusion").
        description: Human-readable description of the violation.
        positions: List of (x, y) coordinate tuples from violation items.
    """

    sheet: str
    type: str
    severity: str
    description: str
    positions: list[tuple[float, float]]


@dataclass(frozen=True)
class ViolationPosition:
    """A single position from an ERC violation, enriched with context.

    Attributes:
        x: X coordinate in mm.
        y: Y coordinate in mm.
        sheet: Sheet path where the violation occurs.
        description: Human-readable description of the parent violation.
    """

    x: float
    y: float
    sheet: str
    description: str


def parse_erc(sch_path: Path) -> list[ErcViolation]:
    """Parse ERC results for a schematic file.

    Calls run_erc() from erc_drc.py and converts the structured ErcResult
    into a list of ErcViolation with extracted position data.

    Args:
        sch_path: Path to a .kicad_sch file.

    Returns:
        List of ErcViolation instances. If ERC invocation fails, returns a
        single-element list with an "erc_error" violation.
    """
    from kicad_agent.validation.erc_drc import run_erc

    result = run_erc(sch_path)

    if result.error_message is not None:
        return [
            ErcViolation(
                sheet="/",
                type="erc_error",
                severity="error",
                description=result.error_message,
                positions=[],
            )
        ]

    violations: list[ErcViolation] = []
    for v in result.violations:
        positions = _extract_positions(v.items)
        violations.append(
            ErcViolation(
                sheet=v.sheet_path,
                type=v.type,
                severity=v.severity.value,
                description=v.description,
                positions=positions,
            )
        )

    return violations


def extract_violation_positions(
    sch_path: Path,
    violation_type: str,
    sheet_filter: str | None = "/",
) -> list[ViolationPosition]:
    """Extract positions for a specific ERC violation type.

    Filters ERC violations by type and flattens their positions into
    ViolationPosition instances with the parent violation's context.

    Args:
        sch_path: Path to a .kicad_sch file.
        violation_type: Violation type to filter for (e.g. "pin_not_connected").
        sheet_filter: Only include violations from this sheet path.
            Defaults to "/" (root sheet only) to prevent cross-sheet
            coordinate mismatches in hierarchical schematics.
            Pass None to include violations from all sheets.

    Returns:
        List of ViolationPosition instances for matching violations.
    """
    violations = parse_erc(sch_path)
    positions: list[ViolationPosition] = []

    for v in violations:
        if v.type == violation_type:
            if sheet_filter is not None and v.sheet != sheet_filter:
                continue
            for x, y in v.positions:
                positions.append(
                    ViolationPosition(
                        x=x,
                        y=y,
                        sheet=v.sheet,
                        description=v.description,
                    )
                )

    return positions


def _extract_positions(
    items: tuple[dict[str, Any], ...],
) -> list[tuple[float, float]]:
    """Extract (x, y) positions from ERC violation item dicts.

    Each item dict may have a "pos" key with {"x": float, "y": float}.
    KiCad 10's kicad-cli JSON output uses a unit that is 100x smaller than mm
    (e.g. 97.79mm appears as 0.9779). We multiply by 100 to normalize to mm.

    Args:
        items: Tuple of item dicts from a Violation.

    Returns:
        List of (x, y) coordinate tuples in millimeters.
    """
    positions: list[tuple[float, float]] = []
    for item in items:
        pos = item.get("pos")
        if isinstance(pos, dict):
            x = pos.get("x")
            y = pos.get("y")
            if isinstance(x, (int, float)) and isinstance(y, (int, float)):
                positions.append((float(x) * 100.0, float(y) * 100.0))
    return positions
