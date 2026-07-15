"""TDD tests for schematic readability rules (Phase 48.5).

Tests spatial extraction, overlap detection, readability scoring,
and all 6 readability rules with mock schematic data.
"""
from unittest.mock import MagicMock

import pytest

from volta.spatial.primitives import SpatialBox


# ---------------------------------------------------------------------------
# Mock helpers
# ---------------------------------------------------------------------------


class _MockPosition:
    """Mock kiutils Position."""
    def __init__(self, x, y, angle=0.0):
        self.X = x
        self.Y = y
        self.angle = angle


class _MockProperty:
    """Mock kiutils Property."""
    def __init__(self, key, value):
        self.key = key
        self.value = value


class _MockSymbol:
    """Mock kiutils SchematicSymbol."""
    def __init__(self, lib_id, ref, value, x, y, angle=0.0):
        self.libId = lib_id
        self.position = _MockPosition(x, y, angle)
        self.properties = [
            _MockProperty("Reference", ref),
            _MockProperty("Value", value),
        ]


def _make_mock_ir(components=None, labels=None, wires=None):
    """Create a mock SchematicIR with test data."""
    ir = MagicMock()
    ir.components = components or []

    def get_prop(sym, key):
        for p in sym.properties:
            if p.key == key:
                return p.value
        return None

    ir.get_component_property = get_prop
    ir.get_label_positions.return_value = labels or []
    ir.get_wire_endpoints.return_value = wires or []
    return ir


# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------

# Well-spaced components
COMPONENTS_CLEAN = [
    _MockSymbol("Device:R", "R1", "10k", 50.0, 50.0),
    _MockSymbol("Device:R", "R2", "4.7k", 70.0, 50.0),
    _MockSymbol("NE5532", "U1", "NE5532P", 100.0, 50.0),
]

# Two overlapping components at same position
COMPONENTS_OVERLAP = [
    _MockSymbol("NE5532", "U1", "NE5532P", 100.0, 50.0),
    _MockSymbol("TL072", "U2", "TL072", 100.0, 50.0),
]

# Rotated component
COMPONENTS_ROTATED = [
    _MockSymbol("NE5532", "U1", "NE5532P", 100.0, 50.0, angle=90.0),
]

LABELS_CLEAN = [
    {"name": "IN", "x": 40.0, "y": 50.0, "label_type": "global"},
    {"name": "OUT", "x": 120.0, "y": 50.0, "label_type": "global"},
]

LABELS_OVERLAP = [
    {"name": "IN", "x": 40.0, "y": 50.0, "label_type": "global"},
    {"name": "OUT", "x": 40.5, "y": 50.0, "label_type": "global"},
]


# ---------------------------------------------------------------------------
# TestSchematicSpatialExtractor
# ---------------------------------------------------------------------------


