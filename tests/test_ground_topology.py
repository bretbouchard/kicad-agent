"""Tests for ground_topology -- ground net analysis for mixed-signal designs.

Covers: ground net discovery, domain classification, recommendation logic,
ERC connection detection, schema validation, handler dispatch, and
integration with mocked netlist/ERC data.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from kicad_agent.ops.ground_topology import (
    _classify_ground_domain,
    _find_ground_connections,
    _find_ground_nets,
    _recommend,
    analyze_ground_topology,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_erc_short(net_a: str, net_b: str, sheet: str = "/", positions: list | None = None) -> dict:
    """Create a mock ERC short dict."""
    return {
        "net_a": net_a,
        "net_b": net_b,
        "sheet": sheet,
        "positions": positions or [(100.0, 200.0)],
        "description": f"Both {net_a} and {net_b} are attached to the same items",
    }


def _make_net_pins() -> dict[str, set[tuple[str, str]]]:
    """Create a mock netlist with ground and signal nets."""
    return {
        "GND": {("R1", "1"), ("C1", "2"), ("J1", "3")},
        "GNDA": {("U1", "4"), ("R2", "1"), ("C2", "2")},
        "AGND": {("U2", "1"), ("R3", "1")},
        "+3V3": {("U1", "8"), ("C3", "1")},
        "SDA": {("U1", "1"), ("R4", "2")},
    }


# ---------------------------------------------------------------------------
# _find_ground_nets
# ---------------------------------------------------------------------------

class TestFindGroundNets:
    """Tests for _find_ground_nets."""

    @patch("kicad_agent.ops.net_short_detector._is_ground_net")
    def test_auto_detect_filters_to_ground(self, mock_is_ground: MagicMock) -> None:
        mock_is_ground.side_effect = lambda n: n in {"GND", "GNDA", "AGND"}
        net_pins = _make_net_pins()
        result = _find_ground_nets(net_pins)
        assert set(result.keys()) == {"GND", "GNDA", "AGND"}
        assert result["GND"] == _make_net_pins()["GND"]

    @patch("kicad_agent.ops.net_short_detector._is_ground_net")
    def test_explicit_list_ignores_auto_detect(self, mock_is_ground: MagicMock) -> None:
        net_pins = _make_net_pins()
        result = _find_ground_nets(net_pins, explicit_list=["GND", "SDA"])
        assert set(result.keys()) == {"GND", "SDA"}
        mock_is_ground.assert_not_called()

    @patch("kicad_agent.ops.net_short_detector._is_ground_net")
    def test_explicit_list_missing_net_returns_empty(self, mock_is_ground: MagicMock) -> None:
        net_pins = _make_net_pins()
        result = _find_ground_nets(net_pins, explicit_list=["NONEXISTENT"])
        assert result == {}

    @patch("kicad_agent.ops.net_short_detector._is_ground_net")
    def test_no_grounds_returns_empty(self, mock_is_ground: MagicMock) -> None:
        mock_is_ground.return_value = False
        net_pins = {"SDA": {("R1", "1")}, "SCL": {("R2", "1")}}
        result = _find_ground_nets(net_pins)
        assert result == {}

    def test_empty_netlist_returns_empty(self) -> None:
        result = _find_ground_nets({})
        assert result == {}


# ---------------------------------------------------------------------------
# _classify_ground_domain
# ---------------------------------------------------------------------------

class TestClassifyGroundDomain:
    """Tests for _classify_ground_domain."""

    def test_passive_only_resistors(self) -> None:
        pins = {("R1", "1"), ("R2", "2"), ("C1", "1")}
        assert _classify_ground_domain("GND", pins) == "passive_only"

    def test_passive_only_connectors(self) -> None:
        pins = {("J1", "3"), ("P1", "1"), ("R1", "1")}
        assert _classify_ground_domain("GND", pins) == "passive_only"

    def test_digital_mcu(self) -> None:
        pins = {("U1STM32", "4"), ("C1", "1")}
        assert _classify_ground_domain("DGND", pins) == "digital"

    def test_analog_opamp(self) -> None:
        pins = {("U2NE5532", "3"), ("R1", "1")}
        assert _classify_ground_domain("AGND", pins) == "analog"

    def test_analog_codec(self) -> None:
        pins = {("U3CODEC", "5"), ("R1", "1")}
        assert _classify_ground_domain("GNDA", pins) == "analog"

    def test_unknown_ic_defaults_analog(self) -> None:
        pins = {("U99", "1")}
        assert _classify_ground_domain("GND", pins) == "analog"

    def test_empty_pins_returns_passive_only(self) -> None:
        assert _classify_ground_domain("GND", set()) == "passive_only"

    def test_mixed_digital_and_analog_returns_analog(self) -> None:
        pins = {("U1STM32", "4"), ("U2NE5532", "3")}
        assert _classify_ground_domain("GND", pins) == "analog"

    def test_fpga_is_digital(self) -> None:
        pins = {("U1XC7A", "1")}
        assert _classify_ground_domain("GND", pins) == "digital"

    def test_cpld_is_digital(self) -> None:
        pins = {("U1ispMACH", "1")}
        assert _classify_ground_domain("GND", pins) == "digital"

    def test_adc_is_analog(self) -> None:
        pins = {("U1ADC123", "1")}
        assert _classify_ground_domain("AGND", pins) == "analog"

    def test_vref_is_analog(self) -> None:
        pins = {("U1VREF1", "1")}
        assert _classify_ground_domain("AGND", pins) == "analog"

    def test_7400_is_digital(self) -> None:
        pins = {("U17400", "7")}
        assert _classify_ground_domain("GND", pins) == "digital"


# ---------------------------------------------------------------------------
# _recommend
# ---------------------------------------------------------------------------

class TestRecommend:
    """Tests for _recommend logic."""

    def test_both_passive_merge(self) -> None:
        rec = _recommend("passive_only", "passive_only", "GND", "AGND")
        assert rec["recommendation"] == "merge"
        assert "passive" in rec["reason"].lower()

    def test_same_domain_merge(self) -> None:
        rec = _recommend("analog", "analog", "AGND", "GNDA")
        assert rec["recommendation"] == "merge"
        assert "same" in rec["reason"].lower()

    def test_digital_vs_analog_split(self) -> None:
        rec = _recommend("digital", "analog", "DGND", "AGND")
        assert rec["recommendation"] == "split"
        assert "separate" in rec["reason"].lower()

    def test_analog_vs_digital_split(self) -> None:
        rec = _recommend("analog", "digital", "AGND", "DGND")
        assert rec["recommendation"] == "split"

    def test_passive_and_digital_star_point(self) -> None:
        rec = _recommend("passive_only", "digital", "GND", "DGND")
        assert rec["recommendation"] == "star_point"
        assert "star" in rec["recommendation"].lower()

    def test_passive_and_analog_star_point(self) -> None:
        rec = _recommend("passive_only", "analog", "GND", "AGND")
        assert rec["recommendation"] == "star_point"

    def test_digital_and_passive_star_point(self) -> None:
        rec = _recommend("digital", "passive_only", "DGND", "GND")
        assert rec["recommendation"] == "star_point"


# ---------------------------------------------------------------------------
# _find_ground_connections
# ---------------------------------------------------------------------------

class TestFindGroundConnections:
    """Tests for _find_ground_connections."""

    def test_finds_ground_to_ground_short(self) -> None:
        shorts = [_make_erc_short("GND", "AGND")]
        connections = _find_ground_connections({"GND", "AGND", "GNDA"}, shorts)
        assert len(connections) == 1
        assert connections[0]["net_a"] == "GND"
        assert connections[0]["net_b"] == "AGND"

    def test_ignores_signal_shorts(self) -> None:
        shorts = [_make_erc_short("SDA", "SCL")]
        connections = _find_ground_connections({"GND", "AGND"}, shorts)
        assert connections == []

    def test_ignores_power_to_ground(self) -> None:
        shorts = [_make_erc_short("+3V3", "GND")]
        connections = _find_ground_connections({"GND", "AGND"}, shorts)
        assert connections == []

    def test_deduplicates_same_pair(self) -> None:
        shorts = [
            _make_erc_short("GND", "AGND", sheet="/Sheet1"),
            _make_erc_short("GND", "AGND", sheet="/Sheet2"),
        ]
        connections = _find_ground_connections({"GND", "AGND"}, shorts)
        assert len(connections) == 1

    def test_multiple_distinct_connections(self) -> None:
        shorts = [
            _make_erc_short("GND", "AGND"),
            _make_erc_short("AGND", "DGND"),
        ]
        connections = _find_ground_connections({"GND", "AGND", "DGND"}, shorts)
        assert len(connections) == 2

    def test_no_shorts_returns_empty(self) -> None:
        connections = _find_ground_connections({"GND", "AGND"}, [])
        assert connections == []


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------

class TestAnalyzeGroundTopologyOpSchema:
    """Tests for AnalyzeGroundTopologyOp Pydantic schema."""

    def test_default_fields(self) -> None:
        from kicad_agent.ops._schema_schematic_intel import AnalyzeGroundTopologyOp
        op = AnalyzeGroundTopologyOp(target_file="test.kicad_sch")
        assert op.op_type == "analyze_ground_topology"
        assert op.ground_nets is None

    def test_explicit_ground_nets(self) -> None:
        from kicad_agent.ops._schema_schematic_intel import AnalyzeGroundTopologyOp
        op = AnalyzeGroundTopologyOp(
            target_file="test.kicad_sch",
            ground_nets=["GND", "AGND"],
        )
        assert op.ground_nets == ["GND", "AGND"]

    def test_rejects_path_traversal(self) -> None:
        from kicad_agent.ops._schema_schematic_intel import AnalyzeGroundTopologyOp
        import pydantic
        with pytest.raises(pydantic.ValidationError):
            AnalyzeGroundTopologyOp(target_file="../etc/passwd")

    def test_rejects_absolute_path(self) -> None:
        from kicad_agent.ops._schema_schematic_intel import AnalyzeGroundTopologyOp
        import pydantic
        with pytest.raises(pydantic.ValidationError):
            AnalyzeGroundTopologyOp(target_file="/etc/passwd.kicad_sch")

    def test_rejects_too_many_ground_nets(self) -> None:
        from kicad_agent.ops._schema_schematic_intel import AnalyzeGroundTopologyOp
        import pydantic
        with pytest.raises(pydantic.ValidationError):
            AnalyzeGroundTopologyOp(
                target_file="test.kicad_sch",
                ground_nets=[f"GND{i}" for i in range(21)],
            )


# ---------------------------------------------------------------------------
# Integration with mocked netlist/ERC
# ---------------------------------------------------------------------------

class TestAnalyzeGroundTopologyIntegration:
    """Integration tests with mocked kicad-cli and ERC."""

    @patch("kicad_agent.ops.net_short_detector._extract_erc_shorts")
    @patch("kicad_agent.ops.net_short_detector._export_and_parse_netlist")
    def test_single_ground_no_shorts(self, mock_netlist: MagicMock, mock_erc: MagicMock) -> None:
        mock_netlist.return_value = {
            "GND": {("R1", "1"), ("C1", "2")},
            "+3V3": {("U1", "8")},
        }
        mock_erc.return_value = []
        result = analyze_ground_topology(Path("test.kicad_sch"))
        assert result["ground_net_count"] == 1
        assert "GND" in result["ground_nets"]
        assert result["connections"] == []
        assert result["recommendation"] == "merge"
        assert result["ground_nets"]["GND"]["domain"] == "passive_only"

    @patch("kicad_agent.ops.net_short_detector._extract_erc_shorts")
    @patch("kicad_agent.ops.net_short_detector._export_and_parse_netlist")
    def test_ground_short_with_recommendation(self, mock_netlist: MagicMock, mock_erc: MagicMock) -> None:
        mock_netlist.return_value = {
            "GND": {("R1", "1"), ("C1", "2")},
            "AGND": {("U2NE5532", "3"), ("R2", "1")},
            "+3V3": {("U1", "8")},
        }
        mock_erc.return_value = [_make_erc_short("GND", "AGND")]
        result = analyze_ground_topology(Path("test.kicad_sch"))
        assert result["ground_net_count"] == 2
        assert result["connection_count"] == 1
        conn = result["connections"][0]
        assert conn["recommendation"] == "star_point"
        assert "AGND" in conn["reason"]
        assert conn["domain_a"] == "passive_only"
        assert conn["domain_b"] == "analog"

    @patch("kicad_agent.ops.net_short_detector._extract_erc_shorts")
    @patch("kicad_agent.ops.net_short_detector._export_and_parse_netlist")
    def test_digital_analog_split_recommendation(self, mock_netlist: MagicMock, mock_erc: MagicMock) -> None:
        mock_netlist.return_value = {
            "DGND": {("U1STM32", "4"), ("C1", "1")},
            "AGND": {("U2NE5532", "3"), ("R1", "1")},
        }
        mock_erc.return_value = [_make_erc_short("DGND", "AGND")]
        result = analyze_ground_topology(Path("test.kicad_sch"))
        assert result["recommendation"] == "split"
        assert result["connections"][0]["recommendation"] == "split"

    @patch("kicad_agent.ops.net_short_detector._extract_erc_shorts")
    @patch("kicad_agent.ops.net_short_detector._export_and_parse_netlist")
    def test_explicit_ground_nets_list(self, mock_netlist: MagicMock, mock_erc: MagicMock) -> None:
        mock_netlist.return_value = {
            "GND": {("R1", "1")},
            "AGND": {("U1", "1")},
            "DGND": {("U2", "1")},
        }
        mock_erc.return_value = []
        result = analyze_ground_topology(Path("test.kicad_sch"), ground_nets=["GND", "AGND"])
        assert set(result["ground_nets"].keys()) == {"GND", "AGND"}
        assert "DGND" not in result["ground_nets"]

    @patch("kicad_agent.ops.net_short_detector._extract_erc_shorts")
    @patch("kicad_agent.ops.net_short_detector._export_and_parse_netlist")
    def test_empty_netlist(self, mock_netlist: MagicMock, mock_erc: MagicMock) -> None:
        mock_netlist.return_value = {}
        mock_erc.return_value = []
        result = analyze_ground_topology(Path("test.kicad_sch"))
        assert result["ground_net_count"] == 0
        assert result["recommendation"] == "none"
        assert "No ground nets" in result["reason"]

    @patch("kicad_agent.ops.net_short_detector._extract_erc_shorts")
    @patch("kicad_agent.ops.net_short_detector._export_and_parse_netlist")
    def test_pin_count_and_refs_in_output(self, mock_netlist: MagicMock, mock_erc: MagicMock) -> None:
        mock_netlist.return_value = {
            "GND": {("R1", "1"), ("C1", "2"), ("R2", "1")},
            "AGND": {("U1", "4")},
        }
        mock_erc.return_value = []
        result = analyze_ground_topology(Path("test.kicad_sch"))
        assert result["ground_nets"]["GND"]["pin_count"] == 3
        assert result["ground_nets"]["GND"]["refs"] == ["C1", "R1", "R2"]
        assert result["ground_nets"]["AGND"]["pin_count"] == 1

    @patch("kicad_agent.ops.net_short_detector._extract_erc_shorts")
    @patch("kicad_agent.ops.net_short_detector._export_and_parse_netlist")
    def test_kicad_cli_failure_returns_empty(self, mock_netlist: MagicMock, mock_erc: MagicMock) -> None:
        mock_netlist.return_value = {}
        mock_erc.return_value = []
        result = analyze_ground_topology(Path("test.kicad_sch"))
        assert result["ground_net_count"] == 0
        assert result["recommendation"] == "none"


# ---------------------------------------------------------------------------
# Handler dispatch
# ---------------------------------------------------------------------------

class TestHandlerDispatch:
    """Tests for handler registration and dispatch."""

    def test_handler_registered(self) -> None:
        from kicad_agent.ops.handlers.schematic_query import _SCHEMATIC_QUERY_HANDLERS
        assert "analyze_ground_topology" in _SCHEMATIC_QUERY_HANDLERS

    @patch("kicad_agent.ops.net_short_detector._extract_erc_shorts")
    @patch("kicad_agent.ops.net_short_detector._export_and_parse_netlist")
    def test_handler_calls_analyze(self, mock_netlist: MagicMock, mock_erc: MagicMock) -> None:
        from kicad_agent.ops.handlers.schematic_query import _SCHEMATIC_QUERY_HANDLERS
        mock_netlist.return_value = {"GND": {("R1", "1")}}
        mock_erc.return_value = []
        handler = _SCHEMATIC_QUERY_HANDLERS["analyze_ground_topology"]
        op = MagicMock()
        op.ground_nets = None
        ir = MagicMock()
        result = handler(op, ir, Path("test.kicad_sch"))
        assert result["ground_net_count"] == 1
