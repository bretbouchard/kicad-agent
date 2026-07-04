"""Integration tests for GRPO legibility wiring (Plan 04 Task 2).

Validates:
  - AdvantageWeightedTrainer accepts optional legibility_adapter (backward compat)
  - compute_group_rewards preserves existing behavior when adapter=None
  - Multi-objective combine fires when adapter + critique registry entry exist
  - CR-110-03: critique looked up by sample_id in registry (no hasattr on sample)
  - HI-110-05: completeness_source='none' folds weight into correctness
  - LO-110-11: malformed critique -> 0.0 legibility, training continues
"""
from __future__ import annotations

import logging
from types import MappingProxyType
from unittest.mock import MagicMock

import pytest

from kicad_agent.training.grpo import AdvantageWeightedConfig, AdvantageWeightedTrainer
from kicad_agent.training.legibility_reward_adapter import (
    LegibilityRewardAdapter,
    RewardWeights,
)
from kicad_agent.training.rewards import (
    CapInputs,
    CompactnessCap,
    CrossingsFloorCap,
    LegibilityReward,
)


def _make_reward_model():
    """Build a mock reward model.

    Tests patch kicad_agent.training.reward_model.predict_reward directly to
    return a known PredictedReward, so the model object is just a placeholder.
    """
    return MagicMock()


def _patch_predict_reward(monkeypatch, format_score=0.5, quality_score=0.5, accuracy_score=0.5):
    """Patch predict_reward to return a deterministic PredictedReward."""
    from kicad_agent.training.reward_model import PredictedReward
    monkeypatch.setattr(
        "kicad_agent.training.reward_model.predict_reward",
        lambda model, chain_text: PredictedReward(
            format_score=format_score, quality_score=quality_score, accuracy_score=accuracy_score,
        ),
    )


def _make_adapter(completeness_source: str = "none") -> LegibilityRewardAdapter:
    return LegibilityRewardAdapter(
        base_reward=LegibilityReward(),
        compactness_cap=CompactnessCap(threshold_ratio=2.0),
        crossings_floor_cap=CrossingsFloorCap(min_crossings=1, floor_multiplier=0.3),
        weights=RewardWeights(),
        completeness_source=completeness_source,
    )


def _make_critique(factors: dict, model_used: str = "gemma4") -> MagicMock:
    critique = MagicMock()
    critique.factors_view.return_value = MappingProxyType(dict(factors))
    critique.model_used = model_used
    return critique


def _make_cap_inputs(crossings: int = 5) -> CapInputs:
    return CapInputs(bounding_box_mm2=100.0, component_footprint_area_mm2=100.0, crossing_count=crossings)


def _make_sample(sample_id: int) -> MagicMock:
    sample = MagicMock()
    sample.sample_id = sample_id
    return sample


# ---------------------------------------------------------------------------
# Test 1: trainer accepts optional legibility_adapter param
# ---------------------------------------------------------------------------


def test_trainer_accepts_legibility_adapter_param() -> None:
    """Test 1: adapter is optional, default None."""
    policy = MagicMock()
    reward_model = _make_reward_model()
    trainer = AdvantageWeightedTrainer(policy, reward_model, ref_model=None)
    assert trainer.legibility_adapter is None  # default

    adapter = _make_adapter()
    trainer2 = AdvantageWeightedTrainer(policy, reward_model, ref_model=None, legibility_adapter=adapter)
    assert trainer2.legibility_adapter is adapter


# ---------------------------------------------------------------------------
# Test 2: adapter=None preserves existing behavior (regression guard)
# ---------------------------------------------------------------------------


def test_compute_group_rewards_adapter_none_preserves_existing_behavior(monkeypatch) -> None:
    """Test 2: when adapter=None, reward = (format+quality+accuracy)/3."""
    _patch_predict_reward(monkeypatch, format_score=0.6, quality_score=0.6, accuracy_score=0.6)
    policy = MagicMock()
    reward_model = _make_reward_model()
    trainer = AdvantageWeightedTrainer(policy, reward_model, ref_model=None)
    samples = [_make_sample(1), _make_sample(2)]
    chain_groups = [["chain A text", "chain B text"], ["chain C text"]]

    rewards = trainer.compute_group_rewards(chain_groups, samples)
    # 2 groups, with chain counts [2, 1]
    assert len(rewards) == 2
    assert len(rewards[0]) == 2
    assert len(rewards[1]) == 1
    # Each reward is 0.6 (correctness = (0.6+0.6+0.6)/3 = 0.6, no adapter applied)
    for group_rewards in rewards:
        for r in group_rewards:
            assert r == pytest.approx(0.6)


# ---------------------------------------------------------------------------
# Test 3: adapter + registry entry -> 3-term combine
# ---------------------------------------------------------------------------


