"""Tests for GapFillEngine (GAP-08 orchestrator)."""

import os
import shutil
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from volta.analysis.gap_analyzer import (
    BoardInfo,
    GapReport,
    IncompleteNet,
    RoutingStats,
    UnroutedNet,
)
from volta.analysis.gap_fill_engine import GapFillEngine, GapFillResult


@pytest.fixture
def temp_pcb(tmp_path):
    """Create a temporary copy of a real PCB fixture for testing."""
    fixtures = [
        Path("tests/fixtures/Arduino_Mega/Arduino_Mega.kicad_pcb"),
        Path("tests/fixtures/RaspberryPi-uHAT/RaspberryPi-uHAT.kicad_pcb"),
    ]
    for f in fixtures:
        if f.exists():
            dest = tmp_path / "test_board.kicad_pcb"
            shutil.copy2(f, dest)
            return dest
    pytest.skip("No PCB fixtures available")


@pytest.fixture
def mock_gap_report():
    """A GapReport with unrouted nets but no DRC violations."""
    return GapReport(
        board_info=BoardInfo(
            file_path="test.kicad_pcb",
            component_count=10,
            net_count=20,
            layer_count=2,
            bounds=(0.0, 0.0, 100.0, 80.0),
        ),
        routing_stats=RoutingStats(
            total_nets=20,
            routed_nets=15,
            unrouted_nets=3,
            incomplete_nets=2,
            route_percentage=75.0,
        ),
        unrouted_nets=(
            UnroutedNet("NET_A", 2, ((10.0, 20.0), (30.0, 20.0)), 5.0),
        ),
        incomplete_nets=(
            IncompleteNet("NET_D", ((10.0, 50.0),), ((60.0, 50.0),), 50.0),
        ),
        drc_violations=(),
        net_naming_issues=(),
    )


class TestGapFillResult:
    """Test GapFillResult serialization."""

    def test_to_json(self):
        result = GapFillResult(
            success=True,
            iterations=(),
            total_nets_completed=3,
            total_drc_fixed=1,
            total_nets_renamed=2,
            final_route_percentage=85.0,
            rollback_performed=False,
        )
        j = result.to_json()
        assert j["success"] is True
        assert j["total_nets_completed"] == 3
        assert j["final_route_percentage"] == 85.0
        assert j["rollback_performed"] is False

    def test_to_markdown(self):
        result = GapFillResult(
            success=True,
            iterations=(),
            total_nets_completed=2,
            total_drc_fixed=0,
            total_nets_renamed=1,
            final_route_percentage=90.0,
            rollback_performed=False,
        )
        md = result.to_markdown()
        assert "SUCCESS" in md
        assert "90.0%" in md
        assert "Nets completed:" in md
        assert ":** 2" in md

    def test_to_markdown_with_errors(self):
        result = GapFillResult(
            success=False,
            iterations=(),
            total_nets_completed=0,
            total_drc_fixed=0,
            total_nets_renamed=0,
            final_route_percentage=75.0,
            rollback_performed=True,
            errors=("File not found", "Permission denied"),
        )
        md = result.to_markdown()
        assert "FAILED" in md
        assert "Rollback:" in md
        assert "yes" in md
        assert "File not found" in md

    def test_frozen(self):
        result = GapFillResult(
            success=True,
            iterations=(),
            total_nets_completed=0,
            total_drc_fixed=0,
            total_nets_renamed=0,
            final_route_percentage=0.0,
            rollback_performed=False,
        )
        with pytest.raises(AttributeError):
            result.success = False  # type: ignore[misc]


class TestGapFillEngineInit:
    """Test engine initialization."""

    def test_default_params(self):
        engine = GapFillEngine()
        assert engine._max_iterations == 3
        assert engine._target_route_pct == 95.0
        assert engine._run_drc is True
        assert engine._use_ai is True

    def test_custom_params(self):
        engine = GapFillEngine(max_iterations=1, target_route_pct=50.0, run_drc=False, use_ai=False)
        assert engine._max_iterations == 1
        assert engine._target_route_pct == 50.0
        assert engine._run_drc is False
        assert engine._use_ai is False

    def test_max_iterations_clamped(self):
        engine = GapFillEngine(max_iterations=10)
        assert engine._max_iterations == 3

    def test_min_iterations_clamped(self):
        engine = GapFillEngine(max_iterations=0)
        assert engine._max_iterations == 1


