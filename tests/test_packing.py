"""Tests for overlap-free shelf packing and push-apart resolver (Phase 5).

Covers:
- Shelf packing produces overlap-free placements
- Fixed positions are treated as obstacles
- Keepout zones are respected
- Board overflow reports unpacked components
- Push-apart resolver separates overlapping pairs
- SA objective penalizes overlaps heavily
- Engine produces valid (overlap-free) output
- Placement readiness gate passes after auto-place
"""

import math

import pytest

from kicad_agent.placement.graph import PlacementGraph
from kicad_agent.placement.packing import (
    PackResult,
    pack_components_no_overlap,
    resolve_overlaps,
)
from kicad_agent.placement.validation import PlacementValidator


# ---------------------------------------------------------------------------
# Shelf packing tests
# ---------------------------------------------------------------------------


class TestPackNoOverlapBasic:
    """Basic packing produces overlap-free placements."""

    def test_5_components_no_overlaps(self):
        sizes = {
            "R1": (3.0, 1.5),
            "R2": (3.0, 1.5),
            "C1": (2.0, 2.0),
            "C2": (2.0, 2.0),
            "U1": (5.0, 4.0),
        }
        result = pack_components_no_overlap(sizes, 100.0, 80.0, min_clearance=1.0)

        assert result.packed_count == 5
        assert result.unpacked_refs == ()
        assert _count_overlaps(result.positions, sizes) == 0

    def test_single_component(self):
        sizes = {"R1": (3.0, 1.5)}
        result = pack_components_no_overlap(sizes, 100.0, 80.0)

        assert result.packed_count == 1
        assert "R1" in result.positions
        x, y, rot = result.positions["R1"]
        assert 0.0 < x < 100.0
        assert 0.0 < y < 80.0

    def test_rotation_is_zero(self):
        sizes = {"R1": (3.0, 1.5)}
        result = pack_components_no_overlap(sizes, 100.0, 80.0)

        for ref, (x, y, rot) in result.positions.items():
            assert rot == 0.0

    def test_components_on_board(self):
        sizes = {"R1": (10.0, 10.0), "R2": (10.0, 10.0)}
        result = pack_components_no_overlap(sizes, 100.0, 80.0, min_clearance=1.0)

        for ref, (x, y, _rot) in result.positions.items():
            assert 1.0 <= x <= 99.0
            assert 1.0 <= y <= 79.0


class TestPackWithFixedPositions:
    """Fixed positions are treated as obstacles."""

    def test_free_avoids_fixed(self):
        sizes = {
            "R1": (3.0, 1.5),
            "R2": (3.0, 1.5),
            "R3": (3.0, 1.5),
        }
        fixed = {"U1": (50.0, 40.0, 0.0)}
        result = pack_components_no_overlap(
            sizes, 100.0, 80.0, min_clearance=1.0, fixed_positions=fixed
        )

        assert result.packed_count == 3
        assert _count_overlaps(result.positions, sizes, fixed) == 0

    def test_fixed_not_in_output(self):
        sizes = {"R1": (3.0, 1.5)}
        fixed = {"R1": (50.0, 40.0, 0.0)}
        result = pack_components_no_overlap(
            sizes, 100.0, 80.0, min_clearance=1.0, fixed_positions=fixed
        )

        assert "R1" not in result.positions
        assert result.packed_count == 0


class TestPackWithKeepoutZones:
    """Keepout zones are respected."""

    def test_components_avoid_keepout(self):
        sizes = {
            "R1": (3.0, 1.5),
            "R2": (3.0, 1.5),
            "R3": (3.0, 1.5),
        }
        keepouts = [(45.0, 35.0, 55.0, 45.0)]
        result = pack_components_no_overlap(
            sizes, 100.0, 80.0, min_clearance=1.0, keepout_zones=keepouts
        )

        assert result.packed_count == 3
        for ref, (x, y, _rot) in result.positions.items():
            # No component center inside keepout
            inside = (45.0 <= x <= 55.0) and (35.0 <= y <= 45.0)
            assert not inside, f"{ref} placed inside keepout zone"


class TestPackBoardOverflow:
    """Board too small reports unpacked components."""

    def test_overflow_returns_unpacked(self):
        # 5 large components that can't all fit on a small board
        sizes = {f"U{i}": (30.0, 30.0) for i in range(5)}
        result = pack_components_no_overlap(sizes, 50.0, 50.0, min_clearance=1.0)

        assert len(result.unpacked_refs) > 0
        assert result.packed_count < 5

    def test_all_fit_when_space_sufficient(self):
        sizes = {f"R{i}": (2.0, 1.0) for i in range(10)}
        result = pack_components_no_overlap(sizes, 100.0, 80.0, min_clearance=0.5)

        assert result.unpacked_refs == ()
        assert result.packed_count == 10


class TestPackUtilization:
    """Utilization metric is reasonable."""

    def test_utilization_between_zero_and_one(self):
        sizes = {f"R{i}": (2.0, 1.0) for i in range(5)}
        result = pack_components_no_overlap(sizes, 100.0, 80.0, min_clearance=1.0)

        assert 0.0 < result.utilization < 1.0


