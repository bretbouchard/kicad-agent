"""Tests for KiCad-to-LTspice symbol mapping.

Covers SymbolMapper.map_symbol for Device library components,
power library flags, simulation sources, custom overrides, and unmapped symbols.
"""

import pytest

from kicad_agent.ltspice.symbol_mapper import SymbolMapper
from kicad_agent.ltspice.types import SymbolMappingResult, SymbolMappingType


class TestDeviceMappings:
    """KiCad Device library symbols map to LTspice COMPONENT type."""

    def test_resistor_maps_to_res(self) -> None:
        result = SymbolMapper().map_symbol("Device:R")
        assert result.ltspice_symbol == "res"
        assert result.mapping_type == SymbolMappingType.COMPONENT
        assert result.is_power is False

    def test_capacitor_maps_to_cap(self) -> None:
        result = SymbolMapper().map_symbol("Device:C")
        assert result.ltspice_symbol == "cap"
        assert result.mapping_type == SymbolMappingType.COMPONENT

    def test_inductor_maps_to_ind(self) -> None:
        result = SymbolMapper().map_symbol("Device:L")
        assert result.ltspice_symbol == "ind"
        assert result.mapping_type == SymbolMappingType.COMPONENT

    def test_diode_maps_to_diode(self) -> None:
        result = SymbolMapper().map_symbol("Device:D")
        assert result.ltspice_symbol == "diode"
        assert result.mapping_type == SymbolMappingType.COMPONENT

    def test_npn_transistor_maps_to_npn(self) -> None:
        result = SymbolMapper().map_symbol("Device:Q_NPN")
        assert result.ltspice_symbol == "npn"
        assert result.mapping_type == SymbolMappingType.COMPONENT

    def test_nmos_transistor_maps_to_nmos(self) -> None:
        result = SymbolMapper().map_symbol("Device:Q_NMOS")
        assert result.ltspice_symbol == "nmos"
        assert result.mapping_type == SymbolMappingType.COMPONENT


class TestPowerMappings:
    """KiCad power library symbols map to LTspice FLAG type."""

    def test_gnd_maps_to_flag_zero(self) -> None:
        result = SymbolMapper().map_symbol("power:GND")
        assert result.ltspice_symbol == "0"
        assert result.mapping_type == SymbolMappingType.FLAG
        assert result.is_power is True

    def test_vcc_maps_to_flag_vcc(self) -> None:
        result = SymbolMapper().map_symbol("power:VCC")
        assert result.ltspice_symbol == "VCC"
        assert result.mapping_type == SymbolMappingType.FLAG
        assert result.is_power is True

    def test_3v3_maps_to_flag_3v3(self) -> None:
        result = SymbolMapper().map_symbol("power:+3V3")
        assert result.ltspice_symbol == "+3V3"
        assert result.mapping_type == SymbolMappingType.FLAG
        assert result.is_power is True


class TestSimulationMappings:
    """Simulation library sources map to COMPONENT type."""

    def test_voltage_source_maps_to_voltage(self) -> None:
        result = SymbolMapper().map_symbol("Simulation:VOLTAGE")
        assert result.ltspice_symbol == "voltage"
        assert result.mapping_type == SymbolMappingType.COMPONENT
        assert result.is_power is False


class TestUnmappedSymbols:
    """Unknown symbols return UNMAPPED type with empty symbol."""

    def test_unknown_lib_returns_unmapped(self) -> None:
        result = SymbolMapper().map_symbol("UnknownLib:Foo")
        assert result.mapping_type == SymbolMappingType.UNMAPPED
        assert result.ltspice_symbol == ""
        assert result.is_power is False


class TestCustomMappings:
    """Custom mappings override defaults."""

    def test_custom_mapping_overrides_default(self) -> None:
        mapper = SymbolMapper(custom_mappings={"Device:R": "my_res"})
        result = mapper.map_symbol("Device:R")
        assert result.ltspice_symbol == "my_res"
        assert result.mapping_type == SymbolMappingType.COMPONENT


class TestResultIntegrity:
    """Every result echoes back the original lib_id."""

    def test_all_results_echo_lib_id(self) -> None:
        mapper = SymbolMapper()
        test_ids = ["Device:R", "power:GND", "Simulation:VOLTAGE", "Unknown:X"]
        for lib_id in test_ids:
            result = mapper.map_symbol(lib_id)
            assert result.lib_id == lib_id
            assert isinstance(result, SymbolMappingResult)
