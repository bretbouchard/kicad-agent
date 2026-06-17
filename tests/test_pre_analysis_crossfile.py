"""Tests for cross-file pre-flight gate checks (D-06)."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from kicad_agent.ops.pre_analysis import PreAnalysisGate, PreAnalysisResult, PreAnalysisFinding
from kicad_agent.ops.pre_analysis_crossfile import (
    analyze_crossfile,
    _CROSSFILE_MUTATION_OP_TYPES,
)


class TestPreFlightGateCrossFile:
    """Tests for cross-file pre-flight gate checks (D-06)."""

    def _make_ir_map(self, sch_ir=None, pcb_ir=None):
        """Build a synthetic ir_map."""
        ir_map = {}
        if sch_ir is not None:
            ir_map[Path("project.kicad_sch")] = sch_ir
        if pcb_ir is not None:
            ir_map[Path("project.kicad_pcb")] = pcb_ir
        return ir_map

    def test_analyze_crossfile_dispatches_for_valid_extensions(self):
        """_analyze_crossfile is called for cross-file ops on valid extensions."""
        gate = PreAnalysisGate()

        class MockOp:
            op_type = "info"
            target_file = "project.kicad_sym"

        class MockIR:
            pass

        # Non-mutation op should pass through
        result = gate.analyze(MockOp(), MockIR(), Path("project.kicad_sym"))
        assert not result.blocked

    def test_analyze_crossfile_non_mutation_op_passes_through(self):
        """Non-mutation cross-file ops produce no blockers."""
        result = PreAnalysisResult()
        ir_map = self._make_ir_map(sch_ir=MagicMock())

        class MockOp:
            op_type = "info"

        analyze_crossfile(MockOp(), ir_map, Path("project.kicad_sch"), result)
        assert not result.blocked

    def test_propagate_symbol_change_blocked_when_lib_id_not_found(self):
        """propagate_symbol_change blocked when lib_id not found in libraries."""
        sch_ir = MagicMock()
        sch_ir.schematic.libSymbols = []
        ir_map = self._make_ir_map(sch_ir=sch_ir)

        result = PreAnalysisResult()

        class MockOp:
            op_type = "propagate_symbol_change"
            lib_id = "Nonexistent:Symbol"

        analyze_crossfile(MockOp(), ir_map, Path("project.kicad_sch"), result)
        assert result.blocked is True
        assert any(b.category == "unknown_lib_id" for b in result.blockers)

    def test_propagate_symbol_change_proceeds_when_lib_id_found(self):
        """propagate_symbol_change proceeds when lib_id resolves."""
        sch_ir = MagicMock()
        sch_ir.lib_symbols = []  # Force fall-through to sch.schematic.libSymbols
        mock_sym = MagicMock()
        mock_sym.libId = "Device:R_Small"
        sch_ir.schematic.libSymbols = [mock_sym]
        ir_map = self._make_ir_map(sch_ir=sch_ir)

        result = PreAnalysisResult()

        class MockOp:
            op_type = "propagate_symbol_change"
            lib_id = "Device:R_Small"

        analyze_crossfile(MockOp(), ir_map, Path("project.kicad_sch"), result)
        assert not result.blocked

    def test_repopulate_pcb_blocked_when_erc_has_errors(self):
        """repopulate_pcb_from_schematic blocked when ERC has errors."""
        sch_ir = MagicMock()
        sch_ir.schematic.drcExclusions = []
        sch_ir.schematic.drc_exclusions = []
        ir_map = self._make_ir_map(sch_ir=sch_ir)

        result = PreAnalysisResult()

        class MockOp:
            op_type = "repopulate_pcb_from_schematic"
            schematic_file = "project.kicad_sch"
            erc_errors = ["Pin 1 unconnected", "Power pin not driven"]

        analyze_crossfile(MockOp(), ir_map, Path("project.kicad_sch"), result)
        assert result.blocked is True
        assert any(b.category == "erc_errors_present" for b in result.blockers)

    def test_update_pcb_blocked_when_footprint_missing(self):
        """update_pcb_from_schematic blocked when symbol has no valid footprint."""
        sch_ir = MagicMock()
        pcb_ir = MagicMock()

        # Create a component with no Footprint property
        mock_comp = MagicMock()
        ref_prop = MagicMock()
        ref_prop.key = "Reference"
        ref_prop.value = "R1"
        mock_comp.properties = [ref_prop]
        sch_ir.components = [mock_comp]

        ir_map = self._make_ir_map(sch_ir=sch_ir, pcb_ir=pcb_ir)

        result = PreAnalysisResult()

        class MockOp:
            op_type = "update_pcb_from_schematic"

        analyze_crossfile(MockOp(), ir_map, Path("project.kicad_sch"), result)
        assert result.blocked is True
        assert any(b.category == "missing_footprint" for b in result.blockers)

    def test_rebuild_pcb_nets_blocked_when_over_50_percent_change(self):
        """rebuild_pcb_nets blocked when >50% of net assignments would change."""
        sch_ir = MagicMock()
        pcb_ir = MagicMock()

        # Schematic has net A, B, C -- PCB has net X, Y, Z -- no overlap
        sch_ir.get_label_positions.return_value = [
            {"name": "A"}, {"name": "B"}, {"name": "C"},
        ]
        pcb_ir.extract_netlist.return_value = {
            "X": [], "Y": [], "Z": [],
        }

        ir_map = self._make_ir_map(sch_ir=sch_ir, pcb_ir=pcb_ir)

        result = PreAnalysisResult()

        class MockOp:
            op_type = "rebuild_pcb_nets"

        analyze_crossfile(MockOp(), ir_map, Path("project.kicad_sch"), result)
        assert result.blocked is True
        assert any(b.category == "excessive_net_change" for b in result.blockers)

    def test_crossfile_mutation_op_types_is_frozenset(self):
        """_CROSSFILE_MUTATION_OP_TYPES should be a frozenset."""
        assert isinstance(_CROSSFILE_MUTATION_OP_TYPES, frozenset)
        assert "propagate_symbol_change" in _CROSSFILE_MUTATION_OP_TYPES
        assert "repopulate_pcb_from_schematic" in _CROSSFILE_MUTATION_OP_TYPES
        assert "update_pcb_from_schematic" in _CROSSFILE_MUTATION_OP_TYPES
        assert "rebuild_pcb_nets" in _CROSSFILE_MUTATION_OP_TYPES
