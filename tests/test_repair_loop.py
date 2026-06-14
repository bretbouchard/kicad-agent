"""Tests for RepairLoop and audit trail (Phase 92)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from kicad_agent.validation.gate_types import DesignStage, GateResult
from kicad_agent.validation.gates.fix_providers import PlacementBoundsFixProvider
from kicad_agent.validation.gates.repair_loop import (
    RepairAuditEntry,
    RepairLoop,
    serialize_audit_trail,
)


def _failing_gate(context: dict) -> GateResult:
    """Gate that always fails with specific blockers from context."""
    blockers = context.get("_test_blockers", ["blocker1"])
    return GateResult(
        pass_=False,
        gate_name="test_gate",
        stage=DesignStage.ROUTING,
        blockers=blockers,
    )


def _passing_gate(context: dict) -> GateResult:
    """Gate that always passes."""
    return GateResult(
        pass_=True,
        gate_name="test_gate",
        stage=DesignStage.ROUTING,
        next_actions=["Proceed"],
    )


def _adaptive_gate(call_count: dict) -> MagicMock:
    """Gate that fails first N times then passes."""
    gate = MagicMock()
    def side_effect(ctx):
        call_count["n"] = call_count.get("n", 0) + 1
        if call_count["n"] >= 2:
            return GateResult(pass_=True, gate_name="test_gate", stage=DesignStage.ROUTING)
        return GateResult(
            pass_=False,
            gate_name="test_gate",
            stage=DesignStage.ROUTING,
            blockers=["Component R1 outside board outline"],
        )
    gate.side_effect = side_effect
    return gate


def _make_context(
    blockers: list[str] | None = None,
    scope_files: list[str] | None = None,
) -> dict:
    return {
        "_test_blockers": blockers or ["blocker1"],
        "scope_files": scope_files or ["test.kicad_pcb"],
        "target_file": "test.kicad_pcb",
        "component_ref": "R1",
    }


class TestRepairAuditEntry:
    def test_to_dict_roundtrip(self) -> None:
        entry = RepairAuditEntry(
            iteration=1, blocker="b1", proposal_op={"op": "test"},
            accepted=True, source="deterministic", result="applied",
        )
        d = entry.to_dict()
        restored = RepairAuditEntry.from_dict(d)
        assert restored == entry

    def test_frozen(self) -> None:
        entry = RepairAuditEntry(
            iteration=1, blocker="b1", proposal_op=None,
            accepted=False, source="none", result="no_proposal",
        )
        with pytest.raises(Exception):
            entry.result = "changed"


class TestSerializeAuditTrail:
    def test_serializes_to_json(self) -> None:
        entries = [
            RepairAuditEntry(
                iteration=1, blocker="b1", proposal_op=None,
                accepted=False, source="none", result="no_proposal",
            ),
        ]
        json_str = serialize_audit_trail(entries)
        parsed = json.loads(json_str)
        assert len(parsed) == 1
        assert parsed[0]["blocker"] == "b1"

    def test_empty_trail(self) -> None:
        assert serialize_audit_trail([]) == "[]"


class TestRepairLoop:
    def test_gate_passes_immediately(self) -> None:
        loop = RepairLoop(_passing_gate, MagicMock(), max_iterations=3)
        result = loop.run("test", _make_context())
        assert result.pass_ is True
        assert len(loop.audit_trail) == 0

    def test_gate_always_fails_stops_at_max(self) -> None:
        loop = RepairLoop(_failing_gate, MagicMock(), max_iterations=2)
        context = _make_context(blockers=["unrecognized blocker"])
        result = loop.run("test", context)
        assert result.pass_ is False
        # Should have audit entries (no_proposal since no provider matches)
        assert len(loop.audit_trail) > 0
        # Either oscillation or max iterations stops the loop
        has_stop_message = any(
            "oscillation" in a or "exhausted" in a for a in result.next_actions
        )
        assert has_stop_message

    def test_rollback_on_exhaustion(self) -> None:
        loop = RepairLoop(_failing_gate, MagicMock(), max_iterations=2)
        context = _make_context(blockers=["unrecognized"])
        loop.run("test", context)
        # Final entries should have rolled_back=True
        rolled_back = [e for e in loop.audit_trail if e.rolled_back]
        assert len(rolled_back) > 0

    def test_oscillation_detection(self) -> None:
        """Same blocker set in 2 consecutive iterations stops loop."""
        call_count: dict = {}
        gate = MagicMock()
        blockers = ["Component R1 outside board outline"]
        gate.side_effect = lambda ctx: GateResult(
            pass_=False, gate_name="test", stage=DesignStage.ROUTING,
            blockers=blockers,
        )
        loop = RepairLoop(
            gate, MagicMock(), max_iterations=5,
            fix_providers=[PlacementBoundsFixProvider()],
        )
        context = _make_context(blockers=blockers, scope_files=["test.kicad_pcb"])
        result = loop.run("test", context)
        assert result.pass_ is False
        assert any("oscillation" in a for a in result.next_actions)

    def test_audit_trail_in_artifacts(self) -> None:
        loop = RepairLoop(_failing_gate, MagicMock(), max_iterations=1)
        context = _make_context(blockers=["unrecognized"])
        result = loop.run("test", context)
        # Audit trail JSON should be in artifacts
        json_artifacts = [a for a in result.artifacts if a.startswith("[")]
        assert len(json_artifacts) == 1
        parsed = json.loads(json_artifacts[0])
        assert len(parsed) > 0

    def test_dry_run_no_mutation(self) -> None:
        executor = MagicMock()
        loop = RepairLoop(_failing_gate, executor, max_iterations=1, fix_providers=[])
        loop.dry_run = True
        context = _make_context(blockers=["unrecognized"])
        loop.run("test", context)
        executor.execute.assert_not_called()

    def test_scope_violation_recorded(self) -> None:
        """ScopeViolationError during apply is recorded in audit trail."""
        gate = MagicMock()
        gate.side_effect = lambda ctx: GateResult(
            pass_=False, gate_name="test", stage=DesignStage.ROUTING,
            blockers=["Component R1 outside board outline"],
        )
        executor = MagicMock()
        registry = {"move_component": {}, "add_component": {}, "export": {}}
        loop = RepairLoop(
            gate, executor, max_iterations=1,
            fix_providers=[PlacementBoundsFixProvider()],
            registry=registry,
        )
        # scope_files is set to a different file than what provider will target
        # Provider uses context["target_file"] = "forbidden.kicad_pcb" (not in scope)
        context = {
            "scope_files": ["allowed.kicad_pcb"],
            "target_file": "forbidden.kicad_pcb",  # NOT in scope
            "component_ref": "R1",
        }
        result = loop.run("test", context)
        scope_violations = [
            e for e in loop.audit_trail if e.result == "scope_violation"
        ]
        assert len(scope_violations) == 1
