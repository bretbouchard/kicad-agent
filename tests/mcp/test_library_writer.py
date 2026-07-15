"""Tests for volta.mcp.library_writer (kicad-agent-4 fix)."""
from __future__ import annotations

from pathlib import Path

import pytest

from volta.crawler.easyeda_api import (
    EasyEdaComponentData,
    EasyEdaFootprintPad,
    EasyEdaPin,
)
from volta.mcp.library_writer import (
    write_symbol_to_library,
    write_footprint_to_library,
)


@pytest.fixture
def sample_data() -> EasyEdaComponentData:
    """Realistic EasyEDA-parsed component data for ESP32-WROOM-32."""
    return EasyEdaComponentData(
        lcsc="C123456",
        title="ESP32-WROOM-32",
        package="QFN-38",
        pins=(
            EasyEdaPin(pin_number="1", pin_name="GND", pos_x=0, pos_y=0, rotation=0, pin_type=4),
            EasyEdaPin(pin_number="2", pin_name="3V3", pos_x=0, pos_y=0, rotation=0, pin_type=4),
            EasyEdaPin(pin_number="3", pin_name="EN", pos_x=0, pos_y=0, rotation=0, pin_type=1),
            EasyEdaPin(pin_number="4", pin_name="IO0", pos_x=0, pos_y=0, rotation=0, pin_type=3),
        ),
        pads=(
            EasyEdaFootprintPad(pad_number="1", pos_x=-3.0, pos_y=-3.0, width=0.5, height=0.5, layer=1, shape="rect", net=""),
            EasyEdaFootprintPad(pad_number="2", pos_x=3.0, pos_y=-3.0, width=0.5, height=0.5, layer=1, shape="rect", net=""),
        ),
    )


class TestSymbolWriter:
    def test_creates_new_library_file(self, tmp_path: Path, sample_data) -> None:
        sym_file = write_symbol_to_library(sample_data, tmp_path, "my_lib")
        assert sym_file.exists()
        content = sym_file.read_text()
        # Header
        assert "(kicad_symbol_lib" in content
        assert "volta_mcp" in content
        # Symbol block
        assert '(symbol "C123456"' in content  # uses lcsc as symbol name
        # Pins
        assert "(pin power_in line" in content  # GND, 3V3 = power_in (pin_type=4)
        assert "(pin input line" in content  # EN = input (pin_type=1)
        assert "(pin bidirectional line" in content  # IO0 = bidir (pin_type=3)
        assert '(name GND)' in content
        assert '(name "3V3")' in content  # name with digit gets quoted

    def test_appends_to_existing_library(self, tmp_path: Path, sample_data) -> None:
        write_symbol_to_library(sample_data, tmp_path, "my_lib")
        # Write a second symbol
        second = EasyEdaComponentData(
            lcsc="C789012",
            title="Second Part",
            package="SOIC-8",
            pins=(EasyEdaPin(pin_number="1", pin_name="A", pos_x=0, pos_y=0, rotation=0, pin_type=0),),
            pads=(),
        )
        sym_file = write_symbol_to_library(second, tmp_path, "my_lib")
        content = sym_file.read_text()
        assert '"C123456"' in content
        assert '"C789012"' in content
        # Only one library header
        assert content.count("(kicad_symbol_lib") == 1

    def test_creates_parent_directory(self, tmp_path: Path, sample_data) -> None:
        nested = tmp_path / "nested" / "deeper"
        sym_file = write_symbol_to_library(sample_data, nested, "lib")
        assert sym_file.exists()
        assert nested.exists()


class TestFootprintWriter:
    def test_creates_pretty_dir_and_mod_file(self, tmp_path: Path, sample_data) -> None:
        fp_file = write_footprint_to_library(sample_data, tmp_path, "my_lib")
        assert fp_file.exists()
        assert fp_file.parent.name == "my_lib.pretty"
        content = fp_file.read_text()
        assert '(footprint "my_lib:C123456"' in content
        assert "(layer \"F.Cu\")" in content
        assert '(pad "1" smd roundrect' in content
        assert "(at -3.000 -3.000)" in content
        assert '(layers "F.Cu" "F.Paste" "F.Mask")' in content

    def test_handles_no_pads_gracefully(self, tmp_path: Path) -> None:
        """Components with no parsed pads still produce a valid .kicad_mod."""
        data = EasyEdaComponentData(
            lcsc="C999999", title="No Pads Part", package="",
            pins=(), pads=(),
        )
        fp_file = write_footprint_to_library(data, tmp_path, "lib")
        content = fp_file.read_text()
        assert '(footprint "lib:C999999"' in content
        # The "no pads" comment should appear
        assert "no pads parsed" in content or "(pad " not in content

    def test_creates_parent_pretty_dir(self, tmp_path: Path, sample_data) -> None:
        nested = tmp_path / "libs"
        fp_file = write_footprint_to_library(sample_data, nested, "my_lib")
        assert fp_file.exists()
        assert (nested / "my_lib.pretty").exists()
