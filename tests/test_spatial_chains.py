"""Tests for cold-start reasoning chain synthesis from DRC/ERC violations (VP-05).

Validates:
  - Chain produces 5 steps with correct step types in order
  - Steps include coordinate data matching input violation items
  - Diagnosis maps violation types to correct descriptions
  - Recommendations are type-aware and actionable
  - synthesize_chains processes DRC results correctly
  - Empty violations return empty list
  - Coordinate extraction handles items with and without pos data
  - Spatial context step describes nearby primitives
"""

from pathlib import Path

import pytest

from volta.spatial.primitives import SpatialBox, SpatialPoint
from volta.spatial.reasoning_chains import (
    ReasoningChain,
    ReasoningStep,
    _extract_violation_coordinates,
    synthesize_chain,
    synthesize_chains,
)
from volta.validation.erc_drc import DrcResult, ErcResult, Severity, Violation


def _make_violation(
    desc: str = "Clearance violation",
    vtype: str = "clearance",
    items: tuple[dict, ...] | None = None,
    severity: Severity = Severity.ERROR,
) -> Violation:
    """Create a mock Violation for testing."""
    if items is None:
        items = (
            {"pos": {"x": 10.0, "y": 20.0}, "uuid": "abc123"},
        )
    return Violation(
        description=desc,
        severity=severity,
        type=vtype,
        items=tuple(items),
    )


class TestReasoningStepTypes:
    """Tests for ReasoningStep type validation."""

    def test_step_types_exist(self) -> None:
        """ReasoningStep accepts valid step types."""
        for stype in ("observation", "spatial_context", "coordinate_reference", "diagnosis", "recommendation"):
            step = ReasoningStep(step_type=stype, content="test")
            assert step.step_type == stype


class TestSynthesizeChain:
    """Tests for synthesize_chain function."""

    def test_produces_five_steps(self) -> None:
        """synthesize_chain produces exactly 5 steps."""
        v = _make_violation()
        chain = synthesize_chain(v)
        assert len(chain.steps) == 5

    def test_step_types_in_order(self) -> None:
        """Steps follow the correct order: observation -> spatial_context -> coordinate_reference -> diagnosis -> recommendation."""
        v = _make_violation()
        chain = synthesize_chain(v)
        expected = [
            "observation",
            "spatial_context",
            "coordinate_reference",
            "diagnosis",
            "recommendation",
        ]
        actual = [s.step_type for s in chain.steps]
        assert actual == expected

    def test_chain_includes_coordinates(self) -> None:
        """Chain steps include coordinate data matching input violation."""
        v = _make_violation(
            items=(
                {"pos": {"x": 10.0, "y": 20.0}, "uuid": "abc"},
                {"pos": {"x": 30.0, "y": 40.0}, "uuid": "def"},
            )
        )
        chain = synthesize_chain(v)

        # Observation step should have both coordinates
        obs_coords = chain.steps[0].coordinates
        assert (10.0, 20.0) in obs_coords
        assert (30.0, 40.0) in obs_coords

    def test_chain_metadata(self) -> None:
        """ReasoningChain metadata fields are populated."""
        v = _make_violation(desc="Test violation", vtype="clearance")
        chain = synthesize_chain(v)

        assert chain.violation_type == "clearance"
        assert chain.violation_description == "Test violation"
        assert chain.severity == "error"
        assert chain.chain_id != ""

    def test_chain_has_unique_id(self) -> None:
        """Each chain gets a unique chain_id."""
        v = _make_violation()
        c1 = synthesize_chain(v)
        c2 = synthesize_chain(v)
        assert c1.chain_id != c2.chain_id


class TestDiagnosisMapping:
    """Tests for violation type -> diagnosis mapping."""

    @pytest.mark.parametrize(
        "vtype,expected_text",
        [
            ("clearance", "insufficient spacing"),
            ("width", "trace width"),
            ("unconnected_items", "dangling connections"),
        ],
    )
    def test_diagnosis_maps_violation_type(self, vtype: str, expected_text: str) -> None:
        """Diagnosis step maps violation types to descriptive text."""
        v = _make_violation(vtype=vtype)
        chain = synthesize_chain(v)

        diagnosis_step = chain.steps[3]
        assert diagnosis_step.step_type == "diagnosis"
        assert expected_text in diagnosis_step.content

    def test_unknown_type_uses_default(self) -> None:
        """Unknown violation type uses default diagnosis text."""
        v = _make_violation(vtype="unknown_weird_type")
        chain = synthesize_chain(v)

        diagnosis_step = chain.steps[3]
        assert "design rule constraint not met" in diagnosis_step.content


class TestRecommendationMapping:
    """Tests for violation type -> recommendation mapping."""

    def test_recommendation_starts_with_consider(self) -> None:
        """Recommendation step content starts with 'Consider:'."""
        v = _make_violation()
        chain = synthesize_chain(v)
        rec = chain.steps[4]
        assert rec.content.startswith("Consider:")

    @pytest.mark.parametrize(
        "vtype,expected_in_rec",
        [
            ("clearance", "spacing"),
            ("width", "Widen"),
            ("unconnected_items", "Route"),
        ],
    )
    def test_recommendation_matches_type(self, vtype: str, expected_in_rec: str) -> None:
        """Recommendation text matches the violation type."""
        v = _make_violation(vtype=vtype)
        chain = synthesize_chain(v)
        rec = chain.steps[4]
        assert expected_in_rec in rec.content


