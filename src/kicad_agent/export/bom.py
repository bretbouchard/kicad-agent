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
from kicad_agent.dfm.profiles import ManufacturerProfile

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


def _sanitize_csv_cell(value: str) -> str:
    """Defend against CSV formula injection (TM-5).

    Prefixes a cell value with a leading single-quote when it starts with a
    character that spreadsheet applications interpret as a formula
    (=, +, -, @, tab, carriage return). Defensive measure for vendor BOM CSVs
    that may be opened in Excel/Sheets by the manufacturer.
    """
    if not value:
        return value
    # Only the first character determines formula interpretation.
    if value[0] in ("=", "+", "-", "@", "\t", "\r"):
        return "'" + value
    return value


def export_bom_profile(
    sch_path: Path,
    output_dir: Path,
    profile: ManufacturerProfile | None = None,
) -> BomResult:
    """Export BOM using a ManufacturerProfile output format spec (HANDOFF-05).

    If ``profile`` has ``bom_columns``/``bom_filename_pattern``, post-process
    the kicad-cli BOM to match the vendor-specific format. If ``profile`` is
    None or lacks an output spec, use the generic kicad-cli default format.

    The handoff orchestrator MUST call this function rather than the
    hard-coded ``export_jlcpcb_bom`` (Pitfall 3 -- vendor lock-in avoidance).

    Args:
        sch_path: Path to the .kicad_sch file.
        output_dir: Directory to write the BOM into.
        profile: Manufacturer profile with optional output format spec. None =
            generic default format.

    Returns:
        BomResult with component counts and file path.

    Raises:
        FileNotFoundError: If sch_path does not exist or kicad-cli not found.
        ValueError: If sch_path is not a .kicad_sch file.
    """
    stem = sch_path.stem

    # 1. Determine output filename from profile pattern or default.
    if profile and profile.bom_filename_pattern:
        filename = profile.bom_filename_pattern.format(stem=stem)
    else:
        filename = f"{stem}-BOM.csv"
    output_path = output_dir / filename

    has_vendor_columns = bool(profile and profile.bom_columns)

    # 2. Export standard BOM via kicad-cli.
    std_result = export_bom(sch_path, output_path=output_path)

    # 3. If profile is None or has no column spec, the generic default is fine.
    if not has_vendor_columns:
        return std_result

    target_columns = profile.bom_columns  # type: ignore[assignment]

    # 4. Enrich with LCSC when a target column requires it.
    needs_lcsc = "LCSC" in target_columns
    if needs_lcsc:
        enrichment = enrich_with_lcsc(sch_path)
        rows = enrichment["components"]
    else:
        # Parse the kicad-cli-generated CSV directly.
        try:
            rows = parse_bom_csv(output_path) if output_path.exists() else []
        except Exception:
            rows = []

    if not rows:
        return std_result

    # 5. Source-to-target column mapping (alias table).
    #    Comment <- Value (fallback Comment); Designator <- Reference;
    #    Footprint <- Footprint; LCSC <- LCSC (from enrichment).
    #    Any target column with no known source is written as empty string.
    def _resolve(col: str, comp: dict) -> str:
        if col == "Comment":
            return comp.get("Value", comp.get("Comment", ""))
        if col == "Designator":
            return comp.get("Reference", comp.get("Designator", ""))
        # Pass-through for Footprint, LCSC, and any other named source column.
        return comp.get(col, "")

    # 6. Rewrite via csv.DictWriter with profile columns as fieldnames.
    remapped_rows = []
    for comp in rows:
        ref = comp.get("Reference", "")
        if not ref or ref == "?":
            continue
        remapped = {
            col: _sanitize_csv_cell(_resolve(col, comp)) for col in target_columns
        }
        remapped_rows.append(remapped)

    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=list(target_columns))
        writer.writeheader()
        writer.writerows(remapped_rows)

    return BomResult(
        success=True,
        output_path=output_path,
        component_count=sum(
            1 for r in remapped_rows
            for _ in r.get("Designator", "").split(",")
        ),
        unique_components=len(remapped_rows),
        command=std_result.command,
        stderr=std_result.stderr,
    )


def export_jlcpcb_bom(
    schematic_path: Path,
    output_path: Path | None = None,
) -> BomResult:
    """Export BOM in JLCPCB-compatible CSV format.

    JLCPCB requires a specific CSV format for their SMT assembly service.
    This function exports the BOM with LCSC part numbers if available,
    in the format JLCPCB expects: Comment,Designator,Footprint,LCSC.

    Internally delegates to ``export_bom_profile`` with the built-in JLCPCB
    profile (Phase 208). Preserved for backward compatibility.

    Args:
        schematic_path: Path to .kicad_sch file.
        output_path: Output file path. Defaults to sch_path with
            _JLCPCB-BOM.csv suffix.

    Returns:
        BomResult with component counts.
    """
    from kicad_agent.dfm.profiles import load_profile

    profile = load_profile("jlcpcb")
    if output_path is None:
        return export_bom_profile(schematic_path, schematic_path.parent, profile)
    # Preserve the caller-specified output path: write into its parent dir with
    # the JLCPCB column layout, then the profile-driven filename would differ,
    # so delegate to the generic path and move the file into place.
    result = export_bom_profile(schematic_path, output_path.parent, profile)
    if result.output_path != output_path:
        import shutil

        shutil.move(str(result.output_path), str(output_path))
        return BomResult(
            success=result.success,
            output_path=output_path,
            component_count=result.component_count,
            unique_components=result.unique_components,
            command=result.command,
            stderr=result.stderr,
        )
    return result
