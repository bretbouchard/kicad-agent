"""Tests for training output cleanup utility (TRAIN-04).

Covers:
  - Cleanup preserves latest N runs per type prefix
  - Dry-run mode reports files without deleting
  - Report consolidation merges eval_report.json files
  - Empty directory does nothing
  - Configurable keep value
"""

from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from kicad_agent.training.cleanup import CleanupConfig, TrainingCleanup


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _create_mock_run(
    base_dir: Path,
    name: str,
    has_eval_report: bool = True,
    has_adapter: bool = False,
) -> Path:
    """Create a mock training run directory."""
    run_dir = base_dir / name
    run_dir.mkdir(parents=True, exist_ok=True)
    if has_eval_report:
        report = {
            "run": name,
            "config": {"seed": 42},
            "steps": {"baseline": {"avg_reward": 0.5}},
        }
        with open(run_dir / "eval_report.json", "w") as f:
            json.dump(report, f)
    if has_adapter:
        (run_dir / "adapters.safetensors").write_bytes(b"mock")
    return run_dir


def _create_runs(base_dir: Path, prefix: str, count: int) -> list[Path]:
    """Create sequential mock runs with a given prefix."""
    paths = []
    for i in range(count):
        path = _create_mock_run(base_dir, f"{prefix}_v{i}")
        paths.append(path)
    return paths


# ---------------------------------------------------------------------------
# TrainingCleanup tests
# ---------------------------------------------------------------------------


class TestCleanupPreservation:
    """Cleanup preserves latest N runs per type."""

    def test_preserves_recent(self, tmp_path: Path) -> None:
        """Cleanup keeps latest 3 runs, removes older ones."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        runs = _create_runs(output_dir, "grpo", 5)

        config = CleanupConfig(output_dir=output_dir, keep=3, dry_run=False)
        cleanup = TrainingCleanup(config)
        result = cleanup.run()

        # Should delete 2, keep 3
        assert len(result["deleted"]) == 2
        assert len(result["kept"]) == 3

        # Latest 3 directories should still exist
        for run in runs[2:]:
            assert run.exists()

        # Oldest 2 should be gone
        for run in runs[:2]:
            assert not run.exists()

    def test_keep_configurable(self, tmp_path: Path) -> None:
        """Cleanup respects configurable --keep value."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        runs = _create_runs(output_dir, "sft", 5)

        config = CleanupConfig(output_dir=output_dir, keep=1, dry_run=False)
        cleanup = TrainingCleanup(config)
        result = cleanup.run()

        assert len(result["kept"]) == 1
        assert len(result["deleted"]) == 4

        # Only the last one should survive
        for run in runs[:-1]:
            assert not run.exists()
        assert runs[-1].exists()

    def test_preserves_by_type_prefix(self, tmp_path: Path) -> None:
        """Cleanup groups runs by type prefix and keeps N per group."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        grpo_runs = _create_runs(output_dir, "grpo", 4)
        sft_runs = _create_runs(output_dir, "sft", 4)

        config = CleanupConfig(output_dir=output_dir, keep=2, dry_run=False)
        cleanup = TrainingCleanup(config)
        result = cleanup.run()

        # Should delete 2 grpo + 2 sft = 4 total
        assert len(result["deleted"]) == 4
        assert len(result["kept"]) == 4

        # Latest 2 of each should survive
        for run in grpo_runs[2:]:
            assert run.exists()
        for run in sft_runs[2:]:
            assert run.exists()


class TestDryRun:
    """Dry-run mode reports without deleting."""

    def test_dry_run_no_deletion(self, tmp_path: Path) -> None:
        """Dry-run reports files but does not delete."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        runs = _create_runs(output_dir, "grpo", 5)

        config = CleanupConfig(output_dir=output_dir, keep=3, dry_run=True)
        cleanup = TrainingCleanup(config)
        result = cleanup.run()

        # Should report 2 for deletion
        assert len(result["would_delete"]) == 2

        # But nothing should actually be deleted
        for run in runs:
            assert run.exists()


class TestReportConsolidation:
    """Report consolidation merges eval_report.json files."""

    def test_consolidate_reports(self, tmp_path: Path) -> None:
        """Cleanup consolidates eval_report.json into single file."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        _create_runs(output_dir, "grpo", 3)

        config = CleanupConfig(
            output_dir=output_dir, keep=3, dry_run=False, consolidate_reports=True
        )
        cleanup = TrainingCleanup(config)
        cleanup.run()

        consolidated = output_dir / "consolidated_report.json"
        assert consolidated.exists()

        data = json.loads(consolidated.read_text())
        assert "runs" in data
        assert len(data["runs"]) == 3

    def test_no_consolidate_when_disabled(self, tmp_path: Path) -> None:
        """No consolidation when consolidate_reports=False."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        _create_runs(output_dir, "grpo", 3)

        config = CleanupConfig(
            output_dir=output_dir, keep=3, dry_run=False, consolidate_reports=False
        )
        cleanup = TrainingCleanup(config)
        cleanup.run()

        consolidated = output_dir / "consolidated_report.json"
        assert not consolidated.exists()


class TestEdgeCases:
    """Edge cases for cleanup."""

    def test_empty_directory(self, tmp_path: Path) -> None:
        """Empty output directory produces empty result."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()

        config = CleanupConfig(output_dir=output_dir, keep=3)
        cleanup = TrainingCleanup(config)
        result = cleanup.run()

        assert result["deleted"] == []
        assert result["kept"] == []

    def test_fewer_than_keep(self, tmp_path: Path) -> None:
        """Fewer runs than keep value: nothing deleted."""
        output_dir = tmp_path / "output"
        output_dir.mkdir()
        _create_runs(output_dir, "grpo", 2)

        config = CleanupConfig(output_dir=output_dir, keep=5, dry_run=False)
        cleanup = TrainingCleanup(config)
        result = cleanup.run()

        assert len(result["deleted"]) == 0
        assert len(result["kept"]) == 2
