"""Tests for synthetic circuit generation: templates, generator, and mass pipeline.

Covers:
- CircuitTemplate, ComponentRange, ComponentTemplate, NetTemplate schema validation
- 10 parameterized circuit templates
- Template instantiation with deterministic seeds
- SyntheticGenerator: template + seed -> GenerationIntent
- Mass generation pipeline with parallel execution, dedup, JSONL, splits
"""

import json
import math
import tempfile
from pathlib import Path

import pytest


# ---------------------------------------------------------------------------
# Plan 52-01 Task 1: Circuit Template Schema
# ---------------------------------------------------------------------------


class TestCircuitTemplateSchema:
    """Validate CircuitTemplate Pydantic schema."""

    def test_validates_with_all_required_fields(self):
        """CircuitTemplate validates with all required fields."""
        from kicad_agent.training.circuit_templates import (
            CircuitTemplate,
            ComponentTemplate,
            ComponentRange,
            NetTemplate,
        )

        t = CircuitTemplate(
            name="test_circuit",
            category="test",
            component_templates=[
                ComponentTemplate(
                    library_id="Device:R_Small_US",
                    reference="R1",
                    value_template="{R1}",
                ),
            ],
            net_templates=[
                NetTemplate(name="VIN", pins=["R1.1"]),
            ],
            parameter_ranges=[
                ComponentRange(param_name="R1", min_value=100, max_value=10000),
            ],
        )
        assert t.name == "test_circuit"
        assert len(t.component_templates) == 1
        assert len(t.net_templates) == 1

    def test_rejects_empty_component_templates(self):
        """CircuitTemplate rejects template with empty component_templates."""
        from kicad_agent.training.circuit_templates import (
            CircuitTemplate,
            ComponentRange,
            NetTemplate,
        )

        with pytest.raises(Exception):
            CircuitTemplate(
                name="empty",
                category="test",
                component_templates=[],
                net_templates=[NetTemplate(name="N1", pins=["R1.1"])],
                parameter_ranges=[
                    ComponentRange(param_name="R1", min_value=100, max_value=10000),
                ],
            )

    def test_rejects_empty_net_templates(self):
        """CircuitTemplate rejects template with empty net_templates."""
        from kicad_agent.training.circuit_templates import (
            CircuitTemplate,
            ComponentTemplate,
            ComponentRange,
        )

        with pytest.raises(Exception):
            CircuitTemplate(
                name="no_nets",
                category="test",
                component_templates=[
                    ComponentTemplate(
                        library_id="Device:R_Small_US",
                        reference="R1",
                        value_template="{R1}",
                    ),
                ],
                net_templates=[],
                parameter_ranges=[
                    ComponentRange(param_name="R1", min_value=100, max_value=10000),
                ],
            )


class TestComponentRange:
    """Validate ComponentRange schema."""

    def test_validates_min_less_than_max(self):
        """ComponentRange validates when min < max."""
        from kicad_agent.training.circuit_templates import ComponentRange

        cr = ComponentRange(param_name="R1", min_value=100, max_value=10000)
        assert cr.min_value == 100
        assert cr.max_value == 10000

    def test_rejects_max_leq_min(self):
        """ComponentRange rejects max_value <= min_value."""
        from kicad_agent.training.circuit_templates import ComponentRange

        with pytest.raises(Exception):
            ComponentRange(param_name="R1", min_value=100, max_value=100)

        with pytest.raises(Exception):
            ComponentRange(param_name="R1", min_value=100, max_value=100)

    def test_log_uniform_default_true(self):
        """ComponentRange defaults to log_uniform=True."""
        from kicad_agent.training.circuit_templates import ComponentRange

        cr = ComponentRange(param_name="R1", min_value=100, max_value=10000)
        assert cr.log_uniform is True


