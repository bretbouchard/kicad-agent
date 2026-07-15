"""Tests for hybrid placement engine and barrel exports.

Validates:
- Rule-based fallback when ML unavailable
- ML prediction path
- Interactive mode with fixed positions
- Output structure and validation
- Simplified API
- Request validation
- Barrel exports
- End-to-end pipeline
"""

import pytest
from pydantic import ValidationError

from volta.generation.intent import ComponentSpec, NetSpec
from volta.placement.engine import (
    HybridPlacementEngine,
    PlacementOutput,
    PlacementRequest,
)
from volta.placement.graph import PlacementGraph, netlist_to_placement_graph


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_components(n: int = 5) -> list[ComponentSpec]:
    """Create n simple components for testing.

    Produces refs: U1, R1, C1, J1, L1, R2, C2, J2, ... (prefix cycling with count).
    """
    prefixes = ["U", "R", "C", "J", "L"]
    libs = {
        "U": "MCU_ST:STM32F103",
        "R": "Device:R_Small_US",
        "C": "Device:C_Small",
        "J": "Connector:Conn_01x04",
        "L": "Device:L_Small",
    }
    prefix_counts: dict[str, int] = {}
    result = []
    for i in range(n):
        prefix = prefixes[i % len(prefixes)]
        count = prefix_counts.get(prefix, 0) + 1
        prefix_counts[prefix] = count
        ref = f"{prefix}{count}"
        result.append(ComponentSpec(library_id=libs[prefix], reference=ref, value=f"val_{i}"))
    return result


def _make_nets() -> list[NetSpec]:
    """Create sample nets connecting the components."""
    return [
        NetSpec(name="SDA", pins=["U1.3", "R1.1"]),
        NetSpec(name="GND", pins=["U1.5", "C1.2", "J1.4"]),
        NetSpec(name="VCC", pins=["U1.10", "L1.2"]),
        NetSpec(name="CLK", pins=["U1.7", "J1.2"]),
    ]


def _make_request(**overrides) -> PlacementRequest:
    """Create a default PlacementRequest with optional overrides."""
    defaults = {
        "components": _make_components(5),
        "nets": _make_nets(),
        "board_width": 100.0,
        "board_height": 80.0,
    }
    defaults.update(overrides)
    return PlacementRequest(**defaults)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestHybridRuleFallback:
    """Rule-based fallback when ML is disabled or unavailable."""

    def test_hybrid_rule_fallback(self):
        engine = HybridPlacementEngine()
        request = _make_request(use_ml=False)
        output = engine.place(request)

        assert output.source == "rule_based_packed"
        assert len(output.positions) == 5
        assert output.score >= 0.0
        # Rule-based positions are (x, y, 0.0)
        for ref, (x, y, rot) in output.positions.items():
            assert rot == 0.0


class TestHybridMLPrediction:
    """ML prediction path uses the predictor."""

    def test_hybrid_ml_prediction(self):
        engine = HybridPlacementEngine(model_path=None)
        request = _make_request(use_ml=True, refine_sa=False)
        output = engine.place(request)

        assert output.source == "ml_prediction"
        assert len(output.positions) == 5


class TestHybridInteractive:
    """Interactive mode when fixed_positions provided."""

    def test_hybrid_interactive(self):
        engine = HybridPlacementEngine()
        request = _make_request(
            fixed_positions={
                "U1": (30.0, 25.0, 0.0),
                "J1": (80.0, 60.0, 0.0),
            },
        )
        output = engine.place(request)

        assert output.source == "interactive"
        assert output.positions["U1"] == (30.0, 25.0, 0.0)
        assert output.positions["J1"] == (80.0, 60.0, 0.0)
        assert len(output.positions) == 5


class TestHybridOutputValid:
    """PlacementOutput has all required fields with valid values."""

    def test_hybrid_output_valid(self):
        engine = HybridPlacementEngine()
        request = _make_request(use_ml=False)
        output = engine.place(request)

        # All positions present
        assert len(output.positions) == len(request.components)

        # Score in [0, 1]
        assert 0.0 <= output.score <= 1.0

        # HPWL is non-negative
        assert output.hpwl >= 0.0

        # Source is a valid string
        assert output.source in ("ml_prediction", "ml_refined", "rule_based_packed", "interactive")

        # Violations is a list
        assert isinstance(output.violations, list)

        # component_scores populated
        assert isinstance(output.component_scores, dict)


