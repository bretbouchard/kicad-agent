"""Format-agnostic Abstract AST for circuit representation.

The Abstract AST is the internal representation that all format
adapters (KiCad, EasyEDA, Altium, Eagle) convert to and from.
Operations (ERC, routing, BOM generation) can work against
AbstractCircuit for format-portable logic.
"""

from kicad_agent.abstract_ast.models import (
    PinType,
    Position,
    RelativePosition,
    WireSegment,
    AbstractPin,
    AbstractComponent,
    AbstractNet,
    AbstractSheet,
    AbstractCircuit,
)

__all__ = [
    "PinType",
    "Position",
    "RelativePosition",
    "WireSegment",
    "AbstractPin",
    "AbstractComponent",
    "AbstractNet",
    "AbstractSheet",
    "AbstractCircuit",
]
