"""PCB IR -- thin wrapper over a kiutils Board object with mutation tracking.

D-05: Holds reference to kiutils Board (not a copy).
D-06: Tracks mutations, dirty flag.
D-07: PCB-specific IR.

CRITICAL: kiutils drops all UUID tokens from PCB files (only handles legacy tstamp).
_uuid_map is required for serialization. The PCB IR constructor enforces this
requirement.

Usage:
    from kicad_agent.ir.pcb_ir import PcbIR
    from kicad_agent.parser import parse_pcb
    from kicad_agent.parser.uuid_extractor import extract_uuids

    result = parse_pcb(Path("my_board.kicad_pcb"))
    uuid_map = extract_uuids(result.raw_content, "pcb")
    ir = PcbIR(_parse_result=result, _uuid_map=uuid_map)
    footprints = ir.footprints
"""

from dataclasses import dataclass
from typing import Any, Optional

from kiutils.board import Board

from kicad_agent.ir.base import BaseIR
from kicad_agent.parser.types import ParseResult
from kicad_agent.parser.uuid_extractor import UUIDMap


@dataclass
class PcbIR(BaseIR):
    """Thin wrapper over a kiutils Board object with mutation tracking.

    D-05: Holds reference to kiutils Board (not a copy).
    D-06: Tracks mutations, dirty flag, UUID map reference.
    D-07: PCB-specific IR.

    CRITICAL: kiutils drops all UUID tokens from PCB files. _uuid_map is
    required for serialization.
    """

    def __post_init__(self) -> None:
        """Validate file type matches PCB and UUID map is provided."""
        super().__post_init__()
        if self.file_type != "pcb":
            raise ValueError(
                f"Expected file_type='pcb', got {self.file_type!r}"
            )
        if self._uuid_map is None:
            raise ValueError(
                "PcbIR requires a UUID map for serialization. "
                "kiutils drops all UUID tokens from PCB files. "
                "Use extract_uuids() from kicad_agent.parser.uuid_extractor."
            )

    @property
    def board(self) -> Board:
        """Direct access to the kiutils Board object."""
        return self._parse_result.kiutils_obj

    @property
    def footprints(self) -> list:
        """Access to PCB footprints."""
        return self._parse_result.kiutils_obj.footprints

    @property
    def nets(self) -> list:
        """Access to PCB nets."""
        return self._parse_result.kiutils_obj.nets

    @property
    def trace_items(self) -> list:
        """Access to PCB trace items (segments, arcs, vias)."""
        return self._parse_result.kiutils_obj.traceItems
