"""Tests for gate operation handlers."""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from volta.ops._schema_gate import GateStatusOp, RunGateCheckOp
from volta.ops.handlers.gate_handlers import (
    _detect_design_stage,
    get_gate_handler,
    handle_gate_status,
    handle_run_gate_check,
    list_gate_handlers,
)


class TestRunGateCheckOpSchema:
    """Test RunGateCheckOp schema validation."""

    def test_minimal(self):
        op = RunGateCheckOp(gate_name="pre_pcb_schematic")
        assert op.gate_name == "pre_pcb_schematic"
        assert op.project_dir is None

    def test_with_project_dir(self):
        op = RunGateCheckOp(gate_name="test", project_dir="/some/path")
        assert op.project_dir == "/some/path"

    def test_empty_name_raises(self):
        with pytest.raises(Exception):
            RunGateCheckOp(gate_name="")

    def test_op_type_discriminator(self):
        op = RunGateCheckOp(gate_name="test")
        assert op.op_type == "run_gate_check"


class TestGateStatusOpSchema:
    """Test GateStatusOp schema validation."""

    def test_minimal(self):
        op = GateStatusOp()
        assert op.project_dir is None

    def test_with_project_dir(self):
        op = GateStatusOp(project_dir="/some/path")
        assert op.project_dir == "/some/path"

    def test_op_type_discriminator(self):
        op = GateStatusOp()
        assert op.op_type == "gate_status"


class TestHandleRunGateCheck:
    """Test handle_run_gate_check dispatch."""

    def test_unknown_gate_returns_failure(self):
        """Running an unregistered gate returns a failure result."""
        op = RunGateCheckOp(gate_name="nonexistent_gate")
        ir = MagicMock()
        result = handle_run_gate_check(op, ir, Path("/tmp/test.kicad_sch"))
        assert result["pass"] is False
        assert "not registered" in result["blockers"][0]

    def test_registered_gate_dispatches(self):
        """Running a registered gate delegates to GateRunner."""
        from volta.validation.gate_types import GateResult, DesignStage
        from volta.validation.gate_runner import get_gate_runner, register_gate, GateDefinition

        def _pass_fn(ctx):
            return GateResult(pass_=True, gate_name="test_gate", stage=DesignStage.PCB_SETUP)

        register_gate(
            GateDefinition("test_gate", DesignStage.SCHEMATIC, DesignStage.PCB_SETUP, "test_gate"),
            check_fn=_pass_fn,
        )

        op = RunGateCheckOp(gate_name="test_gate")
        ir = MagicMock()
        result = handle_run_gate_check(op, ir, Path("/tmp/test.kicad_sch"))
        assert result["pass"] is True
        assert result["gate"] == "test_gate"


class TestHandleGateStatus:
    """Test handle_gate_status returns stage info."""

    def test_returns_current_stage(self):
        op = GateStatusOp(project_dir="/tmp")
        ir = MagicMock()
        result = handle_gate_status(op, ir, Path("/tmp/test.kicad_sch"))
        assert "current_stage" in result
        assert "registered_gates" in result
        assert "next_actions" in result

    def test_detect_stage_with_schematic(self):
        """Detect schematic stage from .kicad_sch files."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            sch = Path(tmpdir) / "test.kicad_sch"
            sch.touch()
            stage = _detect_design_stage(Path(tmpdir))
            assert stage.value == "schematic"

    def test_detect_stage_empty_dir(self):
        """Empty directory defaults to schematic stage."""
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            stage = _detect_design_stage(Path(tmpdir))
            assert stage.value == "schematic"


class TestGateHandlerRegistry:
    """Test gate handler registration."""

    def test_handlers_registered(self):
        handlers = list_gate_handlers()
        assert "run_gate_check" in handlers
        assert "gate_status" in handlers

    def test_get_known_handler(self):
        fn = get_gate_handler("run_gate_check")
        assert fn is not None
        assert callable(fn)

    def test_get_unknown_handler(self):
        fn = get_gate_handler("nonexistent")
        assert fn is None
