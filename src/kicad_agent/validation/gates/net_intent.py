"""Net intent extraction for schematic intent completeness gate.

Extracts net classification and schematic quality warnings from a SchematicIR.
Extends the existing NetClassifier with gate-specific categories (HIGH_CURRENT,
DIFFERENTIAL_PAIR, ANALOG, DIGITAL) using a delegation pattern -- the base
classifier handles POWER, GROUND, SIGNAL, CLOCK, CONTROL, FEEDBACK, then gate-specific
rules override UNKNOWN results.

Also detects quality issues:
  - Hidden power pins (unconnected power pins inside multi-unit symbols)
  - Ambiguous connectors (connectors without pin-type assignments)
  - Stub symbols (symbols with zero pins)

Module-level pattern constants follow existing validation_gates.py convention
(e.g., _POWER_PIN_TYPES, _COMMON_POWER_NETS).
"""

from __future__ import annotations

import logging
import re
from typing import Any

from kicad_agent.analysis.net_classifier import NetClassifier
from kicad_agent.analysis.types import NetClassification

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Gate-specific pattern constants (council MEDIUM-2: consistent with
# _POWER_PIN_TYPES pattern in validation_gates.py)
# ---------------------------------------------------------------------------

# Suffixes that indicate high-current nets
_HIGH_CURRENT_SUFFIXES = ("_MOT", "_DRV", "_OUT", "_LOAD")

# Regex patterns for high-current net names (motors, heaters, solenoids, drivers)
_HIGH_CURRENT_PATTERNS = re.compile(
    r"(MOT|DRIVE|MOTOR|HEATER|SOLENOID)", re.IGNORECASE
)

# Differential pair naming: name_P / name_N suffix or name+ / name- suffix.
# Requires at least 2 chars before the suffix to avoid false positives like "PIN".
_DIFF_PAIR_PATTERN = re.compile(r"(.{2,})[_](P|N)$|(.{2,})[+-]$")

# Analog signal patterns (ADC, DAC, op-amp related)
_ANALOG_PATTERNS = re.compile(
    r"(ADC|DAC|AIN|AOUT|ANALOG|OPAMP|OP_AMP)", re.IGNORECASE
)

# Digital signal patterns (SPI, UART, I2C, etc.)
_DIGITAL_PATTERNS = re.compile(
    r"(DOUT|DIN|SDA|SCL|SPI|MOSI|MISO|CS|UART|TX|RX)", re.IGNORECASE
)

# Connector reference prefixes
_CONNECTOR_PREFIXES = ("J", "CN", "CONN", "P")


# ---------------------------------------------------------------------------
# Helper functions
# ---------------------------------------------------------------------------


def _is_high_current(name: str) -> bool:
    """Check if a net name indicates a high-current path."""
    upper = name.upper()
    if any(upper.endswith(suffix) for suffix in _HIGH_CURRENT_SUFFIXES):
        return True
    return bool(_HIGH_CURRENT_PATTERNS.search(name))


def _is_differential_pair(name: str) -> bool:
    """Check if a net name follows differential pair naming convention."""
    return bool(_DIFF_PAIR_PATTERN.match(name))


def _is_analog(name: str) -> bool:
    """Check if a net name indicates an analog signal."""
    return bool(_ANALOG_PATTERNS.search(name))


def _is_digital(name: str) -> bool:
    """Check if a net name indicates a digital signal."""
    return bool(_DIGITAL_PATTERNS.search(name))


def _is_connector_ref(reference: str) -> bool:
    """Check if a reference designator indicates a connector."""
    upper = reference.upper()
    return any(upper.startswith(prefix) for prefix in _CONNECTOR_PREFIXES)


# ---------------------------------------------------------------------------
# NetIntentExtractor
# ---------------------------------------------------------------------------


class NetIntentExtractor:
    """Extracts net intent from schematic IR for gate validation.

    Extends existing NetClassifier with gate-specific categories.
    Delegates standard classification to NetClassifier, then applies
    gate-specific rules (high_current, differential_pair, analog, digital)
    that override UNKNOWN results from the base classifier.
    """

    def __init__(self) -> None:
        self._base_classifier = NetClassifier()

    def extract_nets(self, schematic_ir: Any) -> dict[str, NetClassification]:
        """Classify all nets using base classifier + gate-specific rules.

        Builds a net-to-pin-roles mapping from the schematic IR, delegates
        to NetClassifier for standard categories, then applies gate-specific
        rules to upgrade UNKNOWN nets to more specific classifications.

        Args:
            schematic_ir: SchematicIR instance (or mock) with components,
                wires, labels, and net connectivity.

        Returns:
            Mapping of net_name -> NetClassification.
        """
        # Collect net names from the IR
        net_names: set[str] = set()

        # From wire labels (local labels, global labels)
        for label in getattr(schematic_ir, "labels", []):
            name = getattr(label, "text", "") or getattr(label, "name", "")
            if name:
                net_names.add(name)

        # From net labels
        for net_label in getattr(schematic_ir, "net_labels", []):
            name = getattr(net_label, "text", "") or getattr(net_label, "name", "")
            if name:
                net_names.add(name)

        # Classify using base classifier first
        net_map: dict[str, NetClassification] = {}
        for name in net_names:
            base_result = self._base_classifier.classify(name)
            net_map[name] = base_result

        # Apply gate-specific overrides for UNKNOWN results
        for name, cls in list(net_map.items()):
            if cls == NetClassification.UNKNOWN:
                if _is_high_current(name):
                    net_map[name] = NetClassification.HIGH_CURRENT
                elif _is_differential_pair(name):
                    net_map[name] = NetClassification.DIFFERENTIAL_PAIR
                elif _is_analog(name):
                    net_map[name] = NetClassification.ANALOG
                elif _is_digital(name):
                    net_map[name] = NetClassification.DIGITAL

        return net_map

    def detect_hidden_power_pins(self, schematic_ir: Any) -> list[str]:
        """Find unconnected power pins inside multi-unit symbols.

        Scans lib_symbols for multi-unit components where power pins exist
        in units that may not be visible on the schematic. Returns a list
        of "Reference.pin_name" strings for unconnected power pins.

        Args:
            schematic_ir: SchematicIR instance with components and lib_symbols.

        Returns:
            List of "Reference.pin_name" strings for hidden power pins.
        """
        hidden: list[str] = []

        lib_symbols = getattr(schematic_ir, "schematic", None)
        if lib_symbols is None:
            return hidden
        lib_symbols_list = getattr(lib_symbols, "libSymbols", [])

        components = getattr(schematic_ir, "components", [])
        for comp in components:
            comp_lib_id = getattr(comp, "libId", "")
            ref = None
            for prop in getattr(comp, "properties", []):
                if getattr(prop, "key", "") == "Reference":
                    ref = getattr(prop, "value", "")
                    break
            if ref is None:
                continue

            # Find matching lib_symbol
            for lib_sym in lib_symbols_list:
                sym_lib_id = getattr(lib_sym, "libId", "")
                if sym_lib_id != comp_lib_id:
                    # Fallback: match by entry name
                    if ":" in comp_lib_id:
                        entry = comp_lib_id.split(":")[-1]
                        sym_entry = getattr(lib_sym, "entryName", "")
                        if sym_entry != entry:
                            continue
                    else:
                        continue

                # Check for multi-unit with power pins
                units = getattr(lib_sym, "units", [])
                if len(units) <= 1:
                    # Also check direct pins on lib_symbol (no units)
                    pins = getattr(lib_sym, "pins", [])
                    for pin in pins:
                        etype = getattr(pin, "electricalType", "")
                        pin_name = getattr(pin, "name", "")
                        if etype == "power_in" and pin_name:
                            hidden.append(f"{ref}.{pin_name}")
                    continue

                # Multi-unit: check units beyond the first for power pins
                for unit in units[1:]:
                    for pin in getattr(unit, "pins", []):
                        etype = getattr(pin, "electricalType", "")
                        pin_name = getattr(pin, "name", "")
                        if etype == "power_in" and pin_name:
                            hidden.append(f"{ref}.{pin_name}")

        return hidden

    def detect_ambiguous_connectors(self, schematic_ir: Any) -> list[str]:
        """Find connectors without pin-type assignments.

        A connector is ambiguous if all its pins have generic "passive"
        electrical type. Connectors typically should have input, output,
        or bidirectional pin types assigned for proper net intent inference.

        Args:
            schematic_ir: SchematicIR instance with components and lib_symbols.

        Returns:
            List of connector references with ambiguous pin types.
        """
        ambiguous: list[str] = []

        lib_symbols = getattr(schematic_ir, "schematic", None)
        if lib_symbols is None:
            return ambiguous
        lib_symbols_list = getattr(lib_symbols, "libSymbols", [])

        components = getattr(schematic_ir, "components", [])
        for comp in components:
            lib_id = getattr(comp, "libId", "")
            ref = None
            for prop in getattr(comp, "properties", []):
                if getattr(prop, "key", "") == "Reference":
                    ref = getattr(prop, "value", "")
                    break
            if ref is None:
                continue

            # Check if this is a connector by reference prefix
            if not _is_connector_ref(ref):
                # Also check by lib_id
                entry = lib_id.split(":")[-1] if ":" in lib_id else lib_id
                if not any(
                    entry.upper().startswith(p) for p in _CONNECTOR_PREFIXES
                ):
                    continue

            # Find matching lib_symbol and check pin types
            for lib_sym in lib_symbols_list:
                sym_lib_id = getattr(lib_sym, "libId", "")
                if sym_lib_id != lib_id:
                    if ":" in lib_id:
                        entry = lib_id.split(":")[-1]
                        sym_entry = getattr(lib_sym, "entryName", "")
                        if sym_entry != entry:
                            continue
                    else:
                        continue

                # Collect all pin electrical types
                pin_types: list[str] = []
                units = getattr(lib_sym, "units", [])
                if units:
                    for unit in units:
                        for pin in getattr(unit, "pins", []):
                            etype = getattr(pin, "electricalType", "")
                            if etype:
                                pin_types.append(etype)
                else:
                    for pin in getattr(lib_sym, "pins", []):
                        etype = getattr(pin, "electricalType", "")
                        if etype:
                            pin_types.append(etype)

                # If all pins are "passive" and there are pins, it's ambiguous
                if pin_types and all(t == "passive" for t in pin_types):
                    ambiguous.append(ref)

        return ambiguous

    def detect_stub_symbols(self, schematic_ir: Any) -> list[str]:
        """Find symbols with zero pins.

        Stub symbols have no pins at all in their lib_symbol definition.
        These are usually placeholder or broken symbols that should not
        proceed to PCB layout.

        Args:
            schematic_ir: SchematicIR instance with components and lib_symbols.

        Returns:
            List of symbol references that have no pins.
        """
        stubs: list[str] = []

        lib_symbols = getattr(schematic_ir, "schematic", None)
        if lib_symbols is None:
            return stubs
        lib_symbols_list = getattr(lib_symbols, "libSymbols", [])

        components = getattr(schematic_ir, "components", [])
        for comp in components:
            lib_id = getattr(comp, "libId", "")
            ref = None
            for prop in getattr(comp, "properties", []):
                if getattr(prop, "key", "") == "Reference":
                    ref = getattr(prop, "value", "")
                    break
            if ref is None:
                continue

            # Find matching lib_symbol
            for lib_sym in lib_symbols_list:
                sym_lib_id = getattr(lib_sym, "libId", "")
                if sym_lib_id != lib_id:
                    if ":" in lib_id:
                        entry = lib_id.split(":")[-1]
                        sym_entry = getattr(lib_sym, "entryName", "")
                        if sym_entry != entry:
                            continue
                    else:
                        continue

                # Count total pins across all units
                pin_count = 0
                units = getattr(lib_sym, "units", [])
                if units:
                    for unit in units:
                        pin_count += len(getattr(unit, "pins", []))
                else:
                    pin_count = len(getattr(lib_sym, "pins", []))

                if pin_count == 0:
                    stubs.append(ref)

        return stubs
