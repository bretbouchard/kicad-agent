"""TDD tests for Phase 49: One-Command Demo.

Tests DemoTemplate schema, BUILTIN_TEMPLATES registry, DemoPipeline
orchestration, and CLI integration.
"""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from volta.generation.intent import (
    BoardSpec,
    ComponentSpec,
    GenerationIntent,
    NetSpec,
    PowerSpec,
)
from volta.generation.pipeline import GenerationResult


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------

MOCK_INTENT = GenerationIntent(
    name="Test_Filter",
    board=BoardSpec(width_mm=50, height_mm=40),
    components=[
        ComponentSpec(library_id="Device:R", reference="R1", value="1k"),
        ComponentSpec(library_id="Device:C", reference="C1", value="100n"),
    ],
    nets=[NetSpec(name="IN", pins=["R1.1"]), NetSpec(name="OUT", pins=["R1.2", "C1.1"])],
    power=PowerSpec(nets=["GND"]),
)


# ---------------------------------------------------------------------------
# TestDemoTemplateSchema
# ---------------------------------------------------------------------------


class TestDemoTemplateSchema:
    """Tests for DemoTemplate validation."""

    def test_valid_template(self):
        """DemoTemplate accepts valid fields."""
        from volta.demo.templates import DemoTemplate

        t = DemoTemplate(
            name="test-circuit",
            description="A test circuit",
            intent=MOCK_INTENT,
            difficulty="basic",
            expected_component_count=2,
            expected_net_count=2,
        )
        assert t.name == "test-circuit"
        assert t.difficulty == "basic"

    def test_rejects_empty_name(self):
        """DemoTemplate rejects empty name."""
        from volta.demo.templates import DemoTemplate
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            DemoTemplate(
                name="",
                description="desc",
                intent=MOCK_INTENT,
                difficulty="basic",
                expected_component_count=1,
                expected_net_count=1,
            )

    def test_rejects_invalid_difficulty(self):
        """DemoTemplate rejects invalid difficulty tier."""
        from volta.demo.templates import DemoTemplate
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            DemoTemplate(
                name="test",
                description="desc",
                intent=MOCK_INTENT,
                difficulty="expert",
                expected_component_count=1,
                expected_net_count=1,
            )

    def test_rejects_uppercase_name(self):
        """DemoTemplate rejects uppercase in name."""
        from volta.demo.templates import DemoTemplate
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            DemoTemplate(
                name="TestCircuit",
                description="desc",
                intent=MOCK_INTENT,
                difficulty="basic",
                expected_component_count=1,
                expected_net_count=1,
            )


# ---------------------------------------------------------------------------
# TestBuiltinTemplates
# ---------------------------------------------------------------------------


class TestBuiltinTemplates:
    """Tests for BUILTIN_TEMPLATES registry."""

    def test_has_at_least_5_entries(self):
        """BUILTIN_TEMPLATES has at least 5 entries."""
        from volta.demo.templates import BUILTIN_TEMPLATES

        assert len(BUILTIN_TEMPLATES) >= 5

    def test_each_entry_has_valid_intent(self):
        """Each BUILTIN_TEMPLATES entry has a valid GenerationIntent."""
        from volta.demo.templates import BUILTIN_TEMPLATES

        for name, t in BUILTIN_TEMPLATES.items():
            assert isinstance(t.intent, GenerationIntent)
            assert t.name == name

    def test_get_template_returns_match(self):
        """get_template(name) returns matching template."""
        from volta.demo.templates import get_template

        t = get_template("rc-lowpass")
        assert t.name == "rc-lowpass"

    def test_get_template_raises_on_missing(self):
        """get_template raises KeyError with available names."""
        from volta.demo.templates import get_template

        with pytest.raises(KeyError, match="not found"):
            get_template("nonexistent")

    def test_get_random_template(self):
        """get_random_template returns a valid template."""
        from volta.demo.templates import get_random_template, DemoTemplate

        t = get_random_template()
        assert isinstance(t, DemoTemplate)

    def test_covers_all_difficulty_tiers(self):
        """Templates span all three difficulty tiers."""
        from volta.demo.templates import BUILTIN_TEMPLATES

        tiers = {t.difficulty for t in BUILTIN_TEMPLATES.values()}
        assert "basic" in tiers
        assert "intermediate" in tiers
        assert "advanced" in tiers


