"""TDD tests for SchematicReviewer orchestrator (Phase 48.5 Plan 03).

Tests the reviewer pipeline, ReviewSchematicOp schema, vision finding parser,
and executor query handler integration.
"""
from unittest.mock import MagicMock, patch

import pytest

from kicad_agent.spatial.primitives import SpatialBox


# Reuse mock helpers from test_schematic_readability
from test_schematic_readability import (
    _MockSymbol,
    _make_mock_ir,
    COMPONENTS_CLEAN,
    COMPONENTS_OVERLAP,
    LABELS_CLEAN,
)


# ---------------------------------------------------------------------------
# TestReviewSchematicOp
# ---------------------------------------------------------------------------


class TestReviewSchematicOp:
    """Tests for ReviewSchematicOp schema."""

    def test_default_values(self):
        """Op has sensible defaults."""
        from kicad_agent.ops._schema_readability import ReviewSchematicOp

        op = ReviewSchematicOp(file_path="test.kicad_sch")
        assert op.operation_type == "review_schematic"
        assert op.vision is False
        assert op.output_format == "markdown"
        assert op.config_path is None

    def test_all_fields_set(self):
        """Op accepts all fields."""
        from kicad_agent.ops._schema_readability import ReviewSchematicOp

        op = ReviewSchematicOp(
            file_path="test.kicad_sch",
            vision=True,
            output_format="json",
            config_path="/path/to/config.yaml",
        )
        assert op.vision is True
        assert op.output_format == "json"
        assert op.config_path == "/path/to/config.yaml"

    def test_invalid_format_rejected(self):
        """Op rejects invalid output_format."""
        from kicad_agent.ops._schema_readability import ReviewSchematicOp
        from pydantic import ValidationError

        with pytest.raises(ValidationError):
            ReviewSchematicOp(file_path="test.kicad_sch", output_format="xml")


# ---------------------------------------------------------------------------
# TestVisionFindingParsing
# ---------------------------------------------------------------------------


class TestVisionFindingParsing:
    """Tests for SchematicReviewer._parse_vision_findings."""

    def test_parses_bullet_points(self):
        """Bullet-point items become VisionFindings."""
        from kicad_agent.analysis.schematic_reviewer import SchematicReviewer

        text = """
- Critical: Component U1 overlaps with R2
- Warning: Label IN is too close to OUT
- Suggestion: Consider moving C1 for better flow
"""
        findings = SchematicReviewer._parse_vision_findings(text)
        assert len(findings) == 3
        assert findings[0].severity == "critical"
        assert findings[1].severity == "warning"
        assert findings[2].severity == "suggestion"

    def test_parses_numbered_items(self):
        """Numbered items are parsed as findings."""
        from kicad_agent.analysis.schematic_reviewer import SchematicReviewer

        text = """
1. Critical issue with spacing
2. Warning about wire routing
3. Info suggestion for grouping
"""
        findings = SchematicReviewer._parse_vision_findings(text)
        assert len(findings) == 3

    def test_empty_text_returns_empty(self):
        """Empty review text produces no findings."""
        from kicad_agent.analysis.schematic_reviewer import SchematicReviewer

        findings = SchematicReviewer._parse_vision_findings("")
        assert len(findings) == 0

    def test_plain_text_no_bullets_no_findings(self):
        """Plain prose without bullet/number markers produces no findings."""
        from kicad_agent.analysis.schematic_reviewer import SchematicReviewer

        text = "This schematic looks great. Overall readability: excellent."
        findings = SchematicReviewer._parse_vision_findings(text)
        assert len(findings) == 0


# ---------------------------------------------------------------------------
# TestSchematicReviewer
# ---------------------------------------------------------------------------


