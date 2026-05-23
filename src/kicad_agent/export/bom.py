"""BOM (Bill of Materials) export via kicad-cli.

GEN-02: BOM export with field customization and grouping.

Wraps ``kicad-cli sch export bom`` with schema validation, field
customization, grouping, and CSV parsing.

Usage:
    from kicad_agent.export.bom import export_bom, parse_bom_csv

    result = export_bom(Path("board.kicad_sch"))
    print(f"Components: {result.component_count}")
"""

import csv
import io
import logging
from dataclasses import dataclass
from pathlib import Path

from kicad_agent.export.gerber import ExportResult, _find_kicad_cli, _run_kicad_export

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class BomResult:
    """Structured result from a BOM export.

    Attributes:
        success: Whether the export completed without errors.
        output_path: Path to the generated BOM file.
        component_count: Total number of component instances in the BOM.
        unique_components: Number of unique component groups in the BOM.
        command: The full command string that was executed.
        stderr: Captured stderr output.
    """

    success: bool
    output_path: Path
    component_count: int
    unique_components: int
    command: str
    stderr: str = ""


def _validate_sch_path(sch_path: Path) -> None:
    """Validate a schematic file path for BOM export.

    Args:
        sch_path: Path to validate.

    Raises:
        FileNotFoundError: If the file does not exist.
        ValueError: If the file is not a .kicad_sch file.
    """
    # Check suffix before existence so wrong type is always ValueError
    if sch_path.suffix != ".kicad_sch":
        raise ValueError(
            f"Expected .kicad_sch file, got: {sch_path.suffix}"
        )

    if ".." in sch_path.parts:
        raise ValueError("Path must not contain '..' path traversal")

    if not sch_path.exists():
        raise FileNotFoundError(f"Schematic file not found: {sch_path}")


def export_bom(
    sch_path: Path,
    output_path: Path | None = None,
    fields: list[str] | None = None,
    group_by: list[str] | None = None,
    exclude_dnp: bool = False,
) -> BomResult:
    """Export BOM from a schematic via kicad-cli.

    Invokes ``kicad-cli sch export bom`` with field and grouping options.

    Args:
        sch_path: Path to the .kicad_sch file.
        output_path: Output file path. Defaults to sch_path with .csv suffix
            in sch_path parent directory.
        fields: Ordered list of fields to export (e.g. ["Reference", "Value",
            "Footprint", "QUANTITY"]). None = kicad-cli defaults.
        group_by: Fields to group references by when field values match.
            None = no grouping.
        exclude_dnp: Exclude DNP (Do Not Populate) components (default False).

    Returns:
        BomResult with component counts and file path.

    Raises:
        FileNotFoundError: If sch_path does not exist or kicad-cli not found.
        ValueError: If sch_path is not a .kicad_sch file.
    """
    _validate_sch_path(sch_path)

    if output_path is None:
        output_path = sch_path.parent / (sch_path.stem + "-BOM.csv")

    # Validate output path for traversal
    if ".." in output_path.parts:
        raise ValueError("Output path must not contain '..' path traversal")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    # kicad-cli sch export bom --output FILE [options] INPUT
    args = ["sch", "export", "bom", "--output", str(output_path)]

    if fields:
        args.extend(["--fields", ",".join(fields)])

    if group_by:
        args.extend(["--group-by", ",".join(group_by)])

    if exclude_dnp:
        args.append("--exclude-dnp")

    args.append(str(sch_path))

    cli_result = _run_kicad_export(args)

    # Parse the CSV to count components
    component_count = 0
    unique_components = 0

    if cli_result["success"] and output_path.exists():
        try:
            rows = parse_bom_csv(output_path)
            unique_components = len(rows)
            # Sum up QUANTITY column if present
            for row in rows:
                qty_str = row.get("Qty", row.get("QUANTITY", "1"))
                try:
                    component_count += int(qty_str)
                except (ValueError, TypeError):
                    component_count += 1
            # If no quantity column, component_count = number of rows
            if component_count == 0:
                component_count = unique_components
        except Exception:
            # If CSV parsing fails, just count lines
            try:
                lines = output_path.read_text(encoding="utf-8").strip().split("\n")
                unique_components = max(0, len(lines) - 1)  # exclude header
                component_count = unique_components
            except Exception:
                pass

    return BomResult(
        success=cli_result["success"] and output_path.exists(),
        output_path=output_path,
        component_count=component_count,
        unique_components=unique_components,
        command=cli_result["command"],
        stderr=cli_result["stderr"],
    )


def parse_bom_csv(path: Path) -> list[dict]:
    """Parse a BOM CSV file into a list of component dictionaries.

    Handles quoted fields with commas (standard CSV quoting).

    Args:
        path: Path to the BOM CSV file.

    Returns:
        List of dicts with keys matching CSV column headers.
        Common keys: Reference, Value, Footprint, Qty, DNP.

    Raises:
        FileNotFoundError: If path does not exist.
        ValueError: If the file cannot be parsed as CSV.
    """
    if not path.exists():
        raise FileNotFoundError(f"BOM file not found: {path}")

    text = path.read_text(encoding="utf-8")
    reader = csv.DictReader(io.StringIO(text))
    return list(reader)
