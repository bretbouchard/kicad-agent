"""Tests for serializer sub-modules: normalizer, uuid reinjector."""

from pathlib import Path

import pytest

from volta.serializer.normalizer import normalize_kicad_output
from volta.serializer.uuid_reinjector import UUIDMap


class TestNormalizerModule:
    """Tests for normalizer module."""

    def test_normalize_handles_kicad_sch(self):
        """Normalizer handles KiCad schematic content."""
        content = '(kicad_sch (version 20240108) (generator "eeschema"))'
        result = normalize_kicad_output(content)
        assert "kicad_sch" in result

    def test_normalize_handles_kicad_pcb(self):
        """Normalizer handles KiCad PCB content."""
        content = '(kicad_pcb (version 20240108) (generator "kicad-cli"))'
        result = normalize_kicad_output(content)
        assert "kicad_pcb" in result

    def test_normalize_idempotent(self):
        """Normalizing twice produces same result."""
        content = '(kicad_sch (version 20240108))'
        r1 = normalize_kicad_output(content)
        r2 = normalize_kicad_output(r1)
        assert r1 == r2


class TestUuidReinjectorModule:
    """Tests for UUID reinjector module."""

    def test_uuid_map_creation(self):
        """UUIDMap can be created."""
        m = UUIDMap()
        assert m.entries == ()

    def test_uuid_map_with_source_type(self):
        """UUIDMap accepts source_file_type."""
        m = UUIDMap(source_file_type="schematic")
        assert m.source_file_type == "schematic"
