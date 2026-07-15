"""Tests for workflow templates and dependency validation."""

import pytest

from volta.ops.registry import OPERATION_REGISTRY, validate_dependencies, validate_conflicts
from volta.ops.workflows import (
    WORKFLOW_TEMPLATES,
    WorkflowStep,
    WorkflowTemplate,
    get_workflow,
    list_workflows,
)


class TestListWorkflows:
    """Test list_workflows returns expected summaries."""

    def test_returns_at_least_6_templates(self) -> None:
        result = list_workflows()
        assert len(result) >= 6

    def test_each_entry_has_required_keys(self) -> None:
        for entry in list_workflows():
            assert "name" in entry
            assert "description" in entry
            assert "steps" in entry
            assert isinstance(entry["steps"], int)


class TestGetWorkflow:
    """Test get_workflow lookup."""

    def test_fix_erc_errors(self) -> None:
        wf = get_workflow("fix_erc_errors")
        assert wf is not None
        assert wf.name == "fix_erc_errors"
        assert len(wf.steps) == 5
        assert wf.steps[0].op_type == "parse_erc"
        assert wf.steps[3].op_type == "erc_auto_fix"

    def test_wire_schematic(self) -> None:
        wf = get_workflow("wire_schematic")
        assert wf is not None
        assert wf.name == "wire_schematic"
        assert len(wf.steps) == 5

    def test_returns_none_for_unknown(self) -> None:
        assert get_workflow("nonexistent") is None


class TestWorkflowStepOpTypes:
    """Verify every step's op_type exists in the registry."""

    @pytest.mark.parametrize("wf_name", list(WORKFLOW_TEMPLATES.keys()))
    def test_step_op_types_are_registered(self, wf_name: str) -> None:
        wf = WORKFLOW_TEMPLATES[wf_name]
        for step in wf.steps:
            assert step.op_type in OPERATION_REGISTRY, (
                f"Workflow {wf_name!r} step {step.op_type!r} not in registry"
            )


class TestWorkflowDependencyChains:
    """Verify each workflow's dependency chain is internally consistent."""

    @pytest.mark.parametrize("wf_name", list(WORKFLOW_TEMPLATES.keys()))
    def test_dependency_chain_is_valid(self, wf_name: str) -> None:
        wf = WORKFLOW_TEMPLATES[wf_name]
        step_types = [s.op_type for s in wf.steps]
        missing = validate_dependencies(step_types)
        assert missing == [], (
            f"Workflow {wf_name!r} has unresolved prerequisites: {missing}"
        )


class TestValidateDependencies:
    """Test the validate_dependencies function directly."""

    def test_empty_list(self) -> None:
        assert validate_dependencies([]) == []

    def test_no_deps_needed(self) -> None:
        assert validate_dependencies(["add_component"]) == []

    def test_missing_prerequisite(self) -> None:
        result = validate_dependencies(["connect_pins"])
        assert result == ["resolve_pin_positions"]

    def test_satisfied_prerequisite(self) -> None:
        result = validate_dependencies(["resolve_pin_positions", "connect_pins"])
        assert result == []

    def test_missing_erc_dep(self) -> None:
        result = validate_dependencies(["erc_auto_fix"])
        assert result == ["parse_erc"]

    def test_satisfied_erc_dep(self) -> None:
        result = validate_dependencies(["parse_erc", "erc_auto_fix"])
        assert result == []

    def test_unknown_op_skipped(self) -> None:
        # Unknown ops don't cause errors; they just get added to seen set
        result = validate_dependencies(["nonexistent_op", "connect_pins"])
        # connect_pins still needs resolve_pin_positions
        assert result == ["resolve_pin_positions"]

    def test_chain_of_deps(self) -> None:
        # diagnose_violations requires classify_violations,
        # classify_violations has no requires
        result = validate_dependencies(["diagnose_violations"])
        assert result == ["classify_violations"]

        result = validate_dependencies(["classify_violations", "diagnose_violations"])
        assert result == []

    def test_repair_pipeline_deps(self) -> None:
        # fix_shorted_nets requires parse_erc
        result = validate_dependencies(["fix_shorted_nets"])
        assert "parse_erc" in result

        result = validate_dependencies(["parse_erc", "fix_shorted_nets"])
        assert result == []


class TestWorkflowConflictFree:
    """Verify each workflow's steps are conflict-free."""

    @pytest.mark.parametrize("wf_name", list(WORKFLOW_TEMPLATES.keys()))
    def test_workflow_has_no_conflicts(self, wf_name: str) -> None:
        wf = WORKFLOW_TEMPLATES[wf_name]
        step_types = [s.op_type for s in wf.steps]
        conflicts = validate_conflicts(step_types)
        assert conflicts == [], (
            f"Workflow {wf_name!r} has conflicting steps: {conflicts}"
        )
