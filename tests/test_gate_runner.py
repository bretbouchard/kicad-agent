"""Tests for GateRunner orchestrator."""

import pytest

from volta.validation.gate_types import (
    DesignStage,
    GateDefinition,
    GateResult,
)
from volta.validation.gate_runner import GateRunner, get_gate_runner, register_gate


def _passing_gate(ctx: dict) -> GateResult:
    return GateResult(pass_=True, gate_name="test_pass", stage=DesignStage.PCB_SETUP)


def _failing_gate(ctx: dict) -> GateResult:
    return GateResult(
        pass_=False,
        gate_name="test_fail",
        stage=DesignStage.SCHEMATIC,
        blockers=["Something broke"],
        next_actions=["Fix it"],
    )


def _dict_gate(ctx: dict) -> dict:
    """Gate that returns a legacy dict instead of GateResult."""
    return {"pass": True, "gate": "dict_gate", "ready_for_pcb": True}


def _warn_gate(ctx: dict) -> GateResult:
    return GateResult(
        pass_=True,
        gate_name="test_warn",
        stage=DesignStage.PCB_SETUP,
        warnings=["Minor issue"],
        artifacts=["net_map"],
    )


class TestGateRunnerRegistration:
    """Test gate registration and lookup."""

    def test_register_and_get(self):
        runner = GateRunner()
        gate_def = GateDefinition(
            name="test_gate",
            from_stage=DesignStage.SCHEMATIC,
            to_stage=DesignStage.PCB_SETUP,
            check_fn_name="test_check",
        )
        runner.register_gate(gate_def, check_fn=_passing_gate)
        assert runner.get_gate("test_gate") is gate_def

    def test_get_unknown_returns_none(self):
        runner = GateRunner()
        assert runner.get_gate("nonexistent") is None

    def test_list_gates(self):
        runner = GateRunner()
        runner.register_gate(
            GateDefinition("a", DesignStage.SCHEMATIC, DesignStage.PCB_SETUP, "a"),
            check_fn=_passing_gate,
        )
        runner.register_gate(
            GateDefinition("b", DesignStage.PCB_SETUP, DesignStage.PLACEMENT, "b"),
            check_fn=_passing_gate,
        )
        assert len(runner.list_gates()) == 2

    def test_register_without_check_fn(self):
        """Gate can be registered without check_fn (metadata only)."""
        runner = GateRunner()
        gate_def = GateDefinition(
            name="meta_only",
            from_stage=DesignStage.SCHEMATIC,
            to_stage=DesignStage.PCB_SETUP,
            check_fn_name="meta_check",
        )
        runner.register_gate(gate_def)
        assert runner.get_gate("meta_only") is gate_def


class TestGateRunnerExecution:
    """Test run_gate with passing/failing checks."""

    def test_run_passing_gate(self):
        runner = GateRunner()
        runner.register_gate(
            GateDefinition("pass_gate", DesignStage.SCHEMATIC, DesignStage.PCB_SETUP, "pass"),
            check_fn=_passing_gate,
        )
        result = runner.run_gate("pass_gate", {})
        assert result.pass_bool is True

    def test_run_failing_gate(self):
        runner = GateRunner()
        runner.register_gate(
            GateDefinition("fail_gate", DesignStage.SCHEMATIC, DesignStage.PCB_SETUP, "fail"),
            check_fn=_failing_gate,
        )
        result = runner.run_gate("fail_gate", {})
        assert result.pass_bool is False
        assert "Something broke" in result.blockers

    def test_run_unknown_gate_raises(self):
        runner = GateRunner()
        with pytest.raises(KeyError, match="not registered"):
            runner.run_gate("nonexistent", {})

    def test_run_gate_without_check_fn_raises(self):
        runner = GateRunner()
        runner.register_gate(
            GateDefinition("no_fn", DesignStage.SCHEMATIC, DesignStage.PCB_SETUP, "missing"),
        )
        with pytest.raises(RuntimeError, match="Check function not registered"):
            runner.run_gate("no_fn", {})

    def test_dict_result_wrapped_in_gate_result(self):
        """Gates returning plain dicts get wrapped into GateResult."""
        runner = GateRunner()
        runner.register_gate(
            GateDefinition("dict_gate", DesignStage.SCHEMATIC, DesignStage.PCB_SETUP, "dict"),
            check_fn=_dict_gate,
        )
        result = runner.run_gate("dict_gate", {})
        assert isinstance(result, GateResult)
        assert result.pass_bool is True


