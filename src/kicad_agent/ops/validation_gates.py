"""Pre-PCB validation gates -- ERC, power net, and annotation checks.

Validates schematics before PCB work begins:
  - Power pin connectivity (all power pins have power symbols)
  - ERC clean check (structured wrapper around run_erc)
  - Pre-PCB gate (comprehensive validation combining ERC, power, annotation)

Usage:
    from kicad_agent.ops.validation_gates import validate_power_nets, pre_pcb_gate

    result = validate_power_nets(ir)
    if not result["valid"]:
        print(f"Unconnected power pins: {result['unconnected_power_pins']}")
"""

import logging
import re
from pathlib import Path
from typing import Any

from kicad_agent.ir.schematic_ir import SchematicIR

logger = logging.getLogger(__name__)

# Pin electrical types that indicate power pins
_POWER_PIN_TYPES = {"power_in", "power_out"}

# Common power net names for checking coverage
_COMMON_POWER_NETS = {"GND", "VCC", "+5V", "+3V3", "+3.3V", "VDD", "VSS"}


def validate_power_nets(
    ir: SchematicIR,
    file_path: Path | None = None,
    check_hierarchical: bool = False,
) -> dict[str, Any]:
    """Check all power pins have connected power symbols.

    Finds all power pins (power_in, power_out) in the schematic and verifies
    each is connected to a power symbol (power:* library reference).

    Args:
        ir: SchematicIR for the target schematic.
        file_path: Path to the .kicad_sch file (required for hierarchical check).
        check_hierarchical: Also traverse sub-sheets for power connectivity.

    Returns:
        Dict with:
        - valid: bool -- True if all power pins connected
        - unconnected_power_pins: list of dicts with pin details
        - power_nets: list of power net names found
        - missing_power_symbols: list of net names lacking power sources
        - hierarchical_issues: list of dicts (only when check_hierarchical=True)
    """
    sch = ir.schematic
    pin_positions = ir.get_pin_positions()
    label_positions = ir.get_label_positions()

    # Find power pins
    power_pins = [p for p in pin_positions if p["electrical_type"] in _POWER_PIN_TYPES]

    # Find power symbols (symbols with libId starting with "power:")
    power_symbol_nets: set[str] = set()
    for sym in sch.schematicSymbols:
        if sym.libId.startswith("power:"):
            # Power symbol name is the part after "power:"
            net_name = sym.libId.split(":", 1)[1]
            # Also check the Value property
            for prop in sym.properties:
                if prop.key == "Value":
                    net_name = prop.value
                    break
            power_symbol_nets.add(net_name)

    # Map label positions to net names for connectivity check
    label_net_map: dict[tuple[float, float], str] = {}
    for lp in label_positions:
        key = _round_pos(lp["x"], lp["y"])
        label_net_map[key] = lp["name"]

    # Check each power pin for connectivity
    unconnected: list[dict[str, Any]] = []
    for pin in power_pins:
        pin_key = _round_pos(pin["x"], pin["y"])

        # Check if a label is at the pin position (implies net connectivity)
        connected_label = label_net_map.get(pin_key)

        # Check if any wire endpoint is at the pin position
        wire_connected = False
        for we in ir.get_wire_endpoints():
            if (_distance(pin["x"], pin["y"], we["start_x"], we["start_y"]) <= 0.01
                    or _distance(pin["x"], pin["y"], we["end_x"], we["end_y"]) <= 0.01):
                wire_connected = True
                break

        if not connected_label and not wire_connected:
            unconnected.append({
                "reference": pin["reference"],
                "pin_name": pin["pin_name"],
                "pin_number": pin["pin_number"],
                "position": (round(pin["x"], 4), round(pin["y"], 4)),
                "electrical_type": pin["electrical_type"],
            })

    # Identify power nets that lack power sources (power_out symbols)
    # power_in pins consume power; power_out symbols provide it
    power_in_nets: set[str] = set()
    for pin in power_pins:
        if pin["electrical_type"] == "power_in":
            pin_key = _round_pos(pin["x"], pin["y"])
            label_name = label_net_map.get(pin_key)
            if label_name:
                power_in_nets.add(label_name)

    # Check which common power nets are missing power sources
    missing_power_symbols: list[str] = []
    for net in _COMMON_POWER_NETS:
        if net in power_in_nets and net not in power_symbol_nets:
            missing_power_symbols.append(net)

    # Also check any net consumed by power_in pins but not provided
    for net in power_in_nets:
        if net not in power_symbol_nets and net not in _COMMON_POWER_NETS:
            missing_power_symbols.append(net)

    all_power_nets = sorted(power_symbol_nets | power_in_nets)
    valid = len(unconnected) == 0 and len(missing_power_symbols) == 0

    result: dict[str, Any] = {
        "valid": valid,
        "unconnected_power_pins": unconnected,
        "power_nets": all_power_nets,
        "missing_power_symbols": sorted(set(missing_power_symbols)),
    }

    if check_hierarchical and file_path is not None:
        hierarchical_issues = _check_hierarchical_power(ir, file_path)
        result["hierarchical_issues"] = hierarchical_issues
        result["valid"] = valid and len(hierarchical_issues) == 0

    return result


