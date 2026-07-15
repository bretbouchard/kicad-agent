"""Symbol library IR -- thin wrapper over a kiutils SymbolLib object with mutation tracking.

D-05: Holds reference to kiutils SymbolLib (not a copy).
D-06: Tracks mutations, dirty flag.
D-07: Symbol library-specific IR.

Usage:
    from volta.ir.symbol_lib_ir import SymbolLibIR
    from volta.parser import parse_symbol_lib

    result = parse_symbol_lib(Path("Device.kicad_sym"))
    ir = SymbolLibIR(_parse_result=result)
    symbols = ir.symbols
"""

from dataclasses import dataclass
from typing import Any, Optional

from kiutils.symbol import SymbolLib

from volta.ir.base import BaseIR
from volta.parser.types import ParseResult
from volta.parser.uuid_extractor import UUIDMap


@dataclass
class SymbolLibIR(BaseIR):
    """Thin wrapper over a kiutils SymbolLib object with mutation tracking.

    D-05: Holds reference to kiutils SymbolLib (not a copy).
    D-06: Tracks mutations, dirty flag.
    D-07: Symbol library-specific IR.
    """

    def __post_init__(self) -> None:
        """Validate file type matches symbol library."""
        super().__post_init__()
        if self.file_type != "symbol_lib":
            raise ValueError(
                f"Expected file_type='symbol_lib', got {self.file_type!r}"
            )

    @property
    def symbol_lib(self) -> SymbolLib:
        """Direct access to the kiutils SymbolLib object."""
        return self._parse_result.kiutils_obj

    @property
    def symbols(self) -> list:
        """Access to symbol library symbols."""
        return self._parse_result.kiutils_obj.symbols
