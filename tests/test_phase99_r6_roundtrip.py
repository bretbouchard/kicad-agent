"""Phase 99 R-6: DSN -> Freerouting -> SES -> segments roundtrip (slow integration).

Runs the full pipeline on the Arduino_Mega fixture and verifies that:
  - Freerouting produces a valid SES file
  - parse_ses extracts wires and vias
  - ses_to_kicad_sexpr produces valid KiCad S-expressions
  - Via layers are correctly extracted (not hardcoded)

JAR-skip fixture: skips gracefully when Freerouting JAR or Java is unavailable.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from kicad_agent.routing.freerouting import (
    is_freerouting_available,
    parse_ses,
    route_with_freerouting,
    ses_to_kicad_sexpr,
)

pytestmark = pytest.mark.slow


@pytest.fixture(autouse=True)
def _skip_if_no_freerouting():
    """JAR-skip fixture: skip slow integration when Freerouting unavailable."""
    if not is_freerouting_available():
        pytest.skip("Freerouting JAR or Java runtime not available")


_ARDUINO_MEGA = Path(__file__).parent / "fixtures" / "Arduino_Mega" / "Arduino_Mega.kicad_pcb"


def test_dsn_freerouting_ses_segments_roundtrip():
    """R-6 slow: full DSN -> Freerouting -> SES -> segments roundtrip.

    Generates DSN from Arduino_Mega, runs Freerouting (2 passes), parses SES,
    converts to KiCad S-expressions, asserts output contains valid segments/vias.
    """
    result = route_with_freerouting(_ARDUINO_MEGA, max_passes=2)
    assert result.success, (
        f"Freerouting failed: stderr={result.stderr[:300]}"
    )
    assert result.ses_path is not None and result.ses_path.exists()

    ses_text = result.ses_path.read_text(encoding="utf-8")
    ses_result = parse_ses(ses_text)

    # Routing must produce SOME output (wires or vias).
    total_items = len(ses_result.wires) + len(ses_result.vias)
    assert total_items > 0, (
        "Freerouting produced zero wires and zero vias — routing did not run"
    )

    # If Freerouting produced vias, each must have valid layer fields.
    for via in ses_result.vias:
        assert via.from_layer, f"Via missing from_layer: {via}"
        assert via.to_layer, f"Via missing to_layer: {via}"
        # Via coordinates must be in valid board range (Arduino_Mega is
        # ~100-200mm x ~46-100mm). Allow generous tolerance for Y-negation.
        assert -200.0 < via.x_mm < 300.0, f"Via x_mm out of range: {via.x_mm}"
        assert -200.0 < via.y_mm < 200.0, f"Via y_mm out of range: {via.y_mm}"

    # ses_to_kicad_sexpr must produce valid KiCad output.
    sexpr = ses_to_kicad_sexpr(ses_result)
    if ses_result.wires:
        assert "(segment" in sexpr, "Wires present but no (segment ...) in output"
    if ses_result.vias:
        assert "(via" in sexpr, "Vias present but no (via ...) in output"

    # Print summary for diagnostic visibility (captured by pytest -s).
    print(
        f"\nRoundtrip result: {len(ses_result.wires)} wires, "
        f"{len(ses_result.vias)} vias"
    )
