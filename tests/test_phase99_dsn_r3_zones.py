"""R-3: zone emission with C-1 3-way classification (plane / keepout / skip)."""
from __future__ import annotations

from pathlib import Path

import pytest

from kicad_agent.parser.pcb_native_parser import NativeParser
from kicad_agent.routing.dsn_generator import generate_dsn

_REPO_ROOT = Path(__file__).resolve().parents[1]
_UHAT = _REPO_ROOT / "tests" / "fixtures" / "RaspberryPi-uHAT" / "RaspberryPi-uHAT.kicad_pcb"
_SMD = _REPO_ROOT / "tests" / "fixtures" / "smd_test_board.kicad_pcb"


def test_r3_zone_classification_matches_is_routing_keepout() -> None:
    """M-5 fix: DSN emission must match zone.is_routing_keepout classification (C-1)."""
    if not _UHAT.exists():
        pytest.skip(f"Fixture missing: {_UHAT}")
    board = NativeParser.parse_pcb(_UHAT)
    assert len(board.zones) >= 1, "Fixture must have at least 1 zone for R-3"
    zone = board.zones[0]
    dsn = generate_dsn(_UHAT.read_text(encoding="utf-8"), _UHAT)

    net_name = zone.net_name or getattr(zone, "netName", "")
    if net_name:
        # Category 1: copper pour
        assert '(plane "' in dsn, "Copper-pour zone must emit (plane ...)"
        assert "(keepout" not in dsn, "Copper-pour zone must NOT emit (keepout ...)"
    elif getattr(zone, "is_routing_keepout", False):
        # Category 2: routing keepout
        assert "(keepout" in dsn, "Routing keepout zone must emit (keepout ...)"
    else:
        # Category 3 (the actual fixture case): placement-only keepout
        assert "(keepout" not in dsn, (
            "Placement-only keepout (is_routing_keepout=False) must NOT emit "
            "(keepout ...) — that would tell Freerouting to avoid a region the "
            "source PCB allows tracks through (C-1 bug)"
        )


def test_r3_uhat_zone_is_placement_only_keepout() -> None:
    """C-1 motivation: RaspberryPi-uHAT zone is placement-only (footprints not_allowed,
    tracks/vias allowed). is_routing_keepout must be False."""
    if not _UHAT.exists():
        pytest.skip(f"Fixture missing: {_UHAT}")
    board = NativeParser.parse_pcb(_UHAT)
    assert len(board.zones) >= 1
    zone = board.zones[0]
    # The fixture is a placement-only keepout (PoE footprint exclusion zone).
    assert zone.keepout_footprints == "not_allowed", (
        "Fixture precondition: uHAT zone must have footprints not_allowed"
    )
    assert zone.keepout_tracks == "allowed", (
        "Fixture precondition: uHAT zone must have tracks allowed"
    )
    assert zone.keepout_vias == "allowed", (
        "Fixture precondition: uHAT zone must have vias allowed"
    )
    assert zone.is_routing_keepout is False, (
        "Placement-only keepout must NOT be classified as routing keepout (C-1)"
    )


def test_r3_zero_zones_emits_no_keepout_or_plane() -> None:
    """Negative case: PCB with zero zones produces zero (keepout)/(plane)."""
    if not _SMD.exists():
        pytest.skip(f"Fixture missing: {_SMD}")
    dsn = generate_dsn(_SMD.read_text(encoding="utf-8"), _SMD)
    assert "(keepout" not in dsn
    assert "(plane" not in dsn


def test_r3_copper_pour_zone_skipped_after_bead_24() -> None:
    """Category 1 (revised post-Bead-#24): copper-pour zones are SKIPPED entirely.

    Original R-3 spec called for `(plane ...)` emission, but Bead #24 fix
    (analog-ecosystem Phase 129) intentionally skips plane emission because
    Freerouting rejects plane polygons due to layer declaration mismatches
    in padstacks. Freerouting treats copper pours as routing obstacles via
    pad clearances — no plane declarations needed for routing to succeed.

    Test now asserts the new intended behavior: no (plane ...) emitted, no
    (keepout ...) emitted (it's not a routing keepout, just a copper pour).
    """
    pcb = """\
(kicad_pcb
  (net 0 "")
  (net 1 "GND")
  (zone
    (net 1)
    (net_name "GND")
    (layer "F.Cu")
    (uuid "abc12345-6789-def0-1234-567890abcdef")
    (polygon
      (pts
        (xy 0 0)
        (xy 10 0)
        (xy 10 10)
        (xy 0 10)
      )
    )
  )
)
"""
    dsn = generate_dsn(pcb)
    # Plane emission intentionally skipped per Bead #24
    assert '(plane' not in dsn, "Plane emission disabled per Bead #24 (Freerouting rejects)"
    # Also NOT a keepout — it's a copper pour, not a routing keepout
    assert '(keepout' not in dsn, "Copper pour should not emit as keepout"


def test_r3_routing_keepout_zone_emits_keepout() -> None:
    """Category 2: a zone with tracks not_allowed emits (keepout ...)."""
    pcb = """\
(kicad_pcb
  (net 0 "")
  (zone
    (net 0)
    (net_name "")
    (layer "B.Cu")
    (uuid "deadbeef-0000-0000-0000-000000000001")
    (keepout
      (tracks not_allowed)
      (vias not_allowed)
      (pads allowed)
      (copperpour allowed)
      (footprints allowed)
    )
    (polygon
      (pts
        (xy 0 0)
        (xy 5 0)
        (xy 5 5)
        (xy 0 5)
      )
    )
  )
)
"""
    dsn = generate_dsn(pcb)
    assert '(keepout' in dsn, "Routing keepout zone (tracks not_allowed) must emit (keepout ...)"
    assert '(plane' not in dsn
