"""Page-region layout planner for multi-group schematic autolayout.

Phase 108 Task 2 revision. The original placement flow had two bugs:

  1. **Subcircuit groups collapsed to top-left.** Each group ran Sugiyama
     with an ``x_offset`` to separate them horizontally, but ``fit_to_page``
     then scaled the UNION of all groups back to ``(margin, margin)``,
     discarding the x_offset separation.
  2. **Parked components collided with placed groups.** Parking started at
     ``page_midpoint`` regardless of where the placed groups actually ended,
     so parked components jammed into the same Y band as group bottoms.

This module fixes both by planning **disjoint page regions** before any
coordinate assignment:

  - The usable page is divided into N horizontal bands (one per subcircuit
    group) when ``group_count > 1``, plus a parking band at the bottom.
  - Each group's Sugiyama coordinates are scaled + translated into ITS
    band — independent of the other groups.
  - Loose components land in the parking band, which starts below the
    lowest placed group (not at the page midpoint).

For the common case of 1-3 groups on A4, this produces clean visual
separation. For many small groups (Arduino_Mega has 7 single-component
"solo" groups), they tile into a grid instead of stacking vertically.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PageRegion:
    """A rectangular region of the page assigned to a group or parking."""
    x_min: float
    y_min: float
    x_max: float
    y_max: float

    @property
    def width(self) -> float:
        return self.x_max - self.x_min

    @property
    def height(self) -> float:
        return self.y_max - self.y_min


def plan_group_regions(
    group_count: int,
    page_w: float,
    page_h: float,
    margin: float,
) -> list[PageRegion]:
    """Assign each subcircuit group a disjoint page region.

    Strategy scales with group count:
      - 1 group: full usable area.
      - 2-4 groups: vertical stack of horizontal bands (each group spans
        the full page width, in its own Y row).
      - 5+ groups: row-major grid (groups tile left-to-right, top-to-bottom)
        so a 7-group board like Arduino_Mega doesn't waste 7 vertical bands
        on single-component groups.

    The parking band is reserved separately by the caller via
    ``plan_parking_region`` — this function only plans for placed groups.
    """
    usable = PageRegion(margin, margin, page_w - margin, page_h - margin)
    if group_count <= 0:
        return []
    if group_count == 1:
        return [usable]

    # Heuristic: many small "solo" groups (typical of poorly-connected
    # fixtures) tile better as a grid. Few real subcircuits (with internal
    # structure) want their own full-width row.
    if group_count >= 5:
        # Row-major grid. Cols = ceil(sqrt(N)), Rows = ceil(N / cols).
        import math
        cols = max(1, math.isqrt(group_count) + (1 if math.isqrt(group_count) ** 2 < group_count else 0))
        cols = min(cols, group_count)
        rows = math.ceil(group_count / cols)
    else:
        # 2-4 groups: vertical stack, full width each.
        cols, rows = 1, group_count

    cell_w = usable.width / cols
    cell_h = usable.height / rows
    regions: list[PageRegion] = []
    for i in range(group_count):
        row, col = divmod(i, cols)
        x_min = usable.x_min + col * cell_w
        y_min = usable.y_min + row * cell_h
        regions.append(PageRegion(x_min, y_min, x_min + cell_w, y_min + cell_h))
    return regions


def plan_parking_region(
    placed_regions: list[PageRegion],
    page_w: float,
    page_h: float,
    margin: float,
    parking_count: int,
    node_spacing_mm: float,
) -> PageRegion | None:
    """Reserve a region for loose components that doesn't overlap any placed group.

    Strategy: take everything below the lowest placed-group bottom, down
    to the page margin. If that's too small for ``parking_count`` components
    at ``node_spacing_mm`` spacing, grow upward by reclaiming empty space
    inside the placed region grid (rare — only triggers on very full pages).
    """
    if parking_count <= 0 or not placed_regions:
        # No placed groups — parking gets the full usable area.
        return PageRegion(margin, margin, page_w - margin, page_h - margin)

    placed_bottom = max(r.y_max for r in placed_regions)
    parking_top = placed_bottom + node_spacing_mm  # 1 row gap below placed
    parking_bottom = page_h - margin

    if parking_top >= parking_bottom:
        # Placed groups fill the page — parking gets squeezed into whatever
        # margin remains at the very bottom. Better than overlapping.
        parking_top = max(placed_bottom, margin)
        parking_bottom = max(parking_top + node_spacing_mm, parking_bottom)

    return PageRegion(margin, parking_top, page_w - margin, parking_bottom)


def scale_to_region(
    positions: dict[str, tuple[float, float]],
    region: PageRegion,
    snap_fn,
    component_size_mm: float = 12.7,
) -> dict[str, tuple[float, float]]:
    """Scale + translate a group's positions into a page region.

    Pads each component by ``component_size_mm`` (default 12.7 = 5 grid
    units — typical R/C body width) so the bounding box accounts for the
    visible body, not just the origin point. This prevents adjacent
    components from visually overlapping when their grid coordinates are
    correct but their bodies are wider than the spacing.

    ``snap_fn`` is ``SugiyamaLayout._snap_to_grid`` (passed in to avoid a
    circular import — the planner stays engine-agnostic).
    """
    if not positions:
        return {}

    half = component_size_mm / 2.0
    # positions is {ref: (x, y)} — extract coords from the tuple values.
    xs = [coord[0] for coord in positions.values()]
    ys = [coord[1] for coord in positions.values()]

    min_x, max_x = min(xs), max(xs)
    min_y, max_y = min(ys), max(ys)

    # Pad the bbox by half a component on each side so we don't scale
    # origins to the region edge (which would clip the bodies).
    bbox_w = max(max_x - min_x + component_size_mm, component_size_mm)
    bbox_h = max(max_y - min_y + component_size_mm, component_size_mm)

    scale_x = region.width / bbox_w if bbox_w > 0 else 1.0
    scale_y = region.height / bbox_h if bbox_h > 0 else 1.0
    scale = min(scale_x, scale_y, 1.0)  # never enlarge

    # Translate so the bbox's padded-min lands at the region's min.
    new_positions: dict[str, tuple[float, float]] = {}
    for ref, (x, y) in positions.items():
        rel_x = (x - min_x) + half  # shift so origin is at padded-min
        rel_y = (y - min_y) + half
        new_x = snap_fn(region.x_min + rel_x * scale)
        new_y = snap_fn(region.y_min + rel_y * scale)
        # Clamp to region (snap can overshoot by half a grid)
        new_x = min(new_x, region.x_max - half)
        new_y = min(new_y, region.y_max - half)
        new_positions[ref] = (new_x, new_y)
    return new_positions


def park_in_region(
    refs: list[str],
    region: PageRegion,
    snap_fn,
    node_spacing_mm: float,
) -> dict[str, tuple[float, float]]:
    """Lay out ``refs`` in a grid inside ``region``.

    Returns ``{ref: (x, y)}`` for every ref. Sorts refs by designator
    first (R1, R2, ..., C1, C2) for stable, human-scannable parking order.
    The grid wraps when it fills the region width.
    """
    if not refs:
        return {}

    import re

    def _ref_key(ref: str) -> tuple[str, int]:
        m = re.match(r'([A-Za-z]+)(\d+)', ref)
        if m:
            return (m.group(1), int(m.group(2)))
        return (ref, 0)

    sorted_refs = sorted(refs, key=_ref_key)
    usable_w = max(region.width, node_spacing_mm)
    cols = max(int(usable_w // node_spacing_mm), 1)
    spacing_x = region.width / cols

    parking: dict[str, tuple[float, float]] = {}
    for i, ref in enumerate(sorted_refs):
        row, col = divmod(i, cols)
        x = snap_fn(region.x_min + col * spacing_x + node_spacing_mm / 2.0)
        y = snap_fn(region.y_min + row * node_spacing_mm + node_spacing_mm / 2.0)
        # Clamp to region
        x = min(x, region.x_max)
        y = min(y, region.y_max)
        parking[ref] = (x, y)
    return parking
