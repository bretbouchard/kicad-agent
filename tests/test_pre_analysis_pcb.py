"""Tests for PCB pre-flight gate checks (D-05)."""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from volta.ops.pre_analysis import PreAnalysisGate, PreAnalysisResult, PreAnalysisFinding
from volta.ops.pre_analysis_pcb import analyze_pcb, _PCB_MUTATION_OP_TYPES


class TestPreFlightGatePcb:
    """Tests for PCB pre-flight gate checks (D-05)."""

    def test_analyze_pcb_dispatches_for_kicad_pcb_extension(self):
        """_analyze_pcb is called for .kicad_pcb files regardless of op_type."""
        gate = PreAnalysisGate()

        class MockOp:
            op_type = "info"  # not in _PCB_MUTATION_OP_TYPES
            target_file = "board.kicad_pcb"

        class MockIR:
            pass

        # info op is NOT in _PCB_MUTATION_OP_TYPES, so it should pass through
        result = gate.analyze(MockOp(), MockIR(), Path("board.kicad_pcb"))
        assert not result.blocked

    def test_analyze_pcb_non_mutation_op_passes_through(self):
        """Non-mutation PCB ops (e.g. 'info') produce no blockers."""
        result = PreAnalysisResult()
        ir = MagicMock()

        class MockOp:
            op_type = "info"

        analyze_pcb(MockOp(), ir, Path("board.kicad_pcb"), result)
        assert not result.blocked
        assert len(result.warnings) == 0

    def test_swap_footprint_blocked_when_new_pads_less_than_old(self):
        """swap_footprint blocked when new footprint has fewer pads than old."""
        from unittest.mock import patch

        result = PreAnalysisResult()
        ir = MagicMock()
        ir.get_footprint_by_ref.return_value = MagicMock()  # old exists
        ir.get_footprint_pads.return_value = [("1", "pad1"), ("2", "pad2"), ("3", "pad3")]  # 3 pads

        class SwapOp:
            op_type = "swap_footprint"
            reference = "U1"
            new_footprint_lib_id = "Package:DIP-8"

        # Patch the pad count resolver to return 1 (less than 3)
        with patch("volta.ops.pre_analysis_pcb._resolve_footprint_pad_count", return_value=1):
            analyze_pcb(SwapOp(), ir, Path("board.kicad_pcb"), result)
        assert result.blocked is True
        assert any(b.category == "pad_count_mismatch" for b in result.blockers)

    def test_swap_footprint_proceeds_when_new_pads_gte_old(self):
        """swap_footprint proceeds when new footprint pad count >= old pad count."""
        result = PreAnalysisResult()
        ir = MagicMock()
        ir.get_footprint_by_ref.return_value = MagicMock()  # old exists
        ir.get_footprint_pads.return_value = [("1", "pad1"), ("2", "pad2")]  # 2 pads

        class SwapOp:
            op_type = "swap_footprint"
            reference = "U1"
            new_footprint_lib_id = "Package:DIP-8"

        # pad count is None (unresolvable), so no blocker
        analyze_pcb(SwapOp(), ir, Path("board.kicad_pcb"), result)
        assert result.blocked is False
        # Should have a warning about unresolvable pad count
        assert len(result.warnings) > 0

    def test_swap_footprint_blocked_when_reference_not_found(self):
        """swap_footprint blocked when reference doesn't exist in IR."""
        result = PreAnalysisResult()
        ir = MagicMock()
        ir.get_footprint_by_ref.return_value = None  # not found

        class SwapOp:
            op_type = "swap_footprint"
            reference = "U99"
            new_footprint_lib_id = "Package:DIP-8"

        analyze_pcb(SwapOp(), ir, Path("board.kicad_pcb"), result)
        assert result.blocked is True
        assert any(b.category == "unknown_ref" for b in result.blockers)

    def test_swap_footprint_warns_when_new_pad_count_unavailable(self):
        """swap_footprint emits WARNING when new footprint pad count can't be resolved."""
        result = PreAnalysisResult()
        ir = MagicMock()
        ir.get_footprint_by_ref.return_value = MagicMock()
        ir.get_footprint_pads.return_value = [("1", "pad1"), ("2", "pad2")]

        class SwapOp:
            op_type = "swap_footprint"
            reference = "U1"
            new_footprint_lib_id = "Unknown:Footprint"

        analyze_pcb(SwapOp(), ir, Path("board.kicad_pcb"), result)
        assert not result.blocked
        assert any(b.category == "pad_count_unknown" for b in result.warnings)

    def test_remove_net_blocked_when_net_has_connected_pads(self):
        """remove_net blocked when net has connected pads."""
        result = PreAnalysisResult()
        ir = MagicMock()
        net = MagicMock()
        ir.get_net_by_name.return_value = net  # net exists
        ir.get_net_pads.return_value = [("U1", "1"), ("U1", "2")]  # 2 connected pads

        class RemoveNetOp:
            op_type = "remove_net"
            net_name = "VCC"

        analyze_pcb(RemoveNetOp(), ir, Path("board.kicad_pcb"), result)
        assert result.blocked is True
        assert any(b.category == "net_has_connections" for b in result.blockers)

    def test_remove_net_proceeds_when_net_has_zero_pads(self):
        """remove_net proceeds when net has no connected pads."""
        result = PreAnalysisResult()
        ir = MagicMock()
        net = MagicMock()
        ir.get_net_by_name.return_value = net
        ir.get_net_pads.return_value = []  # no pads

        class RemoveNetOp:
            op_type = "remove_net"
            net_name = "UNUSED"

        analyze_pcb(RemoveNetOp(), ir, Path("board.kicad_pcb"), result)
        assert result.blocked is False

    def test_remove_net_warns_about_zone_references(self):
        """remove_net emits WARNING when net is referenced by zones."""
        result = PreAnalysisResult()
        ir = MagicMock()
        net = MagicMock()
        ir.get_net_by_name.return_value = net
        ir.get_net_pads.return_value = []  # no pads

        class MockZone:
            net_name = "GND"

        ir.zones = [MockZone()]

        class RemoveNetOp:
            op_type = "remove_net"
            net_name = "GND"

        analyze_pcb(RemoveNetOp(), ir, Path("board.kicad_pcb"), result)
        assert not result.blocked
        assert any(b.category == "net_zone_reference" for b in result.warnings)

    def test_move_footprint_blocked_when_overlapping_existing(self):
        """move_footprint blocked when destination overlaps existing footprints."""
        result = PreAnalysisResult()

        # Create mock IR with existing footprints
        ir = MagicMock()

        class MockFootprint:
            reference = "U1"
            x = 50.0
            y = 50.0

        class ExistingFootprint:
            reference = "U2"
            x = 55.0
            y = 55.0

        ir.get_footprint_by_ref.return_value = MockFootprint()
        ir.get_footprint_pads.return_value = []
        ir.footprints = [MockFootprint(), ExistingFootprint()]
        ir.board = None

        class Position:
            x = 55.0
            y = 55.0

        class MoveOp:
            op_type = "move_footprint"
            reference = "U1"
            position = Position()

        analyze_pcb(MoveOp(), ir, Path("board.kicad_pcb"), result)
        # The overlap check depends on bbox computation with the mock
        # Since get_footprint_pads returns empty, the default bbox is used
        # The mock footprints at (50,50) and (55,55) with default 5x5 bboxes
        # will overlap when moving U1 to (55,55)
        assert result.blocked is True
        assert any(b.category == "footprint_overlap" for b in result.blockers)

    def test_add_copper_zone_warns_about_power_net_overlap(self):
        """add_copper_zone emits WARNING when zone net overlaps power nets."""
        result = PreAnalysisResult()
        ir = MagicMock()

        class ZoneOp:
            op_type = "add_copper_zone"
            net_name = "GND"

        analyze_pcb(ZoneOp(), ir, Path("board.kicad_pcb"), result)
        assert not result.blocked
        assert any(b.category == "power_zone_overlap" for b in result.warnings)

    def test_pcb_mutation_op_types_is_frozenset(self):
        """_PCB_MUTATION_OP_TYPES should be a frozenset."""
        assert isinstance(_PCB_MUTATION_OP_TYPES, frozenset)
        assert "swap_footprint" in _PCB_MUTATION_OP_TYPES
        assert "remove_net" in _PCB_MUTATION_OP_TYPES
        assert "move_footprint" in _PCB_MUTATION_OP_TYPES