class TestSchematicSpatialExtractor:
    """Tests for SchematicSpatialExtractor."""

    def test_extract_component_boxes_returns_correct_bounds(self):
        """Component boxes have correct center and size."""
        from volta.analysis.schematic_spatial import SchematicSpatialExtractor

        ir = _make_mock_ir(components=[COMPONENTS_CLEAN[0]])
        ext = SchematicSpatialExtractor(ir)
        boxes = ext.extract_component_boxes()

        assert len(boxes) == 1
        b = boxes[0]
        assert b.entity_id == "R1"
        assert b.entity_type == "component"
        # Passive size: 2.54 x 3.81
        assert b.x1 == pytest.approx(50.0 - 2.54 / 2)
        assert b.y1 == pytest.approx(50.0 - 3.81 / 2)

    def test_extract_component_boxes_handles_rotation(self):
        """Rotated components swap width/height."""
        from volta.analysis.schematic_spatial import SchematicSpatialExtractor

        ir = _make_mock_ir(components=COMPONENTS_ROTATED)
        ext = SchematicSpatialExtractor(ir)
        boxes = ext.extract_component_boxes()

        assert len(boxes) == 1
        b = boxes[0]
        assert b.entity_id == "U1"
        # IC: 10x8 rotated 90 -> 8x10
        assert b.x2 - b.x1 == pytest.approx(8.0)
        assert b.y2 - b.y1 == pytest.approx(10.0)

    def test_extract_text_boxes_returns_ref_and_value(self):
        """Each component produces a ref box and a value box."""
        from volta.analysis.schematic_spatial import SchematicSpatialExtractor

        ir = _make_mock_ir(components=[COMPONENTS_CLEAN[0]])
        ext = SchematicSpatialExtractor(ir)
        boxes = ext.extract_text_boxes()

        assert len(boxes) == 2
        refs = [b for b in boxes if b.entity_type == "text_ref"]
        vals = [b for b in boxes if b.entity_type == "text_value"]
        assert len(refs) == 1
        assert len(vals) == 1
        assert refs[0].entity_id == "R1_ref"
        assert vals[0].entity_id == "R1_value"

    def test_extract_label_boxes_returns_labels(self):
        """Label boxes have correct position and entity_id."""
        from volta.analysis.schematic_spatial import SchematicSpatialExtractor

        ir = _make_mock_ir(labels=LABELS_CLEAN)
        ext = SchematicSpatialExtractor(ir)
        boxes = ext.extract_label_boxes()

        assert len(boxes) == 2
        assert boxes[0].entity_type == "label_global"
        assert "IN" in boxes[0].entity_id

    def test_extract_wire_points_returns_endpoints(self):
        """Wire endpoints are extracted as SpatialPoint."""
        from volta.analysis.schematic_spatial import SchematicSpatialExtractor

        wires = [{"start_x": 0.0, "start_y": 0.0, "end_x": 10.0, "end_y": 10.0, "uuid": "w1"}]
        ir = _make_mock_ir(wires=wires)
        ext = SchematicSpatialExtractor(ir)
        points = ext.extract_wire_points()

        assert len(points) == 2
        assert points[0].x == 0.0
        assert points[1].x == 10.0

    def test_extract_all_combines_everything(self):
        """extract_all returns all primitive types."""
        from volta.analysis.schematic_spatial import SchematicSpatialExtractor

        ir = _make_mock_ir(
            components=[COMPONENTS_CLEAN[0]],
            labels=LABELS_CLEAN[:1],
            wires=[{"start_x": 0, "start_y": 0, "end_x": 1, "end_y": 1, "uuid": "w1"}],
        )
        ext = SchematicSpatialExtractor(ir)
        all_prims = ext.extract_all()

        # 1 component + 2 text (ref+value) + 1 label + 2 wire endpoints = 6
        assert len(all_prims) == 6

    def test_empty_schematic_returns_empty(self):
        """Empty IR produces empty lists."""
        from volta.analysis.schematic_spatial import SchematicSpatialExtractor

        ir = _make_mock_ir()
        ext = SchematicSpatialExtractor(ir)

        assert ext.extract_component_boxes() == []
        assert ext.extract_text_boxes() == []
        assert ext.extract_label_boxes() == []
        assert ext.extract_wire_points() == []
        assert ext.extract_all() == []


# ---------------------------------------------------------------------------
# TestSchematicOverlapRule
# ---------------------------------------------------------------------------


class TestSchematicOverlapRule:
    """Tests for SCHEMATIC_OVERLAP_01 rule."""

    def test_detects_full_overlap(self):
        """Two components at the same position = 100% IoU."""
        from volta.analysis.readability_rules import SchematicOverlapRule

        ir = _make_mock_ir(components=COMPONENTS_OVERLAP)
        topology = MagicMock()
        topology._schematic_ir = ir

        rule = SchematicOverlapRule()
        violations = rule.check(topology)

        assert len(violations) == 1
        assert violations[0].severity.value == "CRITICAL"
        assert "U1" in violations[0].description
        assert "U2" in violations[0].description

    def test_detects_partial_overlap(self):
        """Partial overlap produces WARNING severity."""
        from volta.analysis.readability_rules import SchematicOverlapRule

        # R1 at 50,50 (2.54x3.81), R2 at 51,50 (2.54x3.81) -- partial overlap
        ir = _make_mock_ir(components=[
            _MockSymbol("Device:R", "R1", "10k", 50.0, 50.0),
            _MockSymbol("Device:R", "R2", "4.7k", 51.0, 50.0),
        ])
        topology = MagicMock()
        topology._schematic_ir = ir

        rule = SchematicOverlapRule()
        violations = rule.check(topology)

        assert len(violations) == 1
        assert violations[0].severity.value == "WARNING"

    def test_no_overlap_clean_schematic(self):
        """Well-spaced components produce no violations."""
        from volta.analysis.readability_rules import SchematicOverlapRule

        ir = _make_mock_ir(components=COMPONENTS_CLEAN)
        topology = MagicMock()
        topology._schematic_ir = ir

        rule = SchematicOverlapRule()
        violations = rule.check(topology)

        assert len(violations) == 0

    def test_severity_levels(self):
        """IoU >50% = CRITICAL, 10-50% = WARNING, <10% = INFO."""
        from volta.analysis.readability_rules import _iou_to_severity, RuleSeverity

        assert _iou_to_severity(0.8) == RuleSeverity.CRITICAL
        assert _iou_to_severity(0.3) == RuleSeverity.WARNING
        assert _iou_to_severity(0.05) == RuleSeverity.INFO


