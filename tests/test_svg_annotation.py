"""TDD tests for Phase 50: SVG Annotation Engine.

Tests svg_utils parsing/manipulation and SvgAnnotator annotation overlay.
"""
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest

from volta.spatial.svg_utils import (
    SVG_NS,
    create_svg_circle,
    create_svg_group,
    create_svg_text,
    get_svg_dimensions,
    parse_svg,
    sanitize_svg,
    svg_to_mm,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

FIXTURE_SVG = '''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg"
     xmlns:xlink="http://www.w3.org/1999/xlink"
     width="297mm" height="210mm"
     viewBox="0 0 297 210">
  <rect x="10" y="10" width="50" height="30" fill="none" stroke="black"/>
  <text x="20" y="25" font-size="3">R1</text>
</svg>
'''


@pytest.fixture
def fixture_svg(tmp_path):
    svg_path = tmp_path / "test.svg"
    svg_path.write_text(FIXTURE_SVG)
    return svg_path


@pytest.fixture
def unsafe_svg(tmp_path):
    svg = '''<?xml version="1.0" encoding="UTF-8"?>
<svg xmlns="http://www.w3.org/2000/svg"
     xmlns:xlink="http://www.w3.org/1999/xlink"
     width="100" height="100">
  <script>alert("xss")</script>
  <rect x="0" y="0" width="10" height="10" onclick="evil()" />
  <a xlink:href="javascript:void(0)"><text>bad</text></a>
  <circle cx="50" cy="50" r="10" fill="blue"/>
</svg>'''
    svg_path = tmp_path / "unsafe.svg"
    svg_path.write_text(svg)
    return svg_path


# ---------------------------------------------------------------------------
# TestSvgUtils
# ---------------------------------------------------------------------------


class TestSvgUtils:
    """Tests for SVG parsing utilities."""

    def test_parse_svg_returns_root(self, fixture_svg):
        """parse_svg returns Element root."""
        root = parse_svg(fixture_svg)
        assert root is not None
        assert "svg" in root.tag

    def test_parse_svg_preserves_namespaces(self, fixture_svg):
        """SVG root has namespace in tag."""
        root = parse_svg(fixture_svg)
        assert SVG_NS in root.tag

    def test_parse_svg_raises_on_missing(self):
        """parse_svg raises FileNotFoundError for missing file."""
        with pytest.raises(FileNotFoundError):
            parse_svg(Path("/nonexistent/test.svg"))

    def test_parse_svg_raises_on_non_svg(self, tmp_path):
        """parse_svg raises ValueError for non-SVG content."""
        bad = tmp_path / "bad.svg"
        bad.write_text("<html><body>not svg</body></html>")
        with pytest.raises(ValueError):
            parse_svg(bad)

    def test_svg_to_mm_with_viewbox(self, fixture_svg):
        """svg_to_mm converts coordinates using viewBox offset."""
        root = parse_svg(fixture_svg)
        x, y = svg_to_mm(root, 50.0, 100.0)
        assert x == 50.0
        assert y == 100.0

    def test_svg_to_mm_no_viewbox(self, tmp_path):
        """svg_to_mm returns identity when no viewBox."""
        svg = '<svg xmlns="http://www.w3.org/2000/svg" width="100" height="100"><rect/></svg>'
        p = tmp_path / "novb.svg"
        p.write_text(svg)
        root = parse_svg(p)
        x, y = svg_to_mm(root, 50.0, 75.0)
        assert x == 50.0
        assert y == 75.0

    def test_get_svg_dimensions(self, fixture_svg):
        """get_svg_dimensions returns (width, height) from viewBox."""
        root = parse_svg(fixture_svg)
        w, h = get_svg_dimensions(root)
        assert w == 297.0
        assert h == 210.0

    def test_create_svg_circle(self):
        """create_svg_circle produces correct element."""
        c = create_svg_circle(cx=10, cy=20, r=5)
        assert c.tag == f"{{{SVG_NS}}}circle"
        assert c.attrib["cx"] == "10"
        assert c.attrib["cy"] == "20"
        assert c.attrib["r"] == "5"

    def test_create_svg_text(self):
        """create_svg_text produces correct element."""
        t = create_svg_text(x=5, y=10, text="R1")
        assert t.tag == f"{{{SVG_NS}}}text"
        assert t.text == "R1"
        assert t.attrib["x"] == "5"

    def test_create_svg_group(self):
        """create_svg_group produces correct element."""
        g = create_svg_group(id_attr="test-group")
        assert g.tag == f"{{{SVG_NS}}}g"
        assert g.attrib.get("id") == "test-group"


class TestSvgSanitization:
    """Tests for SVG sanitization."""

    def test_removes_script_elements(self, unsafe_svg):
        """sanitize_svg strips <script> elements."""
        root = parse_svg(unsafe_svg)
        sanitized = sanitize_svg(root)
        scripts = sanitized.findall(f".//{{{SVG_NS}}}script")
        assert len(scripts) == 0

    def test_removes_event_handlers(self, unsafe_svg):
        """sanitize_svg removes onclick etc."""
        root = parse_svg(unsafe_svg)
        sanitized = sanitize_svg(root)
        for elem in sanitized.iter():
            for attr in elem.attrib:
                assert not attr.lower().startswith("on")

    def test_removes_javascript_urls(self, unsafe_svg):
        """sanitize_svg removes javascript: URLs."""
        root = parse_svg(unsafe_svg)
        sanitized = sanitize_svg(root)
        for elem in sanitized.iter():
            for attr, val in elem.attrib.items():
                if "href" in attr.lower():
                    assert not str(val).lower().startswith("javascript:")

    def test_preserves_legitimate_elements(self, unsafe_svg):
        """sanitize_svg keeps non-dangerous elements."""
        root = parse_svg(unsafe_svg)
        sanitized = sanitize_svg(root)
        circles = sanitized.findall(f".//{{{SVG_NS}}}circle")
        assert len(circles) >= 1


# ---------------------------------------------------------------------------
# TestSvgAnnotator
# ---------------------------------------------------------------------------


class TestSvgAnnotator:
    """Tests for SvgAnnotator."""

    def test_annotate_creates_output(self, fixture_svg, tmp_path):
        """annotate() creates annotated SVG file."""
        from volta.spatial.annotator import Annotation, SvgAnnotator

        output = tmp_path / "out.svg"
        annotator = SvgAnnotator()
        annotations = [Annotation(x=50.0, y=50.0, label="err", description="Pin not connected")]

        result = annotator.annotate(fixture_svg, annotations, output_path=output)

        assert result == output
        assert output.exists()

    def test_annotate_adds_markers(self, fixture_svg, tmp_path):
        """Annotated SVG contains circle markers."""
        from volta.spatial.annotator import Annotation, SvgAnnotator

        output = tmp_path / "out.svg"
        annotator = SvgAnnotator()
        annotations = [
            Annotation(x=30.0, y=40.0, label="err1", description="Error 1"),
            Annotation(x=80.0, y=90.0, label="err2", description="Error 2"),
        ]

        annotator.annotate(fixture_svg, annotations, output_path=output)

        root = ET.parse(str(output)).getroot()
        circles = root.findall(f".//{{{SVG_NS}}}circle")
        assert len(circles) >= 2

    def test_annotate_adds_legend(self, fixture_svg, tmp_path):
        """Annotated SVG contains a legend."""
        from volta.spatial.annotator import Annotation, SvgAnnotator

        output = tmp_path / "out.svg"
        annotator = SvgAnnotator()
        annotations = [Annotation(x=50.0, y=50.0, label="err", description="Test violation")]

        annotator.annotate(fixture_svg, annotations, output_path=output)

        content = output.read_text()
        assert "Annotations" in content

    def test_severity_colors(self):
        """Different severities produce different colors."""
        from volta.spatial.annotator import SvgAnnotator

        assert SvgAnnotator._severity_color("error") == "red"
        assert SvgAnnotator._severity_color("warning") == "orange"
        assert SvgAnnotator._severity_color("info") == "dodgerblue"

    def test_annotate_defaults_output_path(self, fixture_svg):
        """annotate() defaults to _annotated suffix."""
        from volta.spatial.annotator import Annotation, SvgAnnotator

        annotator = SvgAnnotator()
        annotations = [Annotation(x=50.0, y=50.0, label="err", description="Test")]

        result = annotator.annotate(fixture_svg, annotations)

        assert "_annotated" in result.name
        # Cleanup
        result.unlink(missing_ok=True)

    def test_annotation_style_defaults(self):
        """AnnotationStyle has sensible defaults."""
        from volta.spatial.annotator import AnnotationStyle

        style = AnnotationStyle()
        assert style.color == "red"
        assert style.circle_radius == 3.0
        assert style.opacity == 0.3