class TestHybridPositionsInBounds:
    """All positions within board bounds."""

    def test_hybrid_positions_in_bounds(self):
        board_w, board_h = 100.0, 80.0
        engine = HybridPlacementEngine()
        request = _make_request(board_width=board_w, board_height=board_h, use_ml=False)
        output = engine.place(request)

        for ref, (x, y, rot) in output.positions.items():
            assert 0.0 <= x <= board_w, f"{ref} x={x} out of bounds"
            assert 0.0 <= y <= board_h, f"{ref} y={y} out of bounds"


class TestHybridSimpleAPI:
    """place_components_simple works with minimal arguments."""

    def test_hybrid_simple_api(self):
        engine = HybridPlacementEngine()
        components = _make_components(5)
        output = engine.place_components_simple(components, 100.0, 80.0)

        assert isinstance(output, PlacementOutput)
        assert output.source == "rule_based_packed"  # Simple API disables ML
        assert len(output.positions) == 5


class TestPlacementRequestValidation:
    """PlacementRequest validates inputs."""

    def test_placement_request_invalid_board_width(self):
        with pytest.raises(ValidationError):
            PlacementRequest(
                components=_make_components(2),
                board_width=0.0,
                board_height=80.0,
            )

    def test_placement_request_invalid_board_height(self):
        with pytest.raises(ValidationError):
            PlacementRequest(
                components=_make_components(2),
                board_width=100.0,
                board_height=-10.0,
            )

    def test_placement_request_invalid_clearance(self):
        with pytest.raises(ValidationError):
            PlacementRequest(
                components=_make_components(2),
                board_width=100.0,
                board_height=80.0,
                min_clearance=0.0,
            )


class TestPlacementRequestComponentCap:
    """Component count cap enforced at place() time."""

    def test_placement_request_component_cap(self):
        engine = HybridPlacementEngine()
        components = [
            ComponentSpec(library_id="Device:R", reference=f"R{i}", value="1k")
            for i in range(501)
        ]
        request = PlacementRequest(
            components=components,
            board_width=500.0,
            board_height=500.0,
        )
        with pytest.raises(ValueError, match="exceeds maximum"):
            engine.place(request)


class TestBarrelExports:
    """All placement module exports accessible from volta.placement."""

    def test_barrel_exports(self):
        from volta.placement import (
            BipartiteAttentionLayer,
            HybridPlacementEngine,
            PlacementGraph,
            PlacementModel,
            PlacementPredictor,
        )

        assert HybridPlacementEngine is not None
        assert PlacementGraph is not None
        assert PlacementPredictor is not None
        assert PlacementModel is not None
        assert BipartiteAttentionLayer is not None

    def test_barrel_export_count(self):
        import volta.placement

        assert len(volta.placement.__all__) >= 20


class TestEndToEndPipeline:
    """Full pipeline: request -> graph -> predict -> validate -> score -> output."""

    def test_end_to_end_pipeline(self):
        engine = HybridPlacementEngine()
        components = _make_components(8)
        nets = [
            NetSpec(name="SDA", pins=["U1.3", "R1.1", "J1.2"]),
            NetSpec(name="SCL", pins=["U1.4", "R2.1"]),
            NetSpec(name="GND", pins=["U1.5", "C1.2", "J1.4", "C2.2"]),
            NetSpec(name="VCC", pins=["U1.10", "C1.1", "C2.1"]),
        ]
        request = PlacementRequest(
            components=components,
            nets=nets,
            board_width=120.0,
            board_height=90.0,
            fixed_positions={"U1": (60.0, 45.0, 0.0)},
        )
        output = engine.place(request)

        assert output.source == "interactive"
        assert output.positions["U1"] == (60.0, 45.0, 0.0)
        assert len(output.positions) == 8
        assert output.score > 0.0
        assert output.hpwl >= 0.0