class TestGapFillEngineFileNotFound:
    """Test engine with missing file."""

    def test_file_not_found(self):
        engine = GapFillEngine(use_ai=False)
        result = engine.fill_gaps("/nonexistent/board.kicad_pcb")
        assert result.success is False
        assert "File not found" in result.errors[0]
        assert result.iterations == ()


class TestGapFillEngineIteration:
    """Test iteration loop behavior with mocked analyzer."""

    def test_max_iterations_respected(self, temp_pcb, mock_gap_report):
        """Verify the loop never exceeds max_iterations."""
        with patch("volta.analysis.gap_fill_engine.GapAnalyzer") as MockAnalyzer, \
             patch("volta.ops.executor.OperationExecutor"):
            analyzer_instance = MockAnalyzer.return_value
            analyzer_instance.analyze.return_value = mock_gap_report

            engine = GapFillEngine(max_iterations=2, use_ai=False)
            result = engine.fill_gaps(str(temp_pcb))

        # Loop should stop after max_iterations or when no progress
        assert len(result.iterations) <= 2

    def test_convergence_detection(self, temp_pcb):
        """Verify early exit when target route % is reached."""
        converged_report = GapReport(
            board_info=BoardInfo("t.kicad_pcb", 10, 20, 2, None),
            routing_stats=RoutingStats(20, 20, 0, 0, 100.0),
            unrouted_nets=(),
            incomplete_nets=(),
            drc_violations=(),
            net_naming_issues=(),
        )

        with patch("volta.analysis.gap_fill_engine.GapAnalyzer") as MockAnalyzer, \
             patch("volta.ops.executor.OperationExecutor"):
            analyzer_instance = MockAnalyzer.return_value
            analyzer_instance.analyze.return_value = converged_report

            engine = GapFillEngine(max_iterations=3, target_route_pct=95.0, use_ai=False)
            result = engine.fill_gaps(str(temp_pcb))

        # Should exit immediately — no iterations needed
        assert len(result.iterations) == 0
        assert result.final_route_percentage == 100.0


class TestGapFillEngineSnapshot:
    """Test transaction safety (git-like file snapshot)."""

    def test_snapshot_created_and_cleaned(self, temp_pcb):
        """Verify backup file is created during execution and cleaned up after."""
        backup = Path(str(temp_pcb) + ".gapfill-backup")

        converged_report = GapReport(
            board_info=BoardInfo("t.kicad_pcb", 10, 20, 2, None),
            routing_stats=RoutingStats(20, 20, 0, 0, 100.0),
            unrouted_nets=(),
            incomplete_nets=(),
            drc_violations=(),
            net_naming_issues=(),
        )

        with patch("volta.analysis.gap_fill_engine.GapAnalyzer") as MockAnalyzer:
            analyzer_instance = MockAnalyzer.return_value
            analyzer_instance.analyze.return_value = converged_report

            engine = GapFillEngine(max_iterations=1, use_ai=False)
            result = engine.fill_gaps(str(temp_pcb))

        # Backup should be cleaned up
        assert not backup.exists()
        # Original should still exist
        assert temp_pcb.exists()

    def test_rollback_on_catastrophic_failure(self, temp_pcb):
        """Verify file is restored on catastrophic failure."""
        original_content = temp_pcb.read_text()

        progress_report = GapReport(
            board_info=BoardInfo("t.kicad_pcb", 10, 20, 2, None),
            routing_stats=RoutingStats(20, 15, 3, 2, 75.0),
            unrouted_nets=(
                UnroutedNet("NET_A", 2, ((10.0, 20.0), (30.0, 20.0)), 5.0),
            ),
            incomplete_nets=(),
            drc_violations=(),
            net_naming_issues=(),
        )

        with patch("volta.analysis.gap_fill_engine.GapAnalyzer") as MockAnalyzer, \
             patch("volta.ops.executor.OperationExecutor"):
            # First call succeeds, second raises, third (finally) succeeds
            analyzer_instance = MockAnalyzer.return_value
            analyzer_instance.analyze.side_effect = [
                progress_report,
                RuntimeError("Catastrophic failure"),
                progress_report,  # final report in finally block
            ]

            engine = GapFillEngine(max_iterations=1, use_ai=False)
            result = engine.fill_gaps(str(temp_pcb))

        assert result.rollback_performed is True
        # File should be restored to original content
        restored_content = temp_pcb.read_text()
        assert restored_content == original_content
