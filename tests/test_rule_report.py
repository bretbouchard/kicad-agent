"""TDD tests for design rule report generators and CLI.

DOMAIN-04: Multi-format reporting for design rule results.

Tests cover:
- JSON report generation matches DesignRuleReport schema
- Markdown report generation with severity badges and summary
- CLI subcommand invocation with mock topology
"""
from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from kicad_agent.analysis.design_rules import (
    DesignRuleReport,
    DesignRuleViolation,
    RuleSeverity,
)


# ---------------------------------------------------------------------------
# Shared test data
# ---------------------------------------------------------------------------

MOCK_VIOLATION_WARNING = DesignRuleViolation(
    rule_id="BYPASS_CAP_01",
    description="U1 (NE5532) has no bypass capacitor on +15V",
    severity=RuleSeverity.WARNING,
    location="U1",
    suggestion="Add 100nF ceramic cap between +15V and GND near U1",
    affected_components=("U1",),
)

MOCK_VIOLATION_SUGGESTION = DesignRuleViolation(
    rule_id="FEEDBACK_01",
    description="U2 (TL072) has no compensation cap on feedback",
    severity=RuleSeverity.SUGGESTION,
    location="U2",
    suggestion="Add 22pF cap across feedback resistor",
    affected_components=("U2",),
)

MOCK_VIOLATION_CRITICAL = DesignRuleViolation(
    rule_id="POWER_01",
    description="+12V rail has no bulk decoupling capacitor",
    severity=RuleSeverity.CRITICAL,
    location="+12V",
    suggestion="Add 10uF electrolytic on +12V rail",
    affected_components=("U3", "U4"),
)

MOCK_REPORT = DesignRuleReport(
    violations=(MOCK_VIOLATION_CRITICAL, MOCK_VIOLATION_WARNING, MOCK_VIOLATION_SUGGESTION),
    schematic_path="compressor.kicad_sch",
    rules_run=8,
    rules_passed=5,
    rules_failed=3,
    elapsed_ms=45.3,
)

CLEAN_REPORT = DesignRuleReport(
    violations=(),
    schematic_path="clean-design.kicad_sch",
    rules_run=8,
    rules_passed=8,
    rules_failed=0,
    elapsed_ms=12.1,
)


# ---------------------------------------------------------------------------
# JSON Report Tests
# ---------------------------------------------------------------------------


class TestJsonReport:
    """Tests for JSON report generation."""

    def test_generate_json_report_valid_json(self):
        """JSON report is valid JSON that parses."""
        from kicad_agent.analysis.rule_report import generate_json_report

        output = generate_json_report(MOCK_REPORT)
        parsed = json.loads(output)

        assert isinstance(parsed, dict)

    def test_generate_json_report_matches_schema(self):
        """JSON report contains all DesignRuleReport fields."""
        from kicad_agent.analysis.rule_report import generate_json_report

        output = generate_json_report(MOCK_REPORT)
        parsed = json.loads(output)

        assert parsed["schematic_path"] == "compressor.kicad_sch"
        assert parsed["rules_run"] == 8
        assert parsed["rules_passed"] == 5
        assert parsed["rules_failed"] == 3
        assert len(parsed["violations"]) == 3

    def test_generate_json_report_violation_fields(self):
        """Each violation in JSON has all required fields."""
        from kicad_agent.analysis.rule_report import generate_json_report

        output = generate_json_report(MOCK_REPORT)
        parsed = json.loads(output)

        v = parsed["violations"][0]
        assert v["rule_id"] == "POWER_01"
        assert v["severity"] == "CRITICAL"
        assert v["location"] == "+12V"
        assert "description" in v
        assert "suggestion" in v

    def test_generate_json_report_roundtrip(self):
        """JSON report can be loaded back into DesignRuleReport."""
        from kicad_agent.analysis.rule_report import generate_json_report

        output = generate_json_report(MOCK_REPORT)
        restored = DesignRuleReport.model_validate_json(output)

        assert restored.schematic_path == MOCK_REPORT.schematic_path
        assert len(restored.violations) == len(MOCK_REPORT.violations)


# ---------------------------------------------------------------------------
# Markdown Report Tests
# ---------------------------------------------------------------------------


class TestMarkdownReport:
    """Tests for Markdown report generation."""

    def test_markdown_report_has_header(self):
        """Markdown report starts with proper header."""
        from kicad_agent.analysis.rule_report import generate_markdown_report

        output = generate_markdown_report(MOCK_REPORT)

        assert "# Design Rule Report" in output

    def test_markdown_report_has_severity_badges(self):
        """Markdown report uses severity badges: [!!], [!], [>], [i]."""
        from kicad_agent.analysis.rule_report import generate_markdown_report

        output = generate_markdown_report(MOCK_REPORT)

        # CRITICAL -> [!!]
        assert "[!!]" in output
        # WARNING -> [!]
        assert "[!]" in output
        # SUGGESTION -> [>]
        assert "[>]" in output

    def test_markdown_report_has_summary_table(self):
        """Markdown report has summary table with severity counts."""
        from kicad_agent.analysis.rule_report import generate_markdown_report

        output = generate_markdown_report(MOCK_REPORT)

        assert "## Summary" in output
        assert "| Severity | Count |" in output
        assert "CRITICAL" in output
        assert "WARNING" in output
        assert "SUGGESTION" in output

    def test_markdown_report_has_violation_details(self):
        """Markdown report lists each violation with details."""
        from kicad_agent.analysis.rule_report import generate_markdown_report

        output = generate_markdown_report(MOCK_REPORT)

        assert "## Violations" in output
        assert "BYPASS_CAP_01" in output
        assert "FEEDBACK_01" in output
        assert "POWER_01" in output
        assert "**Suggestion:**" in output
        assert "**Affected:**" in output

    def test_markdown_report_no_violations(self):
        """Markdown report for clean design shows no violations."""
        from kicad_agent.analysis.rule_report import generate_markdown_report

        output = generate_markdown_report(CLEAN_REPORT)

        assert "No violations found" in output
        assert "All design rules passed" in output

    def test_markdown_report_includes_schematic_path(self):
        """Markdown report shows which schematic was checked."""
        from kicad_agent.analysis.rule_report import generate_markdown_report

        output = generate_markdown_report(MOCK_REPORT)

        assert "compressor.kicad_sch" in output