class TestGateRunnerRequiredGates:
    """Test get_required_gates for stage transitions."""

    def test_adjacent_stages(self):
        runner = GateRunner()
        runner.register_gate(
            GateDefinition("g1", DesignStage.SCHEMATIC, DesignStage.PCB_SETUP, "g1"),
            check_fn=_passing_gate,
        )
        gates = runner.get_required_gates(DesignStage.SCHEMATIC, DesignStage.PCB_SETUP)
        assert gates == ["g1"]

    def test_multi_stage_chain(self):
        runner = GateRunner()
        runner.register_gate(
            GateDefinition("g1", DesignStage.SCHEMATIC, DesignStage.PCB_SETUP, "g1"),
            check_fn=_passing_gate,
        )
        runner.register_gate(
            GateDefinition("g2", DesignStage.PCB_SETUP, DesignStage.PLACEMENT, "g2"),
            check_fn=_passing_gate,
        )
        gates = runner.get_required_gates(DesignStage.SCHEMATIC, DesignStage.PLACEMENT)
        assert gates == ["g1", "g2"]

    def test_backward_transition_returns_empty(self):
        runner = GateRunner()
        runner.register_gate(
            GateDefinition("g1", DesignStage.SCHEMATIC, DesignStage.PCB_SETUP, "g1"),
            check_fn=_passing_gate,
        )
        gates = runner.get_required_gates(DesignStage.PCB_SETUP, DesignStage.SCHEMATIC)
        assert gates == []

    def test_same_stage_returns_empty(self):
        runner = GateRunner()
        gates = runner.get_required_gates(DesignStage.SCHEMATIC, DesignStage.SCHEMATIC)
        assert gates == []

    def test_unregistered_stage_gap_skipped(self):
        """Stages without registered gates are skipped in the chain."""
        runner = GateRunner()
        runner.register_gate(
            GateDefinition("g1", DesignStage.SCHEMATIC, DesignStage.PCB_SETUP, "g1"),
            check_fn=_passing_gate,
        )
        # No gate for PCB_SETUP -> PLACEMENT
        runner.register_gate(
            GateDefinition("g3", DesignStage.PLACEMENT, DesignStage.ROUTING, "g3"),
            check_fn=_passing_gate,
        )
        gates = runner.get_required_gates(DesignStage.SCHEMATIC, DesignStage.ROUTING)
        assert gates == ["g1", "g3"]


class TestGateRunnerChain:
    """Test run_all_gates chains correctly."""

    def test_all_pass(self):
        runner = GateRunner()
        runner.register_gate(
            GateDefinition("g1", DesignStage.SCHEMATIC, DesignStage.PCB_SETUP, "g1"),
            check_fn=_passing_gate,
        )
        runner.register_gate(
            GateDefinition("g2", DesignStage.PCB_SETUP, DesignStage.PLACEMENT, "g2"),
            check_fn=_passing_gate,
        )
        result = runner.run_all_gates(DesignStage.SCHEMATIC, DesignStage.PLACEMENT, {})
        assert result.pass_bool is True
        assert result.stage == DesignStage.PLACEMENT

    def test_stops_on_first_failure(self):
        runner = GateRunner()
        runner.register_gate(
            GateDefinition("g1", DesignStage.SCHEMATIC, DesignStage.PCB_SETUP, "g1"),
            check_fn=_failing_gate,
        )
        runner.register_gate(
            GateDefinition("g2", DesignStage.PCB_SETUP, DesignStage.PLACEMENT, "g2"),
            check_fn=_passing_gate,
        )
        result = runner.run_all_gates(DesignStage.SCHEMATIC, DesignStage.PLACEMENT, {})
        assert result.pass_bool is False
        assert "Something broke" in result.blockers

    def test_no_gates_returns_pass(self):
        runner = GateRunner()
        result = runner.run_all_gates(DesignStage.SCHEMATIC, DesignStage.PCB_SETUP, {})
        assert result.pass_bool is True
        assert "Proceed to" in result.next_actions[0]

    def test_warnings_accumulate(self):
        runner = GateRunner()
        runner.register_gate(
            GateDefinition("g1", DesignStage.SCHEMATIC, DesignStage.PCB_SETUP, "g1"),
            check_fn=_warn_gate,
        )
        runner.register_gate(
            GateDefinition("g2", DesignStage.PCB_SETUP, DesignStage.PLACEMENT, "g2"),
            check_fn=_passing_gate,
        )
        result = runner.run_all_gates(DesignStage.SCHEMATIC, DesignStage.PLACEMENT, {})
        assert result.pass_bool is True
        assert len(result.warnings) == 1
        assert len(result.artifacts) == 1


class TestDefaultRunner:
    """Test module-level singleton runner."""

    def test_get_gate_runner_returns_instance(self):
        runner = get_gate_runner()
        assert isinstance(runner, GateRunner)

    def test_register_gate_function(self):
        gate_def = GateDefinition(
            name="singleton_test",
            from_stage=DesignStage.SCHEMATIC,
            to_stage=DesignStage.PCB_SETUP,
            check_fn_name="test",
        )
        register_gate(gate_def, check_fn=_passing_gate)
        runner = get_gate_runner()
        assert runner.get_gate("singleton_test") is gate_def

    def test_fail_closed_blocks_downstream(self):
        """Failing gate result prevents downstream operations."""
        runner = GateRunner()
        runner.register_gate(
            GateDefinition("blocker", DesignStage.SCHEMATIC, DesignStage.PCB_SETUP, "block"),
            check_fn=_failing_gate,
        )
        result = runner.run_all_gates(DesignStage.SCHEMATIC, DesignStage.PCB_SETUP, {})
        assert result.pass_bool is False
        assert len(result.blockers) > 0
