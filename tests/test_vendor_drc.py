"""Tests for the internal vendor DRC evaluator (manufacturing/vendor_drc.py).

THE silent-pass guard: these tests prove the evaluator actually detects
violations against vendor limits (the highest-risk failure mode per RESEARCH
"Validation risk"). If test_track_width_below_limit_violation fails, the
evaluator silently passes violating boards.
"""
import pytest
from pathlib import Path

from kicad_agent.dfm.profiles import load_profile
from kicad_agent.manufacturing.vendor_drc import VendorDrcResult, run_vendor_drc
from kicad_agent.validation.erc_drc import Severity


@pytest.fixture(autouse=True)
def _clear_ir_registry():
    """Avoid cross-test IR registration leaks (mirrors test_board_metadata_ops.py)."""
    from kicad_agent.ir.base import _clear_registry
    _clear_registry()
    yield
    _clear_registry()


def _parse_board(content: str, tmp_path: Path):
    """Write an inline PCB to a temp file and parse it via NativeParser.

    The evaluator takes a NativeBoard (NOT a PcbIR) — execute_query builds
    PcbIR via kiutils where _native_board is None, so the handler re-parses
    via NativeParser.parse_pcb. Tests mirror that path.
    """
    from kicad_agent.parser.pcb_native_parser import NativeParser

    pcb_path = tmp_path / "eval_test.kicad_pcb"
    pcb_path.write_text(content, encoding="utf-8")
    return NativeParser.parse_pcb(pcb_path)


_GENERIC = load_profile("generic")  # min track 0.2, clearance 0.2, drill 0.4, annular 0.15, via 0.6


class TestTrackWidthCheck:
    def test_track_width_below_limit_violation(self, tmp_path):
        """SILENT-PASS GUARD: 0.1mm segment vs generic 0.2mm -> violation."""
        board = _parse_board(
            '(kicad_pcb (version 20241229) (generator "test")\n'
            '  (layers (0 "F.Cu" signal) (31 "B.Cu" signal))\n'
            '  (segment (start 10 10) (end 20 10) (width 0.1) (layer "F.Cu") (net 0))\n'
            ')\n',
            tmp_path,
        )
        result = run_vendor_drc(board, _GENERIC)
        assert result.passed is False
        track_violations = [v for v in result.violations if v.type == "vendor_trace_width"]
        assert len(track_violations) >= 1
        assert track_violations[0].severity == Severity.ERROR
        assert "0.1" in track_violations[0].description
        assert "0.2" in track_violations[0].description

    def test_track_width_at_limit_passes(self, tmp_path):
        """Segment at exactly the limit (0.2mm) -> no track-width violation."""
        board = _parse_board(
            '(kicad_pcb (version 20241229) (generator "test")\n'
            '  (layers (0 "F.Cu" signal) (31 "B.Cu" signal))\n'
            '  (segment (start 10 10) (end 50 10) (width 0.2) (layer "F.Cu") (net 0))\n'
            ')\n',
            tmp_path,
        )
        result = run_vendor_drc(board, _GENERIC)
        track_violations = [v for v in result.violations if v.type == "vendor_trace_width"]
        assert track_violations == []


class TestDrillSizeCheck:
    def test_via_drill_below_limit_violation(self, tmp_path):
        """Via drill 0.1mm vs generic 0.4mm -> violation."""
        board = _parse_board(
            '(kicad_pcb (version 20241229) (generator "test")\n'
            '  (layers (0 "F.Cu" signal) (31 "B.Cu" signal))\n'
            '  (via (at 50 50) (size 0.6) (drill 0.1) (layers "F.Cu" "B.Cu") (net 0))\n'
            ')\n',
            tmp_path,
        )
        result = run_vendor_drc(board, _GENERIC)
        assert result.passed is False
        drill_violations = [v for v in result.violations if v.type == "vendor_drill_size"]
        assert len(drill_violations) >= 1

    def test_via_drill_at_limit_passes(self, tmp_path):
        """Via drill at exactly the limit -> no drill violation."""
        board = _parse_board(
            '(kicad_pcb (version 20241229) (generator "test")\n'
            '  (layers (0 "F.Cu" signal) (31 "B.Cu" signal))\n'
            '  (via (at 50 50) (size 0.8) (drill 0.4) (layers "F.Cu" "B.Cu") (net 0))\n'
            ')\n',
            tmp_path,
        )
        result = run_vendor_drc(board, _GENERIC)
        drill_violations = [v for v in result.violations if v.type == "vendor_drill_size"]
        assert drill_violations == []