# ---------------------------------------------------------------------------
# Push-apart resolver tests
# ---------------------------------------------------------------------------


class TestResolveOverlaps:
    """Push-apart resolver separates overlapping components."""

    def test_two_overlapping_separated(self):
        positions = {"R1": (50.0, 40.0, 0.0), "R2": (51.0, 40.0, 0.0)}
        sizes = {"R1": 5.0, "R2": 5.0}  # half-size = 2.5, they're only 1mm apart

        resolved = resolve_overlaps(positions, sizes, 100.0, 80.0, min_clearance=1.0)

        overlap_count = _count_overlaps_halfsizes(resolved, sizes)
        assert overlap_count == 0

    def test_chain_overlap_resolved(self):
        positions = {
            "R1": (50.0, 40.0, 0.0),
            "R2": (51.0, 40.0, 0.0),
            "R3": (52.0, 40.0, 0.0),
        }
        sizes = {"R1": 5.0, "R2": 5.0, "R3": 5.0}

        resolved = resolve_overlaps(positions, sizes, 100.0, 80.0, min_clearance=1.0)

        overlap_count = _count_overlaps_halfsizes(resolved, sizes)
        assert overlap_count == 0

    def test_no_overlap_is_noop(self):
        positions = {"R1": (20.0, 20.0, 0.0), "R2": (80.0, 60.0, 0.0)}
        sizes = {"R1": 5.0, "R2": 5.0}

        resolved = resolve_overlaps(positions, sizes, 100.0, 80.0, min_clearance=1.0)

        assert resolved["R1"] == positions["R1"]
        assert resolved["R2"] == positions["R2"]

    def test_components_clamped_to_board(self):
        positions = {"R1": (1.0, 1.0, 0.0), "R2": (99.0, 1.0, 0.0)}
        sizes = {"R1": 5.0, "R2": 5.0}

        resolved = resolve_overlaps(positions, sizes, 100.0, 80.0, min_clearance=1.0)

        for ref, (x, y, _rot) in resolved.items():
            assert 1.0 <= x <= 99.0
            assert 1.0 <= y <= 79.0


# ---------------------------------------------------------------------------
# SA overlap penalty test
# ---------------------------------------------------------------------------


class TestSAOverlapPenalty:
    """SA objective heavily penalizes overlaps."""

    def test_overlap_penalty_is_large(self):
        from kicad_agent.placement.interactive import _compute_overlap_penalty

        # Two components at same position — large penalty
        positions = {"R1": (50.0, 40.0, 0.0), "R2": (50.0, 40.0, 0.0)}
        sizes = {"R1": 5.0, "R2": 5.0}
        penalty = _compute_overlap_penalty(positions, sizes, 1.0)

        assert penalty >= 1000.0  # 1 overlap * 1000 weight

    def test_no_overlap_penalty_is_zero(self):
        from kicad_agent.placement.interactive import _compute_overlap_penalty

        positions = {"R1": (20.0, 20.0, 0.0), "R2": (80.0, 60.0, 0.0)}
        sizes = {"R1": 5.0, "R2": 5.0}
        penalty = _compute_overlap_penalty(positions, sizes, 1.0)

        assert penalty == 0.0

    def test_penalty_scales_with_count(self):
        from kicad_agent.placement.interactive import _compute_overlap_penalty

        # 3 overlapping components
        positions = {
            "R1": (50.0, 40.0, 0.0),
            "R2": (50.5, 40.0, 0.0),
            "R3": (51.0, 40.0, 0.0),
        }
        sizes = {"R1": 5.0, "R2": 5.0, "R3": 5.0}
        penalty = _compute_overlap_penalty(positions, sizes, 1.0)

        # 3 overlapping pairs: (R1,R2), (R1,R3), (R2,R3)
        assert penalty >= 3000.0


# ---------------------------------------------------------------------------
# Engine integration
# ---------------------------------------------------------------------------


class TestEngineOverlapFree:
    """HybridPlacementEngine produces overlap-free output with packing."""

    def test_rule_based_50_components(self):
        from kicad_agent.generation.intent import ComponentSpec
        from kicad_agent.placement.engine import HybridPlacementEngine, PlacementRequest

        components = [
            ComponentSpec(reference=f"R{i}", library_id="Device:R")
            for i in range(50)
        ]
        request = PlacementRequest(
            components=components,
            board_width=100.0,
            board_height=80.0,
            min_clearance=1.0,
            use_ml=False,
            refine_sa=True,
        )

        engine = HybridPlacementEngine()
        output = engine.place(request)

        # Extract sizes for validation (ComponentSpec has no width/height — use default 2.0mm)
        comp_sizes = {c.reference: 2.0 for c in components}
        validator = PlacementValidator(
            board_width=100.0, board_height=80.0, min_clearance=1.0
        )
        has_any, count = validator.has_overlaps(output.positions, comp_sizes)

        assert has_any is False, f"Engine produced {count} overlaps"
        assert output.source == "rule_based_packed"

    def test_engine_with_fixed_positions(self):
        from kicad_agent.generation.intent import ComponentSpec
        from kicad_agent.placement.engine import HybridPlacementEngine, PlacementRequest

        components = [
            ComponentSpec(reference=f"R{i}", library_id="Device:R")
            for i in range(20)
        ]
        request = PlacementRequest(
            components=components,
            board_width=100.0,
            board_height=80.0,
            min_clearance=1.0,
            fixed_positions={"R0": (10.0, 10.0, 0.0), "R1": (90.0, 70.0, 0.0)},
            use_ml=False,
        )

        engine = HybridPlacementEngine()
        output = engine.place(request)

        comp_sizes = {c.reference: 2.0 for c in components}
        validator = PlacementValidator(
            board_width=100.0, board_height=80.0, min_clearance=1.0
        )
        has_any, count = validator.has_overlaps(output.positions, comp_sizes)

        assert has_any is False, f"Engine produced {count} overlaps"


