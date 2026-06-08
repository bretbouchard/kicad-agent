"""Tests for serializer module: schematic, PCB, symbol, footprint serialization."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from kicad_agent.serializer import (
    normalize_kicad_output,
    reinject_uuids,
    serialize_footprint,
    serialize_pcb,
    serialize_schematic,
    serialize_symbol_lib,
)


class TestSerializerImports:
    """Verify all serializer module exports."""

    def test_all_exports_importable(self):
        """All __all__ exports can be imported."""
        from kicad_agent import serializer
        for name in serializer.__all__:
            assert hasattr(serializer, name), f"Missing export: {name}"


class TestSerializeSchematic:
    """Tests for schematic serializer."""

    def test_serialize_schematic_wrong_type_raises(self):
        """serialize_schematic raises ValueError for wrong file_type."""
        mock_result = MagicMock()
        mock_result.file_type = "pcb"
        with pytest.raises(ValueError, match="Expected file_type='schematic'"):
            serialize_schematic(mock_result, Path("/tmp/out.kicad_sch"))


class TestSerializePCB:
    """Tests for PCB serializer."""

    def test_serialize_pcb_wrong_type_raises(self):
        """serialize_pcb raises ValueError for wrong file_type."""
        mock_result = MagicMock()
        mock_result.file_type = "schematic"
        with pytest.raises(ValueError, match="Expected file_type='pcb'"):
            serialize_pcb(mock_result, Path("/tmp/out.kicad_pcb"))


class TestSerializeSymbolLib:
    """Tests for symbol library serializer."""

    def test_serialize_symbol_lib_callable(self):
        """serialize_symbol_lib is callable."""
        assert callable(serialize_symbol_lib)


class TestSerializeFootprint:
    """Tests for footprint serializer."""

    def test_serialize_footprint_wrong_type_raises(self):
        """serialize_footprint raises ValueError for wrong file_type."""
        mock_result = MagicMock()
        mock_result.file_type = "schematic"
        with pytest.raises(ValueError, match="Expected file_type='footprint'"):
            serialize_footprint(mock_result, Path("/tmp/out.kicad_mod"))


class TestNormalizeKicadOutput:
    """Tests for normalize_kicad_output."""

    def test_normalize_returns_empty_for_empty(self):
        """normalize_kicad_output returns empty string for empty content."""
        result = normalize_kicad_output("")
        assert result == ""

    def test_normalize_returns_input_for_non_kicad(self):
        """normalize_kicad_output returns input unchanged for non-KiCad content."""
        result = normalize_kicad_output("this is not a KiCad file")
        assert result == "this is not a KiCad file"

    def test_normalize_accepts_kicad_content(self):
        """normalize_kicad_output accepts valid KiCad S-expression content."""
        content = '(kicad_sch (version 20240108) (generator "test"))'
        result = normalize_kicad_output(content)
        assert "kicad_sch" in result


class TestReinjectUuids:
    """Tests for reinject_uuids."""

    def test_reinject_callable(self):
        """reinject_uuids is callable."""
        assert callable(reinject_uuids)

    def test_reinject_empty_map(self):
        """reinject_uuids with empty UUIDMap entries returns content unchanged."""
        from kicad_agent.parser.uuid_extractor import UUIDMap
        content = '(uuid "abc123")'
        uuid_map = UUIDMap()
        result = reinject_uuids(content, uuid_map)
        # Empty map means no re-injection happens
        assert "abc123" in result

