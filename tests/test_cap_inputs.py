"""Unit tests for CapInputs value object (Plan 01 Task 3, CR-110-04 fix)."""
from __future__ import annotations

from dataclasses import FrozenInstanceError
from pathlib import Path

import pytest

from volta.training.rewards.cap_inputs import CapInputs


def test_cap_inputs_constructs_cleanly() -> None:
    """Test 1: basic construction with all 3 fields."""
    inputs = CapInputs(
        bounding_box_mm2=5000.0,
        component_footprint_area_mm2=2500.0,
        crossing_count=3,
    )
    assert inputs.bounding_box_mm2 == 5000.0
    assert inputs.component_footprint_area_mm2 == 2500.0
    assert inputs.crossing_count == 3


def test_cap_inputs_is_frozen() -> None:
    """Test 6: Phase 100 CR-01 — CapInputs is frozen."""
    inputs = CapInputs(bounding_box_mm2=100.0, component_footprint_area_mm2=50.0, crossing_count=0)
    with pytest.raises(FrozenInstanceError):
        inputs.bounding_box_mm2 = 200.0  # type: ignore[misc]


def test_from_layout_result_none_raises_valueerror() -> None:
    """Test 5: layout_result=None is an explicit error (use from_spatial_extractor for raw)."""
    # We pass None directly — the factory must reject it.
    with pytest.raises(ValueError, match="layout_result must not be None"):
        CapInputs.from_layout_result(None, None)  # type: ignore[arg-type]


def test_from_spatial_extractor_with_empty_components_returns_zeros() -> None:
    """Test 4: empty component list -> bbox=0.0, footprint=0.0."""
    extractor = _FakeExtractor(component_boxes=[])
    inputs = CapInputs.from_spatial_extractor(extractor, crossing_count=0)
    assert inputs.bounding_box_mm2 == 0.0
    assert inputs.component_footprint_area_mm2 == 0.0
    assert inputs.crossing_count == 0


def test_from_spatial_extractor_computes_bbox_and_footprint() -> None:
    """Test 3: bbox/footprint computed from extractor.extract_component_boxes()."""
    # Two 10x10 boxes side-by-side: bbox = 20*10 = 200, footprint = 100+100 = 200
    boxes = [
        _FakeBox(x1=0.0, y1=0.0, x2=10.0, y2=10.0),
        _FakeBox(x1=10.0, y1=0.0, x2=20.0, y2=10.0),
    ]
    extractor = _FakeExtractor(component_boxes=boxes)
    inputs = CapInputs.from_spatial_extractor(extractor, crossing_count=0)
    assert inputs.bounding_box_mm2 == pytest.approx(200.0)
    assert inputs.component_footprint_area_mm2 == pytest.approx(200.0)
    assert inputs.crossing_count == 0


def test_from_spatial_extractor_accepts_crossing_count_arg() -> None:
    """Test 3b: crossing_count arg is honored."""
    extractor = _FakeExtractor(component_boxes=[])
    inputs = CapInputs.from_spatial_extractor(extractor, crossing_count=7)
    assert inputs.crossing_count == 7


def test_from_layout_result_with_real_fixture() -> None:
    """Test 7 (integration): real Arduino_Mega fixture -> bbox > 0 and footprint > 0."""
    fixture = Path("tests/fixtures/Arduino_Mega/Arduino_Mega.kicad_sch")
    if not fixture.exists():
        pytest.skip(f"fixture {fixture} not available")

    from volta.analysis.schematic_spatial import SchematicSpatialExtractor
    from volta.ir.schematic_ir import SchematicIR
    from volta.parser.schematic_parser import parse_schematic

    parse_result = parse_schematic(fixture)
    ir = SchematicIR(_parse_result=parse_result)
    extractor = SchematicSpatialExtractor(ir)
    inputs = CapInputs.from_spatial_extractor(extractor, crossing_count=0)

    assert inputs.bounding_box_mm2 > 0, "bbox should be positive for Arduino_Mega"
    assert inputs.component_footprint_area_mm2 > 0, "footprint should be positive"
    assert inputs.crossing_count == 0


def test_from_layout_result_extracts_crossing_count_from_layout_result() -> None:
    """Test 2: from_layout_result pulls crossing_count from LayoutResult.

    Uses the real SchematicIR/SchematicSpatialExtractor chain on the
    Arduino_Mega fixture (covered by test_from_layout_result_with_real_chain
    below). Skipped here to avoid duplication."""
    pytest.skip("Covered by test_from_layout_result_with_real_chain")


def test_from_layout_result_with_real_chain() -> None:
    """Test 2 (integration): from_layout_result integrates with real SchematicIR."""
    fixture = Path("tests/fixtures/Arduino_Mega/Arduino_Mega.kicad_sch")
    if not fixture.exists():
        pytest.skip(f"fixture {fixture} not available")

    from volta.ir.schematic_ir import SchematicIR
    from volta.parser.schematic_parser import parse_schematic

    parse_result = parse_schematic(fixture)
    ir = SchematicIR(_parse_result=parse_result)

    fake_layout = _FakeLayoutResult(crossing_count=11)
    inputs = CapInputs.from_layout_result(fake_layout, ir)

    assert inputs.crossing_count == 11
    assert inputs.bounding_box_mm2 > 0
    assert inputs.component_footprint_area_mm2 > 0


# ---------------------------------------------------------------------------
# Test helpers
# ---------------------------------------------------------------------------


class _FakeBox:
    """Minimal SpatialBox stand-in."""

    def __init__(self, x1: float, y1: float, x2: float, y2: float) -> None:
        self.x1 = x1
        self.y1 = y1
        self.x2 = x2
        self.y2 = y2


class _FakeExtractor:
    """Minimal SchematicSpatialExtractor stand-in."""

    def __init__(self, component_boxes: list) -> None:
        self._boxes = component_boxes

    def extract_component_boxes(self) -> list:
        return self._boxes


class _FakeLayoutResult:
    """Minimal LayoutResult stand-in (only needs crossing_count)."""

    def __init__(self, crossing_count: int) -> None:
        self.crossing_count = crossing_count


class _FakeIR:
    """Stand-in for SchematicIR when we don't need a real one."""
