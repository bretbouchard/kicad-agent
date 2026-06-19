"""Tests for the AdapterRegistry module (versioned adapter metadata)."""

from __future__ import annotations

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pytest

from kicad_agent.training.adapter_registry import (
    AdapterMetadata,
    AdapterRegistry,
    DatasetInfo,
)


class TestDatasetInfo:
    """Tests for the DatasetInfo Pydantic model."""

    def test_dataset_info_creation(self) -> None:
        info = DatasetInfo(
            maze_samples=135946,
            pcb_samples=6696,
            total_samples=142642,
        )
        assert info.maze_samples == 135946
        assert info.pcb_samples == 6696
        assert info.total_samples == 142642

    def test_dataset_info_defaults(self) -> None:
        info = DatasetInfo(
            maze_samples=100,
            pcb_samples=50,
            total_samples=150,
        )
        assert info.maze_chains_file == "training_output/chains_100k.jsonl"
        assert info.maze_samples_file == "training_output/maze_samples_100k.jsonl"
        assert info.pcb_vision_dir == "training_output/vision_data/train/"

    def test_dataset_info_is_frozen(self) -> None:
        info = DatasetInfo(
            maze_samples=100,
            pcb_samples=50,
            total_samples=150,
        )
        with pytest.raises(Exception):
            info.maze_samples = 200  # type: ignore[misc]

    def test_dataset_info_serialization(self) -> None:
        info = DatasetInfo(
            maze_samples=135946,
            pcb_samples=6696,
            total_samples=142642,
        )
        d = info.model_dump()
        assert d["maze_samples"] == 135946
        assert d["pcb_samples"] == 6696
        assert d["total_samples"] == 142642


class TestAdapterMetadata:
    """Tests for the AdapterMetadata Pydantic model."""

    def _make_dataset_info(self) -> DatasetInfo:
        return DatasetInfo(
            maze_samples=135946,
            pcb_samples=6696,
            total_samples=142642,
        )

    def test_metadata_creation_with_defaults(self) -> None:
        meta = AdapterMetadata(
            version="v1",
            created="2026-06-19T00:00:00Z",
            dataset=self._make_dataset_info(),
        )
        assert meta.version == "v1"
        assert meta.base_model == "google/gemma-4-12b-it"
        assert meta.training_platform == "vast.ai RTX 3090"
        assert meta.training_steps == 400
        assert meta.training_loss is None
        assert meta.lora_rank == 16
        assert meta.lora_alpha == 32
        assert meta.learning_rate == 1e-5
        assert meta.verified_mlx is False
        assert meta.notes == ""
        assert meta.vast_instance_id is None
        assert meta.training_started is None
        assert meta.training_completed is None
        assert meta.git_commit is None
        assert meta.actual_cost_usd is None

    def test_metadata_provenance_fields(self) -> None:
        meta = AdapterMetadata(
            version="v1",
            created="2026-06-19T00:00:00Z",
            dataset=self._make_dataset_info(),
            vast_instance_id="i-12345",
            training_started="2026-06-19T01:00:00Z",
            training_completed="2026-06-19T02:00:00Z",
            git_commit="abc1234",
            actual_cost_usd=3.50,
        )
        assert meta.vast_instance_id == "i-12345"
        assert meta.training_started == "2026-06-19T01:00:00Z"
        assert meta.training_completed == "2026-06-19T02:00:00Z"
        assert meta.git_commit == "abc1234"
        assert meta.actual_cost_usd == 3.50

    def test_metadata_extra_forbid(self) -> None:
        with pytest.raises(Exception):
            AdapterMetadata(
                version="v1",
                created="2026-06-19T00:00:00Z",
                dataset=self._make_dataset_info(),
                unknown_field="bad",  # type: ignore[arg-type]
            )

    def test_metadata_serialization_roundtrip(self) -> None:
        meta = AdapterMetadata(
            version="v1",
            created="2026-06-19T00:00:00Z",
            training_steps=400,
            training_loss=2.1,
            dataset=self._make_dataset_info(),
            vast_instance_id="i-abc",
            git_commit="def456",
            actual_cost_usd=4.20,
        )
        json_str = meta.model_dump_json()
        parsed = json.loads(json_str)
        assert parsed["version"] == "v1"
        assert parsed["training_steps"] == 400
        assert parsed["training_loss"] == 2.1
        assert parsed["dataset"]["maze_samples"] == 135946
        assert parsed["vast_instance_id"] == "i-abc"
        assert parsed["git_commit"] == "def456"
        assert parsed["actual_cost_usd"] == 4.20

        # Roundtrip
        restored = AdapterMetadata.model_validate_json(json_str)
        assert restored.version == meta.version
        assert restored.dataset.total_samples == meta.dataset.total_samples


