"""Maps KiCad library parts to SKIDL part wrappers.

Three strategies:
1. Known part → use existing parts.py wrapper (NE5532, DG413, etc.)
2. Generic passive → use skidl Part directly (R, C, L, LED, etc.)
3. Unknown IC → generate Conn_01xNN wrapper (like AK4619VN pattern)
"""

from __future__ import annotations
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class MappedPart:
    """Result of mapping a KiCad part to a SKIDL representation."""
    strategy: str  # "wrapper", "generic", "connector"
    lib_id: str
    value: str
    footprint: str
    wrapper_name: Optional[str] = None  # e.g. "NE5532" if using a wrapper
    pin_count: int = 0
    pin_aliases: dict[str, list[str]] = field(default_factory=dict)
    notes: str = ""


# Known parts that have wrappers in parts.py
KNOWN_WRAPPERS = {
    # lib_id prefix → wrapper name
    "Amplifier_Operational:NE5532": "NE5532",
    "Analog_Switch:DG413": "DG413",
    "Interface_Expansion:MCP23017": "MCP23017",
    "Interface_Expansion:MCP23008": "MCP23008",
    "Potentiometer_Digital:MCP4131": "MCP4131",
    "Analog_DAC:MCP4728": "MCP4728",
    "MCU_RaspberryPi:RP2350": "RP2350B",
    "MCU_RaspberryPi:RP2040": "RP2040",
    "Interface_Ethernet:W5500": "W5500",
    "Memory_Flash:W25Q16": "W25Q16",
    "Power_Protection:USBLC6": "USBLC6",
    "Regulator_Linear:AMS1117": "AMS1117",
    "Regulator_Linear:AP2112": "AP2112",
    "Regulator_Switching:TPS54202": "TPS54202",
    "Regulator_Switching:TPS65131": "TPS65131",
    "Regulator_Switching:LT3580": "LT3580",
    "Regulator_Switching:MP1584": "MP1584EN",
    "Isolator:EL817": "EL817",
}

# Generic passives that skidl handles directly
GENERIC_PARTS = {
    "Device:R": {"skidl_lib": "Device", "skidl_name": "R", "pins": 2},
    "Device:C": {"skidl_lib": "Device", "skidl_name": "C", "pins": 2},
    "Device:L": {"skidl_lib": "Device", "skidl_name": "L", "pins": 2},
    "Device:LED": {"skidl_lib": "Device", "skidl_name": "LED", "pins": 2},
    "Device:D_TVS": {"skidl_lib": "Device", "skidl_name": "D_TVS", "pins": 2},
    "Device:D_Schottky": {"skidl_lib": "Device", "skidl_name": "D_Schottky", "pins": 2},
    "Device:Fuse": {"skidl_lib": "Device", "skidl_name": "Fuse", "pins": 2},
    "Device:Crystal": {"skidl_lib": "Device", "skidl_name": "Crystal", "pins": 2},
    "Device:FerriteBead": {"skidl_lib": "Device", "skidl_name": "FerriteBead", "pins": 2},
    "Device:Q_NPN": {"skidl_lib": "Device", "skidl_name": "Q_NPN", "pins": 3},
    "Device:Q_PNP": {"skidl_lib": "Device", "skidl_name": "Q_PNP", "pins": 3},
    "Device:R_Potentiometer": {"skidl_lib": "Device", "skidl_name": "R_Potentiometer", "pins": 3},
}

# Power symbols (become Net assignments, not parts)
POWER_SYMBOLS = {
    "power:GND", "power:GNDA", "power:AGND", "power:DGND",
    "power:+3V3", "power:+5V", "power:+12V", "power:-12V",
    "power:+15V", "power:-15V", "power:+24V", "power:VBUS",
    "power:PWR_FLAG",
}


class PartsMapper:
    """Maps KiCad library IDs to SKIDL part representations."""

    def map(self, lib_id: str, value: str, footprint: str,
            pin_count: int = 0) -> MappedPart:
        """Map a KiCad lib_id to a SKIDL part strategy."""
        
        # Check power symbols first
        for pwr in POWER_SYMBOLS:
            if lib_id.startswith(pwr):
                return MappedPart(
                    strategy="power",
                    lib_id=lib_id,
                    value=value,
                    footprint="",
                    notes=f"Power symbol → Net('{value}')"
                )
        
        # Check known wrappers
        for prefix, wrapper in KNOWN_WRAPPERS.items():
            if lib_id.startswith(prefix):
                return MappedPart(
                    strategy="wrapper",
                    lib_id=lib_id,
                    value=value,
                    footprint=footprint,
                    wrapper_name=wrapper,
                    pin_count=pin_count,
                    notes=f"Use {wrapper}() wrapper from parts.py"
                )
        
        # Check generic passives
        for prefix, info in GENERIC_PARTS.items():
            if lib_id.startswith(prefix):
                return MappedPart(
                    strategy="generic",
                    lib_id=lib_id,
                    value=value,
                    footprint=footprint,
                    pin_count=info["pins"],
                    notes=f"Use Part('{info['skidl_lib']}', '{info['skidl_name']}')"
                )
        
        # Unknown — model as connector
        pins = pin_count if pin_count > 0 else self._guess_pin_count(lib_id)
        return MappedPart(
            strategy="connector",
            lib_id=lib_id,
            value=value or lib_id.split(":")[-1],
            footprint=footprint,
            pin_count=pins,
            notes=f"Generated Conn_01x{pins} wrapper (unknown part)"
        )

    def _guess_pin_count(self, lib_id: str) -> int:
        """Guess pin count from lib_id for unknown parts."""
        # Try to extract from common patterns
        name = lib_id.split(":")[-1] if ":" in lib_id else lib_id
        # Common IC packages
        if "QFN-32" in name or "QFN32" in name:
            return 32
        if "QFN-48" in name or "LQFP-48" in name:
            return 48
        if "QFN-60" in name:
            return 60
        if "QFN-80" in name:
            return 80
        if "SOIC-8" in name:
            return 8
        if "SOIC-14" in name:
            return 14
        if "SOIC-16" in name:
            return 16
        if "SOIC-28" in name or "SOIC-28W" in name:
            return 28
        if "TSSOP" in name:
            return 20
        if "MSOP-10" in name:
            return 10
        # Default to 16 pins for unknown
        return 16
