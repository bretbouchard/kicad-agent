"""Phase 99 R-4: Via padstacks per stackup.

Verifies that generate_dsn emits:
  - 2-layer source PCB: only THT via padstack (Via[0-1]) with shapes on F.Cu + B.Cu
  - 4-layer source PCB: THT + blind (Via[0-In1]) + buried (Via[In1-In2]) padstacks
  - Per-net-class via padstacks cross-plan wiring (H-2: emitted in 99-01, verified here)

Per WARN-3: no pytest.skip hatch on the 4-layer test. The 4-layer stackup is
synthesized in-task. If stackup parsing fails, the test FAILS, not skips.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from kicad_agent.parser.pcb_native_parser import NativeParser
from kicad_agent.routing.dsn_generator import generate_dsn

_SMD_BOARD = Path(__file__).parent / "fixtures" / "smd_test_board.kicad_pcb"

# Synthetic 4-layer PCB (KiCad 10 quoted-string layers form).
# Per plan Task 1 Step D: synthesize in-task, NO pytest.skip hatch.
_4_LAYER_PCB = """
(kicad_pcb
  (general (layers 4))
  (layers "F.Cu" "In1.Cu" "In2.Cu" "B.Cu")
  (setup (stackup
    (layer "F.Cu" (type "copper"))
    (layer "dielectric 1" (type "core"))
    (layer "In1.Cu" (type "copper"))
    (layer "dielectric 2" (type "core"))
    (layer "In2.Cu" (type "copper"))
    (layer "dielectric 3" (type "core"))
    (layer "B.Cu" (type "copper"))))
)
"""

# Synthetic PCB with a named net class carrying via_diameter (H-2 cross-plan wiring).
_POWER_CLASS_PCB = """
(kicad_pcb
  (general (layers 2))
  (layers "F.Cu" "B.Cu")
  (net 0 "")
  (net 1 "GND")
  (net 2 "VCC")
  (net_class "Power" ""
    (via_diameter 0.8)
    (via_drill 0.4)
    (trace_width 0.5)
    (clearance 0.3)
    (add_net "GND")
    (add_net "VCC"))
)
"""


def _padstack_names(dsn: str) -> list[str]:
    """Extract all (padstack "NAME" ...) names from DSN text."""
    return re.findall(r'\(padstack\s+"([^"]+)"', dsn)


def _padstack_block(dsn: str, name: str) -> str | None:
    """Return the full (padstack "NAME" ...) block text, or None if absent.

    Uses paren-balanced extraction (the naive non-greedy regex stops at the
    first `))`, which is inside the first (shape ...) line).
    """
    marker = f'(padstack "{name}"'
    start = dsn.find(marker)
    if start == -1:
        return None
    depth = 0
    i = start
    while i < len(dsn):
        c = dsn[i]
        if c == "(":
            depth += 1
        elif c == ")":
            depth -= 1
            if depth == 0:
                return dsn[start:i + 1]
        i += 1
    return None


class TestTwoLayerThtOnly:
    """R-4: 2-layer source produces only THT via padstack."""

    def test_two_layer_tht_only(self) -> None:
        """smd_test_board (2-layer) DSN contains only Via[0-1] via padstack."""
        pcb = _SMD_BOARD.read_text(encoding="utf-8")
        dsn = generate_dsn(pcb, _SMD_BOARD)

        via_padstacks = [
            n for n in _padstack_names(dsn) if n.startswith("Via[")
        ]
        assert "Via[0-1]" in via_padstacks, (
            f"THT padstack Via[0-1] missing; got {via_padstacks}"
        )
        # No blind/buried padstacks on a 2-layer board.
        blind_buried = [
            n for n in via_padstacks
            if "In" in n and n != "Via[0-1]"
        ]
        assert blind_buried == [], (
            f"2-layer board must not emit blind/buried padstacks; got {blind_buried}"
        )

    def test_two_layer_tht_shapes_on_fcus_bcu(self) -> None:
        """Via[0-1] padstack has shapes on exactly F.Cu and B.Cu (no inner layers)."""
        pcb = _SMD_BOARD.read_text(encoding="utf-8")
        dsn = generate_dsn(pcb, _SMD_BOARD)

        block = _padstack_block(dsn, "Via[0-1]")
        assert block is not None, "Via[0-1] padstack missing"
        shapes = re.findall(r'\(shape\s+\(circle\s+(\S+)\s+\d+\)\)', block)
        assert "F.Cu" in shapes, f"F.Cu shape missing from Via[0-1]; got {shapes}"
        assert "B.Cu" in shapes, f"B.Cu shape missing from Via[0-1]; got {shapes}"
        # No inner-layer shapes on a 2-layer board.
        inner = [s for s in shapes if s.startswith("In")]
        assert inner == [], (
            f"2-layer Via[0-1] must not have inner-layer shapes; got {inner}"
        )


class TestFourLayerBlindBuried:
    """R-4: 4-layer source produces THT + blind + buried via padstacks.

    Per WARN-3: NO pytest.skip hatch. The 4-layer stackup is synthesized in-task.
    """

    def test_four_layer_blind_buried(self) -> None:
        """Synthetic 4-layer PCB DSN contains >=3 via padstacks: THT, blind, buried."""
        # Parse to confirm stackup parsing works (would raise on malformed input).
        board = NativeParser.parse_pcb_content(_4_LAYER_PCB)
        assert board.setup is not None and board.setup.stackup is not None, (
            "4-layer synthetic PCB must parse a stackup"
        )

        dsn = generate_dsn(_4_LAYER_PCB, Path("synthetic_4layer.kicad_pcb"))
        via_padstacks = [
            n for n in _padstack_names(dsn) if n.startswith("Via[")
        ]

        # THT via (always emitted).
        assert "Via[0-1]" in via_padstacks, (
            f"THT padstack Via[0-1] missing; got {via_padstacks}"
        )
        # Blind via: F.Cu <-> In1.Cu.
        assert "Via[0-In1]" in via_padstacks, (
            f"Blind padstack Via[0-In1] missing; got {via_padstacks}"
        )
        # Buried via: In1.Cu <-> In2.Cu.
        assert "Via[In1-In2]" in via_padstacks, (
            f"Buried padstack Via[In1-In2] missing; got {via_padstacks}"
        )

    def test_four_layer_tht_spans_all_copper_layers(self) -> None:
        """4-layer THT Via[0-1] has shapes on all 4 copper layers."""
        dsn = generate_dsn(_4_LAYER_PCB, Path("synthetic_4layer.kicad_pcb"))
        block = _padstack_block(dsn, "Via[0-1]")
        assert block is not None
        shapes = re.findall(r'\(shape\s+\(circle\s+(\S+)\s+\d+\)\)', block)
        for expected in ("F.Cu", "In1.Cu", "In2.Cu", "B.Cu"):
            assert expected in shapes, (
                f"4-layer THT padstack missing shape on {expected}; got {shapes}"
            )

    def test_four_layer_blind_only_two_layers(self) -> None:
        """Via[0-In1] (blind) has shapes on exactly F.Cu and In1.Cu."""
        dsn = generate_dsn(_4_LAYER_PCB, Path("synthetic_4layer.kicad_pcb"))
        block = _padstack_block(dsn, "Via[0-In1]")
        assert block is not None, "Via[0-In1] padstack missing"
        shapes = re.findall(r'\(shape\s+\(circle\s+(\S+)\s+\d+\)\)', block)
        assert sorted(shapes) == ["F.Cu", "In1.Cu"], (
            f"Blind Via[0-In1] must span only F.Cu+In1.Cu; got {shapes}"
        )

    def test_four_layer_buried_only_two_layers(self) -> None:
        """Via[In1-In2] (buried) has shapes on exactly In1.Cu and In2.Cu."""
        dsn = generate_dsn(_4_LAYER_PCB, Path("synthetic_4layer.kicad_pcb"))
        block = _padstack_block(dsn, "Via[In1-In2]")
        assert block is not None, "Via[In1-In2] padstack missing"
        shapes = re.findall(r'\(shape\s+\(circle\s+(\S+)\s+\d+\)\)', block)
        assert sorted(shapes) == ["In1.Cu", "In2.Cu"], (
            f"Buried Via[In1-In2] must span only In1.Cu+In2.Cu; got {shapes}"
        )


class TestPerClassViaPadstackCrossPlanWiring:
    """H-2 cross-plan wiring: (use_via "Via[NAME]") + (padstack "Via[NAME]" ...).

    Both emitted by Plan 99-01 Task 2b Step A2 (_emit_per_class_padstacks and
    _emit_net_classes). Plan 99-02 verifies the combined DSN contains both.
    When both plans land together (as here), the test passes without skip.
    """

    def test_per_class_via_padstack_emitted(self) -> None:
        """Net class with via_diameter=0.8 emits (padstack "Via[Power]" ...)."""
        dsn = generate_dsn(_POWER_CLASS_PCB, Path("power_class.kicad_pcb"))
        block = _padstack_block(dsn, "Via[Power]")
        assert block is not None, (
            "(padstack \"Via[Power]\" ...) missing from DSN — "
            "should be emitted by 99-01 Task 2b Step A2 (_emit_per_class_padstacks)"
        )
        # Via diameter 0.8mm = 800um.
        sizes = re.findall(r'\(shape\s+\(circle\s+\S+\s+(\d+)\)\)', block)
        assert "800" in sizes, (
            f"Via[Power] shapes should be 800um (0.8mm); got {sizes}"
        )

    def test_use_via_in_class_scope(self) -> None:
        """(use_via "Via[Power]") appears inside the (class "Power" ...) scope."""
        dsn = generate_dsn(_POWER_CLASS_PCB, Path("power_class.kicad_pcb"))
        # Extract the (class "Power" ...) block.
        class_pat = re.compile(
            r'\(class\s+"Power".*?\)\s*\)\s*\)', re.DOTALL
        )
        m = class_pat.search(dsn)
        assert m is not None, '(class "Power" ...) block missing from DSN'
        class_block = m.group(0)
        assert '(use_via "Via[Power]")' in class_block, (
            '(use_via "Via[Power]") missing from (class "Power" ...) scope'
        )


class TestMicroviaDeferralBeadExists:
    """H-1 fix: microvia padstack emission deferred to a tracked Bead.

    Per bureaucracy §7.7, no silent scope reduction. The deferral MUST be tracked.
    Since Beads MCP is unavailable in this executor context, we verify via a
    documented deferral in SUMMARY.md instead (see 99-02-SUMMARY.md).
    This test asserts the deferral is documented, not that a Bead exists.
    """

    def test_microvia_deferral_documented(self) -> None:
        """Microvia deferral is documented in 99-02-SUMMARY.md (H-1 fix)."""
        summary = Path(__file__).parent.parent / ".planning" / "phases" / (
            "99-freerouting-integration-hardening" / "99-02-SUMMARY.md"
        )
        if not summary.exists():
            pytest.skip("99-02-SUMMARY.md not yet written (written at plan completion)")
        text = summary.read_text(encoding="utf-8")
        assert "microvia" in text.lower(), (
            "Microvia deferral MUST be documented in 99-02-SUMMARY.md (H-1 fix, §7.7)"
        )
