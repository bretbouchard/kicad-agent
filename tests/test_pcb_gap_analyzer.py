"""Tests for PCB GapAnalyzer — deterministic gap analysis of partially-routed PCBs.

Tests the GapAnalyzer in volta.analysis.gap_analyzer (Phase 81),
which reads .kicad_pcb files and produces GapReport with unrouted nets,
incomplete nets, DRC violations, and net naming issues.

Uses real PCB fixtures for integration tests and mock data for unit tests.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path

import pytest

from volta.analysis.gap_analyzer import (
    BoardInfo,
    GapAnalyzer,
    GapReport,
    IncompleteNet,
    NetNamingIssue,
    RoutingStats,
    UnroutedNet,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"

# Paths to real PCB fixtures.
_ARDUINO_PCB = FIXTURES_DIR / "Arduino_Mega" / "Arduino_Mega.kicad_pcb"
_RPI_PCB = FIXTURES_DIR / "RaspberryPi-uHAT" / "RaspberryPi-uHAT.kicad_pcb"
_SMD_PCB = FIXTURES_DIR / "smd_test_board.kicad_pcb"

AVAILABLE_FIXTURES = [p for p in [_ARDUINO_PCB, _RPI_PCB, _SMD_PCB] if p.exists()]


# ---------------------------------------------------------------------------
# Schema tests (no PCB needed)
# ---------------------------------------------------------------------------


class TestBoardInfo:
    def test_to_json_with_bounds(self):
        info = BoardInfo("board.kicad_pcb", 10, 20, 4, (0.0, 0.0, 100.0, 80.0))
        j = info.to_json()
        assert j["file_path"] == "board.kicad_pcb"
        assert j["component_count"] == 10
        assert j["bounds"] == [0.0, 0.0, 100.0, 80.0]

    def test_to_json_without_bounds(self):
        info = BoardInfo("board.kicad_pcb", 5, 10, 2, None)
        j = info.to_json()
        assert j["bounds"] is None


class TestRoutingStats:
    def test_to_json(self):
        stats = RoutingStats(
            total_nets=100, routed_nets=70, unrouted_nets=20,
            incomplete_nets=10, route_percentage=70.0,
        )
        j = stats.to_json()
        assert j["route_percentage"] == 70.0
        assert j["total_nets"] == 100


class TestUnroutedNet:
    def test_to_json(self):
        un = UnroutedNet(
            net_name="N_42", pad_count=2,
            pin_positions=((10.0, 20.0), (30.0, 40.0)),
            nearest_obstacle_distance=3.5,
        )
        j = un.to_json()
        assert j["net_name"] == "N_42"
        assert len(j["pin_positions"]) == 2
        assert j["nearest_obstacle_distance"] == 3.5

    def test_to_json_no_obstacles(self):
        un = UnroutedNet("N_1", 1, ((5.0, 5.0),), -1.0)
        j = un.to_json()
        assert j["nearest_obstacle_distance"] == -1.0


class TestIncompleteNet:
    def test_to_json(self):
        inc = IncompleteNet(
            net_name="SDA", routed_pins=((10.0, 20.0),),
            unrouted_pins=((50.0, 60.0),), gap_distance=56.5685,
        )
        j = inc.to_json()
        assert j["net_name"] == "SDA"
        assert len(j["routed_pins"]) == 1
        assert len(j["unrouted_pins"]) == 1


class TestNetNamingIssue:
    def test_to_json(self):
        ni = NetNamingIssue(
            current_name="N_15", suggested_name="R1_R2_NET",
            connected_components=("R1", "R2"), reason="Connected to R1, R2",
        )
        j = ni.to_json()
        assert j["current_name"] == "N_15"
        assert j["suggested_name"] == "R1_R2_NET"
        assert j["connected_components"] == ["R1", "R2"]


class TestGapReport:
    def test_to_json(self):
        report = GapReport(
            board_info=BoardInfo("test.kicad_pcb", 5, 3, 2, None),
            routing_stats=RoutingStats(3, 1, 1, 1, 33.3333),
            unrouted_nets=(UnroutedNet("N_1", 2, ((1.0, 2.0),), -1.0),),
            incomplete_nets=(
                IncompleteNet("N_2", ((1.0, 1.0),), ((5.0, 5.0),), 5.6569),
            ),
            drc_violations=(),
            net_naming_issues=(
                NetNamingIssue("N_1", "GND", ("U1",), "Ground net"),
            ),
        )
        j = report.to_json()
        assert j["board_info"]["component_count"] == 5
        assert len(j["unrouted_nets"]) == 1
        assert len(j["incomplete_nets"]) == 1
        assert len(j["net_naming_issues"]) == 1

    def test_to_markdown_basic(self):
        report = GapReport(
            board_info=BoardInfo("test.kicad_pcb", 5, 3, 2, (0.0, 0.0, 100.0, 80.0)),
            routing_stats=RoutingStats(3, 2, 1, 0, 66.6667),
            unrouted_nets=(
                UnroutedNet("N_1", 2, ((10.0, 20.0), (30.0, 40.0)), 5.0),
            ),
            incomplete_nets=(),
            drc_violations=(),
            net_naming_issues=(),
        )
        md = report.to_markdown()
        assert "# Gap Analysis Report" in md
        assert "N_1" in md
        assert "66.7%" in md
        assert "Unrouted Nets (1)" in md

    def test_to_markdown_empty(self):
        report = GapReport(
            board_info=BoardInfo("empty.kicad_pcb", 0, 0, 2, None),
            routing_stats=RoutingStats(0, 0, 0, 0, 0.0),
            unrouted_nets=(),
            incomplete_nets=(),
            drc_violations=(),
            net_naming_issues=(),
        )
        md = report.to_markdown()
        assert "# Gap Analysis Report" in md
        assert "0.0%" in md

    def test_frozen(self):
        """GapReport is frozen — mutation raises FrozenInstanceError."""
        report = GapReport(
            board_info=BoardInfo("t", 0, 0, 0, None),
            routing_stats=RoutingStats(0, 0, 0, 0, 0.0),
            unrouted_nets=(), incomplete_nets=(),
            drc_violations=(), net_naming_issues=(),
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            report.board_info = BoardInfo("x", 1, 1, 1, None)


# ---------------------------------------------------------------------------
# Net classification unit tests
# ---------------------------------------------------------------------------


class TestNetClassification:
    """Unit tests for _classify_nets using mock NativeBoard."""

    @staticmethod
    def _make_board(segments=None, vias=None, nets=None):
        from volta.parser.pcb_native_types import (
            NativeBoard, NativeNet, NativeSegment, NativeVia,
            _NativePosition, NativeGeneral,
        )
        return NativeBoard(
            nets=nets or [],
            footprints=[],
            segments=segments or [],
            vias=vias or [],
            general=NativeGeneral(),
        )

    def test_unrouted_net_no_segments(self):
        from volta.parser.pcb_native_types import NativeNet

        board = self._make_board(nets=[NativeNet(number=1, name="N_UNROUTED")])
        analyzer = GapAnalyzer(run_drc=False)
        result = analyzer._classify_nets(board, {"N_UNROUTED": [(10.0, 20.0), (30.0, 40.0)]})
        assert result["N_UNROUTED"] == "unrouted"

    def test_routed_net_all_pins_connected(self):
        from volta.parser.pcb_native_types import (
            NativeNet, NativeSegment, _NativePosition,
        )
        seg = NativeSegment(
            start=_NativePosition(10.0, 20.0), end=_NativePosition(30.0, 40.0),
            width=0.25, layer="F.Cu", net_number=1, net_name="NET_A",
        )
        board = self._make_board(segments=[seg], nets=[NativeNet(number=1, name="NET_A")])
        analyzer = GapAnalyzer(run_drc=False)
        result = analyzer._classify_nets(board, {"NET_A": [(10.0, 20.0), (30.0, 40.0)]})
        assert result["NET_A"] == "routed"

    def test_incomplete_net_partial_routing(self):
        from volta.parser.pcb_native_types import (
            NativeNet, NativeSegment, _NativePosition,
        )
        seg = NativeSegment(
            start=_NativePosition(10.0, 20.0), end=_NativePosition(30.0, 40.0),
            width=0.25, layer="F.Cu", net_number=1, net_name="NET_B",
        )
        board = self._make_board(segments=[seg], nets=[NativeNet(number=1, name="NET_B")])
        analyzer = GapAnalyzer(run_drc=False)
        result = analyzer._classify_nets(
            board, {"NET_B": [(10.0, 20.0), (30.0, 40.0), (100.0, 100.0)]},
        )
        assert result["NET_B"] == "incomplete"

    def test_skip_net_zero(self):
        board = self._make_board()
        analyzer = GapAnalyzer(run_drc=False)
        result = analyzer._classify_nets(board, {"": [(0.0, 0.0)]})
        assert "" not in result

    def test_multi_segment_routed_net(self):
        from volta.parser.pcb_native_types import (
            NativeNet, NativeSegment, _NativePosition,
        )
        segs = [
            NativeSegment(
                start=_NativePosition(0.0, 0.0), end=_NativePosition(10.0, 0.0),
                width=0.25, layer="F.Cu", net_number=1, net_name="CHAIN",
            ),
            NativeSegment(
                start=_NativePosition(10.0, 0.0), end=_NativePosition(20.0, 0.0),
                width=0.25, layer="F.Cu", net_number=1, net_name="CHAIN",
            ),
        ]
        board = self._make_board(segments=segs, nets=[NativeNet(number=1, name="CHAIN")])
        analyzer = GapAnalyzer(run_drc=False)
        result = analyzer._classify_nets(board, {"CHAIN": [(0.0, 0.0), (20.0, 0.0)]})
        assert result["CHAIN"] == "routed"


# ---------------------------------------------------------------------------
# Naming tests
# ---------------------------------------------------------------------------


class TestNamingDetection:
    """Unit tests for _detect_naming_issues."""

    @staticmethod
    def _make_board_with_net(net_name, net_number, pads_by_ref):
        """Build mock NativeBoard.

        pads_by_ref: {ref: [(pad_number, net_name, pinfunction, pintype)]}
        """
        from volta.parser.pcb_native_types import (
            NativeBoard, NativeFootprint, NativeNet, NativePad, NativeGeneral,
        )
        footprints = []
        for ref, pad_list in pads_by_ref.items():
            pads = [
                NativePad(
                    number=pn, net_name=pn_net,
                    net_number=net_number if pn_net == net_name else 0,
                    position=(0.0, 0.0), pinfunction=pf, pintype=pt,
                )
                for pn, pn_net, pf, pt in pad_list
            ]
            footprints.append(NativeFootprint(
                lib_id="test:FP",
                _properties_tuple=(("Reference", ref), ("Value", "X")),
                pads=tuple(pads),
            ))
        return NativeBoard(
            nets=(NativeNet(number=net_number, name=net_name),),
            footprints=tuple(footprints), general=NativeGeneral(),
        )

    def test_detects_auto_named_net(self):
        board = self._make_board_with_net("N_42", 42, {
            "R1": [("1", "N_42", "", "passive")],
            "R2": [("2", "N_42", "", "passive")],
        })
        analyzer = GapAnalyzer(run_drc=False)
        issues = analyzer._detect_naming_issues(board)
        assert len(issues) == 1
        assert issues[0].current_name == "N_42"
        assert "R1" in issues[0].connected_components

    def test_skips_functional_names(self):
        board = self._make_board_with_net("SDA", 5, {
            "U1": [("1", "SDA", "SDA", "input")],
        })
        analyzer = GapAnalyzer(run_drc=False)
        issues = analyzer._detect_naming_issues(board)
        assert len(issues) == 0

    def test_suggests_power_name_from_pinfunction(self):
        board = self._make_board_with_net("N_10", 10, {
            "U1": [("8", "N_10", "VCC", "power_in")],
            "C1": [("1", "N_10", "", "passive")],
        })
        analyzer = GapAnalyzer(run_drc=False)
        issues = analyzer._detect_naming_issues(board)
        assert len(issues) == 1
        assert "VCC" in issues[0].suggested_name

    def test_suggests_gnd_name(self):
        board = self._make_board_with_net("N_3", 3, {
            "U1": [("4", "N_3", "GND", "power_in")],
        })
        analyzer = GapAnalyzer(run_drc=False)
        issues = analyzer._detect_naming_issues(board)
        assert len(issues) == 1
        assert "GND" in issues[0].suggested_name

    def test_suggests_ref_pattern(self):
        board = self._make_board_with_net("N_99", 99, {
            "R1": [("1", "N_99", "", "passive")],
            "R2": [("2", "N_99", "", "passive")],
        })
        analyzer = GapAnalyzer(run_drc=False)
        issues = analyzer._detect_naming_issues(board)
        assert len(issues) == 1
        assert "R1" in issues[0].suggested_name
        assert "R2" in issues[0].suggested_name


# ---------------------------------------------------------------------------
# Helper method tests
# ---------------------------------------------------------------------------


class TestHelpers:
    def test_point_near_any_true(self):
        assert GapAnalyzer._point_near_any(10.0, 20.0, [(10.01, 20.0)], 1.0) is True

    def test_point_near_any_false(self):
        assert GapAnalyzer._point_near_any(10.0, 20.0, [(100.0, 200.0)], 0.5) is False

    def test_point_near_any_empty(self):
        assert GapAnalyzer._point_near_any(10.0, 20.0, [], 0.5) is False


# ---------------------------------------------------------------------------
# Integration tests (require real PCB fixtures)
# ---------------------------------------------------------------------------


@pytest.fixture
def analyzer():
    return GapAnalyzer(run_drc=False)


@pytest.fixture
def analyzer_with_drc():
    return GapAnalyzer(run_drc=True)


class TestFileNotFound:
    def test_raises_on_missing_file(self, analyzer):
        with pytest.raises(FileNotFoundError, match="not found"):
            analyzer.analyze("/nonexistent/board.kicad_pcb")


@pytest.mark.skipif(not _ARDUINO_PCB.exists(), reason="Arduino Mega fixture not available")
class TestArduinoMega:
    def test_produces_gap_report(self, analyzer):
        report = analyzer.analyze(_ARDUINO_PCB)
        assert isinstance(report, GapReport)

    def test_board_info(self, analyzer):
        report = analyzer.analyze(_ARDUINO_PCB)
        assert report.board_info.component_count > 0
        assert report.board_info.net_count > 0
        assert report.board_info.file_path == str(_ARDUINO_PCB)

    def test_routing_stats(self, analyzer):
        report = analyzer.analyze(_ARDUINO_PCB)
        rs = report.routing_stats
        assert rs.total_nets == rs.routed_nets + rs.unrouted_nets + rs.incomplete_nets
        assert 0.0 <= rs.route_percentage <= 100.0

    def test_to_json_roundtrip(self, analyzer):
        report = analyzer.analyze(_ARDUINO_PCB)
        j = report.to_json()
        assert "board_info" in j
        assert "routing_stats" in j
        assert "unrouted_nets" in j
        assert "incomplete_nets" in j

    def test_to_markdown(self, analyzer):
        report = analyzer.analyze(_ARDUINO_PCB)
        md = report.to_markdown()
        assert "# Gap Analysis Report" in md
        assert "Routing Summary" in md

    def test_naming_issues_detects_auto_nets(self, analyzer):
        report = analyzer.analyze(_ARDUINO_PCB)
        if report.net_naming_issues:
            for ni in report.net_naming_issues:
                assert ni.current_name.startswith("N_")


@pytest.mark.skipif(not _SMD_PCB.exists(), reason="SMD test board fixture not available")
class TestSmdBoard:
    def test_produces_gap_report(self, analyzer):
        report = analyzer.analyze(_SMD_PCB)
        assert isinstance(report, GapReport)

    def test_board_info(self, analyzer):
        report = analyzer.analyze(_SMD_PCB)
        assert report.board_info.component_count > 0

    def test_routing_stats(self, analyzer):
        report = analyzer.analyze(_SMD_PCB)
        rs = report.routing_stats
        assert rs.total_nets == rs.routed_nets + rs.unrouted_nets + rs.incomplete_nets


@pytest.mark.skipif(not _RPI_PCB.exists(), reason="RPi uHAT fixture not available")
class TestRpiHat:
    def test_produces_gap_report(self, analyzer):
        report = analyzer.analyze(_RPI_PCB)
        assert isinstance(report, GapReport)

    def test_routing_stats(self, analyzer):
        report = analyzer.analyze(_RPI_PCB)
        rs = report.routing_stats
        assert rs.total_nets == rs.routed_nets + rs.unrouted_nets + rs.incomplete_nets

    def test_drc_analysis(self, analyzer_with_drc):
        report = analyzer_with_drc.analyze(_RPI_PCB)
        assert isinstance(report, GapReport)
        assert isinstance(report.drc_violations, tuple)


@pytest.mark.skipif(len(AVAILABLE_FIXTURES) == 0, reason="No PCB fixtures available")
class TestCrossFixture:
    """Tests that run across all available fixtures."""

    @pytest.fixture(params=AVAILABLE_FIXTURES)
    def pcb_path(self, request):
        return request.param

    def test_report_has_all_sections(self, analyzer, pcb_path):
        report = analyzer.analyze(pcb_path)
        assert report.board_info is not None
        assert report.routing_stats is not None
        assert isinstance(report.unrouted_nets, tuple)
        assert isinstance(report.incomplete_nets, tuple)
        assert isinstance(report.drc_violations, tuple)
        assert isinstance(report.net_naming_issues, tuple)

    def test_all_unrouted_nets_valid(self, analyzer, pcb_path):
        report = analyzer.analyze(pcb_path)
        for un in report.unrouted_nets:
            assert un.net_name
            assert un.pad_count >= 0

    def test_all_incomplete_nets_valid(self, analyzer, pcb_path):
        report = analyzer.analyze(pcb_path)
        for inc in report.incomplete_nets:
            assert inc.net_name
            assert inc.gap_distance >= 0 or inc.gap_distance == -1.0
            assert len(inc.unrouted_pins) > 0
