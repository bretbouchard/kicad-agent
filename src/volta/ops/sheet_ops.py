"""Hierarchical sheet operation handlers.

Implements add_sheet, add_sheet_pin, and navigate_hierarchy operations
for KiCad hierarchical schematic designs.
"""

import uuid
from pathlib import Path
from typing import Any

from kiutils.items.common import ColorRGBA, Position, Property, Stroke
from kiutils.items.schitems import HierarchicalPin, HierarchicalSheet


def add_sheet(op: Any, ir: Any, file_path: Path) -> dict[str, Any]:
    """Add a hierarchical sheet symbol to the schematic.

    Creates a HierarchicalSheet kiutils object with the specified name, file
    reference, position, and size. Appends it to the schematic's graphicalItems.
    Optionally creates the child .kicad_sch file if it does not already exist.

    Args:
        op: Validated AddSheetOp with sheet_name, file_name, position, etc.
        ir: SchematicIR for the target schematic.
        file_path: Resolved path to the target schematic file.

    Returns:
        Dict with sheet_uuid, sheet_name, file_name, and sub_sheet_created.
    """
    sheet_uuid = str(uuid.uuid4())

    sheet = HierarchicalSheet(
        position=Position(X=op.position.x, Y=op.position.y, angle=op.position.angle or 0),
        width=op.width,
        height=op.height,
        stroke=Stroke(width=0.1524, type="solid", color=ColorRGBA(R=0, G=0, B=0, A=1)),
        fill=ColorRGBA(R=0, G=0, B=0, A=0),
        uuid=sheet_uuid,
        sheetName=Property(key="Sheetname", value=op.sheet_name),
        fileName=Property(key="Filename", value=op.file_name),
        pins=[],
        instances=[],
    )

    schematic = ir._parse_result.kiutils_obj
    schematic.sheets.append(sheet)

    # Optionally create the child schematic file if it does not exist
    sub_sheet_created = False
    if op.create_sub_sheet:
        child_path = file_path.parent / op.file_name
        if not child_path.exists():
            _create_empty_schematic(child_path)
            sub_sheet_created = True

    ir._record_mutation("add_sheet", {
        "sheet_uuid": sheet_uuid,
        "sheet_name": op.sheet_name,
        "file_name": op.file_name,
    })

    return {
        "sheet_uuid": sheet_uuid,
        "sheet_name": op.sheet_name,
        "file_name": op.file_name,
        "sub_sheet_created": sub_sheet_created,
    }


def add_sheet_pin(op: Any, ir: Any, file_path: Path) -> dict[str, Any]:
    """Add a pin to a hierarchical sheet symbol.

    Finds the HierarchicalSheet by UUID and appends a new HierarchicalPin
    to its pins list.

    Args:
        op: Validated AddSheetPinOp with sheet_uuid, pin_name, connection_type, etc.
        ir: SchematicIR for the target schematic.
        file_path: Resolved path to the target schematic file.

    Returns:
        Dict with pin_uuid, pin_name, sheet_uuid, connection_type.

    Raises:
        ValueError: If no HierarchicalSheet with the given UUID is found.
    """
    schematic = ir._parse_result.kiutils_obj
    target_sheet = None

    for item in schematic.sheets:
        if isinstance(item, HierarchicalSheet) and item.uuid == op.sheet_uuid:
            target_sheet = item
            break

    if target_sheet is None:
        raise ValueError(
            f"No HierarchicalSheet found with UUID: {op.sheet_uuid}"
        )

    pin_uuid = str(uuid.uuid4())
    pin = HierarchicalPin(
        name=op.pin_name,
        connectionType=op.connection_type,
        position=Position(X=op.position.x, Y=op.position.y),
        uuid=pin_uuid,
    )

    target_sheet.pins.append(pin)

    ir._record_mutation("add_sheet_pin", {
        "pin_uuid": pin_uuid,
        "pin_name": op.pin_name,
        "sheet_uuid": op.sheet_uuid,
        "connection_type": op.connection_type,
    })

    return {
        "pin_uuid": pin_uuid,
        "pin_name": op.pin_name,
        "sheet_uuid": op.sheet_uuid,
        "connection_type": op.connection_type,
    }


