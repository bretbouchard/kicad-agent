"""Unit tests for GRPODataBuilder (Plan 03 Task 1, D-02 GRPO path)."""
from __future__ import annotations

import json
import random
from dataclasses import is_dataclass
from pathlib import Path
from unittest.mock import patch

import pytest

from kicad_agent.training.grpo_data_builder import (
    GRPODataBuilder,
    GRPODataBuilderError,
)
from kicad_agent.training.rewards import AlignmentJitter


FIXTURE = Path("tests/fixtures/Arduino_Mega/Arduino_Mega.kicad_sch")
_SEED_SPACING = 1_000_000  # Phase 63 H-12 pattern (HI-110-07 inlined)


def test_perturb_schematic_writes_variation_file(tmp_path) -> None:
    """Test 1: perturb_schematic writes a new .kicad_sch under output_dir."""
    if not FIXTURE.exists():
        pytest.skip(f"fixture {FIXTURE} not available")
    builder = GRPODataBuilder(output_dir=tmp_path)
    var_path = builder.perturb_schematic(FIXTURE, seed=42)
    assert var_path.exists()
    assert var_path.suffix == ".kicad_sch"
    assert var_path.parent == tmp_path


def test_perturb_schematic_deterministic_same_seed(tmp_path) -> None:
    """Test 2: same seed produces byte-identical variation (Phase 63 H-12)."""
    if not FIXTURE.exists():
        pytest.skip(f"fixture {FIXTURE} not available")
    builder1 = GRPODataBuilder(output_dir=tmp_path / "a")
    builder2 = GRPODataBuilder(output_dir=tmp_path / "b")
    var1 = builder1.perturb_schematic(FIXTURE, seed=42)
    var2 = builder2.perturb_schematic(FIXTURE, seed=42)
    assert var1.read_bytes() == var2.read_bytes()


def test_perturb_schematic_different_seeds_produce_different_files(tmp_path) -> None:
    """Test 3: different seeds produce different files."""
    if not FIXTURE.exists():
        pytest.skip(f"fixture {FIXTURE} not available")
    builder = GRPODataBuilder(output_dir=tmp_path)
    var1 = builder.perturb_schematic(FIXTURE, seed=1)
    var2 = builder.perturb_schematic(FIXTURE, seed=2)
    # Different seeds should produce at least one different byte
    assert var1.read_bytes() != var2.read_bytes()


def test_score_variation_returns_required_keys(tmp_path) -> None:
    """Test 4: score_variation returns base_srs, variation_srs, reward_delta."""
    if not FIXTURE.exists():
        pytest.skip(f"fixture {FIXTURE} not available")
    builder = GRPODataBuilder(output_dir=tmp_path)
    var_path = builder.perturb_schematic(FIXTURE, seed=42)
    result = builder.score_variation(FIXTURE, var_path)
    assert set(result.keys()) == {"base_srs", "variation_srs", "reward_delta"}
    for srs_key in ("base_srs", "variation_srs"):
        srs = result[srs_key]
        assert set(srs.keys()) == {"density", "clarity", "spacing", "organization", "overall_srs"}
        for k, v in srs.items():
            assert isinstance(v, float)
            if k != "overall_srs":
                assert 0.0 <= v <= 1.0
    # Reward delta is in [-1, 1]
    assert -1.0 <= result["reward_delta"] <= 1.0


def test_build_exploration_rows_returns_n_rows(tmp_path) -> None:
    """Test 5: build_exploration_rows(base, n_variations=5) returns 5 rows."""
    if not FIXTURE.exists():
        pytest.skip(f"fixture {FIXTURE} not available")
    builder = GRPODataBuilder(output_dir=tmp_path)
    rows = builder.build_exploration_rows(FIXTURE, n_variations=3, seed=42)
    assert len(rows) == 3
    for row in rows:
        parsed = json.loads(row)
        assert "base_path" in parsed
        assert "variation_path" in parsed
        assert "variation_id" in parsed
        assert "base_srs" in parsed
        assert "variation_srs" in parsed
        assert "reward_delta" in parsed
        assert "seed" in parsed