def check_erc_clean(sch_path: Path) -> dict[str, Any]:
    """Run ERC and return structured result.

    Wraps the existing run_erc() with a simplified result structure.

    Args:
        sch_path: Path to the .kicad_sch file.

    Returns:
        Dict with clean, error_count, warning_count, errors.
    """
    from kicad_agent.validation.erc_drc import run_erc

    result = run_erc(sch_path)

    errors = [
        {
            "description": v.description,
            "type": v.type,
            "severity": v.severity.value,
        }
        for v in result.violations
    ]

    return {
        "clean": result.passed,
        "error_count": result.error_count,
        "warning_count": result.warning_count,
        "errors": errors,
    }


def pre_pcb_gate(project_dir: Path) -> dict[str, Any]:
    """Comprehensive pre-PCB validation gate.

    Runs ERC, power net validation, and annotation completeness checks
    on all schematic files in the project directory.

    Args:
        project_dir: Path to the project directory containing .kicad_sch files.

    Returns:
        Dict with:
        - pass: bool -- True if all checks pass
        - erc: dict -- ERC check result
        - power: dict -- Power net validation result
        - annotation: dict -- Annotation completeness result
        - recommendations: list of actionable recommendations
    """
    # Find schematic files
    sch_files = sorted(project_dir.glob("*.kicad_sch"))
    if not sch_files:
        return {
            "pass": False,
            "erc": {"clean": False, "error_count": 0, "warning_count": 0, "errors": []},
            "power": {"valid": False, "unconnected_power_pins": [],
                      "power_nets": [], "missing_power_symbols": []},
            "annotation": {"complete": False, "unannotated": []},
            "recommendations": ["No schematic files found in project directory"],
        }

    # Run ERC on ALL schematic files, not just the root (O-BUG-006)
    all_erc_clean = True
    all_erc_results: list[dict[str, Any]] = []
    all_erc_errors: list[dict[str, Any]] = []
    total_erc_errors = 0
    total_erc_warnings = 0
    for sch_file in sch_files:
        erc_result = check_erc_clean(sch_file)
        all_erc_results.append({"file": str(sch_file), **erc_result})
        if not erc_result["clean"]:
            all_erc_clean = False
            total_erc_errors += erc_result["error_count"]
            total_erc_warnings += erc_result["warning_count"]
            for err in erc_result["errors"]:
                all_erc_errors.append({**err, "source_file": str(sch_file)})
    erc_result = {
        "clean": all_erc_clean,
        "error_count": total_erc_errors,
        "warning_count": total_erc_warnings,
        "errors": all_erc_errors,
    }

    # Run power net and annotation validation on ALL schematics (O-BUG-006)
    from kicad_agent.parser import parse_schematic
    all_power_valid = True
    all_power_pins: list[dict[str, Any]] = []
    all_missing_symbols: list[str] = []
    all_power_nets: list[str] = []
    all_unannotated: list[str] = []
    for sch_file in sch_files:
        result = parse_schematic(sch_file)
        ir = SchematicIR(_parse_result=result)
        power_result = validate_power_nets(ir)
        if not power_result["valid"]:
            all_power_valid = False
            all_power_pins.extend(power_result["unconnected_power_pins"])
            all_missing_symbols.extend(power_result["missing_power_symbols"])
        all_power_nets.extend(power_result["power_nets"])
        ref_pattern = re.compile(r"^[A-Za-z]+\?$")
        for ref, _lib_id in ir.get_all_references():
            if ref_pattern.match(ref):
                all_unannotated.append(ref)

    power_result = {
        "valid": all_power_valid,
        "unconnected_power_pins": all_power_pins,
        "power_nets": sorted(set(all_power_nets)),
        "missing_power_symbols": sorted(set(all_missing_symbols)),
    }

    annotation_result = {
        "complete": len(all_unannotated) == 0,
        "unannotated": all_unannotated,
    }

    # Generate recommendations
    recommendations: list[str] = []
    if not erc_result["clean"]:
        recommendations.append(
            f"Fix {erc_result['error_count']} ERC errors before proceeding to PCB"
        )
    if not power_result["valid"]:
        if power_result["unconnected_power_pins"]:
            recommendations.append(
                f"Connect {len(power_result['unconnected_power_pins'])} unconnected power pins"
            )
        if power_result["missing_power_symbols"]:
            symbols = ", ".join(power_result["missing_power_symbols"])
            recommendations.append(
                f"Add power symbols for: {symbols}"
            )
    if not annotation_result["complete"]:
        recommendations.append(
            f"Annotate {len(unannotated)} unannotated components"
        )

    gate_pass = (
        erc_result["clean"]
        and power_result["valid"]
        and annotation_result["complete"]
    )

    return {
        "pass": gate_pass,
        "erc": erc_result,
        "power": power_result,
        "annotation": annotation_result,
        "recommendations": recommendations,
    }


