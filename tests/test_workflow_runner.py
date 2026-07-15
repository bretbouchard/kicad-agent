"""Tests for WorkflowRunner, AgentConfig, and CLI workflow subcommand."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from volta.config import AgentConfig, ModelConfig, RoutingConfig, load_config


# ---------------------------------------------------------------------------
# config.py tests
# ---------------------------------------------------------------------------


class TestAgentConfigDefaults:
    """AgentConfig uses correct hardcoded defaults."""

    def test_routing_defaults(self) -> None:
        config = AgentConfig()
        assert config.routing.target_route_pct == 95.0
        assert config.routing.max_iterations == 3
        assert config.routing.strategy == "auto"

    def test_model_defaults(self) -> None:
        config = AgentConfig()
        assert config.models.vision_model == "gemma-4-12b"
        assert config.models.text_model == "qwen2.5-0.5b"
        assert config.models.use_ai is True

    def test_from_dict_override(self) -> None:
        config = AgentConfig.from_dict({
            "routing": {"target_route_pct": 80.0, "max_iterations": 1},
            "models": {"use_ai": False},
        })
        assert config.routing.target_route_pct == 80.0
        assert config.routing.max_iterations == 1
        assert config.models.use_ai is False


class TestLoadConfig:
    """Config loading with precedence."""

    def test_missing_dir_returns_defaults(self, tmp_path: Path) -> None:
        config = load_config(tmp_path / "nonexistent")
        assert config == AgentConfig()

    def test_yaml_precedence(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / "volta.yaml"
        yaml_file.write_text(
            "routing:\n  target_route_pct: 85.0\nmodels:\n  use_ai: false\n",
            encoding="utf-8",
        )
        config = load_config(tmp_path)
        assert config.routing.target_route_pct == 85.0
        assert config.models.use_ai is False

    def test_explicit_config_path(self, tmp_path: Path) -> None:
        yaml_file = tmp_path / "custom.yaml"
        yaml_file.write_text(
            "routing:\n  max_iterations: 2\n",
            encoding="utf-8",
        )
        config = load_config(config_path=yaml_file)
        assert config.routing.max_iterations == 2


# ---------------------------------------------------------------------------
# workflow_runner.py tests
# ---------------------------------------------------------------------------


class TestWorkflowRunner:
    """WorkflowRunner dispatch and result handling."""

    def _make_gap_result(self, *, success: bool = True) -> MagicMock:
        """Create a mock GapFillResult."""
        result = MagicMock()
        result.success = success
        result.errors = ()
        result.to_json.return_value = {"success": success}
        result.to_markdown.return_value = f"**Status:** {'SUCCESS' if success else 'FAILED'}"
        return result

    def test_route_and_fill_success(self) -> None:
        mock_engine = MagicMock()
        mock_engine.fill_gaps.return_value = self._make_gap_result(success=True)

        with patch(
            "volta.analysis.gap_fill_engine.GapFillEngine",
            return_value=mock_engine,
        ):
            from volta.ops.workflow_runner import WorkflowRunner

            runner = WorkflowRunner()
            result = runner.run("route_and_fill", __file__)  # any existing file

        assert result.success is True
        assert result.workflow_name == "route_and_fill"
        assert result.steps_completed == 1
        assert result.gap_fill_result is not None

    def test_route_and_fill_passes_config(self) -> None:
        from volta.ops.workflow_runner import WorkflowRunner

        mock_engine = MagicMock()
        mock_engine.fill_gaps.return_value = self._make_gap_result()

        config = AgentConfig(
            routing=RoutingConfig(max_iterations=1, target_route_pct=80.0),
            models=ModelConfig(use_ai=False),
        )

        with patch(
            "volta.analysis.gap_fill_engine.GapFillEngine",
            return_value=mock_engine,
        ) as MockEngine:
            runner = WorkflowRunner(config=config)
            runner.run("route_and_fill", __file__)

        MockEngine.assert_called_once_with(
            max_iterations=1,
            target_route_pct=80.0,
            run_drc=True,
            use_ai=False,
        )

    def test_route_and_fill_file_not_found(self) -> None:
        from volta.ops.workflow_runner import WorkflowRunner

        runner = WorkflowRunner()
        result = runner.run("route_and_fill", "/nonexistent/board.kicad_pcb")

        assert result.success is False
        assert "File not found" in result.errors[0]

    def test_route_and_fill_failure(self) -> None:
        mock_engine = MagicMock()
        mock_engine.fill_gaps.return_value = self._make_gap_result(success=False)

        with patch(
            "volta.analysis.gap_fill_engine.GapFillEngine",
            return_value=mock_engine,
        ):
            from volta.ops.workflow_runner import WorkflowRunner

            runner = WorkflowRunner()
            result = runner.run("route_and_fill", __file__)

        assert result.success is False
        assert result.steps_completed == 0

    def test_unknown_workflow(self) -> None:
        from volta.ops.workflow_runner import WorkflowRunner

        runner = WorkflowRunner()
        result = runner.run("nonexistent_workflow", __file__)

        assert result.success is False
        assert "Unknown workflow" in result.errors[0]

    def test_result_to_json(self) -> None:
        mock_engine = MagicMock()
        mock_engine.fill_gaps.return_value = self._make_gap_result()

        with patch(
            "volta.analysis.gap_fill_engine.GapFillEngine",
            return_value=mock_engine,
        ):
            from volta.ops.workflow_runner import WorkflowRunner

            runner = WorkflowRunner()
            result = runner.run("route_and_fill", __file__)

        data = result.to_json()
        assert data["success"] is True
        assert data["workflow_name"] == "route_and_fill"
        assert "gap_fill" in data

    def test_result_to_markdown(self) -> None:
        mock_engine = MagicMock()
        mock_engine.fill_gaps.return_value = self._make_gap_result()

        with patch(
            "volta.analysis.gap_fill_engine.GapFillEngine",
            return_value=mock_engine,
        ):
            from volta.ops.workflow_runner import WorkflowRunner

            runner = WorkflowRunner()
            result = runner.run("route_and_fill", __file__)

        md = result.to_markdown()
        assert "route_and_fill" in md
        assert "SUCCESS" in md


class TestWorkflowList:
    """route_and_fill appears in workflow registry."""

    def test_route_and_fill_in_templates(self) -> None:
        from volta.ops.workflows import WORKFLOW_TEMPLATES

        assert "route_and_fill" in WORKFLOW_TEMPLATES
        assert WORKFLOW_TEMPLATES["route_and_fill"].file_types == [".kicad_pcb"]

    def test_list_workflows_includes_route_and_fill(self) -> None:
        from volta.ops.workflows import list_workflows

        names = [w["name"] for w in list_workflows()]
        assert "route_and_fill" in names