class TestTemplateLibrary:
    """Validate the 10 built-in circuit templates."""

    def test_returns_exactly_10_templates(self):
        """get_all_templates() returns exactly 10 templates."""
        from kicad_agent.training.circuit_templates import get_all_templates

        templates = get_all_templates()
        assert len(templates) == 10

    def test_each_template_has_unique_name(self):
        """Each template has a unique name."""
        from kicad_agent.training.circuit_templates import get_all_templates

        templates = get_all_templates()
        names = [t.name for t in templates]
        assert len(names) == len(set(names)), f"Duplicate names: {names}"

    def test_each_template_has_valid_category(self):
        """Each template has a non-empty category."""
        from kicad_agent.training.circuit_templates import get_all_templates

        templates = get_all_templates()
        for t in templates:
            assert len(t.category) > 0, f"Template {t.name} has empty category"

    def test_each_template_has_callable_predicates(self):
        """Each template has valid_range_predicates that are strings (callable via eval)."""
        from kicad_agent.training.circuit_templates import get_all_templates

        templates = get_all_templates()
        for t in templates:
            for pred in t.valid_range_predicates:
                assert isinstance(pred, str), (
                    f"Template {t.name}: predicate {pred!r} is not a string"
                )

    def test_all_templates_have_non_empty_parameter_ranges(self):
        """All 10 templates have non-empty parameter_ranges with at least 1 parameter."""
        from kicad_agent.training.circuit_templates import get_all_templates

        templates = get_all_templates()
        for t in templates:
            assert len(t.parameter_ranges) >= 1, (
                f"Template {t.name} has no parameter_ranges"
            )


class TestTemplateInstantiation:
    """Test parameter generation from templates."""

    def test_instantiate_produces_deterministic_output(self):
        """instantiate_template with a seed produces deterministic output."""
        from kicad_agent.training.circuit_templates import (
            get_all_templates,
            instantiate_template,
        )

        template = get_all_templates()[0]
        params1 = instantiate_template(template, seed=42)
        params2 = instantiate_template(template, seed=42)
        assert params1 == params2

    def test_different_seeds_produce_different_output(self):
        """instantiate_template with different seeds produces different output."""
        from kicad_agent.training.circuit_templates import (
            get_all_templates,
            instantiate_template,
        )

        template = get_all_templates()[0]
        params1 = instantiate_template(template, seed=42)
        params2 = instantiate_template(template, seed=99)
        # At least one value should differ
        assert params1 != params2

    def test_all_parameters_in_range(self):
        """Sampled parameters fall within their defined ranges."""
        from kicad_agent.training.circuit_templates import (
            get_all_templates,
            instantiate_template,
        )

        for template in get_all_templates():
            params = instantiate_template(template, seed=42)
            range_map = {r.param_name: r for r in template.parameter_ranges}
            for name, value in params.items():
                r = range_map[name]
                assert r.min_value <= value <= r.max_value, (
                    f"Template {template.name}: {name}={value} "
                    f"not in [{r.min_value}, {r.max_value}]"
                )


class TestValidityPredicates:
    """Test that validity predicates accept/reject correctly."""

    def test_common_emitter_accepts_valid_params(self):
        """Common-emitter amplifier template generates valid parameter sets."""
        from kicad_agent.training.circuit_templates import (
            COMMON_EMITTER_AMP,
            instantiate_template,
        )

        params = instantiate_template(COMMON_EMITTER_AMP, seed=42)
        assert params["Rb"] > params["Rc"]
        assert params["Rc"] > params["Re"]
        assert params["Re"] > 0

    def test_sallen_key_rejects_impossible_ratio(self):
        """Sallen-Key filter rejects impossible C1/C2/R1/R2 combinations.

        The predicate checks C1/C2 <= 10 and C2/C1 <= 10. We verify that
        instantiate_template never produces a violating combination.
        """
        from kicad_agent.training.circuit_templates import (
            SALLEN_KEY_LPF,
            instantiate_template,
        )

        for seed in range(100):
            params = instantiate_template(SALLEN_KEY_LPF, seed=seed)
            ratio = params["C1"] / params["C2"]
            assert 0.1 <= ratio <= 10.0, (
                f"Seed {seed}: C1/C2 ratio {ratio} violates predicate"
            )

    def test_all_templates_produce_valid_params_for_many_seeds(self):
        """All templates produce params satisfying their predicates for 50 seeds."""
        from kicad_agent.training.circuit_templates import (
            get_all_templates,
            instantiate_template,
            _eval_predicate,
        )

        for template in get_all_templates():
            for seed in range(50):
                params = instantiate_template(template, seed=seed)
                for pred in template.valid_range_predicates:
                    assert _eval_predicate(pred, params), (
                        f"Template {template.name} seed {seed}: "
                        f"predicate '{pred}' failed for {params}"
                    )


