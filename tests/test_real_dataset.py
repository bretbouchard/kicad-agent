"""Tests for real_dataset module: RealBoardSample, RealBoardDataset, dedup, quality filter, pipeline."""

import json
import logging
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from kicad_agent.crawler.file_fetcher import FileFetcher
from kicad_agent.crawler.github_discovery import GithubDiscovery, KicadFilePair
from kicad_agent.training.graph_builder import BoardGraphResult
from kicad_agent.training.real_dataset import (
    MIN_COMPONENTS,
    MIN_NETS,
    RealBoardDataset,
    RealBoardSample,
    _dict_to_sample,
    _sample_to_dict,
    dedup_by_hash,
    filter_quality,
    is_valid_sample,
    run_pipeline,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_sample(
    sample_id: int = 0,
    component_count: int = 10,
    net_count: int = 5,
    board_hash: str = "abc123",
) -> RealBoardSample:
    """Create a RealBoardSample with sensible defaults for testing."""
    return RealBoardSample(
        sample_id=sample_id,
        repo_url="https://github.com/test/repo",
        repo_name="test/repo",
        schematic_path="board.kicad_sch",
        pcb_path="board.kicad_pcb",
        component_count=component_count,
        net_count=net_count,
        layer_count=2,
        board_width_mm=50.0,
        board_height_mm=50.0,
        difficulty="medium",
        board_hash=board_hash,
        graph_json='{"nodes":[],"links":[]}',
        spatial_summary_json='{"points":0,"boxes":0}',
    )


# ---------------------------------------------------------------------------
# TestRealBoardSample
# ---------------------------------------------------------------------------


class TestRealBoardSample:
    def test_frozen_dataclass_immutable(self):
        sample = _make_sample()
        with pytest.raises(FrozenInstanceError):
            sample.component_count = 99  # type: ignore[misc]

    def test_all_fields_are_serializable(self):
        sample = _make_sample()
        d = _sample_to_dict(sample)
        # Verify all values are JSON-safe primitive types
        for key, value in d.items():
            assert isinstance(value, (str, int, float)), (
                f"Field {key} has non-primitive type {type(value)}"
            )
        # Verify round-trip through JSON
        json_str = json.dumps(d)
        parsed = json.loads(json_str)
        assert parsed == d


# ---------------------------------------------------------------------------
# TestRealBoardDatasetJSONL
# ---------------------------------------------------------------------------


class TestRealBoardDatasetJSONL:
    def test_to_jsonl_writes_one_line_per_sample(self, tmp_path: Path):
        samples = [_make_sample(sample_id=i) for i in range(3)]
        dataset = RealBoardDataset(samples=samples)
        out_path = tmp_path / "test.jsonl"
        count = dataset.to_jsonl(out_path)
        assert count == 3
        lines = out_path.read_text().strip().split("\n")
        assert len(lines) == 3

    def test_from_jsonl_roundtrip(self, tmp_path: Path):
        samples = [_make_sample(sample_id=i, board_hash=f"hash_{i}") for i in range(5)]
        original = RealBoardDataset(samples=samples)
        out_path = tmp_path / "roundtrip.jsonl"
        original.to_jsonl(out_path)

        loaded = RealBoardDataset.from_jsonl(out_path)
        assert len(loaded) == len(original)
        for orig, loaded_s in zip(original.samples, loaded.samples):
            assert orig == loaded_s

    def test_from_jsonl_handles_empty_lines(self, tmp_path: Path):
        samples = [_make_sample(sample_id=i) for i in range(3)]
        dataset = RealBoardDataset(samples=samples)
        out_path = tmp_path / "with_blanks.jsonl"

        # Write JSONL with blank lines between entries
        with open(out_path, "w") as f:
            for s in samples:
                f.write(json.dumps(_sample_to_dict(s)) + "\n")
                f.write("\n")  # blank line

        loaded = RealBoardDataset.from_jsonl(out_path)
        assert len(loaded) == 3

    def test_to_jsonl_creates_parent_dirs(self, tmp_path: Path):
        dataset = RealBoardDataset(samples=[_make_sample()])
        nested_path = tmp_path / "deep" / "nested" / "dir" / "out.jsonl"
        count = dataset.to_jsonl(nested_path)
        assert count == 1
        assert nested_path.exists()


# ---------------------------------------------------------------------------
# TestRealBoardDatasetSplit
# ---------------------------------------------------------------------------


class TestRealBoardDatasetSplit:
    def test_split_produces_three_datasets(self):
        samples = [_make_sample(sample_id=i) for i in range(100)]
        dataset = RealBoardDataset(samples=samples)
        train, val, test = dataset.split()
        assert len(train) == 80
        assert len(val) == 10
        assert len(test) == 10

    def test_split_is_deterministic(self):
        samples = [_make_sample(sample_id=i) for i in range(50)]
        dataset = RealBoardDataset(samples=samples)
        train1, val1, test1 = dataset.split()
        train2, val2, test2 = dataset.split()
        assert [s.sample_id for s in train1.samples] == [s.sample_id for s in train2.samples]
        assert [s.sample_id for s in val1.samples] == [s.sample_id for s in val2.samples]
        assert [s.sample_id for s in test1.samples] == [s.sample_id for s in test2.samples]

    def test_split_raises_on_invalid_fractions(self):
        samples = [_make_sample(sample_id=i) for i in range(10)]
        dataset = RealBoardDataset(samples=samples)
        with pytest.raises(ValueError, match="sum to 1.0"):
            dataset.split(train=0.5, val=0.3, test=0.3)

    def test_split_handles_small_dataset(self):
        samples = [_make_sample(sample_id=i) for i in range(5)]
        dataset = RealBoardDataset(samples=samples)
        train, val, test = dataset.split()
        # 5 * 0.8 = 4, 5 * 0.1 = 0, so train=4, val=0, test=1
        assert len(train) + len(val) + len(test) == 5
        # No empty splits in total
        total = len(train) + len(val) + len(test)
        assert total == 5


# ---------------------------------------------------------------------------
# TestDeduplication
# ---------------------------------------------------------------------------


class TestDeduplication:
    def test_dedup_by_hash_removes_duplicates(self):
        samples = [
            _make_sample(sample_id=0, board_hash="hash_a"),
            _make_sample(sample_id=1, board_hash="hash_b"),
            _make_sample(sample_id=2, board_hash="hash_a"),  # duplicate of 0
            _make_sample(sample_id=3, board_hash="hash_c"),
            _make_sample(sample_id=4, board_hash="hash_b"),  # duplicate of 1
        ]
        result = dedup_by_hash(samples)
        assert len(result) == 3

    def test_dedup_keeps_first_occurrence(self):
        samples = [
            _make_sample(sample_id=0, board_hash="hash_a"),
            _make_sample(sample_id=5, board_hash="hash_a"),
        ]
        result = dedup_by_hash(samples)
        assert len(result) == 1
        assert result[0].sample_id == 0  # first occurrence kept

    def test_dedup_on_empty_list(self):
        result = dedup_by_hash([])
        assert result == []


# ---------------------------------------------------------------------------
# TestQualityFilter
# ---------------------------------------------------------------------------


class TestQualityFilter:
    def test_filter_removes_trivial_boards(self):
        sample = _make_sample(component_count=1, net_count=1)
        assert not is_valid_sample(sample)

    def test_filter_keeps_valid_boards(self):
        sample = _make_sample(component_count=10, net_count=5)
        assert is_valid_sample(sample)

    def test_filter_at_boundary(self):
        # Exactly at minimum thresholds -> should pass (inclusive)
        sample = _make_sample(component_count=MIN_COMPONENTS, net_count=MIN_NETS)
        assert is_valid_sample(sample)

    def test_filter_logs_count_removed(self, caplog):
        samples = [
            _make_sample(component_count=10, net_count=5),  # valid
            _make_sample(component_count=1, net_count=1),  # trivial
            _make_sample(component_count=10, net_count=5),  # valid
        ]
        with caplog.at_level(logging.INFO, logger="kicad_agent.training.real_dataset"):
            result = filter_quality(samples)
        assert len(result) == 2
        assert "removed 1 trivial boards" in caplog.text


# ---------------------------------------------------------------------------
# TestPipelineIntegration
# ---------------------------------------------------------------------------


class TestPipelineIntegration:
    def test_run_pipeline_with_mocks(self, tmp_path: Path):
        """Mock discovery, fetch, and graph build. Verify dataset assembly."""
        # Mock RepoInfo and KicadFilePair
        repo_info = MagicMock()
        repo_info.full_name = "test/repo"
        repo_info.html_url = "https://github.com/test/repo"

        pair1 = MagicMock(spec=KicadFilePair)
        pair1.schematic_path = "a.kicad_sch"
        pair1.pcb_path = "a.kicad_pcb"
        pair1.base_name = "a"

        pair2 = MagicMock(spec=KicadFilePair)
        pair2.schematic_path = "b.kicad_sch"
        pair2.pcb_path = "b.kicad_pcb"
        pair2.base_name = "b"

        pair3 = MagicMock(spec=KicadFilePair)
        pair3.schematic_path = "c.kicad_sch"
        pair3.pcb_path = "c.kicad_pcb"
        pair3.base_name = "c"

        # Mock fetch results
        fetched_sch = MagicMock()
        fetched_sch.local_path = tmp_path / "sch.kicad_sch"
        fetched_pcb = MagicMock()
        fetched_pcb.local_path = tmp_path / "pcb.kicad_pcb"

        # Mock graph results: 2 success, 1 failure (None)
        graph_result_1 = MagicMock(spec=BoardGraphResult)
        graph_result_1.repo_url = "https://github.com/test/repo"
        graph_result_1.repo_name = "test/repo"
        graph_result_1.schematic_path = "a.kicad_sch"
        graph_result_1.pcb_path = "a.kicad_pcb"
        graph_result_1.component_count = 10
        graph_result_1.net_count = 5
        graph_result_1.layer_count = 2
        graph_result_1.board_width_mm = 50.0
        graph_result_1.board_height_mm = 50.0
        graph_result_1.difficulty = "medium"
        graph_result_1.board_hash = "hash_a"
        graph_result_1.graph_json = '{"nodes":[],"links":[]}'
        graph_result_1.spatial_summary_json = '{"points":0,"boxes":0}'

        graph_result_2 = MagicMock(spec=BoardGraphResult)
        graph_result_2.repo_url = "https://github.com/test/repo"
        graph_result_2.repo_name = "test/repo"
        graph_result_2.schematic_path = "b.kicad_sch"
        graph_result_2.pcb_path = "b.kicad_pcb"
        graph_result_2.component_count = 20
        graph_result_2.net_count = 10
        graph_result_2.layer_count = 4
        graph_result_2.board_width_mm = 80.0
        graph_result_2.board_height_mm = 60.0
        graph_result_2.difficulty = "hard"
        graph_result_2.board_hash = "hash_b"
        graph_result_2.graph_json = '{"nodes":[1,2],"links":[3,4]}'
        graph_result_2.spatial_summary_json = '{"points":5,"boxes":3}'

        mock_discovery = MagicMock(spec=GithubDiscovery)
        mock_discovery.discover_pairs.return_value = [
            (repo_info, [pair1, pair2, pair3]),
        ]
        mock_discovery._client = MagicMock()
        mock_discovery._rate_limiter = None

        mock_fetcher = MagicMock(spec=FileFetcher)
        # pair1 and pair2 succeed, pair3 fails (sch is None)
        mock_fetcher.fetch_pair.side_effect = [
            (fetched_sch, fetched_pcb),  # pair1
            (fetched_sch, fetched_pcb),  # pair2
            (None, fetched_pcb),  # pair3 - fails (sch missing)
        ]

        with (
            patch("kicad_agent.training.real_dataset.GithubDiscovery", return_value=mock_discovery),
            patch("kicad_agent.training.real_dataset.FileFetcher", return_value=mock_fetcher),
            patch(
                "kicad_agent.training.real_dataset.build_board_graph",
                side_effect=[graph_result_1, graph_result_2],
            ),
        ):
            dataset = run_pipeline(
                token="ghp_" + "a" * 36,
                staging_dir=tmp_path,
                max_repos=10,
            )

        assert len(dataset) == 2
        assert dataset.samples[0].board_hash == "hash_a"
        assert dataset.samples[1].board_hash == "hash_b"
        assert dataset.metadata["n_parsed"] == 2
        assert dataset.metadata["n_failed"] == 1

    def test_run_pipeline_deduplicates(self, tmp_path: Path):
        """Mock returning 3 results where 2 share a board_hash."""
        repo_info = MagicMock()
        repo_info.full_name = "test/repo"
        repo_info.html_url = "https://github.com/test/repo"

        pairs = [MagicMock(spec=KicadFilePair) for _ in range(3)]
        for i, p in enumerate(pairs):
            p.schematic_path = f"{i}.kicad_sch"
            p.pcb_path = f"{i}.kicad_pcb"
            p.base_name = str(i)

        fetched_sch = MagicMock()
        fetched_sch.local_path = tmp_path / "sch.kicad_sch"
        fetched_pcb = MagicMock()
        fetched_pcb.local_path = tmp_path / "pcb.kicad_pcb"

        def make_graph_result(hash_val: str, idx: int) -> MagicMock:
            gr = MagicMock(spec=BoardGraphResult)
            gr.repo_url = "https://github.com/test/repo"
            gr.repo_name = "test/repo"
            gr.schematic_path = f"{idx}.kicad_sch"
            gr.pcb_path = f"{idx}.kicad_pcb"
            gr.component_count = 10
            gr.net_count = 5
            gr.layer_count = 2
            gr.board_width_mm = 50.0
            gr.board_height_mm = 50.0
            gr.difficulty = "medium"
            gr.board_hash = hash_val
            gr.graph_json = f'{{"idx":{idx}}}'
            gr.spatial_summary_json = '{"points":0}'
            return gr

        # 3 results: first and third share hash "same_hash"
        graph_results = [
            make_graph_result("same_hash", 0),
            make_graph_result("unique_hash", 1),
            make_graph_result("same_hash", 2),
        ]

        mock_discovery = MagicMock(spec=GithubDiscovery)
        mock_discovery.discover_pairs.return_value = [(repo_info, pairs)]
        mock_discovery._client = MagicMock()
        mock_discovery._rate_limiter = None

        mock_fetcher = MagicMock(spec=FileFetcher)
        mock_fetcher.fetch_pair.return_value = (fetched_sch, fetched_pcb)

        with (
            patch("kicad_agent.training.real_dataset.GithubDiscovery", return_value=mock_discovery),
            patch("kicad_agent.training.real_dataset.FileFetcher", return_value=mock_fetcher),
            patch(
                "kicad_agent.training.real_dataset.build_board_graph",
                side_effect=graph_results,
            ),
        ):
            dataset = run_pipeline(
                token="ghp_" + "a" * 36,
                staging_dir=tmp_path,
                max_repos=10,
            )

        assert len(dataset) == 2
        assert dataset.samples[0].board_hash == "same_hash"
        assert dataset.samples[1].board_hash == "unique_hash"
        assert dataset.metadata["n_duplicates_removed"] == 1

    def test_run_pipeline_writes_jsonl_splits(self, tmp_path: Path):
        """Provide output_dir and verify train/val/test JSONL files created."""
        repo_info = MagicMock()
        repo_info.full_name = "test/repo"
        repo_info.html_url = "https://github.com/test/repo"

        # Create 10 pairs to get meaningful splits
        pairs = [MagicMock(spec=KicadFilePair) for _ in range(10)]
        for i, p in enumerate(pairs):
            p.schematic_path = f"{i}.kicad_sch"
            p.pcb_path = f"{i}.kicad_pcb"
            p.base_name = str(i)

        fetched_sch = MagicMock()
        fetched_sch.local_path = tmp_path / "sch.kicad_sch"
        fetched_pcb = MagicMock()
        fetched_pcb.local_path = tmp_path / "pcb.kicad_pcb"

        graph_results = []
        for i in range(10):
            gr = MagicMock(spec=BoardGraphResult)
            gr.repo_url = "https://github.com/test/repo"
            gr.repo_name = "test/repo"
            gr.schematic_path = f"{i}.kicad_sch"
            gr.pcb_path = f"{i}.kicad_pcb"
            gr.component_count = 10
            gr.net_count = 5
            gr.layer_count = 2
            gr.board_width_mm = 50.0
            gr.board_height_mm = 50.0
            gr.difficulty = "medium"
            gr.board_hash = f"unique_hash_{i}"
            gr.graph_json = f'{{"idx":{i}}}'
            gr.spatial_summary_json = '{"points":0}'
            graph_results.append(gr)

        mock_discovery = MagicMock(spec=GithubDiscovery)
        mock_discovery.discover_pairs.return_value = [(repo_info, pairs)]
        mock_discovery._client = MagicMock()
        mock_discovery._rate_limiter = None

        mock_fetcher = MagicMock(spec=FileFetcher)
        mock_fetcher.fetch_pair.return_value = (fetched_sch, fetched_pcb)

        output_dir = tmp_path / "splits"

        with (
            patch("kicad_agent.training.real_dataset.GithubDiscovery", return_value=mock_discovery),
            patch("kicad_agent.training.real_dataset.FileFetcher", return_value=mock_fetcher),
            patch(
                "kicad_agent.training.real_dataset.build_board_graph",
                side_effect=graph_results,
            ),
        ):
            dataset = run_pipeline(
                token="ghp_" + "a" * 36,
                staging_dir=tmp_path,
                max_repos=10,
                output_dir=output_dir,
            )

        assert len(dataset) == 10
        assert (output_dir / "train.jsonl").exists()
        assert (output_dir / "val.jsonl").exists()
        assert (output_dir / "test.jsonl").exists()

        # Verify split ratios: 10 * 0.8 = 8, 10 * 0.1 = 1, rest = 1
        train_lines = (output_dir / "train.jsonl").read_text().strip().split("\n")
        val_lines = (output_dir / "val.jsonl").read_text().strip().split("\n")
        test_lines = (output_dir / "test.jsonl").read_text().strip().split("\n")
        assert len(train_lines) == 8
        assert len(val_lines) == 1
        assert len(test_lines) == 1
