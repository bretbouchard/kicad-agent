"""Phase 99 R-6: SES multi-layer via parse + bridge verification (unit tests).

Verifies that parse_ses:
  - Extracts via padstack name and coordinates from (via "PADSTACK" X Y ...)
  - Derives from_layer/to_layer from the padstack name (Via[0-1] -> F.Cu/B.Cu,
    Via[0-In1] -> F.Cu/In1.Cu, Via[In1-In2] -> In1.Cu/In2.Cu)
  - Falls back to explicit layer tokens when present (future-proof)
  - Applies Y-negation consistently with wires

Also verifies ses_to_kicad_sexpr routes vias through ViaSegment.to_sexpr()
(canonical bridge.py emitter, WARN-2 fix) — no parallel f-string builder.

L-3 fix: synthetic SES strings include (resolution um 10) header so the
resolution factor is parsed correctly.
"""

from __future__ import annotations

import re

import pytest

from kicad_agent.routing.freerouting import (
    SesParseResult,
    SesVia,
    parse_ses,
    ses_to_kicad_sexpr,
)

# L-3 fix: every synthetic SES must include (resolution um 10) as the first
# line inside (session ...) so parse_ses reads the resolution factor correctly.
_SES_HEADER = "(pcb KiCad\n  (resolution um 10)\n  (unit um)\n"
_SES_FOOTER = ")\n"


def _wrap_ses(body: str) -> str:
    """Wrap a body fragment in a minimal valid SES envelope with resolution header."""
    return _SES_HEADER + body + _SES_FOOTER


class TestSesViaParse:
    """R-6 unit tests for parse_ses via extraction."""

    def test_via_with_padstack_name_and_coords(self) -> None:
        """(via "Via[0-1]" X Y) parses to SesVia with coords and default layers.

        This is the ACTUAL format Freerouting v2.2.4 emits (verified via
        reference SES captured in Step B.5). No explicit layer tokens.
        """
        ses = _wrap_ses(
            '  (network_out\n'
            '    (net "GND"\n'
            '      (via "Via[0-1]" 500000 300000\n'
            '        (net GND 1)\n'
            '      )\n'
            '    )\n'
            '  )\n'
        )
        result = parse_ses(ses)
        assert len(result.vias) == 1, f"Expected 1 via, got {len(result.vias)}"
        via = result.vias[0]
        assert via.net == "GND"
        assert via.x_mm == pytest.approx(50.0, abs=0.01)
        assert via.y_mm == pytest.approx(-30.0, abs=0.01)  # Y negated
        # Via[0-1] is THT spanning F.Cu + B.Cu.
        assert via.from_layer == "F.Cu"
        assert via.to_layer == "B.Cu"

    def test_via_blind_padstack_name_derives_layers(self) -> None:
        """Via[0-In1] padstack name derives from_layer=F.Cu, to_layer=In1.Cu."""
        ses = _wrap_ses(
            '  (network_out\n'
            '    (net "SIG"\n'
            '      (via "Via[0-In1]" 100000 200000\n'
            '        (net SIG 1)\n'
            '      )\n'
            '    )\n'
            '  )\n'
        )
        result = parse_ses(ses)
        assert len(result.vias) == 1
        via = result.vias[0]
        assert via.from_layer == "F.Cu"
        assert via.to_layer == "In1.Cu"

    def test_via_buried_padstack_name_derives_layers(self) -> None:
        """Via[In1-In2] padstack name derives from_layer=In1.Cu, to_layer=In2.Cu."""
        ses = _wrap_ses(
            '  (network_out\n'
            '    (net "SIG"\n'
            '      (via "Via[In1-In2]" 100000 200000\n'
            '        (net SIG 1)\n'
            '      )\n'
            '    )\n'
            '  )\n'
        )
        result = parse_ses(ses)
        assert len(result.vias) == 1
        via = result.vias[0]
        assert via.from_layer == "In1.Cu"
        assert via.to_layer == "In2.Cu"

    def test_via_with_explicit_layer_tokens(self) -> None:
        """Future-proof: (via F.Cu In1.Cu X Y SIZE DRILL) parses explicit layers.

        If a future Freerouting version emits explicit layer tokens, parse_ses
        should prefer them over padstack-name derivation.
        """
        ses = _wrap_ses(
            '  (network_out\n'
            '    (net "SIG"\n'
            '      (via F.Cu In1.Cu 50000 30000 800 400)\n'
            '    )\n'
            '  )\n'
        )
        result = parse_ses(ses)
        assert len(result.vias) == 1
        via = result.vias[0]
        assert via.from_layer == "F.Cu"
        assert via.to_layer == "In1.Cu"
        assert via.x_mm == pytest.approx(50.0, abs=0.01)
        assert via.y_mm == pytest.approx(-30.0, abs=0.01)

    def test_via_float_coordinates(self) -> None:
        """Via coordinates may be floating point (reference SES has 117519.3)."""
        ses = _wrap_ses(
            '  (network_out\n'
            '    (net "GND"\n'
            '      (via "Via[0-1]" 117519.3 86715.2\n'
            '        (net GND 1)\n'
            '      )\n'
            '    )\n'
            '  )\n'
        )
        result = parse_ses(ses)
        assert len(result.vias) == 1
        via = result.vias[0]
        assert via.x_mm == pytest.approx(11.75193, abs=0.001)
        assert via.y_mm == pytest.approx(-8.67152, abs=0.001)


