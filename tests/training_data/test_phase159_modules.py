"""Phase 159: Tests for corpus converter, reward combiner, placement pairs."""
from __future__ import annotations

from pathlib import Path

import pytest

from kicad_agent.training_data import (
    combine_rewards,
    compute_spice_reward,
    compute_combined_reward,
    PlacementPair,
    build_placement_pairs,
    convert_repo_to_skidl,
    load_discovered_repos,
)
from kicad_agent.spice.types import DegradationReport


class TestRewardCombiner:
    """TRAIN-04: sim-aware reward combiner."""

    def test_combine_equal_weights(self) -> None:
        score = combine_rewards(spice_score=1.0, res_score=1.0, format_score=1.0)
        assert score == 1.0

    def test_combine_zero_spice(self) -> None:
        score = combine_rewards(spice_score=0.0, res_score=1.0, format_score=1.0)
        assert score < 1.0
        assert score > 0.5  # res + format still contribute

    def test_combine_custom_weights(self) -> None:
        score = combine_rewards(
            spice_score=0.5, res_score=1.0, format_score=1.0,
            weights={"spice": 1.0, "res": 0.0, "format": 0.0},
        )
        assert score == 0.5

    def test_spice_reward_from_degradation(self) -> None:
        deg = DegradationReport(sim_score=0.8)
        assert compute_spice_reward(deg) == 0.8

    def test_combined_with_degradation(self) -> None:
        deg = DegradationReport(sim_score=0.7)
        score = compute_combined_reward(deg, res_score=0.9, format_score=1.0)
        assert 0.7 < score < 0.9

    def test_combined_without_degradation(self) -> None:
        score = compute_combined_reward(None, res_score=0.8, format_score=0.9)
        # spice=1.0 (default), res=0.8, format=0.9 → weighted blend
        assert 0.85 < score < 0.95


class TestCorpusConverter:
    """TRAIN-01: SKIDL corpus converter."""

    def test_load_discovered_repos(self) -> None:
        repos = load_discovered_repos("discovered_repos.json", limit=5)
        assert isinstance(repos, list)
        # May be empty if file not found, but should not crash.

    def test_convert_repo_to_skidl_no_files(self, tmp_path: Path) -> None:
        """Converting an empty repo returns 0,0."""
        success, failure = convert_repo_to_skidl(tmp_path, tmp_path / "out")
        assert success == 0
        assert failure == 0


class TestPlacementPairs:
    """TRAIN-03: placement pair builder."""

    def test_build_pairs_returns_list(self, tmp_path: Path) -> None:
        """build_placement_pairs returns a list (may be empty on failure)."""
        # Use a non-existent file — should return empty list gracefully.
        pairs = build_placement_pairs("/nonexistent.kicad_sch", tmp_path)
        assert isinstance(pairs, list)