def check_sheet_pin_labels(ir: SchematicIR, sch_path: Path) -> dict[str, Any]:
    """Check sheet pins have matching hierarchical labels in sub-sheets.

    For each sheet reference in the root schematic, verifies every sheet pin
    has a corresponding hierarchical label inside the sub-sheet file.

    Args:
        ir: SchematicIR for the root schematic.
        sch_path: Path to the root .kicad_sch file.

    Returns:
        Dict with:
        - passed: bool -- True if all sheet pins have matching labels.
        - unmatched_pins: list of dicts with sheet_name, pin_name, pin_type.
    """
    sch = ir.schematic
    unmatched: list[dict[str, Any]] = []

    for sheet in sch.sheets:
        sheet_file_name = sheet.fileName.value if sheet.fileName else ""
        if not sheet_file_name:
            continue

        # Resolve sub-sheet path relative to the parent schematic
        sub_sch_path = sch_path.resolve().parent / sheet_file_name

        if not sub_sch_path.exists():
            logger.debug(
                "Sub-sheet not found, skipping pin label check: %s", sub_sch_path
            )
            continue

        # Parse the sub-sheet to find its hierarchical labels
        try:
            from kicad_agent.parser import parse_schematic

            sub_result = parse_schematic(sub_sch_path)
            sub_ir = SchematicIR(_parse_result=sub_result)
        except Exception as exc:
            logger.warning(
                "Cannot parse sub-sheet %s for label matching: %s",
                sub_sch_path,
                exc,
            )
            continue

        # Collect hierarchical label names from the sub-sheet
        sub_hier_labels: set[str] = set()
        for label in sub_ir.schematic.hierarchicalLabels:
            if label.text:
                sub_hier_labels.add(label.text)

        # Check each sheet pin against sub-sheet labels
        sheet_name = sheet.sheetName.value if sheet.sheetName else sheet_file_name
        for pin in sheet.pins:
            pin_name = pin.name if pin.name else ""
            if pin_name and pin_name not in sub_hier_labels:
                unmatched.append({
                    "sheet_name": sheet_name,
                    "pin_name": pin_name,
                    "pin_type": pin.connectionType,
                })

    passed = len(unmatched) == 0

    if not passed:
        logger.info(
            "Sheet pin label check: %d unmatched pin(s)", len(unmatched)
        )

    return {
        "passed": passed,
        "unmatched_pins": unmatched,
    }


def _distance(x1: float, y1: float, x2: float, y2: float) -> float:
    """Euclidean distance between two points."""
    return ((x2 - x1) ** 2 + (y2 - y1) ** 2) ** 0.5


def _round_pos(x: float, y: float) -> tuple[float, float]:
    """Round position to 0.01mm precision for grouping."""
    return (round(x, 2), round(y, 2))


