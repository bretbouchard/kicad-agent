"""Footprint (.kicad_mod) file parser.

Placeholder module -- full implementation in Task 2.
"""

from pathlib import Path
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ParseResult:
    """Generic container for parsed KiCad file content."""
    kiutils_obj: Any
    raw_content: str
    file_path: Path
    file_type: str


def parse_footprint(path: Path) -> ParseResult:
    """Parse a .kicad_mod file. Implemented in Task 2."""
    raise NotImplementedError("Task 2")