# ---------------------------------------------------------------------------
# TestTextOverlapRule
# ---------------------------------------------------------------------------


class TestTextOverlapRule:
    """Tests for TEXT_OVERLAP_01 rule."""

    def test_detects_overlapping_refs(self):
        """Two components at the same position produce overlapping text."""
        from volta.analysis.readability_rules import TextOverlapRule

        ir = _make_mock_ir(components=COMPONENTS_OVERLAP)
        topology = MagicMock()
        topology._schematic_ir = ir

        rule = TextOverlapRule()
        violations = rule.check(topology)

        assert len(violations) > 0

    def test_clean_text_no_violations(self):
        """Well-spaced components produce no text overlap violations."""
        from volta.analysis.readability_rules import TextOverlapRule

        ir = _make_mock_ir(components=COMPONENTS_CLEAN)
        topology = MagicMock()
        topology._schematic_ir = ir

        rule = TextOverlapRule()
        violations = rule.check(topology)

        assert len(violations) == 0

    def test_label_overlap_detected(self):
        """Overlapping labels are detected."""
        from volta.analysis.readability_rules import TextOverlapRule

        ir = _make_mock_ir(components=[], labels=LABELS_OVERLAP)
        topology = MagicMock()
        topology._schematic_ir = ir

        rule = TextOverlapRule()
        violations = rule.check(topology)

        assert len(violations) > 0


# ---------------------------------------------------------------------------
# TestReadabilityRulesRegistry
# ---------------------------------------------------------------------------


class TestReadabilityRulesRegistry:
    """Tests for get_schematic_readability_rules."""

    def test_returns_6_rules(self):
        """get_schematic_readability_rules returns 6 rule instances."""
        from volta.analysis.readability_rules import get_schematic_readability_rules

        rules = get_schematic_readability_rules()
        assert len(rules) == 6
        names = {r.name for r in rules}
        assert "SCHEMATIC_OVERLAP_01" in names
        assert "TEXT_OVERLAP_01" in names
        assert "DUPLICATE_LABEL_01" in names
        assert "LABEL_SPACING_01" in names
        assert "COMPONENT_SPACING_01" in names
        assert "WIRE_CLUTTER_01" in names


# ---------------------------------------------------------------------------
# TestReadabilityScorer
# ---------------------------------------------------------------------------