def _check_hierarchical_power(ir: SchematicIR, file_path: Path) -> list[dict[str, Any]]:
    """Check power nets span hierarchical sheets.

    For each sub-sheet referenced by the root schematic, finds power-related
    sheet pins and verifies each has at least one power symbol inside the
    sub-sheet. Reuses the sheet traversal pattern from check_sheet_pin_labels().

    Args:
        ir: SchematicIR for the root schematic.
        file_path: Path to the root .kicad_sch file.

    Returns:
        List of issue dicts with sub_sheet, net, and issue description.
    """
    from kicad_agent.parser import parse_schematic

    sch = ir.schematic
    issues: list[dict[str, Any]] = []

    # Power-related name patterns for sheet pins
    _POWER_NAME_PATTERNS = {
        "GND", "VCC", "VDD", "VSS", "AGND", "DGND",
        "+3V3", "+3.3V", "+5V", "+3V", "+12V", "-12V",
        "+1V8", "+1.2V", "VBAT", "VREF",
    }

    def _is_power_pin_name(name: str) -> bool:
        """Check if a pin name looks like a power net."""
        upper = name.upper().lstrip("+").lstrip("-")
        return name in _POWER_NAME_PATTERNS or upper in _POWER_NAME_PATTERNS

    for sheet in sch.sheets:
        sheet_file_name = sheet.fileName.value if sheet.fileName else ""
        if not sheet_file_name:
            continue

        # Resolve sub-sheet path relative to parent schematic
        sub_sch_path = file_path.resolve().parent / sheet_file_name
        if not sub_sch_path.exists():
            continue

        try:
            sub_result = parse_schematic(sub_sch_path)
            sub_ir = SchematicIR(_parse_result=sub_result)
        except Exception as exc:
            logger.warning(
                "Cannot parse sub-sheet %s for power check: %s", sub_sch_path, exc
            )
            continue

        # Find power symbol nets inside the sub-sheet
        sub_power_symbol_nets: set[str] = set()
        for sym in sub_ir.schematic.schematicSymbols:
            if sym.libId.startswith("power:"):
                net_name = sym.libId.split(":", 1)[1]
                for prop in sym.properties:
                    if prop.key == "Value":
                        net_name = prop.value
                        break
                sub_power_symbol_nets.add(net_name)

        # Check each sheet pin that looks like a power net
        sheet_name = sheet.sheetName.value if sheet.sheetName else sheet_file_name
        for pin in sheet.pins:
            pin_name = pin.name if pin.name else ""
            if pin_name and _is_power_pin_name(pin_name):
                if pin_name not in sub_power_symbol_nets:
                    issues.append({
                        "sub_sheet": sheet_name,
                        "net": pin_name,
                        "issue": "no power symbol for boundary net",
                    })

    return issues


