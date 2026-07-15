"""Tests for fix_silkscreen_over_copper operation (#47)."""

from __future__ import annotations

import pytest
from types import SimpleNamespace
import dataclasses
from pydantic import ValidationError


class TestFixSilkscreenOverCopperOpSchema:
    """Schema validation tests."""

    def test_valid_default(self):
        from volta.ops._schema_pcb import FixSilkscreenOverCopperOp

        op = FixSilkscreenOverCopperOp(target_file="board.kicad_pcb")
        assert op.op_type == "fix_silkscreen_over_copper"
        assert op.clearance_mm == 0.15
        assert op.action == "report"
        assert op.copper_layers == ["F.Cu"]
        assert op.silk_layers == ["F.SilkS", "B.SilkS"]

    def test_valid_relocate(self):
        from volta.ops._schema_pcb import FixSilkscreenOverCopperOp

        op = FixSilkscreenOverCopperOp(
            target_file="board.kicad_pcb",
            action="relocate",
            clearance_mm=0.20,
        )
        assert op.action == "relocate"
        assert op.clearance_mm == 0.20

    def test_invalid_clearance(self):
        from volta.ops._schema_pcb import FixSilkscreenOverCopperOp

        with pytest.raises(ValidationError):
            FixSilkscreenOverCopperOp(
                target_file="board.kicad_pcb",
                clearance_mm=-0.1,
            )

    def test_invalid_action(self):
        from volta.ops._schema_pcb import FixSilkscreenOverCopperOp

        with pytest.raises(ValidationError):
            FixSilkscreenOverCopperOp(
                target_file="board.kicad_pcb",
                action="move",
            )

    def test_registry_entry_exists(self):
        from volta.ops.registry import OPERATION_REGISTRY

        assert "fix_silkscreen_over_copper" in OPERATION_REGISTRY
        meta = OPERATION_REGISTRY["fix_silkscreen_over_copper"]
        assert meta.category == "pcb"
        assert meta.is_readonly is False

    def test_discriminated_union_accepts(self):
        from volta.ops.schema import Operation

        op = Operation.model_validate({
            "root": {
                "op_type": "fix_silkscreen_over_copper",
                "target_file": "board.kicad_pcb",
            },
        })
        assert op.root.op_type == "fix_silkscreen_over_copper"


class TestSilkscreenClearanceEngine:
    """Tests for silkscreen clearance detection engine."""

    def test_no_violations(self):
        """Board with pads far from silkscreen returns clean."""
        from volta.validation.silkscreen_clearance import check_silkscreen_clearance
        from volta.parser.pcb_native_types import NativeBoard, NativeFootprint

        fp = SimpleNamespace(
            properties={"Reference": "R1", "Value": "10k"},
            layer="F.Cu",
            reference=None, value=None, pads=[],
        )
        # Mock reference with position far from copper.
        fp_ref = type("Ref", (), {
            "at": (50.0, 50.0),
        })()
        fp.reference = fp_ref
        fp.value = type("Val", (), {
            "at": (55.0, 50.0),
            "value": "10k",
        })()
        fp.pads = [
            type("Pad", (), {
                "at": (10.0, 10.0),
                "size": (2.0, 2.0),
                "net": "NET1",
            })(),
        ]

        board = dataclasses.replace(NativeBoard(), footprints=(fp,))
        ir = _make_pcb_ir(board)

        result = check_silkscreen_clearance(ir, clearance_mm=0.15)
        assert result.total_checked == 2
        assert len(result.violations) == 0

    def test_violation_detected(self):
        """Silkscreen text overlapping a pad is detected."""
        from volta.validation.silkscreen_clearance import check_silkscreen_clearance
        from volta.parser.pcb_native_types import NativeBoard, NativeFootprint

        fp = SimpleNamespace(
            properties={"Reference": "U1", "Value": "ATMega"},
            layer="F.Cu",
            reference=None, value=None, pads=[],
        )
        # Reference at same position as pad.
        fp_ref = type("Ref", (), {
            "at": (10.0, 10.0),
        })()
        fp.reference = fp_ref
        fp.value = type("Val", (), {
            "at": (55.0, 55.0),
            "value": "ATMega",
        })()
        fp.pads = [
            type("Pad", (), {
                "at": (10.0, 10.0),
                "size": (3.0, 3.0),
                "net": "GND",
            })(),
        ]

        board = dataclasses.replace(NativeBoard(), footprints=(fp,))
        ir = _make_pcb_ir(board)

        result = check_silkscreen_clearance(ir, clearance_mm=0.15)
        assert result.total_checked == 2
        assert len(result.violations) == 1
        assert result.violations[0].text_content == "U1"
        assert result.violations[0].footprint_ref == "U1"
        assert len(result.violations[0].overlapping_items) > 0

    def test_suggested_position(self):
        """Violations include a suggested relocation position."""
        from volta.validation.silkscreen_clearance import check_silkscreen_clearance
        from volta.parser.pcb_native_types import NativeBoard, NativeFootprint

        fp = SimpleNamespace(
            properties={"Reference": "C1", "Value": "100nF"},
            layer="F.Cu",
            reference=None, value=None, pads=[],
        )
        fp_ref = type("Ref", (), {
            "at": (5.0, 5.0),
        })()
        fp.reference = fp_ref
        fp.value = type("Val", (), {
            "at": (100.0, 100.0),
            "value": "100nF",
        })()
        fp.pads = [
            type("Pad", (), {
                "at": (5.0, 5.0),
                "size": (2.0, 2.0),
                "net": "VCC",
            })(),
        ]

        board = dataclasses.replace(NativeBoard(), footprints=(fp,))
        ir = _make_pcb_ir(board)

        result = check_silkscreen_clearance(ir, clearance_mm=0.15)
        assert len(result.violations) == 1
        assert result.violations[0].suggested_position is not None

    def test_empty_board(self):
        """Empty board returns zero checked."""
        from volta.validation.silkscreen_clearance import check_silkscreen_clearance
        from volta.parser.pcb_native_types import NativeBoard

        board = NativeBoard()
        ir = _make_pcb_ir(board)

        result = check_silkscreen_clearance(ir)
        assert result.total_checked == 0
        assert len(result.violations) == 0


def _make_pcb_ir(board):
    """Create a minimal PcbIR for testing."""
    from volta.ir.pcb_ir import PcbIR

    ir = PcbIR.__new__(PcbIR)
    ir._parse_result = type("PR", (), {
        "file_path": "test.kicad_pcb", "raw_content": "",
    })()
    ir._native_board = board
    return ir