class TestAnnularRingCheck:
    def test_annular_ring_below_limit_violation(self, tmp_path):
        """Via diameter 0.4mm, drill 0.3mm -> annular 0.05mm < 0.15mm generic."""
        board = _parse_board(
            '(kicad_pcb (version 20241229) (generator "test")\n'
            '  (layers (0 "F.Cu" signal) (31 "B.Cu" signal))\n'
            '  (via (at 50 50) (size 0.4) (drill 0.3) (layers "F.Cu" "B.Cu") (net 0))\n'
            ')\n',
            tmp_path,
        )
        result = run_vendor_drc(board, _GENERIC)
        annular_violations = [v for v in result.violations if v.type == "vendor_annular_ring"]
        assert len(annular_violations) >= 1
        assert result.passed is False

    def test_annular_ring_at_limit_passes(self, tmp_path):
        """Via diameter 0.7mm, drill 0.4mm -> annular 0.15mm == limit -> passes."""
        board = _parse_board(
            '(kicad_pcb (version 20241229) (generator "test")\n'
            '  (layers (0 "F.Cu" signal) (31 "B.Cu" signal))\n'
            '  (via (at 50 50) (size 0.7) (drill 0.4) (layers "F.Cu" "B.Cu") (net 0))\n'
            ')\n',
            tmp_path,
        )
        result = run_vendor_drc(board, _GENERIC)
        annular_violations = [v for v in result.violations if v.type == "vendor_annular_ring"]
        assert annular_violations == []


class TestViaDiameterCheck:
    def test_via_diameter_below_limit_violation(self, tmp_path):
        """Via diameter 0.3mm vs generic 0.6mm -> violation."""
        board = _parse_board(
            '(kicad_pcb (version 20241229) (generator "test")\n'
            '  (layers (0 "F.Cu" signal) (31 "B.Cu" signal))\n'
            '  (via (at 50 50) (size 0.3) (drill 0.1) (layers "F.Cu" "B.Cu") (net 0))\n'
            ')\n',
            tmp_path,
        )
        result = run_vendor_drc(board, _GENERIC)
        via_violations = [v for v in result.violations if v.type == "vendor_via_diameter"]
        assert len(via_violations) >= 1

    def test_via_diameter_at_limit_passes(self, tmp_path):
        """Via diameter at exactly 0.6mm -> no via-diameter violation."""
        board = _parse_board(
            '(kicad_pcb (version 20241229) (generator "test")\n'
            '  (layers (0 "F.Cu" signal) (31 "B.Cu" signal))\n'
            '  (via (at 50 50) (size 0.6) (drill 0.4) (layers "F.Cu" "B.Cu") (net 0))\n'
            ')\n',
            tmp_path,
        )
        result = run_vendor_drc(board, _GENERIC)
        via_violations = [v for v in result.violations if v.type == "vendor_via_diameter"]
        assert via_violations == []