# ---------------------------------------------------------------------------
# CLI Tests
# ---------------------------------------------------------------------------


class TestDesignRulesCommand:
    """Tests for design-rules CLI subcommand."""

    def _make_args(self, schematic: str, config=None, format="markdown", output=None) -> argparse.Namespace:
        """Build CLI args namespace for testing."""
        return argparse.Namespace(
            schematic=schematic,
            config=config,
            format=format,
            output=output,
        )

    def test_missing_schematic_returns_error(self):
        """CLI returns exit code 2 for missing schematic file."""
        from kicad_agent.cli.design_rules_cmd import design_rules_command

        args = self._make_args("/nonexistent/path.kicad_sch")
        result = design_rules_command(args)

        assert result == 2

    @patch("kicad_agent.cli.design_rules_cmd._extract_topology")
    def test_json_format_output(self, mock_extract):
        """CLI produces JSON output when --format json."""
        from kicad_agent.cli.design_rules_cmd import design_rules_command

        mock_extract.return_value = MagicMock()

        with tempfile.NamedTemporaryFile(suffix=".kicad_sch", delete=False) as f:
            sch_path = f.name

        try:
            args = self._make_args(sch_path, format="json")
            # Capture stdout
            import io
            from contextlib import redirect_stdout

            buf = io.StringIO()
            with redirect_stdout(buf):
                result = design_rules_command(args)

            output = buf.getvalue()
            # Should be valid JSON (may have trailing newline)
            parsed = json.loads(output)
            assert "violations" in parsed
        finally:
            Path(sch_path).unlink(missing_ok=True)

    @patch("kicad_agent.cli.design_rules_cmd._extract_topology")
    def test_markdown_format_output(self, mock_extract):
        """CLI produces Markdown output when --format markdown."""
        from kicad_agent.cli.design_rules_cmd import design_rules_command

        mock_extract.return_value = MagicMock()

        with tempfile.NamedTemporaryFile(suffix=".kicad_sch", delete=False) as f:
            sch_path = f.name

        try:
            args = self._make_args(sch_path, format="markdown")
            import io
            from contextlib import redirect_stdout

            buf = io.StringIO()
            with redirect_stdout(buf):
                result = design_rules_command(args)

            output = buf.getvalue()
            assert "# Design Rule Report" in output
        finally:
            Path(sch_path).unlink(missing_ok=True)

    @patch("kicad_agent.cli.design_rules_cmd._extract_topology")
    def test_output_file_flag(self, mock_extract):
        """CLI writes report to file when --output is specified."""
        from kicad_agent.cli.design_rules_cmd import design_rules_command

        mock_extract.return_value = MagicMock()

        with tempfile.NamedTemporaryFile(suffix=".kicad_sch", delete=False) as sch_f:
            sch_path = sch_f.name

        with tempfile.NamedTemporaryFile(suffix=".md", delete=False) as out_f:
            out_path = out_f.name

        try:
            args = self._make_args(sch_path, format="markdown", output=out_path)
            import io
            from contextlib import redirect_stdout

            buf = io.StringIO()
            with redirect_stdout(buf):
                result = design_rules_command(args)

            content = Path(out_path).read_text()
            assert "# Design Rule Report" in content
        finally:
            Path(sch_path).unlink(missing_ok=True)
            Path(out_path).unlink(missing_ok=True)

    @patch("kicad_agent.cli.design_rules_cmd._extract_topology")
    def test_config_flag_with_valid_yaml(self, mock_extract, tmp_path: Path):
        """CLI accepts --config flag for YAML rule configuration."""
        import yaml
        from kicad_agent.cli.design_rules_cmd import design_rules_command

        mock_extract.return_value = MagicMock()

        config_data = {
            "rules": {
                "IMPEDANCE_01": {"enabled": False},
                "BYPASS_CAP_01": {"enabled": True},
            }
        }
        config_path = tmp_path / "test-config.yaml"
        config_path.write_text(yaml.dump(config_data))

        with tempfile.NamedTemporaryFile(suffix=".kicad_sch", delete=False) as f:
            sch_path = f.name

        try:
            args = self._make_args(sch_path, config=str(config_path), format="json")
            import io
            from contextlib import redirect_stdout

            buf = io.StringIO()
            with redirect_stdout(buf):
                result = design_rules_command(args)

            # Should succeed (exit 0 or 1, not 2 for error)
            assert result in (0, 1)
        finally:
            Path(sch_path).unlink(missing_ok=True)

    def test_register_parser(self):
        """register_parser creates the design-rules subcommand."""
        from kicad_agent.cli.design_rules_cmd import register_parser

        parser = argparse.ArgumentParser()
        subparsers = parser.add_subparsers()
        register_parser(subparsers)

        # Parse the design-rules subcommand
        args = parser.parse_args(["design-rules", "test.kicad_sch"])
        assert hasattr(args, "func")
        assert args.schematic == "test.kicad_sch"
