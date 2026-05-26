"""Handler implementations for file creation operations.

These handlers create new KiCad files from scratch using the kiutils library.
Unlike mutation handlers, they do not use Transaction wrapping (there is nothing
to roll back to for a new file). UUIDs are generated server-side (T-04-01).

Handlers:
    create_schematic -- New empty .kicad_sch file
    create_pcb       -- New empty .kicad_pcb file
    create_project   -- New empty .kicad_pro file
    create_symbol    -- New symbol in a .kicad_sym library file
"""

import json
import uuid
from pathlib import Path
from typing import Any

from kiutils.board import Board
from kiutils.schematic import Schematic
from kiutils.symbol import (
    Effects,
    Fill,
    Font,
    Position,
    Property,
    Stroke,
    SyRect,
    Symbol,
    SymbolLib,
    SymbolPin,
)
from kiutils.items.common import ColorRGBA

from kicad_agent.serializer import normalize_kicad_output


# ---------------------------------------------------------------------------
# Electrical type / graphical style maps (kiutils S-expression names)
# ---------------------------------------------------------------------------

_ELECTRICAL_TYPE_MAP = {
    "input": "input",
    "output": "output",
    "bidirectional": "bidirectional",
    "tri_state": "tri_state",
    "passive": "passive",
    "free": "free",
    "unspecified": "unspecified",
    "power_in": "power_in",
    "power_out": "power_out",
    "open_collector": "open_collector",
    "open_emitter": "open_emitter",
    "no_connect": "no_connect",
}

_GRAPHICAL_STYLE_MAP = {
    "line": "line",
    "inverted": "inverted",
    "clock": "clock",
    "inverted_clock": "inverted_clock",
    "input_low": "input_low",
    "clock_low": "clock_low",
    "output_low": "output_low",
    "edge_clock_high": "edge_clock_high",
    "non_logic": "non_logic",
}


# ---------------------------------------------------------------------------
# create_schematic
# ---------------------------------------------------------------------------


def create_schematic(op: Any, file_path: Path) -> dict[str, Any]:
    """Create a new empty .kicad_sch file.

    Uses ``Schematic.create_new()`` from kiutils, overrides the UUID and
    generator fields to match KiCad conventions, then writes to disk.

    Args:
        op: CreateSchematicOp model instance.
        file_path: Resolved absolute path for the new file.

    Returns:
        Dict with target_file, uuid, paper details.

    Raises:
        FileExistsError: If file_path already exists.
    """
    if file_path.exists():
        raise FileExistsError(f"Cannot create: file already exists: {file_path}")

    file_path.parent.mkdir(parents=True, exist_ok=True)

    schematic = Schematic.create_new()
    schematic.uuid = str(uuid.uuid4())
    schematic.generator = "eeschema"
    schematic.paper.paperSize = op.paper

    if op.title:
        from kiutils.schematic import TitleBlock
        if schematic.titleBlock is None:
            schematic.titleBlock = TitleBlock()
        schematic.titleBlock.title = op.title

    schematic.to_file(str(file_path))

    # Normalize S-expression formatting
    content = file_path.read_text(encoding="utf-8")
    normalized = normalize_kicad_output(content)
    file_path.write_text(normalized, encoding="utf-8")

    return {
        "target_file": op.target_file,
        "uuid": schematic.uuid,
        "paper": op.paper,
        "title": op.title or None,
    }


# ---------------------------------------------------------------------------
# create_pcb
# ---------------------------------------------------------------------------


def create_pcb(op: Any, file_path: Path) -> dict[str, Any]:
    """Create a new empty .kicad_pcb file.

    Uses ``Board.create_new()`` from kiutils, overrides the generator field,
    then writes to disk.

    Args:
        op: CreatePcbOp model instance.
        file_path: Resolved absolute path for the new file.

    Returns:
        Dict with target_file and layer count.

    Raises:
        FileExistsError: If file_path already exists.
    """
    if file_path.exists():
        raise FileExistsError(f"Cannot create: file already exists: {file_path}")

    file_path.parent.mkdir(parents=True, exist_ok=True)

    board = Board.create_new()
    board.generator = "pcbnew"

    board.to_file(str(file_path))

    return {
        "target_file": op.target_file,
        "title": op.title or None,
    }


# ---------------------------------------------------------------------------
# create_project
# ---------------------------------------------------------------------------