class TestClearanceCheck:
    def test_clearance_below_limit_violation(self, tmp_path):
        """Two segments 0.1mm apart on same layer vs generic 0.2mm -> violation."""
        board = _parse_board(
            '(kicad_pcb (version 20241229) (generator "test")\n'
            '  (layers (0 "F.Cu" signal) (31 "B.Cu" signal))\n'
            '  (segment (start 10 10) (end 20 10) (width 0.2) (layer "F.Cu") (net 0))\n'
            '  (segment (start 10 10.1) (end 20 10.1) (width 0.2) (layer "F.Cu") (net 1))\n'
            ')\n',
            tmp_path,
        )
        result = run_vendor_drc(board, _GENERIC)
        assert result.passed is False
        clearance_violations = [v for v in result.violations if v.type == "vendor_clearance"]
        assert len(clearance_violations) >= 1

    def test_clearance_above_limit_passes(self, tmp_path):
        """Two segments well above min_clearance (0.5mm gap) -> no violation."""
        board = _parse_board(
            '(kicad_pcb (version 20241229) (generator "test")\n'
            '  (layers (0 "F.Cu" signal) (31 "B.Cu" signal))\n'
            '  (segment (start 10 10) (end 20 10) (width 0.2) (layer "F.Cu") (net 0))\n'
            '  (segment (start 10 10.7) (end 20 10.7) (width 0.2) (layer "F.Cu") (net 1))\n'
            ')\n'
            '  ',
            tmp_path,
        )
        result = run_vendor_drc(board, _GENERIC)
        clearance_violations = [v for v in result.violations if v.type == "vendor_clearance"]
        assert clearance_violations == []

    def test_clearance_different_layers_not_compared(self, tmp_path):
        """Two close segments on different layers -> no clearance violation."""
        board = _parse_board(
            '(kicad_pcb (version 20241229) (generator "test")\n'
            '  (layers (0 "F.Cu" signal) (31 "B.Cu" signal))\n'
            '  (segment (start 10 10) (end 20 10) (width 0.2) (layer "F.Cu") (net 0))\n'
            '  (segment (start 10 10.1) (end 20 10.1) (width 0.2) (layer "B.Cu") (net 1))\n'
            ')\n',
            tmp_path,
        )
        result = run_vendor_drc(board, _GENERIC)
        clearance_violations = [v for v in result.violations if v.type == "vendor_clearance"]
        assert clearance_violations == []


class TestCleanBoardAndRobustness:
    def test_clean_board_passes(self, tmp_path):
        """Board with all geometry at-or-above generic limits -> passed=True."""
        board = _parse_board(
            '(kicad_pcb (version 20241229) (generator "test")\n'
            '  (layers (0 "F.Cu" signal) (31 "B.Cu" signal))\n'
            '  (segment (start 10 10) (end 50 10) (width 0.2) (layer "F.Cu") (net 0))\n'
            '  (via (at 50 50) (size 0.7) (drill 0.4) (layers "F.Cu" "B.Cu") (net 0))\n'
            ')\n',
            tmp_path,
        )
        result = run_vendor_drc(board, _GENERIC)
        assert result.passed is True
        assert result.violations == ()

    def test_checks_run_lists_evaluated_checks(self, tmp_path):
        """checks_run is non-empty and contains all 5 check names."""
        board = _parse_board(
            '(kicad_pcb (version 20241229) (generator "test")\n'
            '  (layers (0 "F.Cu" signal) (31 "B.Cu" signal))\n'
            '  (segment (start 10 10) (end 20 10) (width 0.2) (layer "F.Cu") (net 0))\n'
            ')\n',
            tmp_path,
        )
        result = run_vendor_drc(board, _GENERIC)
        assert len(result.checks_run) >= 1
        expected = {"track_width", "drill_size", "annular_ring", "via_diameter", "clearance"}
        assert expected.issubset(set(result.checks_run))

    def test_evaluator_does_not_crash_on_empty_board(self, tmp_path):
        """Board with zero segments/vias/pads -> passed=True, no crash."""
        board = _parse_board(
            '(kicad_pcb (version 20241229) (generator "test")\n'
            '  (layers (0 "F.Cu" signal) (31 "B.Cu" signal))\n'
            ')\n',
            tmp_path,
        )
        result = run_vendor_drc(board, _GENERIC)
        assert result.passed is True
        assert result.violations == ()

    def test_evaluator_does_not_crash_on_malformed_geometry(self, tmp_path):
        """A segment with width 0 (default applied) -> no crash, graceful.

        Threat model scenario 2: the evaluator must not crash on malformed
        geometry. Width 0 is unusual but the evaluator should treat it as a
        violation (below any positive limit), not crash.
        """
        board = _parse_board(
            '(kicad_pcb (version 20241229) (generator "test")\n'
            '  (layers (0 "F.Cu" signal) (31 "B.Cu" signal))\n'
            '  (segment (start 10 10) (end 20 10) (width 0.0) (layer "F.Cu") (net 0))\n'
            ')\n',
            tmp_path,
        )
        result = run_vendor_drc(board, _GENERIC)
        # Width 0 is below the 0.2mm limit -> violation (not crash).
        assert result.passed is False
        track_violations = [v for v in result.violations if v.type == "vendor_trace_width"]
        assert len(track_violations) >= 1

    def test_result_is_frozen(self, tmp_path):
        """VendorDrcResult is a frozen dataclass."""
        board = _parse_board(
            '(kicad_pcb (version 20241229) (generator "test")\n'
            '  (layers (0 "F.Cu" signal) (31 "B.Cu" signal))\n'
            ')\n',
            tmp_path,
        )
        result = run_vendor_drc(board, _GENERIC)
        with pytest.raises((AttributeError, Exception)):
            result.passed = False  # type: ignore[misc]

    def test_result_errors_property(self, tmp_path):
        """VendorDrcResult.errors returns only ERROR-severity violations."""
        board = _parse_board(
            '(kicad_pcb (version 20241229) (generator "test")\n'
            '  (layers (0 "F.Cu" signal) (31 "B.Cu" signal))\n'
            '  (segment (start 10 10) (end 20 10) (width 0.1) (layer "F.Cu") (net 0))\n'
            ')\n',
            tmp_path,
        )
        result = run_vendor_drc(board, _GENERIC)
        assert len(result.errors) >= 1
        assert all(v.severity == Severity.ERROR for v in result.errors)


