"""Format-agnostic Abstract AST models for circuit representation.

Defines Pydantic models that capture circuit semantics (components, pins,
nets, sheets) without any format-specific baggage. All format adapters
convert to and from these models.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator, model_validator


class PinType(str, Enum):
    """Format-agnostic pin electrical type.

    Matches KiCad pin types but is format-agnostic. Each format adapter
    maps its native pin types to these values.
    """

    INPUT = "input"
    OUTPUT = "output"
    BIDI = "bidi"
    PASSIVE = "passive"
    POWER_IN = "power_in"
    POWER_OUT = "power_out"
    UNSPECIFIED = "unspecified"
    NO_CONNECT = "no_connect"


class Position(BaseModel):
    """Absolute position on a sheet (mm)."""

    x: float
    y: float


class RelativePosition(BaseModel):
    """Position relative to component origin (mm)."""

    dx: float
    dy: float


class WireSegment(BaseModel):
    """A straight wire segment between two points."""

    start: Position
    end: Position


class AbstractPin(BaseModel):
    """A component pin in format-agnostic representation.

    Attributes:
        number: Pin number (e.g., "1", "A0", "EP" for exposed pad).
        name: Pin name (e.g., "VCC", "OUT+", "NC").
        pin_type: Electrical type of the pin.
        position: Position relative to component origin, if available.
    """

    number: str = Field(min_length=1)
    name: str = Field(min_length=1)
    pin_type: PinType
    position: Optional[RelativePosition] = None


class AbstractComponent(BaseModel):
    """A component in format-agnostic representation.

    Captures electrical identity (ref, value, lib_id) and optional
    physical information (footprint, position, rotation). Pins are
    included when available from the source format.

    Attributes:
        ref: Reference designator (e.g., "U1", "R3", "C10").
        lib_id: Library identifier (e.g., "Device:R", "THAT4301").
        value: Component value (e.g., "10k", "NE5532", "100nF").
        footprint: Footprint assignment, if known.
        position: Absolute position on sheet, if available.
        rotation: Rotation in degrees, if available.
        pins: List of pins with electrical types.
        properties: Format-specific key-value pairs not captured above.
    """

    ref: str = Field(min_length=1)
    lib_id: str = Field(min_length=1)
    value: str = ""
    footprint: Optional[str] = None
    position: Optional[Position] = None
    rotation: float = 0.0
    pins: list[AbstractPin] = Field(default_factory=list)
    properties: dict[str, str] = Field(default_factory=dict)

    @field_validator("ref")
    @classmethod
    def _ref_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("ref must not be empty or whitespace")
        return v

    @field_validator("lib_id")
    @classmethod
    def _lib_id_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("lib_id must not be empty or whitespace")
        return v

    @model_validator(mode="after")
    def _unique_pin_numbers(self) -> "AbstractComponent":
        numbers = [p.number for p in self.pins]
        if len(numbers) != len(set(numbers)):
            seen: set[str] = set()
            duplicates: list[str] = []
            for n in numbers:
                if n in seen:
                    duplicates.append(n)
                seen.add(n)
            raise ValueError(f"Duplicate pin numbers: {duplicates}")
        return self


class AbstractNet(BaseModel):
    """A named net connecting component pins.

    Attributes:
        name: Net name (e.g., "VCC", "feedback", "Net-(R1-Pad1)").
        pin_refs: List of (reference, pin_number) tuples identifying connected pins.
        wire_segments: Visual wire geometry (optional, may be empty for netlist-only data).
        labels: Net label names at various positions.
    """

    name: str = Field(min_length=1)
    pin_refs: list[tuple[str, str]] = Field(min_length=1)
    wire_segments: list[WireSegment] = Field(default_factory=list)
    labels: list[str] = Field(default_factory=list)

    @field_validator("name")
    @classmethod
    def _name_not_empty(cls, v: str) -> str:
        if not v.strip():
            raise ValueError("net name must not be empty or whitespace")
        return v


class AbstractSheet(BaseModel):
    """A schematic sheet (flat or hierarchical).

    Attributes:
        name: Sheet name or identifier.
        file_path: File path for hierarchical sheets.
        components: Components placed on this sheet.
        nets: Nets defined on this sheet.
        hierarchical_labels: Labels exposed to parent sheet.
    """

    name: str = Field(min_length=1)
    file_path: Optional[str] = None
    components: list[AbstractComponent] = Field(default_factory=list)
    nets: list[AbstractNet] = Field(default_factory=list)
    hierarchical_labels: list[str] = Field(default_factory=list)


class AbstractCircuit(BaseModel):
    """Top-level format-agnostic circuit representation.

    This is the central model that all format adapters convert to
    and from. Operations can work against AbstractCircuit for
    format-portable logic.

    Attributes:
        name: Circuit/project name.
        components: All components (flat list; sheets contain their own).
        nets: All nets (flat list; sheets contain their own).
        sheets: Hierarchical sheets (empty for single-sheet designs).
        metadata: Source format, version, creation timestamp, etc.
    """

    name: str = ""
    components: list[AbstractComponent] = Field(default_factory=list)
    nets: list[AbstractNet] = Field(default_factory=list)
    sheets: list[AbstractSheet] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)