def create_project(op: Any, file_path: Path) -> dict[str, Any]:
    """Create a new empty .kicad_pro project file.

    Writes a minimal KiCad project JSON structure that KiCad recognizes.

    Args:
        op: CreateProjectOp model instance.
        file_path: Resolved absolute path for the new file.

    Returns:
        Dict with target_file.

    Raises:
        FileExistsError: If file_path already exists.
    """
    if file_path.exists():
        raise FileExistsError(f"Cannot create: file already exists: {file_path}")

    file_path.parent.mkdir(parents=True, exist_ok=True)

    project = {
        "board": {
            "design_settings": {},
            "layers": [],
        },
        "cvpcb": {},
        "libraries": {},
        "net_settings": {},
        "pcbnew": {},
        "schematic": {
            "legacy_lib_dir": "",
            "legacy_lib_list": [],
        },
        "sheets": [],
        "text_variables": {},
    }

    file_path.write_text(
        json.dumps(project, indent=2) + "\n",
        encoding="utf-8",
    )

    return {
        "target_file": op.target_file,
    }


# ---------------------------------------------------------------------------
# create_symbol
# ---------------------------------------------------------------------------


def create_symbol(op: Any, file_path: Path) -> dict[str, Any]:
    """Create a new symbol definition in a .kicad_sym library file.

    If the library file does not exist, it is created fresh. If it exists,
    the symbol is appended. Duplicate symbol names in an existing library
    are rejected.

    The symbol gets four standard properties (Reference, Value, Footprint,
    Datasheet) plus any custom properties from the op. A body rectangle is
    added at the symbol origin, and pins are placed per the PinSpec list.

    Args:
        op: CreateSymbolOp model instance.
        file_path: Resolved absolute path for the .kicad_sym file.

    Returns:
        Dict with target_file, symbol_name, pin_count.

    Raises:
        FileExistsError: If symbol_name already exists in the library.
    """
    file_path.parent.mkdir(parents=True, exist_ok=True)

    if file_path.exists():
        lib = SymbolLib.from_file(str(file_path))
        # Reject duplicate symbol names
        for existing in lib.symbols:
            if existing.entryName == op.symbol_name:
                raise ValueError(
                    f"Symbol '{op.symbol_name}' already exists in {op.target_file}"
                )
    else:
        lib = SymbolLib(version="20211014", generator="kicad_symbol_editor")

    # Build properties: Reference(0), Value(1), Footprint(2), Datasheet(3)
    properties: list[Property] = [
        Property(key="Reference", value=op.reference_prefix, id=0,
                 position=Position(X=0.0, Y=2.54),
                 effects=Effects(font=Font(height=1.27, width=1.27))),
        Property(key="Value", value=op.value or op.symbol_name, id=1,
                 position=Position(X=0.0, Y=-2.54),
                 effects=Effects(font=Font(height=1.27, width=1.27))),
        Property(key="Footprint", value="", id=2,
                 position=Position(X=0.0, Y=0.0),
                 effects=Effects(font=Font(height=1.27, width=1.27))),
        Property(key="Datasheet", value="", id=3,
                 position=Position(X=0.0, Y=0.0),
                 effects=Effects(font=Font(height=1.27, width=1.27))),
    ]

    # Add custom properties starting at id=4
    for i, prop in enumerate(op.properties):
        properties.append(Property(
            key=prop.name, value=prop.value, id=4 + i,
            position=Position(X=0.0, Y=0.0),
            effects=Effects(font=Font(height=1.27, width=1.27)),
        ))

    # Build pins
    pins: list[SymbolPin] = []
    for pin_spec in op.pins:
        pins.append(SymbolPin(
            electricalType=_ELECTRICAL_TYPE_MAP.get(pin_spec.electrical_type, "passive"),
            graphicalStyle=_GRAPHICAL_STYLE_MAP.get(pin_spec.graphical_style, "line"),
            position=Position(X=pin_spec.position.x, Y=pin_spec.position.y),
            length=pin_spec.length,
            name=pin_spec.name,
            nameEffects=Effects(font=Font(height=1.27, width=1.27)),
            number=pin_spec.number,
            numberEffects=Effects(font=Font(height=1.27, width=1.27)),
            hide=pin_spec.hide,
        ))

    # Build body rectangle centered at origin
    half_w = op.body_width / 2
    half_h = op.body_height / 2
    body_rect = SyRect(
        start=Position(X=-half_w, Y=-half_h),
        end=Position(X=half_w, Y=half_h),
        stroke=Stroke(width=0.0),
        fill=Fill(type="background", color=ColorRGBA(R=255, G=255, B=255, A=0)),
    )

    # Build the symbol
    symbol = Symbol(
        entryName=op.symbol_name,
        inBom=True,
        onBoard=True,
        properties=properties,
        graphicItems=[body_rect],
        pins=pins,
    )

    lib.symbols.append(symbol)
    lib.to_file(str(file_path))

    return {
        "target_file": op.target_file,
        "symbol_name": op.symbol_name,
        "pin_count": len(pins),
        "property_count": len(properties),
    }
