"""Tests for real-world training data integration in training pipeline.

Task 2 Part C of plan 79-05: TrainingPipelineConfig accepts real_data_dir,
loads RealBoardDataset from train.jsonl, and mixes with synthetic data.
"""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


def _make_jsonl_sample(sample_id: int, difficulty: str = "medium") -> dict:
    """Create a minimal RealBoardSample dict for JSONL serialization."""
    return {
        "sample_id": sample_id,
        "repo_url": "https://github.com/test/board",
        "repo_name": f"test/board-{sample_id}",
        "schematic_path": f"board-{sample_id}.kicad_sch",
        "pcb_path": f"board-{sample_id}.kicad_pcb",
        "component_count": 10,
        "net_count": 5,
        "layer_count": 4,
        "board_width_mm": 50.0,
        "board_height_mm": 50.0,
        "difficulty": difficulty,
        "board_hash": f"hash-{sample_id}" * 8,
        "graph_json": '{"nodes": [], "edges": []}',
        "spatial_summary_json": '{"component_density": 0.5}',
        "source_format": "kicad_pcb",
    }


# ---------------------------------------------------------------------------
# Test 7: TrainingPipelineConfig accepts real_data_dir parameter
# ---------------------------------------------------------------------------


def test_config_accepts_real_data_dir() -> None:
    """TrainingPipelineConfig accepts real_data_dir parameter."""
    from kicad_agent.training.pipeline import TrainingPipelineConfig

    config = TrainingPipelineConfig(real_data_dir="/path/to/real/data")
    assert config.real_data_dir == "/path/to/real/data"


def test_config_real_data_dir_default_none() -> None:
    """TrainingPipelineConfig.real_data_dir defaults to None."""
    from kicad_agent.training.pipeline import TrainingPipelineConfig

    config = TrainingPipelineConfig()
    assert config.real_data_dir is None


# ---------------------------------------------------------------------------
# Test 8: run_pipeline with real_data_dir loads RealBoardDataset from train.jsonl
# ---------------------------------------------------------------------------


def test_pipeline_loads_real_data(tmp_path: Path) -> None:
    """run_pipeline with real_data_dir loads RealBoardDataset from train.jsonl."""
    from kicad_agent.training.pipeline import TrainingPipelineConfig, run_pipeline

    # Create a real data directory with train.jsonl
    real_dir = tmp_path / "real_data"
    real_dir.mkdir()
    train_jsonl = real_dir / "train.jsonl"
    with open(train_jsonl, "w") as f:
        for i in range(5):
            f.write(json.dumps(_make_jsonl_sample(i)) + "\n")

    config = TrainingPipelineConfig(
        n_samples=10,
        seed=42,
        output_dir=str(tmp_path / "output"),
        real_data_dir=str(real_dir),
    )

    report = run_pipeline(config)

    # Report should contain real-world sample count
    assert "real_world" in report["steps"] or "real_samples" in report.get("config", {}), \
        f"Expected real-world tracking in report: {report}"
    real_count = report["steps"].get("real_world", {}).get("n_loaded", 0)
    assert real_count == 5, f"Expected 5 real samples, got {real_count}"


# ---------------------------------------------------------------------------
# Test 9: run_pipeline without real_data_dir works unchanged (synthetic only)
# ---------------------------------------------------------------------------


def test_pipeline_without_real_data(tmp_path: Path) -> None:
    """run_pipeline without real_data_dir works unchanged (synthetic only)."""
    from kicad_agent.training.pipeline import TrainingPipelineConfig, run_pipeline

    config = TrainingPipelineConfig(
        n_samples=10,
        seed=42,
        output_dir=str(tmp_path / "output"),
    )

    report = run_pipeline(config)

    # Should have standard pipeline steps
    assert "dataset" in report["steps"]
    assert "split" in report["steps"]
    assert "chains" in report["steps"]
    # No real-world data
    real_count = report["steps"].get("real_world", {}).get("n_loaded", 0)
    assert real_count == 0


# ---------------------------------------------------------------------------
# Test 10: Mixed pipeline combines synthetic and real samples
# ---------------------------------------------------------------------------


def test_mixed_pipeline_tracks_counts(tmp_path: Path) -> None:
    """Mixed pipeline tracks synthetic vs real sample counts in report."""
    from kicad_agent.training.pipeline import TrainingPipelineConfig, run_pipeline

    real_dir = tmp_path / "real_data"
    real_dir.mkdir()
    train_jsonl = real_dir / "train.jsonl"
    with open(train_jsonl, "w") as f:
        for i in range(3):
            f.write(json.dumps(_make_jsonl_sample(i)) + "\n")

    config = TrainingPipelineConfig(
        n_samples=10,
        seed=42,
        output_dir=str(tmp_path / "output"),
        real_data_dir=str(real_dir),
    )

    report = run_pipeline(config)

    # Should track both synthetic and real counts
    real_info = report["steps"]["real_world"]
    assert real_info["n_loaded"] == 3
    # Synthetic count should be the generated dataset count
    synth_count = report["steps"]["dataset"]["n_generated"]
    assert synth_count == 10
    # Total should be sum
    assert report["steps"]["real_world"]["n_synthetic"] == synth_count


# ---------------------------------------------------------------------------
# Test 11: Real-world sample counts tracked in pipeline metadata
# ---------------------------------------------------------------------------


def test_real_world_counts_in_metadata(tmp_path: Path) -> None:
    """Real-world sample counts are tracked in pipeline config metadata."""
    from kicad_agent.training.pipeline import TrainingPipelineConfig, run_pipeline

    real_dir = tmp_path / "real_data"
    real_dir.mkdir()
    train_jsonl = real_dir / "train.jsonl"
    with open(train_jsonl, "w") as f:
        for i in range(2):
            f.write(json.dumps(_make_jsonl_sample(i, difficulty="hard")) + "\n")

    config = TrainingPipelineConfig(
        n_samples=5,
        seed=42,
        output_dir=str(tmp_path / "output"),
        real_data_dir=str(real_dir),
    )

    report = run_pipeline(config)

    # Config section should include real_data_dir
    assert report["config"]["real_data_dir"] == str(real_dir)
    # Real-world step should have difficulty breakdown
    real_info = report["steps"]["real_world"]
    assert "difficulty_counts" in real_info
    assert real_info["difficulty_counts"].get("hard", 0) == 2


# ---------------------------------------------------------------------------
# Test 12: Missing train.jsonl logs warning, continues with synthetic
# ---------------------------------------------------------------------------


def test_missing_train_jsonl_continues_synthetic(tmp_path: Path) -> None:
    """Missing train.jsonl in real_data_dir logs warning and continues."""
    from kicad_agent.training.pipeline import TrainingPipelineConfig, run_pipeline

    real_dir = tmp_path / "real_data"
    real_dir.mkdir()
    # No train.jsonl created

    config = TrainingPipelineConfig(
        n_samples=5,
        seed=42,
        output_dir=str(tmp_path / "output"),
        real_data_dir=str(real_dir),
    )

    report = run_pipeline(config)

    # Should still complete with synthetic data
    assert "dataset" in report["steps"]
    real_info = report["steps"]["real_world"]
    assert real_info["n_loaded"] == 0