class TestSesToKiCadSexprLayers:
    """R-6: ses_to_kicad_sexpr routes through ViaSegment.to_sexpr (WARN-2)."""

    def test_ses_to_kicad_sexpr_derived_layers(self) -> None:
        """Via with derived layers emits (layers "F.Cu" "B.Cu") via ViaSegment.to_sexpr."""
        via = SesVia(
            net="GND",
            x_mm=50.0,
            y_mm=-30.0,
            size_mm=0.8,
            drill_mm=0.4,
            from_layer="F.Cu",
            to_layer="B.Cu",
        )
        result = SesParseResult(vias=[via])
        sexpr = ses_to_kicad_sexpr(result)
        assert '(layers "F.Cu" "B.Cu")' in sexpr
        assert "(via" in sexpr
        assert "(at 50.000000 -30.000000)" in sexpr or "(at 50.0000 -30.0000)" in sexpr

    def test_ses_to_kicad_sexpr_multilayer_layers(self) -> None:
        """Via with In1.Cu/In2.Cu layers emits correct (layers ...) (NOT F.Cu/B.Cu)."""
        via = SesVia(
            net="SIG",
            x_mm=10.0,
            y_mm=20.0,
            size_mm=0.6,
            drill_mm=0.3,
            from_layer="In1.Cu",
            to_layer="In2.Cu",
        )
        result = SesParseResult(vias=[via])
        sexpr = ses_to_kicad_sexpr(result)
        assert '(layers "In1.Cu" "In2.Cu")' in sexpr
        # Ensure the hardcoded bug is gone.
        assert '(layers "F.Cu" "B.Cu")' not in sexpr

    def test_ses_to_kicad_sexpr_uses_via_segment_to_sexpr(self) -> None:
        """WARN-2: ses_to_kicad_sexpr constructs ViaSegment and calls to_sexpr.

        The output must match the bridge.py ViaSegment.to_sexpr format
        (multi-line, indented), NOT a single-line parallel f-string.
        """
        via = SesVia(
            net="N1",
            x_mm=5.0,
            y_mm=6.0,
            size_mm=0.8,
            drill_mm=0.4,
            from_layer="F.Cu",
            to_layer="In1.Cu",
        )
        result = SesParseResult(vias=[via])
        sexpr = ses_to_kicad_sexpr(result)
        # ViaSegment.to_sexpr emits multi-line format:
        #   (via
        #     (at X Y)
        #     (size D)
        #     (drill H)
        #     (layers "L1" "L2")
        #     ...
        #   )
        assert "\n" in sexpr.strip(), (
            "ses_to_kicad_sexpr must produce multi-line ViaSegment.to_sexpr output, "
            "not a single-line f-string"
        )
        # Canonical ViaSegment.to_sexpr uses 4-decimal format (.4f), not 6-decimal.
        # The old parallel builder used .6f — its absence confirms the refactor.
        assert "0.8000" in sexpr, (
            "ViaSegment.to_sexpr uses .4f format; old parallel builder used .6f"
        )

    def test_no_hardcoded_fcus_bcu_in_output(self) -> None:
        """Hardcoded (layers "F.Cu" "B.Cu") must NOT appear for non-default vias."""
        via = SesVia(
            net="N",
            x_mm=1.0,
            y_mm=2.0,
            size_mm=0.5,
            drill_mm=0.25,
            from_layer="F.Cu",
            to_layer="In1.Cu",
        )
        result = SesParseResult(vias=[via])
        sexpr = ses_to_kicad_sexpr(result)
        assert '(layers "F.Cu" "B.Cu")' not in sexpr, (
            "Hardcoded F.Cu/B.Cu layers found in via emission — WARN-2 regression"
        )
