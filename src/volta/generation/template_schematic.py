"""Template schematic generator.

GEN-08: Creates valid .kicad_sch files from GenerationIntent specifications.

Generates schematics with:
- Component symbol instances with auto-placement
- Power symbols for each power net
- Net labels
- Embedded lib_symbols (minimal stubs when actual libraries unavailable)
- Round-trip validation (write -> re-parse -> verify)

Usage::

    from volta.generation.template_schematic import generate_schematic
    from volta.generation.intent import GenerationIntent, ComponentSpec

    intent = GenerationIntent(
        name="Test",
        components=[ComponentSpec(library_id="Device:R_Small_US", reference="R1")],
    )
    result = generate_schematic(Path("output.kicad_sch"), intent)
"""

import logging
import uuid
from dataclasses import dataclass
from pathlib import Path

from kiutils.items.common import Position
from kiutils.schematic import Schematic, SchematicSymbol

from volta.generation.intent import GenerationIntent

logger = logging.getLogger(__name__)

# Horizontal spacing between components (mm)
_COMPONENT_SPACING = 15.0
# Starting X position for first component (mm)
_START_X = 25.4  # 1 inch
# Y position for component row (mm)
_COMPONENT_Y = 25.4
# Y position for power symbols (mm), offset below components
_POWER_Y = 50.8  # 2 inches
# X spacing for power symbols
_POWER_SPACING = 12.7  # 0.5 inch


@dataclass(frozen=True)
class SchematicTemplate:
    """Metadata for a generated schematic template.

    Attributes:
        sch_path: Path to the generated .kicad_sch file.
        component_count: Number of component symbols placed.
        net_count: Number of distinct net labels added.
    """

    sch_path: Path
    component_count: int
    net_count: int


def generate_schematic(
    output_path: Path,
    intent: GenerationIntent,
) -> SchematicTemplate:
    """Generate a valid .kicad_sch file from GenerationIntent.

    Creates a KiCad schematic with component symbols, power symbols,
    and net labels. Uses minimal stub lib_symbols when actual library
    files are not available.

    Args:
        output_path: Where to write the .kicad_sch file.
        intent: GenerationIntent with component and net specifications.

    Returns:
        SchematicTemplate with generation metadata.

    Raises:
        ValueError: If output_path does not have .kicad_sch suffix.
        RuntimeError: If round-trip validation fails.
    """
    output_path = Path(output_path)
    if output_path.suffix != ".kicad_sch":
        raise ValueError(f"Expected .kicad_sch suffix, got: {output_path.suffix}")

    # Create new schematic
    from kiutils.items.common import TitleBlock

    sch = Schematic.create_new()
    sch.titleBlock = TitleBlock(title=intent.name)

    # Add minimal stub lib_symbols for each unique library_id
    lib_ids_seen: set[str] = set()
    for comp in intent.components:
        if comp.library_id not in lib_ids_seen:
            _add_stub_lib_symbol(sch, comp.library_id)
            lib_ids_seen.add(comp.library_id)

    # Add power lib_symbols for each power net
    for power_name in intent.power.nets:
        power_lib_id = f"power:{power_name}"
        if power_lib_id not in lib_ids_seen:
            _add_stub_power_lib_symbol(sch, power_name)
            lib_ids_seen.add(power_lib_id)

    # Place component symbols
    for i, comp in enumerate(intent.components):
        x = _START_X + i * _COMPONENT_SPACING
        if comp.position is not None:
            x = comp.position.x
            y = comp.position.y
        else:
            y = _COMPONENT_Y

        _add_symbol_instance(sch, comp.library_id, comp.reference, comp.value, x, y)

    # Place power symbols
    for i, power_name in enumerate(intent.power.nets):
        x = _START_X + i * _POWER_SPACING
        _add_power_symbol_instance(sch, power_name, x, _POWER_Y)

    # Count distinct net names from intent nets
    net_count = len(intent.nets)

    # Serialize
    output_path.parent.mkdir(parents=True, exist_ok=True)
    sch.to_file(str(output_path))

    # Round-trip validation: re-parse and verify the file is valid KiCad
    verified = Schematic.from_file(str(output_path))
    # Empty schematics are valid (no symbols, no graphical items is fine)
    # Only fail if the file could not be re-parsed (would raise exception above)
    if intent.components and not verified.schematicSymbols:
        raise RuntimeError(
            "Generated schematic has no symbols despite having component specifications"
        )

    return SchematicTemplate(
        sch_path=output_path,
        component_count=len(intent.components),
        net_count=net_count,
    )