class TestSynthesizeChains:
    """Tests for synthesize_chains batch processing."""

    def test_from_drc_result(self) -> None:
        """synthesize_chains processes all DRC violations."""
        v1 = _make_violation(desc="V1", vtype="clearance")
        v2 = _make_violation(desc="V2", vtype="width")
        drc = DrcResult(
            passed=False,
            file_path=Path("test.kicad_pcb"),
            violations=(v1, v2),
        )
        chains = synthesize_chains(drc_result=drc)
        assert len(chains) == 2
        assert chains[0].violation_description == "V1"
        assert chains[1].violation_description == "V2"

    def test_from_erc_result(self) -> None:
        """synthesize_chains processes ERC violations."""
        v = _make_violation(desc="ERC issue", vtype="pin_conflict")
        erc = ErcResult(
            passed=False,
            file_path=Path("test.kicad_sch"),
            violations=(v,),
        )
        chains = synthesize_chains(erc_result=erc)
        assert len(chains) == 1
        assert chains[0].violation_description == "ERC issue"

    def test_both_results(self) -> None:
        """DRC violations come before ERC violations."""
        dv = _make_violation(desc="DRC issue")
        ev = _make_violation(desc="ERC issue")
        drc = DrcResult(passed=False, file_path=Path("d.kicad_pcb"), violations=(dv,))
        erc = ErcResult(passed=False, file_path=Path("e.kicad_sch"), violations=(ev,))
        chains = synthesize_chains(drc_result=drc, erc_result=erc)
        assert len(chains) == 2
        assert chains[0].violation_description == "DRC issue"
        assert chains[1].violation_description == "ERC issue"

    def test_empty_violations(self) -> None:
        """DrcResult with no violations returns empty list."""
        drc = DrcResult(passed=True, file_path=Path("clean.kicad_pcb"))
        chains = synthesize_chains(drc_result=drc)
        assert chains == []

    def test_none_inputs(self) -> None:
        """None inputs return empty list."""
        chains = synthesize_chains()
        assert chains == []

    def test_drc_unconnected_items(self) -> None:
        """DRC unconnected_items are also processed."""
        v = _make_violation(desc="Unconnected", vtype="unconnected_items")
        drc = DrcResult(
            passed=False,
            file_path=Path("test.kicad_pcb"),
            violations=(),
            unconnected_items=(v,),
        )
        chains = synthesize_chains(drc_result=drc)
        assert len(chains) == 1
        assert chains[0].violation_description == "Unconnected"


class TestCoordinateExtraction:
    """Tests for _extract_violation_coordinates."""

    def test_with_pos_data(self) -> None:
        """Items with pos dict yield correct coordinates."""
        v = _make_violation(
            items=(
                {"pos": {"x": 10.0, "y": 20.0}},
                {"pos": {"x": 30.0, "y": 40.0}},
            )
        )
        coords = _extract_violation_coordinates(v)
        assert coords == [(10.0, 20.0), (30.0, 40.0)]

    def test_without_pos_data(self) -> None:
        """Items without pos dict yield (0.0, 0.0)."""
        v = _make_violation(
            items=({"uuid": "abc"},),
        )
        coords = _extract_violation_coordinates(v)
        assert coords == [(0.0, 0.0)]

    def test_mixed_items(self) -> None:
        """Mix of items with and without pos data."""
        v = _make_violation(
            items=(
                {"pos": {"x": 5.0, "y": 10.0}},
                {"uuid": "no-pos"},
            )
        )
        coords = _extract_violation_coordinates(v)
        assert len(coords) == 2
        assert coords[0] == (5.0, 10.0)
        assert coords[1] == (0.0, 0.0)

    def test_empty_items(self) -> None:
        """Violation with no items yields empty list."""
        v = Violation(description="test", severity=Severity.ERROR, type="test")
        coords = _extract_violation_coordinates(v)
        assert coords == []


class TestSpatialContext:
    """Tests for spatial context enrichment with primitives."""

    def test_with_nearby_primitives(self) -> None:
        """Spatial context step describes nearby primitives."""
        v = _make_violation(
            items=({"pos": {"x": 10.0, "y": 10.0}},),
        )

        # Create nearby primitives
        primitives = [
            SpatialBox(
                x1=8.0, y1=8.0, x2=12.0, y2=12.0,
                entity_type="footprint", entity_id="U1",
            ),
            SpatialPoint(x=11.0, y=11.0, entity_type="pad", entity_id="U1.1"),
        ]

        chain = synthesize_chain(v, pcb_primitives=primitives)
        spatial_ctx = chain.steps[1]
        assert spatial_ctx.step_type == "spatial_context"
        assert "footprints" in spatial_ctx.content
        assert "within 5mm" in spatial_ctx.content

    def test_without_primitives(self) -> None:
        """Without primitives, spatial context notes no data available."""
        v = _make_violation()
        chain = synthesize_chain(v)
        spatial_ctx = chain.steps[1]
        assert "No spatial primitives" in spatial_ctx.content

    def test_primitives_in_chain_metadata(self) -> None:
        """Nearby primitives are included in chain's spatial_primitives field."""
        v = _make_violation(
            items=({"pos": {"x": 10.0, "y": 10.0}},),
        )
        primitives = [
            SpatialBox(
                x1=8.0, y1=8.0, x2=12.0, y2=12.0,
                entity_type="footprint", entity_id="U1",
            ),
        ]

        chain = synthesize_chain(v, pcb_primitives=primitives)
        assert len(chain.spatial_primitives) > 0
        assert chain.spatial_primitives[0]["entity_type"] == "footprint"