class TestAdapterRegistry:
    """Tests for the AdapterRegistry class."""

    def _make_sample_metadata(self, version: str = "v1") -> AdapterMetadata:
        return AdapterMetadata(
            version=version,
            created=datetime.now(timezone.utc).isoformat(),
            dataset=DatasetInfo(
                maze_samples=100,
                pcb_samples=50,
                total_samples=150,
            ),
        )

    def test_write_metadata_creates_json(self, tmp_path: Path) -> None:
        registry = AdapterRegistry(base_dir=tmp_path / "adapters")
        meta = self._make_sample_metadata()

        result = registry.write_metadata("test-adapter", meta)

        assert result.exists()
        data = json.loads(result.read_text())
        assert data["version"] == "v1"
        assert data["base_model"] == "google/gemma-4-12b-it"
        assert data["dataset"]["total_samples"] == 150

    def test_metadata_contains_all_required_fields(self, tmp_path: Path) -> None:
        registry = AdapterRegistry(base_dir=tmp_path / "adapters")
        meta = self._make_sample_metadata()

        registry.write_metadata("test-adapter", meta)

        meta_path = tmp_path / "adapters" / "test-adapter" / "training_metadata.json"
        data = json.loads(meta_path.read_text())

        required_fields = [
            "version", "base_model", "created", "training_platform",
            "training_steps", "training_loss", "lora_rank", "lora_alpha",
            "learning_rate", "dataset", "verified_mlx",
        ]
        for field in required_fields:
            assert field in data, f"Missing required field: {field}"

    def test_version_auto_increments_on_conflict(self, tmp_path: Path) -> None:
        registry = AdapterRegistry(base_dir=tmp_path / "adapters")
        meta_v1 = self._make_sample_metadata(version="v1")

        # First write
        registry.write_metadata("test-adapter", meta_v1)

        # Second write should auto-increment to v2
        meta_v2 = self._make_sample_metadata(version="v1")
        result = registry.write_metadata("test-adapter", meta_v2)

        data = json.loads(result.read_text())
        assert data["version"] == "v2"

    def test_version_increments_v2_to_v3(self, tmp_path: Path) -> None:
        registry = AdapterRegistry(base_dir=tmp_path / "adapters")

        # Write v1
        registry.write_metadata("test-adapter", self._make_sample_metadata(version="v1"))
        # Auto-increments to v2
        registry.write_metadata("test-adapter", self._make_sample_metadata(version="v1"))
        # Auto-increments to v3
        registry.write_metadata("test-adapter", self._make_sample_metadata(version="v1"))

        meta_path = tmp_path / "adapters" / "test-adapter" / "training_metadata.json"
        data = json.loads(meta_path.read_text())
        assert data["version"] == "v3"

    def test_write_does_not_overwrite_without_force(self, tmp_path: Path) -> None:
        registry = AdapterRegistry(base_dir=tmp_path / "adapters")
        meta_v1 = self._make_sample_metadata(version="v1")

        registry.write_metadata("test-adapter", meta_v1)

        # Write again with version="v1" and force=False (default) -- should increment
        meta_new = self._make_sample_metadata(version="v1")
        result = registry.write_metadata("test-adapter", meta_new)

        data = json.loads(result.read_text())
        # Version should NOT be v1 (the original), it should be v2
        assert data["version"] == "v2"

    def test_write_with_force_overwrites(self, tmp_path: Path) -> None:
        registry = AdapterRegistry(base_dir=tmp_path / "adapters")
        meta_v1 = self._make_sample_metadata(version="v1")

        registry.write_metadata("test-adapter", meta_v1)

        # Write with force=True -- keeps version as-is
        meta_v1_forced = self._make_sample_metadata(version="v1")
        meta_v1_forced = meta_v1_forced.model_copy(update={"training_steps": 999})
        result = registry.write_metadata("test-adapter", meta_v1_forced, force=True)

        data = json.loads(result.read_text())
        assert data["version"] == "v1"
        assert data["training_steps"] == 999

    def test_metadata_is_valid_json(self, tmp_path: Path) -> None:
        registry = AdapterRegistry(base_dir=tmp_path / "adapters")
        meta = self._make_sample_metadata()

        registry.write_metadata("test-adapter", meta)

        meta_path = tmp_path / "adapters" / "test-adapter" / "training_metadata.json"
        # json.loads should not raise
        data = json.loads(meta_path.read_text())
        assert isinstance(data, dict)

    def test_dataset_subobject_fields(self, tmp_path: Path) -> None:
        registry = AdapterRegistry(base_dir=tmp_path / "adapters")
        meta = self._make_sample_metadata()

        registry.write_metadata("test-adapter", meta)

        meta_path = tmp_path / "adapters" / "test-adapter" / "training_metadata.json"
        data = json.loads(meta_path.read_text())
        dataset = data["dataset"]
        assert "maze_samples" in dataset
        assert "pcb_samples" in dataset
        assert "total_samples" in dataset

    def test_read_metadata_returns_none_when_not_found(self, tmp_path: Path) -> None:
        registry = AdapterRegistry(base_dir=tmp_path / "adapters")
        result = registry.read_metadata("nonexistent")
        assert result is None

    def test_read_metadata_returns_parsed_metadata(self, tmp_path: Path) -> None:
        registry = AdapterRegistry(base_dir=tmp_path / "adapters")
        meta = self._make_sample_metadata()

        registry.write_metadata("test-adapter", meta)
        result = registry.read_metadata("test-adapter")

        assert result is not None
        assert result.version == "v1"
        assert result.dataset.total_samples == 150

    def test_read_after_version_increment(self, tmp_path: Path) -> None:
        registry = AdapterRegistry(base_dir=tmp_path / "adapters")
        registry.write_metadata("test-adapter", self._make_sample_metadata(version="v1"))
        registry.write_metadata("test-adapter", self._make_sample_metadata(version="v1"))

        result = registry.read_metadata("test-adapter")
        assert result is not None
        assert result.version == "v2"

    def test_create_dataset_symlinks(self, tmp_path: Path) -> None:
        registry = AdapterRegistry(base_dir=tmp_path / "adapters")

        # Create a fake source dataset
        source_dir = tmp_path / "training_output" / "unified"
        source_dir.mkdir(parents=True)
        (source_dir / "data.txt").write_text("test")

        link_path = registry.create_dataset_symlinks(source_dir, "unified_train")

        assert link_path.is_symlink()
        assert link_path.resolve() == source_dir.resolve()
        # Verify symlink target is readable
        assert (link_path / "data.txt").read_text() == "test"

    def test_create_dataset_symlinks_replaces_existing(self, tmp_path: Path) -> None:
        registry = AdapterRegistry(base_dir=tmp_path / "adapters")

        source1 = tmp_path / "dataset1"
        source1.mkdir()
        (source1 / "a.txt").write_text("dataset1")

        source2 = tmp_path / "dataset2"
        source2.mkdir()
        (source2 / "b.txt").write_text("dataset2")

        link1 = registry.create_dataset_symlinks(source1, "my_data")
        assert (link1 / "a.txt").read_text() == "dataset1"

        # Replace symlink with new target
        link2 = registry.create_dataset_symlinks(source2, "my_data")
        assert link2 == link1  # Same path
        assert (link2 / "b.txt").read_text() == "dataset2"

    def test_write_creates_adapter_directory(self, tmp_path: Path) -> None:
        registry = AdapterRegistry(base_dir=tmp_path / "adapters")
        meta = self._make_sample_metadata()

        registry.write_metadata("new-adapter", meta)

        adapter_dir = tmp_path / "adapters" / "new-adapter"
        assert adapter_dir.is_dir()
        assert (adapter_dir / "training_metadata.json").exists()

    def test_non_numeric_version_increment(self, tmp_path: Path) -> None:
        """Test that non-numeric version strings get _1 appended."""
        registry = AdapterRegistry(base_dir=tmp_path / "adapters")
        meta_initial = AdapterMetadata(
            version="initial",
            created="2026-06-19T00:00:00Z",
            dataset=DatasetInfo(
                maze_samples=10,
                pcb_samples=5,
                total_samples=15,
            ),
        )
        registry.write_metadata("test-adapter", meta_initial)

        # Try to overwrite with same non-numeric version
        meta_again = AdapterMetadata(
            version="initial",
            created="2026-06-19T00:00:00Z",
            dataset=DatasetInfo(
                maze_samples=10,
                pcb_samples=5,
                total_samples=15,
            ),
        )
        registry.write_metadata("test-adapter", meta_again)

        result = registry.read_metadata("test-adapter")
        assert result is not None
        assert result.version == "initial_1"