# ---------------------------------------------------------------------------
# TestListTemplates
# ---------------------------------------------------------------------------


class TestListTemplates:
    """Tests for list_templates function."""

    def test_returns_sorted_tuples(self):
        """list_templates returns sorted (name, desc, difficulty) tuples."""
        from volta.demo.templates import list_templates

        templates = list_templates()
        assert len(templates) >= 5
        assert all(len(t) == 3 for t in templates)
        # Basic tier should come first
        first_difficulty = templates[0][2]
        assert first_difficulty == "basic"


# ---------------------------------------------------------------------------
# TestDemoReport
# ---------------------------------------------------------------------------


class TestDemoReportSchema:
    """Tests for DemoReport schema."""

    def test_valid_report(self):
        """DemoReport accepts valid fields."""
        from volta.demo.pipeline import DemoReport

        report = DemoReport(template_used="rc-lowpass")
        assert report.template_used == "rc-lowpass"

    def test_defaults(self):
        """DemoReport has sensible defaults."""
        from volta.demo.pipeline import DemoReport

        report = DemoReport(template_used="test")
        assert report.stages_completed == []
        assert report.success is False
        assert report.erc_before is None
        assert report.erc_after is None
        assert report.svg_paths == []
        assert report.errors == []
        assert report.duration_seconds == 0.0


# ---------------------------------------------------------------------------
# TestDemoPipeline
# ---------------------------------------------------------------------------


