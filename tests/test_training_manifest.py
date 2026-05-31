"""Tests for data versioning manifest (TRAIN-01).

Covers:
  - DataManifest.from_directory hashes all JSONL files
  - save/load round-trip preserves all fields
  - verify returns True for unchanged, False for modified/missing files
  - assign_splits records reproducible train/val/test assignments
  - MazeDataset.split(manifest=...) uses manifest for deterministic splits
  - Split reproducibility from saved manifest
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from kicad_agent.training.dataset import MazeDataset, MazeSample
from kicad_agent.training.manifest import DataManifest


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_sample(sample_id: int, seed: int = 42) -> MazeSample:
    """Create a minimal MazeSample for testing."""
    return MazeSample(
        sample_id=sample_id,
        seed=seed,
        board_width_mm=50.0,
        board_height_mm=50.0,
        grid_size_mm=5.0,
        obstacle_count=5,
        obstacle_positions=(),
        source_point=(2.5, 2.5),
        target_point=(47.5, 47.5),
        solution_path=((2.5, 2.5), (47.5, 47.5)),
        solution_length=2,
        difficulty="easy",
        board_hash=f"hash_{sample_id}",
    )


def _write_jsonl(path: Path, records: list[dict]) -> None:
    """Write records as JSONL."""
    with open(path, "w") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")


# ---------------------------------------------------------------------------
# DataManifest tests
# ---------------------------------------------------------------------------


class TestDataManifestFromDirectory:
    """DataManifest.from_directory hashes JSONL files."""

    def test_hashes_all_jsonl_files(self, tmp_path: Path) -> None:
        """from_directory finds and hashes all .jsonl files."""
        _write_jsonl(tmp_path / "train.jsonl", [{"a": 1}])
        _write_jsonl(tmp_path / "val.jsonl", [{"b": 2}])
        manifest = DataManifest.from_directory(tmp_path)
        assert len(manifest.files) == 2
        assert "train.jsonl" in manifest.files
        assert "val.jsonl" in manifest.files
        # SHA256 is 64 hex chars
        for h in manifest.files.values():
            assert len(h) == 64

    def test_ignores_non_jsonl(self, tmp_path: Path) -> None:
        """Non-JSONL files are ignored."""
        _write_jsonl(tmp_path / "data.jsonl", [{"x": 1}])
        (tmp_path / "readme.txt").write_text("ignore me")
        manifest = DataManifest.from_directory(tmp_path)
        assert len(manifest.files) == 1

    def test_empty_directory(self, tmp_path: Path) -> None:
        """Empty directory produces empty manifest."""
        manifest = DataManifest.from_directory(tmp_path)
        assert len(manifest.files) == 0

    def test_default_split_seed(self, tmp_path: Path) -> None:
        """Default split_seed is 42."""
        manifest = DataManifest.from_directory(tmp_path)
        assert manifest.split_seed == 42

    def test_custom_split_seed(self, tmp_path: Path) -> None:
        """Custom split_seed is honored."""
        manifest = DataManifest.from_directory(tmp_path, split_seed=99)
        assert manifest.split_seed == 99


class TestDataManifestRoundTrip:
    """save/load round-trip preserves all fields."""

    def test_round_trip(self, tmp_path: Path) -> None:
        """Manifest survives save/load cycle."""
        _write_jsonl(tmp_path / "data.jsonl", [{"a": 1}])
        original = DataManifest.from_directory(tmp_path, split_seed=7)
        assigned = original.assign_splits(10)

        save_path = tmp_path / "manifest.json"
        assigned.save(save_path)

        loaded = DataManifest.load(save_path)
        assert loaded.files == assigned.files
        assert loaded.split_seed == assigned.split_seed
        assert loaded.split_assignments == assigned.split_assignments
        assert loaded.created_at == assigned.created_at


class TestDataManifestVerify:
    """DataManifest.verify detects changes."""

    def test_verify_unchanged(self, tmp_path: Path) -> None:
        """verify returns True when files unchanged."""
        _write_jsonl(tmp_path / "a.jsonl", [{"x": 1}])
        _write_jsonl(tmp_path / "b.jsonl", [{"y": 2}])
        manifest = DataManifest.from_directory(tmp_path)
        assert manifest.verify(tmp_path) is True

    def test_verify_modified_file(self, tmp_path: Path) -> None:
        """verify returns False when a file is modified."""
        _write_jsonl(tmp_path / "a.jsonl", [{"x": 1}])
        manifest = DataManifest.from_directory(tmp_path)
        # Modify the file
        _write_jsonl(tmp_path / "a.jsonl", [{"x": 999}])
        assert manifest.verify(tmp_path) is False

    def test_verify_missing_file(self, tmp_path: Path) -> None:
        """verify returns False when a file is deleted."""
        _write_jsonl(tmp_path / "a.jsonl", [{"x": 1}])
        _write_jsonl(tmp_path / "b.jsonl", [{"y": 2}])
        manifest = DataManifest.from_directory(tmp_path)
        (tmp_path / "b.jsonl").unlink()
        assert manifest.verify(tmp_path) is False


class TestAssignSplits:
    """assign_splits produces reproducible assignments."""

    def test_all_samples_assigned(self, tmp_path: Path) -> None:
        """All sample IDs get a split label."""
        _write_jsonl(tmp_path / "data.jsonl", [{"x": 1}])
        manifest = DataManifest.from_directory(tmp_path)
        result = manifest.assign_splits(10)
        assert len(result.split_assignments) == 10
        for i in range(10):
            assert i in result.split_assignments
            assert result.split_assignments[i] in ("train", "val", "test")

    def test_split_counts_match_ratios(self, tmp_path: Path) -> None:
        """Split counts approximately match requested ratios."""
        _write_jsonl(tmp_path / "data.jsonl", [{"x": 1}])
        manifest = DataManifest.from_directory(tmp_path)
        result = manifest.assign_splits(100)
        from collections import Counter
        counts = Counter(result.split_assignments.values())
        # 80/10/10 with 100 samples -> 80 train, 10 val, 10 test
        assert counts["train"] == 80
        assert counts["val"] == 10
        assert counts["test"] == 10

    def test_reproducible_from_same_seed(self, tmp_path: Path) -> None:
        """Same split_seed produces identical assignments."""
        _write_jsonl(tmp_path / "data.jsonl", [{"x": 1}])
        m1 = DataManifest.from_directory(tmp_path, split_seed=42)
        m2 = DataManifest.from_directory(tmp_path, split_seed=42)
        r1 = m1.assign_splits(50)
        r2 = m2.assign_splits(50)
        assert r1.split_assignments == r2.split_assignments

    def test_different_seed_different_assignments(self, tmp_path: Path) -> None:
        """Different split_seed produces different assignments."""
        _write_jsonl(tmp_path / "data.jsonl", [{"x": 1}])
        m1 = DataManifest.from_directory(tmp_path, split_seed=42)
        m2 = DataManifest.from_directory(tmp_path, split_seed=99)
        r1 = m1.assign_splits(50)
        r2 = m2.assign_splits(50)
        assert r1.split_assignments != r2.split_assignments


class TestDatasetSplitWithManifest:
    """MazeDataset.split(manifest=...) integrates with DataManifest."""

    def test_split_with_manifest_seed(self, tmp_path: Path) -> None:
        """Manifest seed controls split determinism."""
        samples = [_make_sample(i, seed=42 + i) for i in range(20)]
        ds = MazeDataset(samples=samples)

        _write_jsonl(tmp_path / "data.jsonl", [{"x": 1}])
        manifest = DataManifest.from_directory(tmp_path, split_seed=7)
        train, val, test = ds.split(manifest=manifest)

        # Should split 20 samples: 16/2/2
        assert len(train) + len(val) + len(test) == 20

    def test_split_with_manifest_assignments(self, tmp_path: Path) -> None:
        """Manifest with pre-assigned splits is respected."""
        samples = [_make_sample(i, seed=42 + i) for i in range(20)]
        ds = MazeDataset(samples=samples)

        _write_jsonl(tmp_path / "data.jsonl", [{"x": 1}])
        manifest = DataManifest.from_directory(tmp_path, split_seed=42)
        manifest = manifest.assign_splits(20)

        train, val, test = ds.split(manifest=manifest)
        assert len(train) + len(val) + len(test) == 20

    def test_split_reproducibility(self, tmp_path: Path) -> None:
        """Same manifest produces identical splits on repeated calls."""
        samples = [_make_sample(i, seed=42 + i) for i in range(20)]
        ds = MazeDataset(samples=samples)

        _write_jsonl(tmp_path / "data.jsonl", [{"x": 1}])
        manifest = DataManifest.from_directory(tmp_path, split_seed=42)

        train1, val1, test1 = ds.split(manifest=manifest)
        train2, val2, test2 = ds.split(manifest=manifest)

        t1_ids = {s.sample_id for s in train1.samples}
        t2_ids = {s.sample_id for s in train2.samples}
        assert t1_ids == t2_ids

    def test_split_without_manifest_backwards_compatible(self) -> None:
        """split() without manifest works as before."""
        samples = [_make_sample(i) for i in range(10)]
        ds = MazeDataset(samples=samples)
        train, val, test = ds.split()
        assert len(train) + len(val) + len(test) == 10