def test_compute_group_rewards_with_critique_uses_combine(monkeypatch) -> None:
    """Test 3: when adapter + critique registered, combine() is used."""
    _patch_predict_reward(monkeypatch)
    adapter = _make_adapter(completeness_source="layout_result")
    policy = MagicMock()
    reward_model = _make_reward_model()
    trainer = AdvantageWeightedTrainer(
        policy, reward_model, ref_model=None, legibility_adapter=adapter,
    )
    sample = _make_sample(42)
    critique = _make_critique({
        "density": 1.0, "clarity": 1.0, "spacing": 1.0, "organization": 1.0,
    })
    cap_inputs = _make_cap_inputs(crossings=5)
    trainer.register_critique(42, critique, cap_inputs)

    rewards = trainer.compute_group_rewards([["chain text"]], [sample])
    # With layout_result completeness_source but no layout registered, completeness=None
    # -> combine() folds to 0.8*correctness + 0.2*legibility.
    # legibility = 1.0 (perfect factors, no caps), correctness = 0.5 (patched)
    # Expected = 0.8 * 0.5 + 0.2 * 1.0 = 0.6
    assert rewards[0][0] == pytest.approx(0.6)


# ---------------------------------------------------------------------------
# Test 4: correctness term = (format + quality + accuracy) / 3
# ---------------------------------------------------------------------------


def test_correctness_term_format_quality_accuracy_average(monkeypatch) -> None:
    """Test 4: correctness = (format + quality + accuracy) / 3 (existing semantics)."""
    _patch_predict_reward(monkeypatch, format_score=0.6, quality_score=0.4, accuracy_score=0.5)
    policy = MagicMock()
    reward_model = _make_reward_model()
    trainer = AdvantageWeightedTrainer(policy, reward_model, ref_model=None)
    rewards = trainer.compute_group_rewards([["text"]], [_make_sample(1)])
    # correctness = (0.6 + 0.4 + 0.5) / 3 = 0.5
    assert rewards[0][0] == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Test 5: per-term contributions logged with reward_decomposition prefix
# ---------------------------------------------------------------------------


def test_reward_decomposition_logged_with_critique(caplog, monkeypatch) -> None:
    """Test 5: 'reward_decomposition' log line emitted when adapter+critique fire."""
    _patch_predict_reward(monkeypatch)
    adapter = _make_adapter()
    policy = MagicMock()
    reward_model = _make_reward_model()
    trainer = AdvantageWeightedTrainer(
        policy, reward_model, ref_model=None, legibility_adapter=adapter,
    )
    sample = _make_sample(7)
    critique = _make_critique({
        "density": 0.8, "clarity": 0.7, "spacing": 0.6, "organization": 0.5,
    })
    trainer.register_critique(7, critique, _make_cap_inputs())

    with caplog.at_level(logging.INFO, logger="kicad_agent.training.grpo"):
        trainer.compute_group_rewards([["text"]], [sample])

    found = any("reward_decomposition" in rec.message for rec in caplog.records)
    assert found, "expected 'reward_decomposition' log line not emitted"


# ---------------------------------------------------------------------------
# Test 6: RewardWeights defaults = D-03 0.4/0.4/0.2
# ---------------------------------------------------------------------------


def test_default_reward_weights_match_d03() -> None:
    """Test 6: RewardWeights defaults are 0.40/0.40/0.20."""
    w = RewardWeights()
    assert w.correctness == 0.40
    assert w.completeness == 0.40
    assert w.legibility == 0.20


# ---------------------------------------------------------------------------
# Test 7: CR-110-03 — critique looked up by sample_id (no hasattr)
# ---------------------------------------------------------------------------


def test_critique_registry_lookup_by_sample_id(monkeypatch) -> None:
    """Test 7: CR-110-03 — compute_group_rewards looks up critique by sample_id."""
    _patch_predict_reward(monkeypatch)
    adapter = _make_adapter()
    policy = MagicMock()
    reward_model = _make_reward_model()
    trainer = AdvantageWeightedTrainer(
        policy, reward_model, ref_model=None, legibility_adapter=adapter,
    )
    sample = _make_sample(99)
    critique = _make_critique({
        "density": 1.0, "clarity": 1.0, "spacing": 1.0, "organization": 1.0,
    })
    trainer.register_critique(99, critique, _make_cap_inputs(crossings=5))

    # Patch the class method (frozen instance can't be patched in-place) to
    # count calls. compute_legibility signature is (self, critique, cap_inputs).
    call_count = {"n": 0}
    original = type(adapter).compute_legibility

    def _counting_compute(self, critique, cap_inputs):
        call_count["n"] += 1
        return original(self, critique, cap_inputs)

    from kicad_agent.training.legibility_reward_adapter import LegibilityRewardAdapter as _LRA
    monkeypatch.setattr(_LRA, "compute_legibility", _counting_compute)

    trainer.compute_group_rewards([["text"]], [sample])

    assert call_count["n"] == 1, (
        f"expected adapter.compute_legibility called once (registry lookup), "
        f"got {call_count['n']}"
    )