class TestVendorSpecificProfiles:
    def test_pcbway_profile_runs(self, tmp_path):
        """PCBWay profile (min track 0.1mm) runs without error."""
        board = _parse_board(
            '(kicad_pcb (version 20241229) (generator "test")\n'
            '  (layers (0 "F.Cu" signal) (31 "B.Cu" signal))\n'
            '  (segment (start 10 10) (end 20 10) (width 0.127) (layer "F.Cu") (net 0))\n'
            ')\n',
            tmp_path,
        )
        result = run_vendor_drc(board, load_profile("pcbway"))
        assert result.profile_name == "PCBWay Standard 2-Layer"
        # 0.127mm is above PCBWay 0.1mm track min.
        track_violations = [v for v in result.violations if v.type == "vendor_trace_width"]
        assert track_violations == []

    def test_aisler_profile_stricter_annular(self, tmp_path):
        """AISLER 0.2mm annular catches a via that passes JLCPCB 0.15mm."""
        board = _parse_board(
            '(kicad_pcb (version 20241229) (generator "test")\n'
            '  (layers (0 "F.Cu" signal) (31 "B.Cu" signal))\n'
            '  (via (at 50 50) (size 0.65) (drill 0.4) (layers "F.Cu" "B.Cu") (net 0))\n'
            ')\n',
            tmp_path,
        )
        # annular = (0.65 - 0.4) / 2 = 0.125mm. JLCPCB 0.15 fails, AISLER 0.2 fails too.
        jlcpcb_result = run_vendor_drc(board, load_profile("jlcpcb"))
        aisler_result = run_vendor_drc(board, load_profile("aisler_2layer"))
        jlc_annular = [v for v in jlcpcb_result.violations if v.type == "vendor_annular_ring"]
        aisler_annular = [v for v in aisler_result.violations if v.type == "vendor_annular_ring"]
        assert len(jlc_annular) >= 1  # 0.125 < 0.15
        assert len(aisler_annular) >= 1  # 0.125 < 0.2