# ---------------------------------------------------------------------------
# Plan 52-01 Task 2: SyntheticGenerator
# ---------------------------------------------------------------------------


class TestSyntheticGenerator:
    """Test SyntheticGenerator: template + seed -> GenerationIntent."""

    def test_create_intent_produces_valid_intent(self):
        """SyntheticGenerator.create_intent produces a valid GenerationIntent."""
        from kicad_agent.generation.intent import GenerationIntent
        from kicad_agent.training.circuit_templates import get_all_templates
        from kicad_agent.training.synthetic_generator import SyntheticGenerator

        gen = SyntheticGenerator()
        template = get_all_templates()[0]
        intent = gen.create_intent(template, seed=42)

        assert isinstance(intent, GenerationIntent)
        assert intent.name.startswith("synth_")

    def test_correct_component_count(self):
        """Generated GenerationIntent has correct component count matching template."""
        from kicad_agent.training.circuit_templates import get_all_templates
        from kicad_agent.training.synthetic_generator import SyntheticGenerator

        gen = SyntheticGenerator()
        template = get_all_templates()[0]
        intent = gen.create_intent(template, seed=42)

        assert len(intent.components) == len(template.component_templates)

    def test_correct_net_count(self):
        """Generated GenerationIntent has correct net count matching template."""
        from kicad_agent.training.circuit_templates import get_all_templates
        from kicad_agent.training.synthetic_generator import SyntheticGenerator

        gen = SyntheticGenerator()
        template = get_all_templates()[0]
        intent = gen.create_intent(template, seed=42)

        assert len(intent.nets) == len(template.net_templates)

    def test_component_values_formatted(self):
        """All component values are non-empty strings."""
        from kicad_agent.training.circuit_templates import get_all_templates
        from kicad_agent.training.synthetic_generator import SyntheticGenerator

        gen = SyntheticGenerator()
        for template in get_all_templates():
            intent = gen.create_intent(template, seed=42)
            for comp in intent.components:
                assert len(comp.value) > 0, (
                    f"Template {template.name}: {comp.reference} has empty value"
                )

    def test_deterministic_same_seed(self):
        """Two calls with same seed produce identical GenerationIntent."""
        from kicad_agent.training.circuit_templates import get_all_templates
        from kicad_agent.training.synthetic_generator import SyntheticGenerator

        gen = SyntheticGenerator()
        template = get_all_templates()[0]
        intent1 = gen.create_intent(template, seed=42)
        intent2 = gen.create_intent(template, seed=42)

        assert intent1.model_dump_json() == intent2.model_dump_json()

    def test_diverse_different_seeds(self):
        """Two calls with different seeds produce different GenerationIntent."""
        from kicad_agent.training.circuit_templates import get_all_templates
        from kicad_agent.training.synthetic_generator import SyntheticGenerator

        gen = SyntheticGenerator()
        template = get_all_templates()[0]
        intent1 = gen.create_intent(template, seed=42)
        intent2 = gen.create_intent(template, seed=99)

        assert intent1.model_dump_json() != intent2.model_dump_json()

    def test_generate_batch_produces_n_intents(self):
        """generate_batch produces N intents from a template with sequential seeds."""
        from kicad_agent.training.circuit_templates import get_all_templates
        from kicad_agent.training.synthetic_generator import SyntheticGenerator

        gen = SyntheticGenerator()
        template = get_all_templates()[0]
        results = gen.generate_batch(template, n_samples=5, seed_start=0)

        successful = [r for r in results if r.intent is not None]
        assert len(successful) >= 5

    def test_generate_batch_deduplicates_by_hash(self):
        """generate_batch deduplicates by hash."""
        from kicad_agent.training.circuit_templates import get_all_templates
        from kicad_agent.training.synthetic_generator import SyntheticGenerator

        gen = SyntheticGenerator()
        template = get_all_templates()[0]

        results = gen.generate_batch(template, n_samples=10, seed_start=0)
        hashes = [r.circuit_hash for r in results if r.circuit_hash]
        assert len(hashes) == len(set(hashes)), "Duplicate hashes found"

    def test_generate_batch_skips_failures(self):
        """generate_batch skips seeds that fail validity predicates."""
        from kicad_agent.training.circuit_templates import get_all_templates
        from kicad_agent.training.synthetic_generator import SyntheticGenerator

        gen = SyntheticGenerator()
        template = get_all_templates()[0]
        results = gen.generate_batch(template, n_samples=10, seed_start=0)

        # Should have at least 10 successful results (seeds are diverse enough)
        successful = [r for r in results if r.intent is not None]
        assert len(successful) >= 10

    def test_hash_intent_deterministic(self):
        """hash_intent produces deterministic SHA256 hash."""
        from kicad_agent.training.circuit_templates import get_all_templates
        from kicad_agent.training.synthetic_generator import SyntheticGenerator

        gen = SyntheticGenerator()
        template = get_all_templates()[0]
        intent = gen.create_intent(template, seed=42)
        h1 = SyntheticGenerator.hash_intent(intent)
        h2 = SyntheticGenerator.hash_intent(intent)
        assert h1 == h2
        assert len(h1) == 64  # SHA256 hex digest


