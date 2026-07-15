"""Footprint IR -- thin wrapper over a kiutils Footprint object with mutation tracking.

D-05: Holds reference to kiutils Footprint (not a copy).
D-06: Tracks mutations, dirty flag.
D-07: Footprint-specific IR.

CRITICAL: kiutils drops all UUID tokens from footprint files (only handles legacy tstamp).
_uuid_map is required for serialization. The Footprint IR constructor enforces this
requirement.

Usage:
    from volta.ir.footprint_ir import FootprintIR
    from volta.parser import parse_footprint
    from volta.parser.uuid_extractor import extract_uuids

    result = parse_footprint(Path("MountingHole_3.2mm.kicad_mod"))
    uuid_map = extract_uuids(result.raw_content, "footprint")
    ir = FootprintIR(_parse_result=result, _uuid_map=uuid_map)
    pads = ir.pads
"""

from dataclasses import dataclass
from typing import Any, Optional

from kiutils.footprint import Footprint

from volta.ir.base import BaseIR
from volta.parser.types import ParseResult
from volta.parser.uuid_extractor import UUIDMap


@dataclass
class FootprintIR(BaseIR):
    """Thin wrapper over a kiutils Footprint object with mutation tracking.

    D-05: Holds reference to kiutils Footprint (not a copy).
    D-06: Tracks mutations, dirty flag, UUID map reference.
    D-07: Footprint-specific IR.

    CRITICAL: kiutils drops all UUID tokens from footprint files. _uuid_map is
    required for serialization.
    """

    def __post_init__(self) -> None:
        """Validate file type matches footprint and UUID map is provided."""
        super().__post_init__()
        if self.file_type != "footprint":
            raise ValueError(
                f"Expected file_type='footprint', got {self.file_type!r}"
            )
        if self._uuid_map is None:
            raise ValueError(
                "FootprintIR requires a UUID map for serialization. "
                "kiutils drops all UUID tokens from footprint files. "
                "Use extract_uuids() from volta.parser.uuid_extractor."
            )

    @property
    def footprint(self) -> Footprint:
        """Direct access to the kiutils Footprint object."""
        return self._parse_result.kiutils_obj

    @property
    def pads(self) -> list:
        """Access to footprint pads."""
        return self._parse_result.kiutils_obj.pads

    @property
    def fp_lines(self) -> list:
        """Access to all footprint graphic items (lines, circles, arcs, polygons)."""
        return self._parse_result.kiutils_obj.graphicItems

    @property
    def fp_text(self) -> list:
        """Access to footprint text items (FpText from graphicItems)."""
        from kiutils.items.fpitems import FpText
        return [
            item for item in self._parse_result.kiutils_obj.graphicItems
            if isinstance(item, FpText)
        ]