class TestSchematicReviewer:
    """Tests for SchematicReviewer orchestrator."""

    def test_review_returns_report(self):
        """review() returns a SchematicReviewReport."""
        from kicad_agent.analysis.schematic_reviewer import (
            SchematicReviewer,
            SchematicReviewReport,
        )

        ir = _make_mock_ir(components=COMPONENTS_CLEAN, labels=LABELS_CLEAN)
        reviewer = SchematicReviewer(ir)
        report = reviewer.review()

        assert isinstance(report, SchematicReviewReport)
        assert 0.0 <= report.srs <= 1.0
        assert isinstance(report.readability.factors, dict)
        assert len(report.vision_findings) == 0  # vision=False by default

    def test_review_with_overlapping_components(self):
        """Overlapping components produce rule violations."""
        from kicad_agent.analysis.schematic_reviewer import SchematicReviewer

        ir = _make_mock_ir(components=COMPONENTS_OVERLAP)
        reviewer = SchematicReviewer(ir)
        report = reviewer.review()

        assert len(report.rule_report.violations) > 0

    def test_review_captures_file_path(self):
        """Report includes file_path from IR."""
        from kicad_agent.analysis.schematic_reviewer import SchematicReviewer

        ir = _make_mock_ir(components=COMPONENTS_CLEAN)
        ir.file_path = "/path/to/test.kicad_sch"
        reviewer = SchematicReviewer(ir)
        report = reviewer.review()

        assert report.file_path == "/path/to/test.kicad_sch"

    @patch("kicad_agent.analysis.schematic_reviewer.SchematicReviewer.render_schematic")
    @patch("kicad_agent.analysis.schematic_reviewer.SchematicReviewer.vision_review")
    def test_review_with_vision_calls_render(self, mock_vision, mock_render):
        """review(vision=True) calls render_schematic and vision_review."""
        from kicad_agent.analysis.schematic_reviewer import SchematicReviewer

        mock_render.return_value = "/tmp/rendered.pdf"
        mock_vision.return_value = ()

        ir = _make_mock_ir(components=COMPONENTS_CLEAN)
        reviewer = SchematicReviewer(ir)
        report = reviewer.review(vision=True)

        mock_render.assert_called_once()
        mock_vision.assert_called_once_with("/tmp/rendered.pdf")
        assert report.rendered_path == "/tmp/rendered.pdf"

    @patch("kicad_agent.analysis.schematic_reviewer.SchematicReviewer.render_schematic")
    def test_review_vision_handles_render_failure(self, mock_render):
        """If render fails, vision findings stay empty."""
        from kicad_agent.analysis.schematic_reviewer import SchematicReviewer

        mock_render.return_value = None

        ir = _make_mock_ir(components=COMPONENTS_CLEAN)
        reviewer = SchematicReviewer(ir)
        report = reviewer.review(vision=True)

        assert report.rendered_path is None
        assert len(report.vision_findings) == 0

    def test_review_with_disabled_rules(self):
        """Disabled rules are excluded from report."""
        from kicad_agent.analysis.schematic_reviewer import SchematicReviewer

        ir = _make_mock_ir(components=COMPONENTS_OVERLAP)
        reviewer = SchematicReviewer(ir)
        report = reviewer.review(disabled_rules={"SCHEMATIC_OVERLAP_01"})

        overlap_violations = [
            v for v in report.rule_report.violations
            if v.rule_id == "SCHEMATIC_OVERLAP_01"
        ]
        assert len(overlap_violations) == 0


# ---------------------------------------------------------------------------
# TestExecutorQueryHandler
# ---------------------------------------------------------------------------


class TestExecutorQueryHandler:
    """Tests for the review_schematic executor query handler."""

    def test_schema_validates(self):
        """ReviewSchematicOp validates correctly."""
        from kicad_agent.ops._schema_readability import ReviewSchematicOp

        op = ReviewSchematicOp(
            operation_type="review_schematic",
            file_path="test.kicad_sch",
        )
        assert op.operation_type == "review_schematic"

    def test_query_handler_registered(self):
        """review_schematic query handler exists in executor registry."""
        from kicad_agent.ops.executor import _QUERY_HANDLERS

        assert "review_schematic" in _QUERY_HANDLERS


# ---------------------------------------------------------------------------
# TestCLIRegistration
# ---------------------------------------------------------------------------


class TestCLIRegistration:
    """Tests for review-schematic CLI subcommand registration."""

    def test_cmd_module_importable(self):
        """review_schematic_cmd module is importable."""
        from kicad_agent.cli.review_schematic_cmd import review_schematic_command, register_parser
        assert callable(review_schematic_command)
        assert callable(register_parser)