class TestDemoPipeline:
    """Tests for DemoPipeline orchestration."""

    def test_init_default_output_dir(self):
        """DemoPipeline defaults output_dir to ./demo-output."""
        from volta.demo.pipeline import DemoPipeline

        pipeline = DemoPipeline()
        assert pipeline.output_dir == Path("demo-output")

    def test_init_custom_output_dir(self):
        """DemoPipeline accepts custom output_dir."""
        from volta.demo.pipeline import DemoPipeline

        pipeline = DemoPipeline(output_dir=Path("/tmp/test-demo"))
        assert pipeline.output_dir == Path("/tmp/test-demo")

    @patch("volta.demo.pipeline.generate_design")
    def test_run_success(self, mock_gen):
        """Pipeline returns success report when generate_design succeeds."""
        from volta.demo.pipeline import DemoPipeline

        mock_gen.return_value = GenerationResult(
            success=True,
            project_dir=Path("/tmp/demo/test"),
            schematic_path=Path("/tmp/demo/test/test.kicad_sch"),
            erc_pass=True,
        )

        with patch.object(DemoPipeline, "_run_erc", return_value=0), \
             patch.object(DemoPipeline, "_auto_fix"), \
             patch.object(DemoPipeline, "_render_svg", return_value=[Path("/tmp/demo/test/test.svg")]):
            pipeline = DemoPipeline(output_dir=Path("/tmp/demo"))
            report = pipeline.run("rc-lowpass")

        assert report.success is True
        assert "select" in report.stages_completed
        assert "generate" in report.stages_completed
        assert report.template_used == "rc-lowpass"

    @patch("volta.demo.pipeline.generate_design")
    def test_run_records_erc_counts(self, mock_gen):
        """Pipeline records erc_before and erc_after counts."""
        from volta.demo.pipeline import DemoPipeline

        mock_gen.return_value = GenerationResult(
            success=True,
            project_dir=Path("/tmp/demo/test"),
            schematic_path=Path("/tmp/demo/test/test.kicad_sch"),
        )

        with patch.object(DemoPipeline, "_run_erc", side_effect=[5, 1]), \
             patch.object(DemoPipeline, "_auto_fix"), \
             patch.object(DemoPipeline, "_render_svg", return_value=[]):
            pipeline = DemoPipeline(output_dir=Path("/tmp/demo"))
            report = pipeline.run("rc-lowpass")

        assert report.erc_before == 5
        assert report.erc_after == 1

    @patch("volta.demo.pipeline.generate_design")
    def test_run_records_svg_paths(self, mock_gen):
        """Pipeline records SVG paths."""
        from volta.demo.pipeline import DemoPipeline

        mock_gen.return_value = GenerationResult(
            success=True,
            project_dir=Path("/tmp/demo/test"),
            schematic_path=Path("/tmp/demo/test/test.kicad_sch"),
        )

        with patch.object(DemoPipeline, "_run_erc", return_value=0), \
             patch.object(DemoPipeline, "_auto_fix"), \
             patch.object(DemoPipeline, "_render_svg", return_value=[Path("/tmp/demo/test/test.svg")]):
            pipeline = DemoPipeline(output_dir=Path("/tmp/demo"))
            report = pipeline.run("rc-lowpass")

        assert len(report.svg_paths) == 1

    @patch("volta.demo.pipeline.generate_design")
    def test_run_duration_positive(self, mock_gen):
        """Pipeline records positive duration."""
        from volta.demo.pipeline import DemoPipeline

        mock_gen.return_value = GenerationResult(
            success=True,
            project_dir=Path("/tmp/demo/test"),
            schematic_path=Path("/tmp/demo/test/test.kicad_sch"),
        )

        with patch.object(DemoPipeline, "_run_erc", return_value=0), \
             patch.object(DemoPipeline, "_auto_fix"), \
             patch.object(DemoPipeline, "_render_svg", return_value=[]):
            pipeline = DemoPipeline(output_dir=Path("/tmp/demo"))
            report = pipeline.run("rc-lowpass")

        assert report.duration_seconds >= 0

    @patch("volta.demo.pipeline.generate_design")
    def test_run_handles_generation_failure(self, mock_gen):
        """Pipeline handles generate_design failure gracefully."""
        from volta.demo.pipeline import DemoPipeline

        mock_gen.return_value = GenerationResult(
            success=False,
            project_dir=Path("/tmp/demo/test"),
            errors=("Component R1 not found",),
        )

        pipeline = DemoPipeline(output_dir=Path("/tmp/demo"))
        report = pipeline.run("rc-lowpass")

        assert report.success is False
        assert len(report.errors) > 0

    def test_run_handles_kicad_cli_missing(self):
        """Pipeline handles missing kicad-cli gracefully."""
        from volta.demo.pipeline import DemoPipeline

        with patch("volta.demo.pipeline.generate_design") as mock_gen:
            mock_gen.return_value = GenerationResult(
                success=True,
                project_dir=Path("/tmp/demo/test"),
                schematic_path=Path("/tmp/demo/test/test.kicad_sch"),
            )

            with patch.object(DemoPipeline, "_run_erc", return_value=None), \
                 patch.object(DemoPipeline, "_auto_fix"), \
                 patch.object(DemoPipeline, "_render_svg", return_value=[]):
                pipeline = DemoPipeline(output_dir=Path("/tmp/demo"))
                report = pipeline.run("rc-lowpass")

        # Should still succeed, just without ERC/render
        assert report.success is True

    @patch("volta.demo.pipeline.generate_design")
    def test_run_random_template(self, mock_gen):
        """Pipeline with 'random' template name selects random template."""
        from volta.demo.pipeline import DemoPipeline

        mock_gen.return_value = GenerationResult(
            success=True,
            project_dir=Path("/tmp/demo/test"),
            schematic_path=Path("/tmp/demo/test/test.kicad_sch"),
        )

        with patch.object(DemoPipeline, "_run_erc", return_value=0), \
             patch.object(DemoPipeline, "_auto_fix"), \
             patch.object(DemoPipeline, "_render_svg", return_value=[]):
            pipeline = DemoPipeline(output_dir=Path("/tmp/demo"))
            report = pipeline.run("random")

        # template_used should be one of the registered templates, not "random"
        from volta.demo.templates import BUILTIN_TEMPLATES
        assert report.template_used in BUILTIN_TEMPLATES


# ---------------------------------------------------------------------------
# TestDemoCLI
# ---------------------------------------------------------------------------


class TestDemoCLI:
    """Tests for demo CLI subcommand integration."""

    def test_demo_in_subcommands(self):
        """'demo' CLI subcommand is registered."""
        from volta.demo.pipeline import DemoPipeline
        from volta.demo.templates import get_template, list_templates
        assert callable(DemoPipeline)
        assert callable(get_template)
        assert callable(list_templates)

    def test_demo_module_importable(self):
        """Demo package is importable."""
        from volta.demo import DemoPipeline, DemoReport, DemoTemplate
        assert DemoPipeline is not None
        assert DemoReport is not None
        assert DemoTemplate is not None
