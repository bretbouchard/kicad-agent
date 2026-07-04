"""Phase 156: Immutable circuit IR types.

Frozen dataclasses mirroring the ltspice/types.py pattern. These are the
canonical representation that build_circuit produces and downstream phases
(157 floor planner, 158 SPICE, 159 training data) consume.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PinRef:
    """A reference to a specific pin on a specific component.

    Attributes:
        reference: Component reference designator (e.g. "R1", "U3").
        pin_number: Pin number as a string (e.g. "1", "8", "A").
        pin_name: Pin name from the symbol library (e.g. "VCC", "IN+").
        unit: Unit number for multi-unit symbols (None for single-unit).
    """

    reference: str
    pin_number: str
    pin_name: str
    unit: int | None = None


@dataclass(frozen=True)
class PartDescriptor:
    """A component extracted from a KiCad schematic.

    Attributes:
        lib_id: KiCad library ID (e.g. "Device:R", "Amplifier_Operational:NE5532").
        reference: Reference designator (e.g. "R1").
        value: Component value (e.g. "10k", "NE5532").
        footprint: KiCad footprint lib_id (may be empty).
        unit: Unit number (1 for single-unit, >1 for multi-unit instances).
        is_power: True if this is a power symbol (handled as Net, not Part).
        pins: Tuple of PinRefs for this part.
        sheet: Originating sheet path (for hierarchical schematics). None = root.
    """

    lib_id: str
    reference: str
    value: str
    footprint: str
    unit: int
    is_power: bool
    pins: tuple[PinRef, ...]
    sheet: str | None = None


@dataclass(frozen=True)
class NetDescriptor:
    """A net (electrical connection) extracted from the schematic.

    Attributes:
        name: Net name (from labels, or auto-generated "Net_N").
        pins: Tuple of PinRefs connected to this net.
        is_power: True if this is a power rail (GND, +3V3, etc.).
    """

    name: str
    pins: tuple[PinRef, ...]
    is_power: bool = False


@dataclass(frozen=True)
class CircuitIR:
    """The complete circuit intermediate representation.

    Immutable and hashable. This is what build_circuit returns alongside
    the live skidl.Circuit — downstream phases consume CircuitIR.

    Attributes:
        parts: Tuple of all non-power PartDescriptors.
        nets: Tuple of all NetDescriptors (including power nets).
        diagnostics: Tuple of diagnostic messages (fallbacks, warnings).
        source_file: Path to the source .kicad_sch file.
    """

    parts: tuple[PartDescriptor, ...]
    nets: tuple[NetDescriptor, ...]
    diagnostics: tuple[str, ...]
    source_file: str
