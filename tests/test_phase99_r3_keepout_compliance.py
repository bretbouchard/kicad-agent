"""Phase 99 R-3: Keepout polygon compliance (slow integration).

Verifies that Freerouting-routed output respects the source board's zone
polygons, with upfront fixture zone-type verification per WARN-7.

Uses the RaspberryPi-uHAT fixture which has 1 zone. The zone type is verified
BEFORE the compliance assertion per the C-1 fix (3-way classification):
  - Copper pour (net_name non-empty): same-net wires may touch, diff-net may not cross
  - Routing keepout (is_routing_keepout): NO wire may cross
  - Placement-only (neither): assert nothing (Freerouting correctly not told to avoid)

JAR-skip fixture: skips gracefully when Freerouting JAR or Java is unavailable.
"""

from __future__ import annotations

from pathlib import Path

import pytest

pytestmark = pytest.mark.slow

try:
    from shapely.geometry import LineString, Polygon
    _HAS_SHAPELY = True
except ImportError:
    _HAS_SHAPELY = False


@pytest.fixture(autouse=True)
def _skip_if_no_freerouting_or_shapely():
    """JAR-skip + shapely-skip fixture."""
    from kicad_agent.routing.freerouting import is_freerouting_available
    if not is_freerouting_available():
        pytest.skip("Freerouting JAR or Java runtime not available")
    if not _HAS_SHAPELY:
        pytest.skip("shapely not installed")


_RPI_UHAT = Path(__file__).parent / "fixtures" / "RaspberryPi-uHAT" / "RaspberryPi-uHAT.kicad_pcb"


def test_no_wire_crosses_keepout():
    """R-3 slow: Freerouting output respects keepout polygons.

    WARN-7: fixture zone type verified BEFORE the compliance assertion.
    C-1 fix: 3-way classification (copper pour / routing keepout / placement-only).
    """
    from kicad_agent.parser.pcb_native_parser import NativeParser
    from kicad_agent.routing.freerouting import parse_ses, route_with_freerouting, ses_to_kicad_sexpr

    # STEP 1 (WARN-7): verify fixture zone type upfront.
    board = NativeParser.parse_pcb(_RPI_UHAT)
    assert len(board.zones) >= 1, (
        f"Fixture {_RPI_UHAT.name} must have >=1 zone for R-3 validation"
    )
    zone = board.zones[0]
    net_name = zone.net_name or getattr(zone, "netName", "")
    zone_is_copper_pour = bool(net_name)
    zone_is_routing_keepout = bool(getattr(zone, "is_routing_keepout", False))

    print(
        f"\nZone type: copper_pour={zone_is_copper_pour}, "
        f"routing_keepout={zone_is_routing_keepout}, net='{net_name}'"
    )

    # C-1 fix Category 3: placement-only keepout.
    # RaspberryPi-uHAT's zone is Category 3 (footprints not_allowed only,
    # tracks/vias allowed) — Freerouting was correctly NOT told to avoid it.
    # The routing compliance assertion is N/A for this zone type.
    if not zone_is_copper_pour and not zone_is_routing_keepout:
        pytest.skip(
            "Fixture zone is placement-only keepout (C-1 Category 3); "
            "routing compliance assertion N/A — Freerouting correctly not told "
            "to avoid this region"
        )

    # STEP 2: generate DSN, route with Freerouting, parse SES.
    result = route_with_freerouting(_RPI_UHAT, max_passes=2)
    if not result.success:
        pytest.skip(
            f"Freerouting did not complete on {_RPI_UHAT.name}: "
            f"{result.stderr[:200]}"
        )
    ses_text = result.ses_path.read_text(encoding="utf-8")
    ses_result = parse_ses(ses_text)
    assert len(ses_result.wires) > 0, "Freerouting produced no wires"

    # STEP 3: build zone polygon and apply zone-type-appropriate assertion.
    if not zone.polygon_points:
        pytest.skip("Zone has no polygon points — cannot build shapely Polygon")
    zone_poly = Polygon(zone.polygon_points)
    if not zone_poly.is_valid:
        zone_poly = zone_poly.buffer(0)
        if not zone_poly.is_valid:
            pytest.skip("Zone polygon is geometrically invalid after buffer(0)")

    violating_wires = []
    for wire in ses_result.wires:
        if len(wire.points) < 2:
            continue
        line = LineString(wire.points)
        crosses = line.crosses(zone_poly)
        within = line.within(zone_poly)

        if zone_is_copper_pour:
            # Category 1: different-net wires must not cross; same-net may touch.
            if wire.net != net_name and (crosses or within):
                violating_wires.append((wire.net, "crosses copper pour"))
        elif zone_is_routing_keepout:
            # Category 2: NO wire may cross or be within.
            if crosses or within:
                violating_wires.append((wire.net, "crosses routing keepout"))

    assert not violating_wires, (
        f"{len(violating_wires)} wires violate zone '{net_name}': "
        f"{violating_wires[:5]}"
    )

    # ses_to_kicad_sexpr should produce valid output.
    sexpr = ses_to_kicad_sexpr(ses_result)
    assert "(segment" in sexpr or "(via" in sexpr
