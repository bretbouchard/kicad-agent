"""Tests for gate type models: DesignStage, GateResult, GateDefinition."""

import json

import pytest
from pydantic import ValidationError

from kicad_agent.validation.gate_types import (
    DesignStage,
    GateDefinition,
    GateResult,
)


class TestDesignStage:
    """Test DesignStage enum."""

    def test_has_five_values(self):
        assert len(DesignStage) == 5

    def test_stage_values(self):
        assert DesignStage.SCHEMATIC.value == "schematic"
        assert DesignStage.PCB_SETUP.value == "pcb_setup"
        assert DesignStage.PLACEMENT.value == "placement"
        assert DesignStage.ROUTING.value == "routing"
        assert DesignStage.MANUFACTURING.value == "manufacturing"

    def test_from_string(self):
        stage = DesignStage("schematic")
        assert stage is DesignStage.SCHEMATIC

    def test_invalid_string_raises(self):
        with pytest.raises(ValueError):
            DesignStage("nonexistent")


class TestGateResultPassing:
    """Test GateResult creation with pass=True."""

    def test_create_passing(self):
        result = GateResult(pass_=True, gate_name="test_gate")
        assert result.pass_bool is True
        assert result.blockers == []
        assert result.gate_name == "test_gate"

    def test_passing_with_warnings(self):
        result = GateResult(
            pass_=True,
            gate_name="test",
            warnings=["Minor issue"],
        )
        assert result.pass_bool is True
        assert len(result.warnings) == 1

    def test_passing_with_artifacts(self):
        result = GateResult(
            pass_=True,
            gate_name="test",
            artifacts=["net_intent:power"],
        )
        assert result.pass_bool is True
        assert result.artifacts == ["net_intent:power"]

    def test_passing_with_next_actions(self):
        result = GateResult(
            pass_=True,
            gate_name="test",
            next_actions=["Proceed to PCB setup"],
        )
        assert result.next_actions == ["Proceed to PCB setup"]

    def test_default_stage_is_schematic(self):
        result = GateResult(pass_=True)
        assert result.stage == DesignStage.SCHEMATIC


class TestGateResultFailing:
    """Test GateResult creation with pass=False."""

    def test_create_failing(self):
        result = GateResult(
            pass_=False,
            gate_name="test_gate",
            blockers=["Missing footprint"],
        )
        assert result.pass_bool is False
        assert result.blockers == ["Missing footprint"]

    def test_failing_with_warnings(self):
        result = GateResult(
            pass_=False,
            gate_name="test",
            blockers=["ERC error"],
            warnings=["Annotation issue"],
        )
        assert result.pass_bool is False
        assert len(result.blockers) == 1
        assert len(result.warnings) == 1

    def test_failing_multiple_blockers(self):
        result = GateResult(
            pass_=False,
            gate_name="test",
            blockers=["Error 1", "Error 2", "Error 3"],
        )
        assert len(result.blockers) == 3


class TestGateResultInvariants:
    """Test blocker invariant enforcement."""

    def test_pass_with_blockers_raises(self):
        with pytest.raises(ValidationError, match="blockers must be empty"):
            GateResult(pass_=True, blockers=["This should fail"])

    def test_fail_without_blockers_raises(self):
        with pytest.raises(ValidationError, match="blockers must be non-empty"):
            GateResult(pass_=False)

    def test_pass_true_empty_blockers_ok(self):
        result = GateResult(pass_=True, blockers=[])
        assert result.pass_bool is True

    def test_pass_false_nonempty_blockers_ok(self):
        result = GateResult(pass_=False, blockers=["Block"])
        assert result.pass_bool is False