def navigate_hierarchy(op: Any, ir: Any, file_path: Path) -> dict[str, Any]:
    """Walk the sheet hierarchy and return a tree structure.

    Read-only query that inspects all HierarchicalSheet objects in the
    schematic's graphicalItems, collecting their names, file references,
    UUIDs, and pin information. Does NOT mutate the IR.

    Args:
        op: Validated NavigateSheetsOp with max_depth.
        ir: SchematicIR for the target schematic.
        file_path: Resolved path to the target schematic file.

    Returns:
        Dict with root_file and sheets list (tree structure).
    """
    schematic = ir._parse_result.kiutils_obj
    sheets = _collect_sheets(schematic, file_path, current_depth=0, max_depth=op.max_depth)

    return {
        "root_file": str(file_path.name),
        "sheet_count": len(sheets),
        "sheets": sheets,
    }


def _collect_sheets(
    schematic: Any,
    file_path: Path,
    current_depth: int,
    max_depth: int,
) -> list[dict[str, Any]]:
    """Recursively collect sheet hierarchy information.

    Args:
        schematic: kiutils Schematic object.
        file_path: Path to the current schematic file.
        current_depth: Current traversal depth.
        max_depth: Maximum depth (-1 for unlimited).

    Returns:
        List of sheet info dicts.
    """
    if max_depth >= 0 and current_depth >= max_depth:
        return []

    sheets: list[dict[str, Any]] = []
    for item in schematic.sheets:
        if isinstance(item, HierarchicalSheet):
            pin_info = [
                {
                    "name": p.name,
                    "connection_type": p.connectionType,
                    "uuid": p.uuid,
                }
                for p in item.pins
            ]

            child_sheets: list[dict[str, Any]] = []
            child_path = file_path.parent / item.fileName.value
            if child_path.exists() and max_depth != 0:
                try:
                    from kiutils.schematic import Schematic as KiutilsSchematic
                    child_sch = KiutilsSchematic.from_file(str(child_path))
                    child_sheets = _collect_sheets(
                        child_sch, child_path, current_depth + 1, max_depth,
                    )
                except Exception:
                    pass  # Skip unparseable child sheets

            sheets.append({
                "sheet_name": item.sheetName.value,
                "file_name": item.fileName.value,
                "uuid": item.uuid,
                "pin_count": len(item.pins),
                "stale_pin_count": _detect_stale_pins(item, child_path),
                "pins": pin_info,
                "children": child_sheets,
            })

    return sheets

def _detect_stale_pins(sheet_item: HierarchicalSheet, child_path: Path) -> bool:
    """Detect if parent sheet pins are out of sync with child hierarchical labels.

    Compares the parent HierarchicalSheet's pins against the hierarchical
    labels defined in the child .kicad_sch file. Returns True if they differ.

    Args:
        sheet_item: kiutils HierarchicalSheet from the parent schematic.
        child_path: Path to the child schematic file.

    Returns:
        True if pin count or names differ, False if in sync.
    """
    if not child_path.exists():
        return False

    try:
        # Parse hierarchical labels from child schematic
        with open(child_path, "r", encoding="utf-8") as f:
            content = f.read()

        # Extract hierarchical label names from child
        import re
        child_labels: set[str] = set()
        for m in re.finditer(
            r'\(hierarchical_label\s+"([^"]+)"',
            content,
        ):
            child_labels.add(m.group(1))

        # Compare with parent pins
        parent_pins: set[str] = {p.name for p in sheet_item.pins}
        return parent_pins != child_labels
    except Exception:
        return False  # Can't determine staleness




def _create_empty_schematic(path: Path) -> None:
    """Create a minimal valid KiCad schematic file.

    Args:
        path: Path where the new schematic file should be created.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    content = (
        "(kicad_sch\n"
        "  (version 20250114)\n"
        "  (generator volta)\n"
        f"  (uuid {uuid.uuid4()})\n"
        "  (paper \"A4\")\n"
        "  (lib_symbols)\n"
        "  (sheet_instances\n"
        "    (path \"/\" (page \"1\"))\n"
        "  )\n"
        ")\n"
    )
    path.write_text(content, encoding="utf-8")