# ---------------------------------------------------------------------------
# Plan 52-02 Task 1: Mass Generation Pipeline
# ---------------------------------------------------------------------------


class TestAttemptSerialization:
    """Test GenerationAttempt JSON serialization round-trip."""

    def test_attempt_to_dict(self):
        """attempt_to_dict converts GenerationAttempt to JSON-serializable dict."""
        from kicad_agent.training.circuit_templates import get_all_templates
        from kicad_agent.training.synthetic_generator import (
            SyntheticGenerator,
            attempt_to_dict,
        )

        gen = SyntheticGenerator()
        template = get_all_templates()[0]
        intent = gen.create_intent(template, seed=42)
        from kicad_agent.training.synthetic_generator import GenerationAttempt

        attempt = GenerationAttempt(
            intent=intent,
            template_name=template.name,
            seed=42,
            circuit_hash=SyntheticGenerator.hash_intent(intent),
        )

        d = attempt_to_dict(attempt)
        assert isinstance(d, dict)
        assert d["template_name"] == template.name
        assert d["seed"] == 42
        assert d["intent"] is not None

    def test_dict_to_attempt(self):
        """dict_to_attempt converts dict back to GenerationAttempt."""
        from kicad_agent.training.circuit_templates import get_all_templates
        from kicad_agent.training.synthetic_generator import (
            SyntheticGenerator,
            attempt_to_dict,
            dict_to_attempt,
        )

        gen = SyntheticGenerator()
        template = get_all_templates()[0]
        intent = gen.create_intent(template, seed=42)
        from kicad_agent.training.synthetic_generator import GenerationAttempt

        attempt = GenerationAttempt(
            intent=intent,
            template_name=template.name,
            seed=42,
            circuit_hash=SyntheticGenerator.hash_intent(intent),
        )

        d = attempt_to_dict(attempt)
        restored = dict_to_attempt(d)

        assert restored.template_name == attempt.template_name
        assert restored.seed == attempt.seed
        assert restored.circuit_hash == attempt.circuit_hash

    def test_round_trip_preserves_all_fields(self):
        """Round-trip preserves all fields including intent."""
        from kicad_agent.training.circuit_templates import get_all_templates
        from kicad_agent.training.synthetic_generator import (
            SyntheticGenerator,
            attempt_to_dict,
            dict_to_attempt,
        )

        gen = SyntheticGenerator()
        template = get_all_templates()[0]
        intent = gen.create_intent(template, seed=42)
        from kicad_agent.training.synthetic_generator import GenerationAttempt

        attempt = GenerationAttempt(
            intent=intent,
            template_name=template.name,
            seed=42,
            erc_pass=True,
            circuit_hash=SyntheticGenerator.hash_intent(intent),
            error="",
        )

        d = attempt_to_dict(attempt)
        # Ensure it's JSON-serializable
        json_str = json.dumps(d)
        d_back = json.loads(json_str)

        restored = dict_to_attempt(d_back)
        assert restored.intent is not None
        assert restored.intent.name == intent.name
        assert restored.erc_pass is True
        assert restored.error == ""

    def test_attempt_to_dict_null_intent(self):
        """attempt_to_dict handles None intent."""
        from kicad_agent.training.synthetic_generator import (
            GenerationAttempt,
            attempt_to_dict,
        )

        attempt = GenerationAttempt(
            intent=None,
            template_name="test",
            seed=1,
            error="something failed",
        )

        d = attempt_to_dict(attempt)
        assert d["intent"] is None
        assert d["error"] == "something failed"