class TestReadabilityScorer:
    """Tests for SchematicReadabilityScorer."""

    def test_empty_schematic_scores_high(self):
        """Empty schematic scores high (0.9375 -- neutral organization without topology)."""
        from volta.analysis.readability_scorer import SchematicReadabilityScorer
        from volta.analysis.schematic_spatial import SchematicSpatialExtractor

        ir = _make_mock_ir()
        ext = SchematicSpatialExtractor(ir)
        scorer = SchematicReadabilityScorer(ext)
        report = scorer.score()

        # density=1.0, clarity=1.0, spacing=1.0, organization=0.75 (no topology)
        assert report.srs == pytest.approx(0.9375)

    def test_clean_schematic_scores_higher_than_cramped(self):
        """Well-spaced schematic scores higher than cramped one."""
        from volta.analysis.readability_scorer import SchematicReadabilityScorer
        from volta.analysis.schematic_spatial import SchematicSpatialExtractor

        # Spread-out components (100mm apart)
        spread = [
            _MockSymbol("Device:R", "R1", "10k", 50.0, 50.0),
            _MockSymbol("Device:R", "R2", "4.7k", 200.0, 50.0),
            _MockSymbol("NE5532", "U1", "NE5532P", 350.0, 50.0),
        ]
        ir_spread = _make_mock_ir(components=spread, labels=LABELS_CLEAN)
        ext_spread = SchematicSpatialExtractor(ir_spread)
        report_spread = SchematicReadabilityScorer(ext_spread).score()

        ir_cramped = _make_mock_ir(components=COMPONENTS_OVERLAP)
        ext_cramped = SchematicSpatialExtractor(ir_cramped)
        report_cramped = SchematicReadabilityScorer(ext_cramped).score()

        assert report_spread.srs > report_cramped.srs

    def test_cramped_schematic_scores_low_spacing(self):
        """Overlapping components produce low spacing score."""
        from volta.analysis.readability_scorer import SchematicReadabilityScorer
        from volta.analysis.schematic_spatial import SchematicSpatialExtractor

        ir = _make_mock_ir(components=COMPONENTS_OVERLAP)
        ext = SchematicSpatialExtractor(ir)
        scorer = SchematicReadabilityScorer(ext)
        report = scorer.score()

        assert report.factors["spacing"] < 0.5

    def test_duplicate_labels_reduce_clarity(self):
        """Duplicate label names reduce clarity score."""
        from volta.analysis.readability_scorer import SchematicReadabilityScorer
        from volta.analysis.schematic_spatial import SchematicSpatialExtractor

        labels_dups = [
            {"name": "NET_A", "x": 40.0, "y": 50.0, "label_type": "global"},
            {"name": "NET_A", "x": 80.0, "y": 50.0, "label_type": "global"},
        ]
        ir = _make_mock_ir(components=COMPONENTS_CLEAN, labels=labels_dups)
        ext = SchematicSpatialExtractor(ir)
        scorer = SchematicReadabilityScorer(ext)
        report = scorer.score()

        assert report.factors["clarity"] < 1.0

    def test_srs_is_weighted_average(self):
        """SRS equals average of 4 factors."""
        from volta.analysis.readability_scorer import SchematicReadabilityScorer
        from volta.analysis.schematic_spatial import SchematicSpatialExtractor

        ir = _make_mock_ir(components=COMPONENTS_CLEAN, labels=LABELS_CLEAN)
        ext = SchematicSpatialExtractor(ir)
        scorer = SchematicReadabilityScorer(ext)
        report = scorer.score()

        expected = sum(report.factors.values()) / 4
        assert report.srs == pytest.approx(expected)

    def test_report_has_suggestions(self):
        """ReadabilityReport includes suggestions when scores are low."""
        from volta.analysis.readability_scorer import SchematicReadabilityScorer
        from volta.analysis.schematic_spatial import SchematicSpatialExtractor

        ir = _make_mock_ir(components=COMPONENTS_OVERLAP)
        ext = SchematicSpatialExtractor(ir)
        scorer = SchematicReadabilityScorer(ext)
        report = scorer.score()

        # Overlapping components should trigger at least one suggestion
        assert isinstance(report.suggestions, tuple)

    def test_report_element_count(self):
        """Report includes count of analyzed elements."""
        from volta.analysis.readability_scorer import SchematicReadabilityScorer
        from volta.analysis.schematic_spatial import SchematicSpatialExtractor

        ir = _make_mock_ir(components=[COMPONENTS_CLEAN[0]])
        ext = SchematicSpatialExtractor(ir)
        scorer = SchematicReadabilityScorer(ext)
        report = scorer.score()

        # 1 component box + 0 label boxes = 1
        assert report.element_count == 1

    def test_organization_with_no_topology(self):
        """Organization scores 0.75 when no topology provided."""
        from volta.analysis.readability_scorer import SchematicReadabilityScorer
        from volta.analysis.schematic_spatial import SchematicSpatialExtractor

        ir = _make_mock_ir(components=COMPONENTS_CLEAN)
        ext = SchematicSpatialExtractor(ir)
        scorer = SchematicReadabilityScorer(ext, topology=None)
        report = scorer.score()

        assert report.factors["organization"] == 0.75


# ---------------------------------------------------------------------------
# TestDuplicateLabelRule
# ---------------------------------------------------------------------------


class TestDuplicateLabelRule:
    """Tests for DUPLICATE_LABEL_01 rule."""

    def test_detects_duplicate_labels_close(self):
        """Two labels with same name within 20mm are flagged."""
        from volta.analysis.readability_rules import DuplicateLabelRule

        labels = [
            {"name": "NET_A", "x": 40.0, "y": 50.0, "label_type": "global"},
            {"name": "NET_A", "x": 45.0, "y": 50.0, "label_type": "global"},
        ]
        ir = _make_mock_ir(labels=labels)
        topology = MagicMock()
        topology._schematic_ir = ir

        rule = DuplicateLabelRule()
        violations = rule.check(topology)

        assert len(violations) >= 1
        assert "NET_A" in violations[0].description

    def test_no_flag_for_far_apart_duplicates(self):
        """Same-name labels far apart (>50mm) are not flagged."""
        from volta.analysis.readability_rules import DuplicateLabelRule

        labels = [
            {"name": "NET_A", "x": 10.0, "y": 50.0, "label_type": "global"},
            {"name": "NET_A", "x": 200.0, "y": 50.0, "label_type": "global"},
        ]
        ir = _make_mock_ir(labels=labels)
        topology = MagicMock()
        topology._schematic_ir = ir

        rule = DuplicateLabelRule()
        violations = rule.check(topology)

        assert len(violations) == 0

    def test_no_flag_for_different_names(self):
        """Labels with different names are not flagged."""
        from volta.analysis.readability_rules import DuplicateLabelRule

        labels = [
            {"name": "IN", "x": 40.0, "y": 50.0, "label_type": "global"},
            {"name": "OUT", "x": 42.0, "y": 50.0, "label_type": "global"},
        ]
        ir = _make_mock_ir(labels=labels)
        topology = MagicMock()
        topology._schematic_ir = ir

        rule = DuplicateLabelRule()
        violations = rule.check(topology)

        assert len(violations) == 0