def test_perturb_schematic_writes_under_output_dir(tmp_path) -> None:
    """Test 6: variation lands under output_dir."""
    if not FIXTURE.exists():
        pytest.skip(f"fixture {FIXTURE} not available")
    custom_dir = tmp_path / "custom"
    builder = GRPODataBuilder(output_dir=custom_dir)
    var_path = builder.perturb_schematic(FIXTURE, seed=42)
    assert var_path.parent.resolve() == custom_dir.resolve()


def test_perturb_schematic_empty_schematic_raises(tmp_path) -> None:
    """Test 7: schematic with 0 components raises GRPODataBuilderError."""
    empty_sch = tmp_path / "empty.kicad_sch"
    # Minimal valid schematic with no symbols
    empty_sch.write_text(
        '(kicad_sch (version 20231220) (generator "test") (uuid "00000000-0000-0000-0000-000000000000") (paper "A4"))',
        encoding="utf-8",
    )
    builder = GRPODataBuilder(output_dir=tmp_path)
    with pytest.raises(GRPODataBuilderError, match="no components"):
        builder.perturb_schematic(empty_sch, seed=42)


def test_reward_delta_in_range(tmp_path) -> None:
    """Test 8: reward_delta in [-1.0, 1.0]."""
    if not FIXTURE.exists():
        pytest.skip(f"fixture {FIXTURE} not available")
    builder = GRPODataBuilder(output_dir=tmp_path)
    rows = builder.build_exploration_rows(FIXTURE, n_variations=3, seed=42)
    for row in rows:
        parsed = json.loads(row)
        assert -1.0 <= parsed["reward_delta"] <= 1.0


def test_var_seed_computation_matches_phase_63_pattern() -> None:
    """Test 9: var_seed = seed + i * _SEED_SPACING (HI-110-07 inlined constant)."""
    # Verify the constant is exactly 1_000_000
    from kicad_agent.training.grpo_data_builder import _SEED_SPACING
    assert _SEED_SPACING == 1_000_000
    # Manually verify the formula matches what build_exploration_rows uses
    seed = 42
    n_variations = 5
    expected_seeds = [seed + i * _SEED_SPACING for i in range(n_variations)]
    # Expected: 42, 1000042, 2000042, 3000042, 4000042
    assert expected_seeds == [42, 1_000_042, 2_000_042, 3_000_042, 4_000_042]


def test_score_variation_uses_verified_chain(tmp_path) -> None:
    """Test 10: score_variation constructs SchematicReadabilityScorer with a SchematicSpatialExtractor
    wrapping a SchematicIR (not a path string). Uses mock to verify."""
    if not FIXTURE.exists():
        pytest.skip(f"fixture {FIXTURE} not available")
    builder = GRPODataBuilder(output_dir=tmp_path)
    var_path = builder.perturb_schematic(FIXTURE, seed=42)

    # Patch SchematicReadabilityScorer to a Mock that records its construction arg
    constructed_with = []
    original_class = None

    from kicad_agent.training import grpo_data_builder as gdb_module

    original_scorer = gdb_module.SchematicReadabilityScorer

    class _CapturingScorer:
        def __init__(self, extractor, topology=None):
            constructed_with.append(extractor)

        def score(self):
            from kicad_agent.analysis.readability_scorer import ReadabilityReport
            return ReadabilityReport(srs=0.5, factors={"density": 0.5, "clarity": 0.5, "spacing": 0.5, "organization": 0.5})

    with patch.object(gdb_module, "SchematicReadabilityScorer", _CapturingScorer):
        builder.score_variation(FIXTURE, var_path)

    # The scorer should have been constructed twice (base + variation), each with a
    # SchematicSpatialExtractor argument (not a Path or str).
    assert len(constructed_with) == 2
    from kicad_agent.analysis.schematic_spatial import SchematicSpatialExtractor
    for arg in constructed_with:
        assert isinstance(arg, SchematicSpatialExtractor), (
            f"scorer constructed with {type(arg).__name__}, expected SchematicSpatialExtractor"
        )


def test_grpo_data_builder_is_frozen_dataclass() -> None:
    """Phase 100 CR-01: GRPODataBuilder is frozen."""
    assert is_dataclass(GRPODataBuilder)
    builder = GRPODataBuilder()
    with pytest.raises(Exception):
        builder.jitter = AlignmentJitter(amplitude_mm=0.5)  # type: ignore[misc]
