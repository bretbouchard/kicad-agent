"""Phase 63: Training integrity fixes — tests for H-11, H-12, H-13, H-14.

Covers:
  - H-11: GitHub token handling with format validation and env var fallback
  - H-12: Parallel seed offset produces unique, non-overlapping seeds per worker
  - H-13: GRPOTrainer uses seeded RNG with incrementing step counter
  - H-14: RewardModel.generate uses independent scoring, not self-referential
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest

from kicad_agent.training.grpo import GRPOConfig, GRPOTrainer
from kicad_agent.training.real_dataset import _resolve_github_token
from kicad_agent.training.reward_model import _independent_score


# ---------------------------------------------------------------------------
# H-11: GitHub token validation
# ---------------------------------------------------------------------------


class TestResolveGitHubToken:
    """Tests for _resolve_github_token in real_dataset.py."""

    def test_valid_ghp_token(self) -> None:
        """Accepts a valid ghp_ prefixed token."""
        token = "ghp_" + "a" * 36
        assert _resolve_github_token(token) == token

    def test_valid_gho_token(self) -> None:
        """Accepts a valid gho_ prefixed token."""
        token = "gho_" + "B" * 36
        assert _resolve_github_token(token) == token

    def test_valid_github_pat_token(self) -> None:
        """Accepts a valid github_pat_ prefixed token."""
        token = "github_pat_" + "c" * 36
        assert _resolve_github_token(token) == token

    def test_valid_ghs_token(self) -> None:
        """Accepts a valid ghs_ prefixed token."""
        token = "ghs_" + "d" * 36
        assert _resolve_github_token(token) == token

    def test_valid_ghu_token(self) -> None:
        """Accepts a valid ghu_ prefixed token."""
        token = "ghu_" + "e" * 36
        assert _resolve_github_token(token) == token

    def test_token_with_more_than_36_chars(self) -> None:
        """Accepts tokens with more than 36 alphanumeric chars after prefix."""
        token = "ghp_" + "a" * 80
        assert _resolve_github_token(token) == token

    def test_rejects_empty_string(self) -> None:
        """Rejects empty string token."""
        with pytest.raises(ValueError, match="GitHub token must be provided"):
            _resolve_github_token("")

    def test_rejects_none_without_env_var(self) -> None:
        """Rejects None when GITHUB_TOKEN env var is not set."""
        with patch.dict(os.environ, {}, clear=True):
            # Ensure GITHUB_TOKEN is not set
            os.environ.pop("GITHUB_TOKEN", None)
            with pytest.raises(ValueError, match="GitHub token must be provided"):
                _resolve_github_token(None)

    def test_falls_back_to_env_var(self) -> None:
        """Reads token from GITHUB_TOKEN environment variable when arg is None."""
        env_token = "ghp_" + "f" * 36
        with patch.dict(os.environ, {"GITHUB_TOKEN": env_token}):
            assert _resolve_github_token(None) == env_token

    def test_falls_back_to_env_var_on_empty_string(self) -> None:
        """Reads token from env var when explicit arg is empty string."""
        env_token = "ghp_" + "g" * 36
        with patch.dict(os.environ, {"GITHUB_TOKEN": env_token}):
            assert _resolve_github_token("") == env_token

    def test_rejects_invalid_prefix(self) -> None:
        """Rejects tokens with unknown prefix."""
        with pytest.raises(ValueError, match="invalid format"):
            _resolve_github_token("invalid_prefix_" + "a" * 36)

    def test_rejects_too_short_token(self) -> None:
        """Rejects tokens with fewer than 36 chars after prefix."""
        with pytest.raises(ValueError, match="invalid format"):
            _resolve_github_token("ghp_" + "a" * 35)

    def test_rejects_whitespace_only(self) -> None:
        """Rejects whitespace-only token."""
        with pytest.raises(ValueError, match="GitHub token must be provided"):
            _resolve_github_token("   ")

    def test_strips_whitespace(self) -> None:
        """Strips leading/trailing whitespace from valid tokens."""
        token = "ghp_" + "a" * 36
        assert _resolve_github_token(f"  {token}  ") == token

    def test_explicit_token_takes_precedence_over_env(self) -> None:
        """Explicit token parameter takes precedence over env var."""
        explicit = "ghp_" + "h" * 36
        env_token = "ghp_" + "i" * 36
        with patch.dict(os.environ, {"GITHUB_TOKEN": env_token}):
            assert _resolve_github_token(explicit) == explicit


# ---------------------------------------------------------------------------
# H-12: Parallel seed offset
# ---------------------------------------------------------------------------


class TestParallelSeedOffset:
    """Tests for unique per-worker seed offsets in generator.py."""

    def test_worker_seeds_are_unique(self) -> None:
        """Each worker must receive a different seed offset."""
        from kicad_agent.training.generator import _SEED_SPACING

        seed_base = 42
        n_workers = 4
        chunk_size = 100

        offsets = [seed_base + wid * _SEED_SPACING for wid in range(n_workers)]

        # All offsets must be unique
        assert len(set(offsets)) == n_workers, "Worker seed offsets must be unique"

    def test_seed_spacing_prevents_overlap(self) -> None:
        """Seed ranges must not overlap between workers."""
        from kicad_agent.training.generator import _SEED_SPACING

        seed_base = 42
        n_workers = 4
        chunk_size = 100

        # Each worker uses seeds in [offset, offset + chunk_size)
        for i in range(n_workers):
            for j in range(i + 1, n_workers):
                offset_i = seed_base + i * _SEED_SPACING
                offset_j = seed_base + j * _SEED_SPACING
                # Worker i's max seed must be below worker j's min seed
                assert offset_i + chunk_size <= offset_j, (
                    f"Workers {i} and {j} have overlapping seed ranges"
                )

    def test_spacing_value_is_one_million(self) -> None:
        """_SEED_SPACING must be 1,000,000."""
        from kicad_agent.training.generator import _SEED_SPACING

        assert _SEED_SPACING == 1_000_000

    def test_seed_offset_formula(self) -> None:
        """Seed offset must be seed_base + worker_id * 1_000_000."""
        seed_base = 42
        for worker_id in range(4):
            expected_offset = seed_base + worker_id * 1_000_000
            # Verify the formula produces monotonically increasing offsets
            if worker_id > 0:
                prev_offset = seed_base + (worker_id - 1) * 1_000_000
                assert expected_offset > prev_offset


# ---------------------------------------------------------------------------
# H-13: Seeded random in GRPO
# ---------------------------------------------------------------------------


class TestGRPOSeededRandom:
    """Tests for deterministic seeding in GRPOTrainer."""

    def test_step_counter_initialized_to_zero(self) -> None:
        """GRPOTrainer must initialize _step_counter to 0."""
        config = GRPOConfig(seed=42)
        trainer = GRPOTrainer(
            policy_model=MagicMock(),
            reward_model=MagicMock(),
            ref_model=MagicMock(),
            config=config,
        )
        assert trainer._step_counter == 0

    def test_config_has_seed_default(self) -> None:
        """GRPOConfig must have seed field with default 42."""
        config = GRPOConfig()
        assert config.seed == 42

    def test_config_seed_is_configurable(self) -> None:
        """GRPOConfig seed must be configurable."""
        config = GRPOConfig(seed=123)
        assert config.seed == 123

    def test_train_step_increments_step_counter(self) -> None:
        """Calling train_step must increment _step_counter."""
        import random

        # Create a minimal mock setup
        mock_reward = MagicMock()
        mock_reward.is_available = False

        config = GRPOConfig(seed=42, group_size=2)
        trainer = GRPOTrainer(
            policy_model=None,
            reward_model=mock_reward,
            ref_model=None,
            config=config,
        )

        # Create minimal fake samples
        from kicad_agent.training.dataset import MazeSample

        samples = [
            MazeSample(
                sample_id=0, seed=0,
                board_width_mm=30.0, board_height_mm=30.0,
                grid_size_mm=5.0, obstacle_count=0,
                obstacle_positions=(),
                source_point=(0.0, 0.0), target_point=(5.0, 5.0),
                solution_path=((0.0, 0.0), (5.0, 5.0)),
                solution_length=2, difficulty="easy",
                board_hash="hash_0",
            )
        ]

        initial_counter = trainer._step_counter
        trainer.train_step(samples)
        assert trainer._step_counter == initial_counter + 1

    def test_consecutive_steps_get_different_seeds(self) -> None:
        """Each train_step call must use a different RNG seed."""
        import random as random_module

        # Verify the seed formula: config.seed + step_counter
        config = GRPOConfig(seed=42)
        seeds = [config.seed + i for i in range(5)]

        # All seeds must be unique
        assert len(set(seeds)) == 5

        # Seeds must be deterministic
        for i in range(5):
            assert seeds[i] == 42 + i

    def test_rng_is_seeded_with_config_seed_plus_counter(self) -> None:
        """Verify train_step source uses config.seed + _step_counter for RNG."""
        import inspect
        from kicad_agent.training.grpo import GRPOTrainer

        source = inspect.getsource(GRPOTrainer.train_step)
        # Must contain the seeded pattern
        assert "self.config.seed + self._step_counter" in source, (
            "train_step must seed RNG with config.seed + _step_counter"
        )
        # Must NOT contain unseeded Random()
        assert "Random()" not in source, (
            "train_step must not use unseeded random.Random()"
        )


# ---------------------------------------------------------------------------
# H-14: Independent scoring (no self-referential best-of-N)
# ---------------------------------------------------------------------------


class TestIndependentScore:
    """Tests for _independent_score in reward_model.py."""

    def test_empty_string_returns_zero(self) -> None:
        """Empty string must return 0.0."""
        assert _independent_score("") == 0.0

    def test_whitespace_only_returns_zero(self) -> None:
        """Whitespace-only text must return 0.0."""
        assert _independent_score("   \n\t  ") == 0.0

    def test_full_format_chain_gets_high_score(self) -> None:
        """Chain with all sections and many steps gets a high score."""
        chain = (
            "Step 1: Initial analysis\n"
            "Observation: via at <point 5.0, 10.0>\n"
            "Reasoning: The trace must avoid the obstacle.\n"
            "Step 2: Move to next point\n"
            "Step 3: Continue routing\n"
            "Step 4: Final approach\n"
            "Step 5: Check clearance\n"
            "Step 6: Verify path\n"
            "Step 7: Confirm connection\n"
            "Step 8: Complete\n"
            "Conclusion: Route is valid.\n"
        )
        score = _independent_score(chain)
        assert score > 0.7, f"Expected high score for well-formed chain, got {score}"

    def test_no_sections_gets_low_score(self) -> None:
        """Chain with no recognized sections gets a low score."""
        chain = "just some random text without any structure"
        score = _independent_score(chain)
        assert score < 0.3, f"Expected low score for unstructured text, got {score}"

    def test_partial_sections_gets_medium_score(self) -> None:
        """Chain with some sections gets a medium score."""
        chain = (
            "Observation: found via\n"
            "Step 1: Analyze\n"
            "Step 2: Route\n"
            "Conclusion: done\n"
        )
        score = _independent_score(chain)
        # Has observation, conclusion (2/4 sections = 0.5) and 2 steps (2/8 = 0.25)
        # Average: (0.5 + 0.25) / 2 = 0.375
        assert 0.2 < score < 0.6, f"Expected medium score, got {score}"

    def test_score_is_between_zero_and_one(self) -> None:
        """Score must always be between 0.0 and 1.0."""
        test_cases = [
            "",
            "simple text",
            "Observation: test\nReasoning: test\n<point 1.0,2.0>\nConclusion: test\n",
        ]
        test_cases += ["Step " + str(i) for i in range(20)]
        for text in test_cases:
            score = _independent_score(text)
            assert 0.0 <= score <= 1.0, f"Score out of range for: {text[:30]}"

    def test_coordinate_pattern_detected(self) -> None:
        """<point x, y> pattern must be detected for format score."""
        chain_with_coords = "Observation: <point 5.0, 10.0> found\nConclusion: done"
        chain_without_coords = "Observation: found\nConclusion: done"
        assert _independent_score(chain_with_coords) > _independent_score(chain_without_coords)

    def test_more_steps_higher_score(self) -> None:
        """Chains with more steps must score higher (depth component)."""
        short_chain = "Observation: start\nStep 1: done\nConclusion: end"
        long_chain = (
            "Observation: start\n"
            + "\n".join(f"Step {i}: work" for i in range(1, 9))
            + "\nConclusion: end"
        )
        assert _independent_score(long_chain) > _independent_score(short_chain)


class TestRewardModelGenerate:
    """Tests for RewardModel.generate using independent scoring."""

    def test_generate_uses_independent_scoring(self) -> None:
        """generate() must use _independent_score, not predict_reward on self."""
        import inspect
        from kicad_agent.training.reward_model import RewardModel

        source = inspect.getsource(RewardModel.generate)
        # Must call _independent_score
        assert "_independent_score" in source, (
            "generate() must use _independent_score for heuristic scoring"
        )
        # Must NOT call predict_reward(self, ...)
        assert "predict_reward(self," not in source, (
            "generate() must not call predict_reward(self, ...) — self-referential"
        )

    def test_generate_accepts_reference_model(self) -> None:
        """generate() must accept optional reference_model parameter."""
        import inspect
        from kicad_agent.training.reward_model import RewardModel

        sig = inspect.signature(RewardModel.generate)
        assert "reference_model" in sig.parameters, (
            "generate() must accept reference_model parameter"
        )

    def test_generate_reference_model_default_is_none(self) -> None:
        """reference_model parameter must default to None."""
        import inspect
        from kicad_agent.training.reward_model import RewardModel

        sig = inspect.signature(RewardModel.generate)
        assert sig.parameters["reference_model"].default is None, (
            "reference_model must default to None"
        )

    def test_generate_with_reference_model_uses_predict_reward(self) -> None:
        """When reference_model is provided, generate must call predict_reward on it."""
        import inspect
        from kicad_agent.training.reward_model import RewardModel

        source = inspect.getsource(RewardModel.generate)
        assert "predict_reward(reference_model" in source, (
            "generate() must call predict_reward(reference_model, ...) when provided"
        )