def validate_schematic_completeness(
    sch_path: Path,
    *,
    check_symbol_resolution: bool = True,
    check_format: bool = True,
    check_power_nets: bool = True,
    check_annotation: bool = True,
    check_grid: bool = True,
    check_symbol_mismatch: bool = True,
    check_sheet_pins: bool = True,
) -> dict[str, Any]:
    """Comprehensive schematic validation combining all checks.

    Runs KiCad 10 format validation, symbol resolution, power net checks,
    annotation completeness, grid alignment, symbol copy mismatch, and
    sheet pin matching on a schematic file.

    Args:
        sch_path: Path to the .kicad_sch file.
        check_symbol_resolution: Verify all lib_ids resolve to symbol definitions.
        check_format: Validate KiCad 10 S-expression format rules.
        check_power_nets: Check power pin connectivity.
        check_annotation: Check for unannotated components.
        check_grid: Check pin/wire grid alignment.
        check_symbol_mismatch: Check embedded symbols match library originals.
        check_sheet_pins: Check sheet pins have matching hierarchical labels.

    Returns:
        Dict with:
        - pass: bool -- True if all enabled checks pass
        - format: dict -- Format check results (if enabled)
        - symbol_resolution: dict -- Symbol resolution results (if enabled)
        - power: dict -- Power net validation results (if enabled)
        - annotation: dict -- Annotation completeness results (if enabled)
        - grid: dict -- Grid alignment results (if enabled)
        - symbol_mismatch: dict -- Symbol copy mismatch results (if enabled)
        - sheet_pins: dict -- Sheet pin matching results (if enabled)
        - recommendations: list of actionable recommendations
    """
    from kicad_agent.parser import parse_schematic
    from kicad_agent.ir.schematic_ir import SchematicIR

    results: dict[str, Any] = {
        "pass": True,
        "recommendations": [],
    }

    # 1. Format check (KiCad 10 S-expression rules)
    if check_format:
        from kicad_agent.validation.format_check import validate_kicad10_format

        content = sch_path.read_text(encoding="utf-8")
        format_result = validate_kicad10_format(content, sch_path)
        results["format"] = {
            "pass": format_result.passed,
            "checks": [
                {"name": c.name, "passed": c.passed, "detail": c.detail}
                for c in format_result.checks
            ],
        }
        if not format_result.passed:
            results["pass"] = False
            failed_checks = [c for c in format_result.checks if not c.passed]
            results["recommendations"].append(
                f"Fix {len(failed_checks)} format issue(s): "
                + ", ".join(c.name for c in failed_checks)
            )

    # Parse the schematic for remaining checks
    parse_result = parse_schematic(sch_path)
    ir = SchematicIR(_parse_result=parse_result)

    # 2. Symbol resolution (no question marks)
    if check_symbol_resolution:
        from kicad_agent.validation.symbol_resolution import validate_symbol_resolution

        sym_result = validate_symbol_resolution(ir, sch_path)
        results["symbol_resolution"] = {
            "pass": sym_result.passed,
            "resolved_count": len(sym_result.resolved),
            "unresolved_count": len(sym_result.unresolved),
            "unresolved": [
                {"lib_id": u.lib_id, "reference": u.reference, "detail": u.detail}
                for u in sym_result.unresolved
            ],
        }
        if not sym_result.passed:
            results["pass"] = False
            unresolved_names = sorted(set(u.lib_id for u in sym_result.unresolved))
            results["recommendations"].append(
                f"Add symbol definitions for {len(unresolved_names)} unresolved lib_id(s): "
                + ", ".join(unresolved_names)
            )

    # 3. Power net validation
    if check_power_nets:
        power_result = validate_power_nets(ir)
        results["power"] = power_result
        if not power_result["valid"]:
            results["pass"] = False
            if power_result["unconnected_power_pins"]:
                results["recommendations"].append(
                    f"Connect {len(power_result['unconnected_power_pins'])} unconnected power pins"
                )
            if power_result["missing_power_symbols"]:
                symbols = ", ".join(power_result["missing_power_symbols"])
                results["recommendations"].append(f"Add power symbols for: {symbols}")

    # 4. Annotation completeness
    if check_annotation:
        unannotated: list[str] = []
        ref_pattern = re.compile(r"^[A-Za-z]+\?$")
        for ref, _lib_id in ir.get_all_references():
            if ref_pattern.match(ref):
                unannotated.append(ref)

        results["annotation"] = {
            "complete": len(unannotated) == 0,
            "unannotated": unannotated,
        }
        if unannotated:
            results["pass"] = False
            results["recommendations"].append(
                f"Annotate {len(unannotated)} unannotated components"
            )

    # 5. Grid alignment (off-grid pins and wire endpoints)
    if check_grid:
        from kicad_agent.validation.grid_check import check_grid_alignment

        grid_result = check_grid_alignment(ir)
        results["grid"] = {
            "pass": grid_result.passed,
            "off_grid_pins": [
                {"reference": p["reference"], "pin_name": p["pin_name"],
                 "x": p["x"], "y": p["y"]}
                for p in grid_result.off_grid_pins
            ],
            "off_grid_wire_endpoints": [
                {"x": w["x"], "y": w["y"], "endpoint_type": w["endpoint_type"]}
                for w in grid_result.off_grid_wire_endpoints
            ],
        }
        if not grid_result.passed:
            results["pass"] = False
            total = len(grid_result.off_grid_pins) + len(grid_result.off_grid_wire_endpoints)
            results["recommendations"].append(
                f"Fix {total} off-grid element(s): "
                f"{len(grid_result.off_grid_pins)} pin(s), "
                f"{len(grid_result.off_grid_wire_endpoints)} wire endpoint(s)"
            )

    # 6. Symbol copy mismatch (embedded vs library originals)
    if check_symbol_mismatch:
        from kicad_agent.validation.symbol_mismatch import check_symbol_copy_mismatch

        mismatch_result = check_symbol_copy_mismatch(ir, sch_path)
        results["symbol_mismatch"] = {
            "pass": mismatch_result.passed,
            "mismatches": [
                {"lib_id": m["lib_id"], "reference": m["reference"],
                 "differences": m["differences"]}
                for m in mismatch_result.mismatches
            ],
        }
        if not mismatch_result.passed:
            results["pass"] = False
            results["recommendations"].append(
                f"Resolve {len(mismatch_result.mismatches)} symbol copy mismatch(es): "
                + ", ".join(m["lib_id"] for m in mismatch_result.mismatches)
            )

    # 7. Sheet pin / hierarchical label matching
    if check_sheet_pins:
        sheet_pin_result = check_sheet_pin_labels(ir, sch_path)
        results["sheet_pins"] = sheet_pin_result
        if not sheet_pin_result["passed"]:
            results["pass"] = False
            results["recommendations"].append(
                f"Fix {len(sheet_pin_result['unmatched_pins'])} sheet pin(s) "
                "with missing hierarchical labels in sub-sheets"
            )

    return results