class TestGateResultSerialization:
    """Test to_dict, from_dict, to_json."""

    def test_to_dict_shape(self):
        result = GateResult(
            pass_=True,
            gate_name="test_gate",
            warnings=["A warning"],
            artifacts=["artifact1"],
            next_actions=["Do X"],
        )
        d = result.to_dict()
        assert d["pass"] is True
        assert d["ready_for_pcb"] is True
        assert d["gate"] == "test_gate"
        assert d["recommendations"] == ["A warning", "Do X"]
        assert d["artifacts"] == ["artifact1"]

    def test_to_dict_failing_shape(self):
        result = GateResult(
            pass_=False,
            gate_name="test",
            blockers=["Error A"],
            warnings=["Warning B"],
            next_actions=["Fix A"],
        )
        d = result.to_dict()
        assert d["pass"] is False
        assert d["ready_for_pcb"] is False
        assert d["blockers"] == ["Error A"]
        assert d["recommendations"] == ["Warning B", "Fix A"]

    def test_from_dict_round_trip(self):
        original = GateResult(
            pass_=False,
            gate_name="test",
            stage=DesignStage.PCB_SETUP,
            blockers=["B1"],
            warnings=["W1"],
            artifacts=["A1"],
            next_actions=["N1"],
        )
        d = original.to_dict()
        restored = GateResult.from_dict(d)
        assert restored.pass_bool is False
        assert restored.gate_name == "test"
        assert restored.blockers == ["B1"]

    def test_from_dict_legacy_shape(self):
        """from_dict handles legacy pre_pcb_schematic_gate dict."""
        legacy = {
            "pass": True,
            "gate": "pre_pcb_schematic",
            "ready_for_pcb": True,
            "recommendations": ["Add power symbols"],
        }
        result = GateResult.from_dict(legacy)
        assert result.pass_bool is True
        assert result.gate_name == "pre_pcb_schematic"
        assert result.warnings == ["Add power symbols"]

    def test_from_dict_legacy_fail_shape(self):
        """from_dict promotes recommendations to blockers for failing legacy dicts."""
        legacy = {
            "pass": False,
            "gate": "pre_pcb_schematic",
            "ready_for_pcb": False,
            "recommendations": ["Fix ERC errors"],
        }
        result = GateResult.from_dict(legacy)
        assert result.pass_bool is False
        # recommendations promoted to blockers to satisfy fail-closed invariant
        assert "Fix ERC errors" in result.blockers

    def test_to_json(self):
        result = GateResult(pass_=True, gate_name="test")
        json_str = result.to_json()
        parsed = json.loads(json_str)
        assert parsed["pass"] is True
        assert parsed["gate"] == "test"

    def test_frozen_model(self):
        """GateResult is immutable."""
        result = GateResult(pass_=True, gate_name="test")
        with pytest.raises(Exception):
            result.gate_name = "changed"


class TestGateDefinition:
    """Test GateDefinition dataclass."""

    def test_create(self):
        gate = GateDefinition(
            name="pre_pcb_schematic",
            from_stage=DesignStage.SCHEMATIC,
            to_stage=DesignStage.PCB_SETUP,
            check_fn_name="pre_pcb_schematic_gate",
        )
        assert gate.name == "pre_pcb_schematic"
        assert gate.block_on_fail is True

    def test_block_on_fail_default(self):
        gate = GateDefinition(
            name="test",
            from_stage=DesignStage.SCHEMATIC,
            to_stage=DesignStage.PCB_SETUP,
            check_fn_name="test_fn",
        )
        assert gate.block_on_fail is True

    def test_block_on_fail_false(self):
        gate = GateDefinition(
            name="test",
            from_stage=DesignStage.SCHEMATIC,
            to_stage=DesignStage.PCB_SETUP,
            check_fn_name="test_fn",
            block_on_fail=False,
        )
        assert gate.block_on_fail is False

    def test_frozen(self):
        gate = GateDefinition(
            name="test",
            from_stage=DesignStage.SCHEMATIC,
            to_stage=DesignStage.PCB_SETUP,
            check_fn_name="test_fn",
        )
        with pytest.raises(Exception):
            gate.name = "changed"
