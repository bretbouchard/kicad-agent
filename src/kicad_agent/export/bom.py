"""BOM (Bill of Materials) export via kicad-cli.

GEN-02: BOM export with field customization and grouping.
FEAT-004: LCSC/JLCPCB part number support for direct ordering.

Wraps ``kicad-cli sch export bom`` with schema validation, field
customization, grouping, and CSV parsing.

Usage:
    from kicad_agent.export.bom import export_bom, parse_bom_csv, enrich_with_lcsc

    result = export_bom(Path("board.kicad_sch"))
    print(f"Components: {result.component_count}")

    # Enrich with LCSC codes from schematic fields
    enriched = enrich_with_lcsc(Path("board.kicad_sch"))
    print(f"LCSC coverage: {enriched['lcsc_coverage']:.0%}")
"""

import csv
import io
import logging
import re
from dataclasses import dataclass, field
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


# Common LCSC/JLCPCB field names in KiCad schematics
_LCSC_FIELD_NAMES = {"LCSC", "JLCPCB", "lcsc", "jlcpcb", "LCSC Part"}


def _extract_lcsc_from_schematic(schematic_path: Path) -> dict[str, str]:
    """Extract LCSC part numbers from schematic component fields.

    Scans the .kicad_sch file for property fields named LCSC/JLCPCB
    and extracts the reference-to-LCSC mapping.

    Args:
        schematic_path: Path to .kicad_sch file.

    Returns:
        Dict mapping component reference (e.g. "R1") to LCSC part number.
    """
    if not schematic_path.exists():
        return {}

    content = schematic_path.read_text(encoding="utf-8")
    lcsc_map: dict[str, str] = {}

    # Pattern: (property "LCSC" "C12345") inside symbol blocks
    # KiCad stores fields as (property "Field Name" "Value")
    for field_match in re.finditer(
        r'\(property\s+"((?:(?:LCSC|JLCPCB|LCSC Part)[^"]*?))"\s+"([^"]*)"',
        content,
        re.IGNORECASE,
    ):
        field_name = field_match.group(1)
        field_value = field_match.group(2).strip()
        if field_value and field_value != "~":
            # Walk backwards to find the reference for this symbol
            # Look for the nearest (property "Reference" "XXX") before this field
            pos = field_match.start()
            preceding = content[:pos]
            ref_match = re.search(
                r'\(property\s+"Reference"\s+"([^"]+)"',
                preceding,
            )
            if ref_match:
                ref = ref_match.group(1)
                # Only update if we haven't found an LCSC code for this ref yet,
                # or this is a more specific field name
                if ref not in lcsc_map:
                    lcsc_map[ref] = field_value

    return lcsc_map


def enrich_with_lcsc(
    schematic_path: Path,
    bom_path: Path | None = None,
) -> dict:
    """Enrich BOM with LCSC part numbers from schematic fields.

    Reads the schematic to find LCSC/JLCPCB fields on components and
    matches them against the BOM entries by reference designator.

    Args:
        schematic_path: Path to .kicad_sch file.
        bom_path: Path to existing BOM CSV. If None, extracts BOM
            data directly from the schematic.

    Returns:
        Dict with:
            components: List of component dicts with LCSC field added.
            lcsc_coverage: Fraction of components with LCSC codes (0.0-1.0).
            missing_lcsc: List of references without LCSC codes.
            total_components: Total unique component count.
    """
    lcsc_map = _extract_lcsc_from_schematic(schematic_path)

    # Get component list
    if bom_path and bom_path.exists():
        components = parse_bom_csv(bom_path)
    else:
        # Extract basic component info from schematic
        content = schematic_path.read_text(encoding="utf-8") if schematic_path.exists() else ""
        components = []
        for sym_match in re.finditer(r'\(symbol\s+\(lib_id\s+"([^"]+)"\)', content):
            lib_id = sym_match.group(1)
            # Find reference for this symbol
            block_end = content.find("\n)", sym_match.end())
            block = content[sym_match.start():block_end] if block_end > sym_match.start() else ""
            ref_match = re.search(r'\(property\s+"Reference"\s+"([^"]+)"', block)
            val_match = re.search(r'\(property\s+"Value"\s+"([^"]+)"', block)
            fp_match = re.search(r'\(property\s+"Footprint"\s+"([^"]+)"', block)
            components.append({
                "Reference": ref_match.group(1) if ref_match else "?",
                "Value": val_match.group(1) if val_match else "?",
                "Footprint": fp_match.group(1) if fp_match else "",
                "lib_id": lib_id,
            })

    # Enrich with LCSC codes
    missing_lcsc: list[str] = []
    enriched = []
    for comp in components:
        ref = comp.get("Reference", "")
        lcsc = lcsc_map.get(ref, "")
        enriched_comp = dict(comp)
        enriched_comp["LCSC"] = lcsc
        enriched.append(enriched_comp)
        if ref and not lcsc:
            missing_lcsc.append(ref)

    total = len([c for c in enriched if c.get("Reference", "?") != "?"])
    with_lcsc = total - len(missing_lcsc)
    coverage = (with_lcsc / total) if total > 0 else 0.0

    return {
        "components": enriched,
        "lcsc_coverage": coverage,
        "missing_lcsc": missing_lcsc,
        "total_components": total,
    }


def export_jlcpcb_bom(
    schematic_path: Path,
    output_path: Path | None = None,
) -> BomResult:
    """Export BOM in JLCPCB-compatible CSV format.

    JLCPCB requires a specific CSV format for their SMT assembly service.
    This function exports the BOM with LCSC part numbers if available,
    in the format JLCPCB expects: Comment,Designator,Footprint,LCSC

    Args:
        schematic_path: Path to .kicad_sch file.
        output_path: Output file path. Defaults to sch_path with
            _JLCPCB-BOM.csv suffix.

    Returns:
        BomResult with component counts.
    """
    if output_path is None:
        output_path = schematic_path.parent / f"{schematic_path.stem}_JLCPCB-BOM.csv"

    # First export the standard BOM
    std_result = export_bom(schematic_path, output_path)

    # Enrich with LCSC codes
    enrichment = enrich_with_lcsc(schematic_path)

    # Rewrite in JLCPCB format
    rows = enrichment["components"]
    if not rows:
        return std_result

    # Write JLCPCB-format CSV
    jlcpcb_rows = []
    for comp in rows:
        ref = comp.get("Reference", "")
        value = comp.get("Value", comp.get("Comment", ""))
        footprint = comp.get("Footprint", "")
        lcsc = comp.get("LCSC", "")
        if ref and ref != "?":
            jlcpcb_rows.append({
                "Comment": value,
                "Designator": ref,
                "Footprint": footprint,
                "LCSC": lcsc,
            })

    # Write CSV
    fieldnames = ["Comment", "Designator", "Footprint", "LCSC"]
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(jlcpcb_rows)

    return BomResult(
        success=True,
        output_path=output_path,
        component_count=sum(
            1 for c in jlcpcb_rows
            for _ in c.get("Designator", "").split(",")
        ),
        unique_components=len(jlcpcb_rows),
        command=std_result.command,
        stderr=std_result.stderr,
    )
