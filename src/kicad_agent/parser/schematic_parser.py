"""Schematic (.kicad_sch) file parser.

Parses KiCad schematic files into kiutils Schematic objects with raw content
preservation for downstream processing. Schematic UUIDs are preserved by kiutils.

Usage:
    from kicad_agent.parser.schematic_parser import parse_schematic

    result = parse_schematic(Path("my_schematic.kicad_sch"))
    components = result.kiutils_obj.schematicSymbols
    raw_text = result.raw_content  # For UUID extraction if needed
"""

from pathlib import Path
from dataclasses import dataclass
from typing import Any

from kiutils.schematic import Schematic


@dataclass(frozen=True)
class ParseResult:
    """Generic container for parsed KiCad file content.

    Attributes:
        kiutils_obj: The typed kiutils object (Schematic, Board, SymbolLib, Footprint).
        raw_content: Original file text preserved for UUID extraction and fallback processing.
        file_path: Source file path.
        file_type: One of: 'schematic', 'pcb', 'symbol_lib', 'footprint'.
    """

    kiutils_obj: Any
    raw_content: str
    file_path: Path
    file_type: str


def parse_schematic(path: Path) -> ParseResult:
    """Parse a .kicad_sch file into a kiutils Schematic object.

    Reads the file text for raw content preservation, then parses via
    kiutils for typed dataclass access. Schematic UUIDs are preserved
    by kiutils (unlike PCB/footprint UUIDs which are dropped).

    Args:
        path: Path to a .kicad_sch file.

    Returns:
        ParseResult with kiutils_obj as Schematic, raw_content as file text,
        file_type as 'schematic'.

    Raises:
        FileNotFoundError: If path does not exist.
        ValueError: If file extension is not .kicad_sch.
    """
    if not path.exists():
        raise FileNotFoundError(f"Schematic file not found: {path}")

    if path.suffix != ".kicad_sch":
        raise ValueError(f"Expected .kicad_sch file, got {path.suffix}")

    raw_content = path.read_text(encoding="utf-8")
    schematic = Schematic.from_file(str(path))

    return ParseResult(
        kiutils_obj=schematic,
        raw_content=raw_content,
        file_path=path,
        file_type="schematic",
    )