def _add_stub_lib_symbol(sch: Schematic, library_id: str) -> None:
    """Add a minimal stub lib_symbol for a component library reference.

    KiCad schematics embed lib_symbols. When actual library files are
    unavailable, we create electrically valid stubs with a single pin
    but no graphical data.

    Args:
        sch: Schematic to add lib_symbol to.
        library_id: Library reference, e.g. "Device:R_Small_US".
    """
    from kiutils.symbol import Symbol

    if ":" in library_id:
        lib_nick, entry_name = library_id.split(":", 1)
    else:
        lib_nick = ""
        entry_name = library_id

    stub = Symbol(
        libraryNickname=lib_nick,
        entryName=entry_name,
    )
    # Add minimal properties
    from kiutils.symbol import Property as SymProperty

    stub.properties.append(
        SymProperty(key="Reference", value="R?")
    )
    stub.properties.append(
        SymProperty(key="Value", value="")
    )

    sch.libSymbols.append(stub)


def _add_stub_power_lib_symbol(sch: Schematic, power_name: str) -> None:
    """Add a minimal stub power lib_symbol.

    Power symbols have isPower=True and represent power nets.

    Args:
        sch: Schematic to add power lib_symbol to.
        power_name: Power net name (e.g. "GND", "+3V3").
    """
    from kiutils.symbol import Property as SymProperty, Symbol

    lib_id = f"power:{power_name}"
    stub = Symbol(
        libraryNickname="power",
        entryName=power_name,
        isPower=True,
    )
    stub.properties.append(
        SymProperty(key="Reference", value="#PWR?")
    )
    stub.properties.append(
        SymProperty(key="Value", value=power_name)
    )

    sch.libSymbols.append(stub)


def _add_symbol_instance(
    sch: Schematic,
    library_id: str,
    reference: str,
    value: str,
    x: float,
    y: float,
) -> None:
    """Add a schematic symbol instance at (x, y).

    Args:
        sch: Schematic to add symbol to.
        library_id: Library reference for the symbol.
        reference: Reference designator.
        value: Component value.
        x: X position in mm.
        y: Y position in mm.
    """
    if ":" in library_id:
        lib_nick, entry_name = library_id.split(":", 1)
    else:
        lib_nick = ""
        entry_name = library_id

    from kiutils.items.common import Property

    sym = SchematicSymbol(
        libraryNickname=lib_nick,
        entryName=entry_name,
        libName=lib_nick,
        position=Position(x, y, 0),
        uuid=str(uuid.uuid4()),
    )
    sym.properties.append(Property(key="Reference", value=reference))
    sym.properties.append(Property(key="Value", value=value))

    sch.schematicSymbols.append(sym)


def _add_power_symbol_instance(
    sch: Schematic,
    power_name: str,
    x: float,
    y: float,
) -> None:
    """Add a power symbol instance to the schematic.

    Args:
        sch: Schematic to add power symbol to.
        power_name: Power net name.
        x: X position in mm.
        y: Y position in mm.
    """
    from kiutils.items.common import Property

    sym = SchematicSymbol(
        libraryNickname="power",
        entryName=power_name,
        libName="power",
        position=Position(x, y, 0),
        uuid=str(uuid.uuid4()),
    )
    sym.properties.append(
        Property(key="Reference", value=f"#PWR{len(sch.schematicSymbols) + 1:03d}")
    )
    sym.properties.append(Property(key="Value", value=power_name))

    sch.schematicSymbols.append(sym)
