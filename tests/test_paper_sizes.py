"""Phase 108 Task 2 — unit tests for paper_sizes + SugiyamaLayout.fit_to_page.

These pin the contract of the on-page guarantee independently of the
integration tests in test_autolayout_srs.py. Fast (no fixture I/O).
"""
from __future__ import annotations

from volta.schematic_autolayout import SugiyamaLayout, paper_sizes
from volta.schematic_autolayout.sugiyama import (
    DEFAULT_LAYER_SPACING_MM,
    DEFAULT_NODE_SPACING_MM,
)


# ---------------------------------------------------------------------------
# paper_sizes
# ---------------------------------------------------------------------------


def test_a4_landscape_dimensions() -> None:
    """A4 must be 297 x 210 mm (landscape, KiCad default)."""
    assert paper_sizes.PAPER_SIZES_MM["A4"] == (297.0, 210.0)


def test_parse_paper_from_sch_extracts_declaration() -> None:
    """parse_paper_from_sch returns the declared paper, not the default."""
    content = '(kicad_sch (version 20250114) (paper "A3") (generator eeschema))'
    assert paper_sizes.parse_paper_from_sch(content) == "A3"


def test_parse_paper_from_sch_defaults_to_a4_when_missing() -> None:
    """Synthetic/minimal fixtures without (paper ...) default to A4."""
    content = '(kicad_sch (version 20250114) (generator eeschema))'
    assert paper_sizes.parse_paper_from_sch(content) == "A4"


def test_paper_dims_mm_falls_back_to_a4_for_unknown() -> None:
    """Unknown paper sizes fall back to A4 rather than crashing."""
    w, h = paper_sizes.paper_dims_mm("Z42")
    assert (w, h) == paper_sizes.PAPER_SIZES_MM["A4"]


def test_usable_area_mm_applies_margin_on_all_sides() -> None:
    """usable_area_mm returns the in-bounds rectangle (margin on each edge)."""
    x_min, y_min, x_max, y_max = paper_sizes.usable_area_mm("A4")
    assert x_min == paper_sizes.USABLE_PAGE_MARGIN_MM
    assert y_min == paper_sizes.USABLE_PAGE_MARGIN_MM
    assert x_max == 297.0 - paper_sizes.USABLE_PAGE_MARGIN_MM
    assert y_max == 210.0 - paper_sizes.USABLE_PAGE_MARGIN_MM


# ---------------------------------------------------------------------------
# SugiyamaLayout.fit_to_page
# ---------------------------------------------------------------------------


def test_fit_to_page_empty_returns_empty() -> None:
    """fit_to_page on empty positions is a no-op (no crash)."""
    layout = SugiyamaLayout()
    assert layout.fit_to_page({}, 297.0, 210.0, 20.0) == {}


def test_fit_to_page_no_scaling_when_already_in_bounds() -> None:
    """Layouts already inside the page are NOT enlarged (scale cap = 1.0).

    fit_to_page translates the bbox min to (margin, margin) so the layout
    sits in the top-left of the usable area; the relative spacing between
    components is preserved exactly (no scaling when scale cap = 1.0).
    """
    layout = SugiyamaLayout()
    positions = {"A": (50.0, 50.0), "B": (100.0, 100.0)}
    fitted = layout.fit_to_page(positions, 297.0, 210.0, 20.0)
    # Original spacing was 50mm in each axis — must be preserved (no scale).
    dx = fitted["B"].x - fitted["A"].x
    dy = fitted["B"].y - fitted["A"].y
    assert abs(dx - 50.0) < layout.grid_mm  # snapped, so allow 1 grid of slack
    assert abs(dy - 50.0) < layout.grid_mm


def test_fit_to_page_scales_when_bbox_exceeds_page() -> None:
    """Layouts bigger than the page get uniformly scaled down to fit."""
    layout = SugiyamaLayout()
    # 500mm wide layout on a 297mm page — must scale down.
    positions = {
        "A": (0.0, 0.0),
        "B": (500.0, 0.0),
    }
    fitted = layout.fit_to_page(positions, 297.0, 210.0, 20.0)
    fitted_width = max(c.x for c in fitted.values()) - min(c.x for c in fitted.values())
    # Usable width = 297 - 2*20 = 257mm. Scaled layout must fit within it.
    assert fitted_width <= 257.0 + layout.grid_mm  # allow grid-snap slack


def test_fit_to_page_every_coord_on_page() -> None:
    """After fit_to_page no coordinate may exceed [margin, page - margin]."""
    layout = SugiyamaLayout()
    # Pathologically large layout (the failure case from Arduino_Mega).
    positions = {f"R{i}": (i * 50.0, i * 30.0) for i in range(20)}
    fitted = layout.fit_to_page(positions, 297.0, 210.0, 20.0)
    margin = 20.0
    for coord in fitted.values():
        assert margin - layout.grid_mm <= coord.x <= 297.0 - margin + layout.grid_mm, (
            f"X out of bounds: {coord.x}"
        )
        assert margin - layout.grid_mm <= coord.y <= 210.0 - margin + layout.grid_mm, (
            f"Y out of bounds: {coord.y}"
        )


def test_fit_to_page_accepts_layout_coordinate_namedtuples() -> None:
    """fit_to_page accepts both tuple and LayoutCoordinate inputs.

    The handler path passes (x, y) tuples; the engine path passes
    LayoutCoordinate NamedTuples. Both must work.
    """
    from volta.schematic_autolayout import LayoutCoordinate

    layout = SugiyamaLayout()
    tuple_positions = {"A": (10.0, 10.0)}
    coord_positions = {
        "A": LayoutCoordinate(x=10.0, y=10.0),
    }
    fitted_from_tuples = layout.fit_to_page(tuple_positions, 297.0, 210.0, 20.0)
    fitted_from_coords = layout.fit_to_page(coord_positions, 297.0, 210.0, 20.0)
    assert fitted_from_tuples["A"] == fitted_from_coords["A"]


def test_default_spacing_constants_unchanged() -> None:
    """Regression guard: Plan 01 spacing constants pinned by Phase 108 tests."""
    assert DEFAULT_LAYER_SPACING_MM == 25.4
    assert DEFAULT_NODE_SPACING_MM == 12.7