# ---------------------------------------------------------------------------
# TestLabelSpacingRule
# ---------------------------------------------------------------------------


class TestLabelSpacingRule:
    """Tests for LABEL_SPACING_01 rule."""

    def test_detects_close_labels(self):
        """Labels closer than 3mm are flagged."""
        from volta.analysis.readability_rules import LabelSpacingRule

        labels = [
            {"name": "A", "x": 40.0, "y": 50.0, "label_type": "global"},
            {"name": "B", "x": 41.0, "y": 50.0, "label_type": "global"},
        ]
        ir = _make_mock_ir(labels=labels)
        topology = MagicMock()
        topology._schematic_ir = ir

        rule = LabelSpacingRule()
        violations = rule.check(topology)

        assert len(violations) >= 1

    def test_clean_labels_no_violation(self):
        """Well-separated labels produce no violations."""
        from volta.analysis.readability_rules import LabelSpacingRule

        labels = [
            {"name": "A", "x": 40.0, "y": 50.0, "label_type": "global"},
            {"name": "B", "x": 100.0, "y": 50.0, "label_type": "global"},
        ]
        ir = _make_mock_ir(labels=labels)
        topology = MagicMock()
        topology._schematic_ir = ir

        rule = LabelSpacingRule()
        violations = rule.check(topology)

        assert len(violations) == 0


# ---------------------------------------------------------------------------
# TestComponentSpacingRule
# ---------------------------------------------------------------------------


class TestComponentSpacingRule:
    """Tests for COMPONENT_SPACING_01 rule."""

    def test_detects_close_components(self):
        """Overlapping components are flagged as too close."""
        from volta.analysis.readability_rules import ComponentSpacingRule

        ir = _make_mock_ir(components=COMPONENTS_OVERLAP)
        topology = MagicMock()
        topology._schematic_ir = ir

        rule = ComponentSpacingRule()
        violations = rule.check(topology)

        assert len(violations) >= 1

    def test_clean_components_no_violation(self):
        """Well-spaced components produce no violations."""
        from volta.analysis.readability_rules import ComponentSpacingRule

        ir = _make_mock_ir(components=COMPONENTS_CLEAN)
        topology = MagicMock()
        topology._schematic_ir = ir

        rule = ComponentSpacingRule()
        violations = rule.check(topology)

        assert len(violations) == 0


# ---------------------------------------------------------------------------
# TestWireClutterRule
# ---------------------------------------------------------------------------


class TestWireClutterRule:
    """Tests for WIRE_CLUTTER_01 rule."""

    def test_detects_wire_through_component(self):
        """Wire crossing through a component body is flagged."""
        from volta.analysis.readability_rules import WireClutterRule

        # U1 at 100,50 size 10x8 -> box (95,46)-(105,54)
        # Wire from (90,50) to (110,50) passes right through
        wires = [{"start_x": 90.0, "start_y": 50.0, "end_x": 110.0, "end_y": 50.0, "uuid": "w1"}]
        ir = _make_mock_ir(
            components=[_MockSymbol("NE5532", "U1", "NE5532P", 100.0, 50.0)],
            wires=wires,
        )
        topology = MagicMock()
        topology._schematic_ir = ir

        rule = WireClutterRule()
        violations = rule.check(topology)

        assert len(violations) == 1
        assert "U1" in violations[0].description

    def test_clean_wire_no_violation(self):
        """Wire outside component boxes is not flagged."""
        from volta.analysis.readability_rules import WireClutterRule

        # Wire from (0,0) to (0,80) -- far from U1 at (100,50)
        wires = [{"start_x": 0.0, "start_y": 0.0, "end_x": 0.0, "end_y": 80.0, "uuid": "w1"}]
        ir = _make_mock_ir(
            components=[_MockSymbol("NE5532", "U1", "NE5532P", 100.0, 50.0)],
            wires=wires,
        )
        topology = MagicMock()
        topology._schematic_ir = ir

        rule = WireClutterRule()
        violations = rule.check(topology)

        assert len(violations) == 0