# ---------------------------------------------------------------------------
# Scoring integration
# ---------------------------------------------------------------------------


class TestScoringOverlapCount:
    """PlacementScore includes overlap_count field."""

    def test_score_reports_overlaps(self):
        from kicad_agent.placement.scoring import PlacementScorer

        scorer = PlacementScorer(board_width=100.0, board_height=80.0, min_clearance=1.0)

        # Create a simple graph with net_nodes support
        class _Graph:
            def __init__(self):
                self._graph = type("G", (), {
                    "nodes": {},
                    "neighbors": lambda self, n: [],
                })()

            def component_nodes(self):
                return [f"c{i}" for i in range(3)]

            def net_nodes(self):
                return []  # No nets — HPWL returns (0, 1)

            @property
            def board_width(self):
                return 100.0

            @property
            def board_height(self):
                return 80.0

        graph = _Graph()
        for i in range(3):
            graph._graph.nodes[f"c{i}"] = {"reference": f"R{i}", "estimated_size": 2.0}

        # Overlapping positions
        positions = {"R0": (50.0, 40.0, 0.0), "R1": (50.5, 40.0, 0.0), "R2": (80.0, 60.0, 0.0)}
        score = scorer.score(positions, graph)

        assert score.overlap_count >= 1  # R0 and R1 overlap

    def test_score_zero_overlaps(self):
        from kicad_agent.placement.scoring import PlacementScorer

        scorer = PlacementScorer(board_width=100.0, board_height=80.0, min_clearance=1.0)

        class _Graph:
            def __init__(self):
                self._graph = type("G", (), {
                    "nodes": {},
                    "neighbors": lambda self, n: [],
                })()

            def component_nodes(self):
                return [f"c{i}" for i in range(3)]

            def net_nodes(self):
                return []

            @property
            def board_width(self):
                return 100.0

            @property
            def board_height(self):
                return 80.0

        graph = _Graph()
        for i in range(3):
            graph._graph.nodes[f"c{i}"] = {"reference": f"R{i}", "estimated_size": 2.0}

        positions = {"R0": (20.0, 20.0, 0.0), "R1": (50.0, 40.0, 0.0), "R2": (80.0, 60.0, 0.0)}
        score = scorer.score(positions, graph)

        assert score.overlap_count == 0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _count_overlaps(
    positions: dict[str, tuple[float, float, float]],
    sizes: dict[str, tuple[float, float]],
    fixed: dict[str, tuple[float, float, float]] | None = None,
) -> int:
    """Count overlapping pairs in a placement (sizes as (w, h) tuples)."""
    all_pos = dict(positions)
    if fixed:
        all_pos.update(fixed)
    all_sizes: dict[str, float] = {}
    for ref, (w, h) in sizes.items():
        all_sizes[ref] = max(w, h)
    refs = list(all_pos.keys())
    n = len(refs)
    count = 0
    for i in range(n):
        xi, yi, _ = all_pos[refs[i]]
        si = all_sizes.get(refs[i], 2.0) / 2.0
        for j in range(i + 1, n):
            xj, yj, _ = all_pos[refs[j]]
            sj = all_sizes.get(refs[j], 2.0) / 2.0
            if math.hypot(xi - xj, yi - yj) < si + sj:
                count += 1
    return count


def _count_overlaps_halfsizes(
    positions: dict[str, tuple[float, float, float]],
    sizes: dict[str, float],
    min_clearance: float = 1.0,
) -> int:
    """Count overlapping pairs in a placement (sizes as diameter floats, matching resolve_overlaps convention)."""
    refs = list(positions.keys())
    n = len(refs)
    count = 0
    for i in range(n):
        xi, yi, _ = positions[refs[i]]
        si = sizes.get(refs[i], 2.0) / 2.0 + min_clearance
        for j in range(i + 1, n):
            xj, yj, _ = positions[refs[j]]
            sj = sizes.get(refs[j], 2.0) / 2.0 + min_clearance
            if math.hypot(xi - xj, yi - yj) < si + sj:
                count += 1
    return count