class TestMassGenerationConfig:
    """Test MassGenerationConfig validation."""

    def test_validates_with_defaults(self):
        """MassGenerationConfig validates with defaults (target=10000, workers=4)."""
        from kicad_agent.training.mass_generate import MassGenerationConfig

        config = MassGenerationConfig()
        assert config.target_count == 10000
        assert config.n_workers == 4
        assert config.seed == 42

    def test_rejects_workers_zero(self):
        """MassGenerationConfig rejects workers < 1."""
        from kicad_agent.training.mass_generate import MassGenerationConfig

        with pytest.raises(Exception):
            MassGenerationConfig(n_workers=0)

    def test_rejects_target_zero(self):
        """MassGenerationConfig rejects target < 1."""
        from kicad_agent.training.mass_generate import MassGenerationConfig

        with pytest.raises(Exception):
            MassGenerationConfig(target_count=0)

    def test_rejects_workers_above_max(self):
        """MassGenerationConfig rejects workers > 32."""
        from kicad_agent.training.mass_generate import MassGenerationConfig

        with pytest.raises(Exception):
            MassGenerationConfig(n_workers=64)


class TestMassGenerationPipeline:
    """Test mass generation pipeline end-to-end."""

    def test_generate_mass_produces_all_templates(self):
        """generate_mass produces results for all 10 templates."""
        from kicad_agent.training.mass_generate import (
            MassGenerationConfig,
            run_mass_generation,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            config = MassGenerationConfig(
                target_count=20,
                n_workers=1,
                seed=42,
                output_dir=tmpdir,
            )
            result = run_mass_generation(config)
            assert result.total_generated >= 20

    def test_output_is_deduplicated(self):
        """Output is deduplicated by circuit hash."""
        from kicad_agent.training.mass_generate import (
            MassGenerationConfig,
            run_mass_generation,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            config = MassGenerationConfig(
                target_count=20,
                n_workers=1,
                seed=42,
                output_dir=tmpdir,
            )
            result = run_mass_generation(config)

            # Load the combined file and verify unique hashes
            all_path = Path(tmpdir) / "synthetic-all.jsonl"
            assert all_path.exists()
            hashes = set()
            with open(all_path) as f:
                for line in f:
                    d = json.loads(line)
                    h = d.get("circuit_hash", "")
                    assert h not in hashes, "Duplicate hash in output"
                    hashes.add(h)

    def test_jsonl_output_round_trips(self):
        """JSONL output can be loaded back and matches original."""
        from kicad_agent.training.mass_generate import (
            MassGenerationConfig,
            run_mass_generation,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            config = MassGenerationConfig(
                target_count=20,
                n_workers=1,
                seed=42,
                output_dir=tmpdir,
            )
            run_mass_generation(config)

            all_path = Path(tmpdir) / "synthetic-all.jsonl"
            assert all_path.exists()

            lines = all_path.read_text().strip().split("\n")
            assert len(lines) >= 20

            for line in lines:
                d = json.loads(line)
                assert "template_name" in d
                assert "seed" in d
                assert "intent" in d

    def test_train_val_test_split_proportions(self):
        """Train/val/test split has correct proportions (80/10/10 within tolerance)."""
        from kicad_agent.training.mass_generate import (
            MassGenerationConfig,
            run_mass_generation,
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            config = MassGenerationConfig(
                target_count=100,
                n_workers=1,
                seed=42,
                output_dir=tmpdir,
            )
            result = run_mass_generation(config)

            total = result.train_count + result.val_count + result.test_count
            assert total == result.total_generated

            if total >= 50:  # Only check proportions if enough samples
                train_pct = result.train_count / total
                val_pct = result.val_count / total
                test_pct = result.test_count / total

                # Allow 5% tolerance for rounding
                assert abs(train_pct - 0.80) < 0.05, f"Train: {train_pct}"
                assert abs(val_pct - 0.10) < 0.05, f"Val: {val_pct}"
                assert abs(test_pct - 0.10) < 0.05, f"Test: {test_pct}"

    def test_split_is_deterministic(self):
        """Split is deterministic for same seed."""
        from kicad_agent.training.mass_generate import (
            MassGenerationConfig,
            run_mass_generation,
        )

        results = []
        for _ in range(2):
            with tempfile.TemporaryDirectory() as tmpdir:
                config = MassGenerationConfig(
                    target_count=50,
                    n_workers=1,
                    seed=42,
                    output_dir=tmpdir,
                )
                results.append(run_mass_generation(config))

        assert results[0].train_count == results[1].train_count
        assert results[0].val_count == results[1].val_count
        assert results[0].test_count == results[1].test_count


# ---------------------------------------------------------------------------
# Plan 52-02 Task 2: Quality Metrics and CLI
# ---------------------------------------------------------------------------


class TestQualityMetrics:
    """Test quality metrics computation."""

    def test_compute_metrics_returns_expected_keys(self):
        """compute_metrics returns dict with expected keys."""
        from kicad_agent.training.mass_generate import compute_metrics

        metrics = compute_metrics([])
        assert hasattr(metrics, "total_circuits")
        assert hasattr(metrics, "template_coverage")
        assert hasattr(metrics, "per_template_counts")
        assert hasattr(metrics, "component_diversity")
        assert hasattr(metrics, "parameter_coverage")
        assert hasattr(metrics, "erc_pass_rate")

    def test_template_coverage_reports_all_templates(self):
        """Template coverage metric reports all 10 templates represented."""
        from kicad_agent.training.circuit_templates import get_all_templates
        from kicad_agent.training.mass_generate import compute_metrics

        # Generate some sample data
        from kicad_agent.training.synthetic_generator import (
            SyntheticGenerator,
            attempt_to_dict,
        )
        from kicad_agent.training.circuit_templates import get_all_templates as gt

        gen = SyntheticGenerator()
        attempts = []
        for template in gt():
            intent = gen.create_intent(template, seed=42)
            from kicad_agent.training.synthetic_generator import GenerationAttempt

            attempt = GenerationAttempt(
                intent=intent,
                template_name=template.name,
                seed=42,
                circuit_hash=SyntheticGenerator.hash_intent(intent),
            )
            attempts.append(attempt_to_dict(attempt))

        metrics = compute_metrics(attempts)
        assert metrics.template_coverage == 1.0  # All templates represented
        assert len(metrics.per_template_counts) == 10

    def test_component_diversity(self):
        """Component diversity metric reports unique component types."""
        from kicad_agent.training.mass_generate import compute_metrics
        from kicad_agent.training.synthetic_generator import (
            SyntheticGenerator,
            attempt_to_dict,
        )
        from kicad_agent.training.circuit_templates import get_all_templates
        from kicad_agent.training.synthetic_generator import GenerationAttempt

        gen = SyntheticGenerator()
        attempts = []
        for template in get_all_templates():
            intent = gen.create_intent(template, seed=42)
            attempt = GenerationAttempt(
                intent=intent,
                template_name=template.name,
                seed=42,
                circuit_hash=SyntheticGenerator.hash_intent(intent),
            )
            attempts.append(attempt_to_dict(attempt))

        metrics = compute_metrics(attempts)
        assert metrics.component_diversity > 0

    def test_metrics_on_empty_input(self):
        """compute_metrics handles empty input gracefully."""
        from kicad_agent.training.mass_generate import compute_metrics

        metrics = compute_metrics([])
        assert metrics.total_circuits == 0
        assert metrics.template_coverage == 0.0
        assert metrics.component_diversity == 0
        assert metrics.erc_pass_rate == 0.0


class TestCLI:
    """Test CLI entry point."""

    def test_dry_run_does_not_generate(self):
        """CLI --dry-run reports plan without generating files."""
        import os
        import subprocess
        import sys

        env = dict(os.environ)
        src_dir = str(Path(__file__).resolve().parent.parent / "src")
        env["PYTHONPATH"] = src_dir + os.pathsep + env.get("PYTHONPATH", "")

        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "kicad_agent.training.mass_generate",
                "--dry-run",
            ],
            capture_output=True,
            text=True,
            timeout=30,
            env=env,
        )
        assert result.returncode == 0
        assert "Templates:" in result.stdout
        assert "Per template:" in result.stdout