# ---------------------------------------------------------------------------
# Test 8: CR-110-03 — no critique -> legibility=0, reward collapses
# ---------------------------------------------------------------------------


def test_no_critique_for_sample_id_falls_back_to_correctness_only(caplog, monkeypatch) -> None:
    """Test 8: sample_id with no critique -> reward = correctness only (logged at debug)."""
    _patch_predict_reward(monkeypatch)
    adapter = _make_adapter()
    policy = MagicMock()
    reward_model = _make_reward_model()
    trainer = AdvantageWeightedTrainer(
        policy, reward_model, ref_model=None, legibility_adapter=adapter,
    )
    sample = _make_sample(1234)  # no critique registered for this id
    rewards = trainer.compute_group_rewards([["text"]], [sample])
    # Reward collapses to correctness (0.5)
    assert rewards[0][0] == pytest.approx(0.5)


# ---------------------------------------------------------------------------
# Test 9: HI-110-05 — completeness_source='none' folds into correctness
# ---------------------------------------------------------------------------


def test_completeness_source_none_folds_into_correctness(monkeypatch) -> None:
    """Test 9: with completeness_source='none', reward = 0.8*correctness + 0.2*legibility."""
    _patch_predict_reward(monkeypatch)
    adapter = _make_adapter(completeness_source="none")
    policy = MagicMock()
    reward_model = _make_reward_model()
    trainer = AdvantageWeightedTrainer(
        policy, reward_model, ref_model=None, legibility_adapter=adapter,
    )
    sample = _make_sample(55)
    critique = _make_critique({
        "density": 1.0, "clarity": 1.0, "spacing": 1.0, "organization": 1.0,
    })
    trainer.register_critique(55, critique, _make_cap_inputs(crossings=5))

    rewards = trainer.compute_group_rewards([["text"]], [sample])
    # correctness = 0.5 (patched), legibility = 1.0 (perfect, no caps)
    # Expected = 0.8 * 0.5 + 0.2 * 1.0 = 0.6
    assert rewards[0][0] == pytest.approx(0.6)


# ---------------------------------------------------------------------------
# Test 10: LO-110-11 — malformed critique -> 0.0 legibility, training continues
# ---------------------------------------------------------------------------


def test_malformed_critique_continues_training(monkeypatch) -> None:
    """Test 10 / LO-110-11: malformed critique -> compute_legibility returns 0.0, no crash."""
    _patch_predict_reward(monkeypatch)
    adapter = _make_adapter()
    policy = MagicMock()
    reward_model = _make_reward_model()
    trainer = AdvantageWeightedTrainer(
        policy, reward_model, ref_model=None, legibility_adapter=adapter,
    )
    sample = _make_sample(77)
    # Malformed: missing "spacing"
    bad_critique = _make_critique({
        "density": 0.8, "clarity": 0.7, "organization": 0.5,
    })
    trainer.register_critique(77, bad_critique, _make_cap_inputs(crossings=5))

    # Must NOT raise — compute_legibility catches and returns 0.0
    rewards = trainer.compute_group_rewards([["text"]], [sample])
    # legibility = 0.0; reward = 0.8*correctness + 0.2*0 = 0.4
    # correctness = 0.5 (patched) -> reward = 0.8*0.5 = 0.4
    assert rewards[0][0] == pytest.approx(0.4)


# ---------------------------------------------------------------------------
# Test 11: registry helpers (register_critique, clear_critique_registry)
# ---------------------------------------------------------------------------


def test_registry_helpers_register_and_clear() -> None:
    """Test 11: register_critique adds, clear_critique_registry empties."""
    adapter = _make_adapter()
    policy = MagicMock()
    reward_model = _make_reward_model()
    trainer = AdvantageWeightedTrainer(
        policy, reward_model, ref_model=None, legibility_adapter=adapter,
    )
    critique = _make_critique({
        "density": 1.0, "clarity": 1.0, "spacing": 1.0, "organization": 1.0,
    })
    trainer.register_critique(1, critique, _make_cap_inputs())
    assert 1 in trainer._critique_registry
    trainer.clear_critique_registry()
    assert len(trainer._critique_registry) == 0


# ---------------------------------------------------------------------------
# config.json integration — verify shape parsed correctly
# ---------------------------------------------------------------------------


def test_config_json_has_training_reward_weights_block() -> None:
    """Smoke check: config.json contains the D-03 reward_weights block."""
    import json
    from pathlib import Path
    config_path = Path(".planning/config.json")
    if not config_path.exists():
        pytest.skip(".planning/config.json not available")
    config = json.loads(config_path.read_text())
    assert "training" in config, "config.json missing 'training' block"
    training = config["training"]
    assert "reward_weights" in training, "training block missing reward_weights"
    weights = training["reward_weights"]
    assert weights.get("correctness") == 0.4
    assert weights.get("completeness") == 0.4
    assert weights.get("legibility") == 0.2
    assert training.get("completeness_source") == "none"
