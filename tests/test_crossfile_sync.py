"""Tests for crossfile propagation module detailed."""

import pytest

from kicad_agent.crossfile.propagation import PropagationResult
from kicad_agent.crossfile.schematic_sync import (
    sync_pcb_from_netlist as synchronize_schematic,
)


class TestPropagationResult:
    """Tests for PropagationResult."""

    def test_import(self):
        """PropagationResult is importable."""
        assert PropagationResult is not None


class TestSchematicSync:
    """Tests for schematic synchronization."""

    def test_import(self):
        """synchronize_schematic is importable."""
        assert callable(synchronize_schematic)
