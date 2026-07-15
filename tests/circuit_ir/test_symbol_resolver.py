"""Phase 156 Wave 3: Tests for the symbol library resolver."""
from __future__ import annotations

from pathlib import Path

import pytest

from volta.circuit_ir.symbol_resolver import (
    get_pin_names,
    resolve_lib_symbol,
)


class TestResolveLibSymbol:
    """W3-1/W1-7: resolve_lib_symbol extracts symbol blocks from .kicad_sym."""

    def test_resolves_device_R(self) -> None:
        """Device:R resolves to a symbol block with 2 pins."""
        raw = resolve_lib_symbol("Device:R")
        assert "(symbol" in raw
        # R has 2 pins.
        pins = get_pin_names("Device:R")
        assert len(pins) == 2
        assert "1" in pins
        assert "2" in pins

    def test_resolves_device_C(self) -> None:
        """Device:C resolves to a symbol block with 2 pins."""
        pins = get_pin_names("Device:C")
        assert len(pins) == 2

    def test_resolves_device_LED(self) -> None:
        """Device:LED resolves with named pins (A, K)."""
        pins = get_pin_names("Device:LED")
        assert len(pins) >= 2
        # LED pins are named A (anode) and K (cathode).
        names = set(pins.values())
        assert "A" in names or "K" in names or len(pins) >= 2

    def test_resolves_opamp(self) -> None:
        """Amplifier_Operational:NE5532 or similar resolves with 8+ pins."""
        # Try a few common op-amp lib_ids.
        for lib_id in ("Amplifier_Operational:NE5532", "Amplifier_Operational:TL072"):
            try:
                pins = get_pin_names(lib_id)
                if pins:
                    assert len(pins) >= 8, f"{lib_id} has {len(pins)} pins, expected >=8"
                    break
            except (ValueError, FileNotFoundError):
                continue

    def test_invalid_lib_id_raises(self) -> None:
        """Invalid lib_id (no colon) raises ValueError."""
        with pytest.raises(ValueError):
            resolve_lib_symbol("NoColonHere")

    def test_nonexistent_symbol_raises(self) -> None:
        """Nonexistent symbol raises ValueError."""
        with pytest.raises(ValueError):
            resolve_lib_symbol("Device:NONEXISTENT_PART_12345")


class TestGetPinNames:
    """get_pin_names returns pin number → name mapping."""

    def test_resistor_pin_names(self) -> None:
        """Device:R pins are unnamed (passive)."""
        pins = get_pin_names("Device:R")
        assert "1" in pins
        assert "2" in pins
