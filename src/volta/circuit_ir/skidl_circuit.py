"""Phase 156 Wave 1: KiCad→SKIDL read-back — build_circuit core.

Composes SchematicIR + extract_nets into a live skdl.Circuit with
pin-name-based wiring (Code-L1 representation). This is the foundational
new capability — the one direction that did not exist.

Pipeline:
  1. Parse the .kicad_sch via the native parser (for component metadata).
  2. Extract net topology via extract_nets (the proven connectivity path).
  3. Build skidl.Part objects for each non-power component.
  4. Build skidl.Net objects and wire pins via the += operator.
  5. Return (circuit, circuit_ir) where circuit_ir is the immutable IR.
"""

from __future__ import annotations

import logging
from pathlib import Path

from volta.circuit_ir.types import (
    CircuitIR,
    NetDescriptor,
    PartDescriptor,
    PinRef,
)

logger = logging.getLogger(__name__)

# Power symbol detection: lib_id prefix or reference pattern.
_POWER_PREFIX = "power:"
_POWER_REF_PREFIXES = ("#PWR", "#FLG")


def build_circuit(
    sch_path: Path | str,
    *,
    symbol_dir: str | None = None,
) -> tuple[object, CircuitIR]:
    """Build a skidl.Circuit from a KiCad schematic file.

    This is the KiCad→SKIDL read-back path. It reads components and nets
    from a .kicad_sch and constructs a live skidl.Circuit with pin-name-
    based wiring.

    Args:
        sch_path: Path to the .kicad_sch file.
        symbol_dir: Optional KICAD_SYMBOL_DIR override.

    Returns:
        Tuple of (skidl.Circuit, CircuitIR). The Circuit is a live skidl
        object that can generate netlists, run ERC, etc. The CircuitIR is
        the immutable intermediate representation for downstream phases.

    Raises:
        FileNotFoundError: If the schematic doesn't exist.
        RuntimeError: If KICAD_SYMBOL_DIR can't be resolved.
    """
    from volta.circuit_ir import _ensure_skidl_env
    _ensure_skidl_env(symbol_dir)

    import skidl
    from volta.parser.pcb_native_parser import NativeParser
    from volta.schematic_routing.net_extractor import extract_nets

    sch_path = Path(sch_path)
    if not sch_path.exists():
        raise FileNotFoundError(f"Schematic not found: {sch_path}")

    # Step 1: Extract net topology using the proven extract_nets path.
    nets_result = extract_nets(sch_path, include_positions=False)
    nets_data: dict[str, list[dict]] = nets_result.get("nets", {})

    # Step 2: Extract components from the raw schematic content.
    content = sch_path.read_text(encoding="utf-8")
    components = _extract_components(content)

    diagnostics: list[str] = []

    # Step 3: Separate power symbols from real components.
    power_nets: set[str] = set()
    real_parts: list[PartDescriptor] = []

    for comp in components:
        if comp.is_power:
            power_nets.add(comp.value)
        else:
            real_parts.append(comp)

    # Step 4: Build the skidl.Circuit.
    circuit = skidl.Circuit()
    circuit.name = sch_path.stem

    # Use the circuit context so all Part/Net creations are scoped.
    with circuit:
        # Create Part objects.
        part_objects: dict[str, object] = {}
        for pd in real_parts:
            try:
                lib, name = pd.lib_id.split(":", 1) if ":" in pd.lib_id else ("Device", pd.lib_id)
                kwargs = {"value": pd.value}
                if pd.footprint:
                    kwargs["footprint"] = pd.footprint
                p = skidl.Part(lib, name, **kwargs)
                # Set the reference explicitly.
                p.ref = pd.reference
                part_objects[pd.reference] = p
            except Exception as e:
                diagnostics.append(
                    f"Failed to create Part for {pd.reference} ({pd.lib_id}): {e}"
                )
                # Fallback: create a generic connector.
                try:
                    p = skidl.Part("Connector_Generic", "Conn_01x02",
                                   value=pd.value, footprint=pd.footprint or "")
                    p.ref = pd.reference
                    part_objects[pd.reference] = p
                    diagnostics.append(
                        f"Fallback: {pd.reference} → Conn_01x02"
                    )
                except Exception:
                    diagnostics.append(
                        f"Complete failure for {pd.reference} — omitted from circuit"
                    )

        # Create Net objects and wire pins.
        net_descriptors: list[NetDescriptor] = []
        for net_name, pins in nets_data.items():
            is_power = net_name in power_nets or _is_power_net_name(net_name)

            # Create the net.
            net = skidl.Net(net_name)

            # Wire each pin.
            pin_refs: list[PinRef] = []
            for pin_info in pins:
                ref = pin_info.get("ref", "")
                pin_num = str(pin_info.get("pin_number", ""))
                pin_name = pin_info.get("pin_name", pin_num)

                if ref in part_objects:
                    part = part_objects[ref]
                    try:
                        # Try pin number first, then pin name.
                        try:
                            net += part[pin_num]
                        except (KeyError, IndexError):
                            if pin_name and pin_name != "?":
                                net += part[pin_name]
                    except Exception as e:
                        diagnostics.append(
                            f"Wire error: {ref}[{pin_num}] ({pin_name}) "
                            f"→ net '{net_name}': {e}"
                        )

                pin_refs.append(PinRef(
                    reference=ref,
                    pin_number=pin_num,
                    pin_name=pin_name,
                ))

            net_descriptors.append(NetDescriptor(
                name=net_name,
                pins=tuple(pin_refs),
                is_power=is_power,
            ))

    # Step 5: Build the immutable CircuitIR.
    circuit_ir = CircuitIR(
        parts=tuple(real_parts),
        nets=tuple(net_descriptors),
        diagnostics=tuple(diagnostics),
        source_file=str(sch_path),
    )

    logger.info(
        "Built circuit from %s: %d parts, %d nets, %d diagnostics",
        sch_path.name, len(real_parts), len(net_descriptors), len(diagnostics),
    )

    return circuit, circuit_ir


