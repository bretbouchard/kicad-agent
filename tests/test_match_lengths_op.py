"""Tests for match_lengths operation (#45)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError


class TestMatchLengthsOpSchema:
    """Schema validation tests for MatchLengthsOp."""

    def test_valid_minimal(self):
        from kicad_agent.ops._schema_pcb import MatchLengthsOp, NetLengthPair

        op = MatchLengthsOp(
            target_file="board.kicad_pcb",
            net_pairs=[NetLengthPair(net_a="CLK+", net_b="CLK-")],
        )
        assert op.op_type == "match_lengths"
        assert len(op.net_pairs) == 1
        assert op.pattern == "sawtooth"
        assert op.half_pitch_mm == 1.0

    def test_valid_multiple_pairs(self):
        from kicad_agent.ops._schema_pcb import MatchLengthsOp, NetLengthPair

        op = MatchLengthsOp(
            target_file="board.kicad_pcb",
            net_pairs=[
                NetLengthPair(net_a="DQ0", net_b="DQ0#", tolerance_mm=0.1),
                NetLengthPair(net_a="DQ1", net_b="DQ1#", tolerance_mm=0.15),
            ],
            pattern="accordion",
        )
        assert len(op.net_pairs) == 2
        assert op.net_pairs[0].tolerance_mm == 0.1
        assert op.pattern == "accordion"

    def test_invalid_empty_pairs(self):
        from kicad_agent.ops._schema_pcb import MatchLengthsOp

        with pytest.raises(ValidationError):
            MatchLengthsOp(
                target_file="board.kicad_pcb",
                net_pairs=[],
            )

    def test_invalid_negative_tolerance(self):
        from kicad_agent.ops._schema_pcb import MatchLengthsOp, NetLengthPair

        with pytest.raises(ValidationError):
            MatchLengthsOp(
                target_file="board.kicad_pcb",
                net_pairs=[NetLengthPair(net_a="A", net_b="B", tolerance_mm=-1.0)],
            )

    def test_invalid_pattern(self):
        from kicad_agent.ops._schema_pcb import MatchLengthsOp, NetLengthPair

        with pytest.raises(ValidationError):
            MatchLengthsOp(
                target_file="board.kicad_pcb",
                net_pairs=[NetLengthPair(net_a="A", net_b="B")],
                pattern="zigzag",
            )

    def test_registry_entry_exists(self):
        from kicad_agent.ops.registry import OPERATION_REGISTRY

        assert "match_lengths" in OPERATION_REGISTRY
        meta = OPERATION_REGISTRY["match_lengths"]
        assert meta.category == "pcb"
        assert meta.is_readonly is False

    def test_discriminated_union_accepts(self):
        from kicad_agent.ops.schema import Operation

        op = Operation.model_validate({
            "root": {
                "op_type": "match_lengths",
                "target_file": "board.kicad_pcb",
                "net_pairs": [{"net_a": "A", "net_b": "B"}],
            },
        })
        assert op.root.op_type == "match_lengths"


class TestExtractNetPath:
    """Tests for PcbIR.extract_net_path."""

    def test_empty_board(self):
        """Empty board returns empty path."""
        from kicad_agent.ir.pcb_ir import PcbIR
        from kicad_agent.parser.pcb_native_types import NativeBoard

        board = NativeBoard()
        ir = _make_pcb_ir(board)

        path = ir.extract_net_path("NET1")
        assert path == ()

    def test_segment_chaining(self):
        """Segments chain into ordered path."""
        from kicad_agent.ir.pcb_ir import PcbIR
        from kicad_agent.parser.pcb_native_types import NativeBoard

        board = NativeBoard()
        # Simulate segments on the board.
        seg1 = type("S", (), {
            "net": "NET1",
            "start": type("P", (), {"x": 0.0, "y": 0.0})(),
            "end": type("P", (), {"x": 10.0, "y": 0.0})(),
        })()
        seg2 = type("S", (), {
            "net": "NET1",
            "start": type("P", (), {"x": 10.0, "y": 0.0})(),
            "end": type("P", (), {"x": 10.0, "y": 10.0})(),
        })()
        seg3 = type("S", (), {
            "net": "NET2",
            "start": type("P", (), {"x": 5.0, "y": 5.0})(),
            "end": type("P", (), {"x": 15.0, "y": 5.0})(),
        })()
        board.segments = [seg1, seg2, seg3]

        ir = _make_pcb_ir(board)

        path = ir.extract_net_path("NET1")
        assert len(path) == 3
        assert path[0] == (0.0, 0.0)
        assert path[1] == (10.0, 0.0)
        assert path[2] == (10.0, 10.0)

        # Different net returns empty.
        path2 = ir.extract_net_path("NET3")
        assert path2 == ()


def _make_pcb_ir(board):
    """Create a minimal PcbIR for testing."""
    from kicad_agent.ir.pcb_ir import PcbIR

    ir = PcbIR.__new__(PcbIR)
    ir._parse_result = type("PR", (), {
        "file_path": "test.kicad_pcb", "raw_content": "",
    })()
    ir._native_board = board
    return ir
