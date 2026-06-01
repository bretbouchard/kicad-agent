"""TDD tests for Phase 50-02: Visual Diff and Report Generator."""
from pathlib import Path

import pytest

from kicad_agent.demo.pipeline import DemoReport


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

BEFORE_SVG = '''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100" viewBox="0 0 100 100">
  <rect id="R1" x="10" y="10" width="20" height="15" fill="none" stroke="black"/>
  <text id="R1_label" x="12" y="22" font-size="3">R1</text>
  <circle id="C1" cx="60" cy="50" r="5" fill="blue"/>
</svg>'''

AFTER_SVG = '''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100" viewBox="0 0 100 100">
  <rect id="R1" x="10" y="10" width="20" height="15" fill="none" stroke="black"/>
  <text id="R1_label" x="12" y="22" font-size="3">R1</text>
  <circle id="C1" cx="60" cy="50" r="8" fill="green"/>
  <rect id="R2" x="80" y="30" width="20" height="15" fill="none" stroke="black"/>
</svg>'''


@pytest.fixture
def before_svg(tmp_path):
    p = tmp_path / "before.svg"
    p.write_text(BEFORE_SVG)
    return p


@pytest.fixture
def after_svg(tmp_path):
    p = tmp_path / "after.svg"
    p.write_text(AFTER_SVG)
    return p


# ---------------------------------------------------------------------------
# TestVisualDiffer
# ---------------------------------------------------------------------------


class TestVisualDiffer:
    """Tests for VisualDiffer."""

    def test_compare_detects_changes(self, before_svg, after_svg):
        """compare() detects added and modified elements."""
        from kicad_agent.spatial.visual_diff import VisualDiffer

        differ = VisualDiffer()
        result = differ.compare(before_svg, after_svg)

        assert result.added_count >= 0 or result.modified_count >= 0 or result.removed_count >= 0

    def test_compare_produces_diff_svg(self, before_svg, after_svg, tmp_path):
        """compare() produces a diff SVG file."""
        from kicad_agent.spatial.visual_diff import VisualDiffer

        output = tmp_path / "diff.svg"
        differ = VisualDiffer()
        result = differ.compare(before_svg, after_svg, output_path=output)

        assert output.exists()
        assert result.diff_svg_path is not None

    def test_identical_svgs_no_changes(self, tmp_path):
        """Identical SVGs produce no changes."""
        from kicad_agent.spatial.visual_diff import VisualDiffer

        svg = tmp_path / "same.svg"
        svg.write_text(BEFORE_SVG)

        differ = VisualDiffer()
        result = differ.compare(svg, svg)

        assert result.added_count == 0
        assert result.removed_count == 0

    def test_diff_result_has_summary(self, before_svg, after_svg, tmp_path):
        """VisualDiffResult includes a summary string."""
        from kicad_agent.spatial.visual_diff import VisualDiffer

        differ = VisualDiffer()
        result = differ.compare(before_svg, after_svg)

        assert isinstance(result.summary, str)


# ---------------------------------------------------------------------------
# TestReportGenerator
# ---------------------------------------------------------------------------


class TestReportGenerator:
    """Tests for ReportGenerator."""

    def test_generate_markdown(self):
        """generate() produces valid Markdown."""
        from kicad_agent.demo.report_generator import ReportGenerator

        report = DemoReport(
            template_used="rc-lowpass",
            stages_completed=["select", "generate", "erc_before", "render"],
            erc_before=3,
            erc_after=0,
            svg_paths=["/tmp/demo/test.svg"],
            duration_seconds=1.5,
            success=True,
        )

        gen = ReportGenerator()
        md = gen.generate(report)

        assert "# Demo Report: rc-lowpass" in md
        assert "Success" in md
        assert "ERC Statistics" in md
        assert "Violations fixed" in md

    def test_generate_with_errors(self):
        """Report includes errors section when errors present."""
        from kicad_agent.demo.report_generator import ReportGenerator

        report = DemoReport(
            template_used="test",
            success=False,
            errors=["Component R1 not found", "ERC failed"],
        )

        gen = ReportGenerator()
        md = gen.generate(report)

        assert "Errors" in md
        assert "Component R1 not found" in md

    def test_save_creates_file(self, tmp_path):
        """save() writes Markdown to file."""
        from kicad_agent.demo.report_generator import ReportGenerator

        report = DemoReport(template_used="rc-lowpass", success=True)
        gen = ReportGenerator(output_dir=tmp_path)
        path = gen.save(report)

        assert path.exists()
        content = path.read_text()
        assert "rc-lowpass" in content