def _extract_components(content: str) -> list[PartDescriptor]:
    """Extract component metadata from raw .kicad_sch S-expression content.

    Parses symbol instances (outside lib_symbols) to get lib_id, reference,
    value, footprint, unit, and pin info. Power symbols are flagged.
    """
    import re

    components: list[PartDescriptor] = []

    # Find the end of lib_symbols section to skip embedded definitions.
    lib_end = _find_lib_symbols_end(content)
    after_lib = content[lib_end:]

    # Match component instances: (symbol (lib_id "...") ... (at X Y) (unit N) ...)
    # Each has properties for Reference, Value, Footprint.
    symbol_re = re.compile(
        r'\(symbol\s+\(lib_id\s+"([^"]+)"\)\s*'
        r'\(at\s+([-0-9.]+)\s+([-0-9.]+)(?:\s+([-0-9.]+))?\)',
        re.DOTALL,
    )

    for sym_match in symbol_re.finditer(after_lib):
        lib_id = sym_match.group(1)

        # Find the end of this symbol block (balanced parens).
        block_start = sym_match.start()
        block_end = _find_block_end(after_lib, block_start)
        block = after_lib[block_start:block_end]

        # Extract properties.
        ref = _extract_property(block, "Reference")
        value = _extract_property(block, "Value")
        footprint = _extract_property(block, "Footprint")

        # Skip if no reference (likely a power flag or internal).
        if not ref or ref.startswith("#") and not ref.startswith("#PWR"):
            # Power symbols have refs like #PWR01 — capture them.
            if ref.startswith("#PWR") or ref.startswith("#FLG"):
                is_power = True
                net_name = value if value else lib_id.split(":")[-1]
            else:
                continue  # Skip non-component symbols.
        else:
            is_power = lib_id.startswith(_POWER_PREFIX)

        # Extract unit number (default 1).
        unit_match = re.search(r'\(unit\s+(\d+)\)', block)
        unit = int(unit_match.group(1)) if unit_match else 1

        # For power symbols, value is the net name.
        if is_power:
            net_name = value if value else lib_id.split(":")[-1]
            pd = PartDescriptor(
                lib_id=lib_id,
                reference=ref,
                value=net_name,
                footprint="",
                unit=unit,
                is_power=True,
                pins=(),  # Power symbols have no BOM pins.
            )
        else:
            pd = PartDescriptor(
                lib_id=lib_id,
                reference=ref,
                value=value or "",
                footprint=footprint or "",
                unit=unit,
                is_power=False,
                pins=(),  # Pins extracted from nets in build_circuit.
            )

        components.append(pd)

    return components


def _find_lib_symbols_end(content: str) -> int:
    """Find the end of the (lib_symbols ...) section."""
    idx = content.find("(lib_symbols")
    if idx < 0:
        return 0
    depth = 0
    for i in range(idx, len(content)):
        if content[i] == "(":
            depth += 1
        elif content[i] == ")":
            depth -= 1
            if depth == 0:
                return i + 1
    return 0


def _find_block_end(content: str, start: int) -> int:
    """Find the end of a balanced-paren block starting at 'start'."""
    depth = 0
    for i in range(start, len(content)):
        if content[i] == "(":
            depth += 1
        elif content[i] == ")":
            depth -= 1
            if depth == 0:
                return i + 1
    return len(content)


def _extract_property(block: str, key: str) -> str:
    """Extract a property value from a symbol block."""
    import re
    match = re.search(
        rf'\(property\s+"{key}"\s+"((?:[^"\\]|\\.)*)"', block
    )
    if match:
        return match.group(1).replace('\\"', '"')
    return ""


def _is_power_net_name(name: str) -> bool:
    """Check if a net name looks like a power rail."""
    power_patterns = ("GND", "VCC", "VDD", "VSS", "VEE", "+3V3", "+5V",
                      "+12V", "-12V", "+1V8", "+9V", "AVDD", "AVCC", "AGND",
                      "DGND", "GNDA", "GNDD", "VBUS", "VBAT")
    name_upper = name.upper()
    for p in power_patterns:
        if name_upper == p or name_upper == p.upper():
            return True
    return name.startswith("+") or name.startswith("-") or name.startswith("V")
