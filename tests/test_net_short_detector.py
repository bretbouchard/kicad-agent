"""Tests for net_short_detector -- netlist-based short detection with severity.

Covers: netlist parsing, severity classification, ERC cross-referencing,
schema validation, and read-only guarantee.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from kicad_agent.ops.net_short_detector import (
    _classify_severity,
    _export_and_parse_netlist,
    _find_shared_pins,
    _is_ground_net,
    _is_power_net,
    _parse_kicad_netlist,
    detect_net_shorts,
)


# ---------------------------------------------------------------------------
# Netlist parsing
# ---------------------------------------------------------------------------

class TestParseKicadNetlist:
    """Tests for KiCad S-expression netlist parser."""

    def test_extracts_single_net(self) -> None:
        content = """(export
\t(version "E")
\t(design)
\t\t(source "test.kicad_sch")
\t)
\t(components)
\t\t(comp (ref "R1") (value "1k"))
\t)
\t(nets
\t\t(net
\t\t\t(code "0")
\t\t\t(name "GND")
\t\t\t(class "Default")
\t\t\t(node
\t\t\t\t(ref "R1")
\t\t\t\t(pin "1")
\t\t\t\t(pintype "passive")
\t\t\t)
\t\t)
\t)
)"""
        result = _parse_kicad_netlist(content)
        assert "GND" in result
        assert ("R1", "1") in result["GND"]

    def test_extracts_multiple_nets(self) -> None:
        content = """(export
\t(version "E")
\t(design)
\t\t(source "test.kicad_sch")
\t)
\t(components)
\t\t(comp (ref "R1") (value "1k"))
\t\t(comp (ref "C1") (value "100nF"))
\t\t(comp (ref "U1") (value "NE5532"))
\t)
\t(nets
\t\t(net
\t\t\t(code "0")
\t\t\t(name "GND")
\t\t\t(class "Default")
\t\t\t(node
\t\t\t\t(ref "R1")
\t\t\t\t(pin "1")
\t\t\t\t(pintype "passive")
\t\t\t)
\t\t\t(node
\t\t\t\t(ref "C1")
\t\t\t\t(pin "2")
\t\t\t\t(pintype "passive")
\t\t\t)
\t\t)
\t\t(net
\t\t\t(code "1")
\t\t\t(name "+3V3")
\t\t\t(class "Default")
\t\t\t(node
\t\t\t\t(ref "U1")
\t\t\t\t(pin "14")
\t\t\t\t(pinfunction "VDD")
\t\t\t\t(pintype "power_in")
\t\t\t)
\t\t)
\t)
)"""
        result = _parse_kicad_netlist(content)
        assert len(result) == 2
        assert ("R1", "1") in result["GND"]
        assert ("C1", "2") in result["GND"]
        assert ("U1", "14") in result["+3V3"]

    def test_extracts_pinfunction(self) -> None:
        content = """(export
\t(version "E")
\t(design)
\t\t(source "test.kicad_sch")
\t)
\t(components)
\t\t(comp (ref "U1") (value "RP2350"))
\t)
\t(nets
\t\t(net
\t\t\t(code "0")
\t\t\t(name "SDA")
\t\t\t(class "Default")
\t\t\t(node
\t\t\t\t(ref "U1")
\t\t\t\t(pin "5")
\t\t\t\t(pinfunction "SDA")
\t\t\t\t(pintype "bidirectional")
\t\t\t)
\t\t)
\t)
)"""
        result = _parse_kicad_netlist(content)
        assert ("U1", "5") in result["SDA"]

    def test_empty_netlist(self) -> None:
        result = _parse_kicad_netlist("(export\n\t(version \"E\")\n)\n")
        assert result == {}

    def test_net_with_no_nodes(self) -> None:
        content = """(export
\t(version "E")
\t(design)
\t\t(source "test.kicad_sch")
\t)
\t(nets
\t\t(net
\t\t\t(code "0")
\t\t\t(name "EMPTY")
\t\t)
\t)
)"""
        result = _parse_kicad_netlist(content)
        assert "EMPTY" in result
        assert result["EMPTY"] == set()


# ---------------------------------------------------------------------------
# Shared pin detection
# ---------------------------------------------------------------------------

class TestFindSharedPins:
    """Tests for cross-net pin overlap detection."""

    def test_finds_shared_pins(self) -> None:
        net_pins = {
            "+3V3": {("U1", "4"), ("U1", "5"), ("U1", "6")},
            "GND": {("U1", "4"), ("U1", "5"), ("C1", "1")},
        }
        shared = _find_shared_pins("+3V3", "GND", net_pins)
        assert shared == ["U1.4", "U1.5"]

    def test_no_shared_pins(self) -> None:
        net_pins = {
            "SDA": {("U1", "5")},
            "SCL": {("U1", "6")},
        }
        shared = _find_shared_pins("SDA", "SCL", net_pins)
        assert shared == []

    def test_missing_net(self) -> None:
        net_pins = {"GND": {("R1", "1")}}
        shared = _find_shared_pins("GND", "+3V3", net_pins)
        assert shared == []


# ---------------------------------------------------------------------------
# Severity classification
# ---------------------------------------------------------------------------

class TestClassifySeverity:
    """Tests for short severity classification rules."""

    # Critical: power-to-ground (hardware damage)
    @pytest.mark.parametrize("a,b", [
        ("+3V3", "GND"),
        ("+5V", "GND"),
        ("+9V", "AGND"),
        ("GNDA", "+9V"),
        ("VCC", "GND"),
        ("VDD", "DGND"),
    ])
    def test_power_to_ground_is_critical(self, a: str, b: str) -> None:
        assert _classify_severity(a, b) == "critical"

    # Critical: power-to-power (different rails)
    @pytest.mark.parametrize("a,b", [
        ("+3V3", "+5V"),
        ("+9V", "+5V"),
        ("VCC", "VDD"),
    ])
    def test_power_to_power_is_critical(self, a: str, b: str) -> None:
        assert _classify_severity(a, b) == "critical"

    # Medium: ground-to-ground (may be intentional)
    @pytest.mark.parametrize("a,b", [
        ("GND", "AGND"),
        ("GND", "GNDA"),
        ("AGND", "DGND"),
        ("GNDA", "AGND"),
    ])
    def test_ground_to_ground_is_medium(self, a: str, b: str) -> None:
        assert _classify_severity(a, b) == "medium"

    # High: signal-to-signal or power-to-signal
    def test_signal_to_signal_is_high(self) -> None:
        assert _classify_severity("SDA", "SCL") == "high"
        assert _classify_severity("SIG_COLD", "SIG_COLD_CH2") == "high"

    def test_power_to_signal_is_high(self) -> None:
        assert _classify_severity("+3V3", "SDA") == "high"


# ---------------------------------------------------------------------------
# Ground/power detection
# ---------------------------------------------------------------------------

class TestIsGroundNet:
    @pytest.mark.parametrize("name", ["GND", "AGND", "DGND", "PGND", "SGND", "GNDA", "CHASSIS"])
    def test_matches_ground_variants(self, name: str) -> None:
        assert _is_ground_net(name)

    def test_rejects_non_ground(self) -> None:
        assert not _is_ground_net("SDA")
        assert not _is_ground_net("+3V3")


class TestIsPowerNet:
    @pytest.mark.parametrize("name", ["+3V3", "+5V", "+9V", "-15V", "VCC", "VDD", "VIN", "VOUT"])
    def test_matches_power_nets(self, name: str) -> None:
        assert _is_power_net(name)

    def test_grounds_are_also_power(self) -> None:
        assert _is_power_net("GND")
        assert _is_power_net("AGND")

    def test_rejects_signal_nets(self) -> None:
        assert not _is_power_net("SDA")
        assert not _is_power_net("SIG_COLD")


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------

class TestDetectNetShortsOpSchema:
    """Tests for DetectNetShortsOp Pydantic schema validation."""

    def test_defaults(self) -> None:
        from kicad_agent.ops._schema_schematic_intel import DetectNetShortsOp
        op = DetectNetShortsOp(target_file="test.kicad_sch")
        assert op.op_type == "detect_net_shorts"
        assert op.include is None
        assert op.severity == "all"

    def test_custom_fields(self) -> None:
        from kicad_agent.ops._schema_schematic_intel import DetectNetShortsOp
        op = DetectNetShortsOp(
            target_file="test.kicad_sch",
            include=["GND", "+3V3"],
            severity="critical",
        )
        assert op.include == ["GND", "+3V3"]
        assert op.severity == "critical"

    def test_invalid_severity(self) -> None:
        from kicad_agent.ops._schema_schematic_intel import DetectNetShortsOp
        with pytest.raises(Exception):
            DetectNetShortsOp(
                target_file="test.kicad_sch",
                severity="low",
            )

    def test_rejects_absolute_path(self) -> None:
        from kicad_agent.ops._schema_schematic_intel import DetectNetShortsOp
        with pytest.raises(Exception):
            DetectNetShortsOp(target_file="/etc/passwd.kicad_sch")

    def test_rejects_path_traversal(self) -> None:
        from kicad_agent.ops._schema_schematic_intel import DetectNetShortsOp
        with pytest.raises(Exception):
            DetectNetShortsOp(target_file="../schematic.kicad_sch")


# ---------------------------------------------------------------------------
# Integration (mocked kicad-cli)
# ---------------------------------------------------------------------------

class TestDetectNetShortsIntegration:
    """Integration tests with mocked kicad-cli and ERC."""

    def _make_erc_violation(
        self,
        net_a: str,
        net_b: str,
        sheet: str = "/",
    ) -> MagicMock:
        """Create a mock ErcViolation for multiple_net_names."""
        from kicad_agent.ops.erc_parser import ErcViolation
        return ErcViolation(
            sheet=sheet,
            type="multiple_net_names",
            severity="warning",
            description=f"Both {net_a} and {net_b} are attached to the same items; {net_a} will be used in the netlist",
            positions=[],
        )

    @patch("kicad_agent.ops.net_short_detector._export_and_parse_netlist")
    @patch("kicad_agent.ops.erc_parser.parse_erc")
    def test_detects_power_to_ground_short(self, mock_parse_erc, mock_netlist) -> None:
        mock_netlist.return_value = {
            "+3V3": {("U1", "4"), ("U1", "5"), ("U1", "6"), ("C1", "2")},
            "GND": {("U1", "4"), ("U1", "5"), ("U1", "6"), ("U2", "4")},
        }
        mock_parse_erc.return_value = [
            self._make_erc_violation("+3V3", "GND"),
        ]

        result = detect_net_shorts(Path("test.kicad_sch"))

        assert result["total"] == 1
        assert result["critical"] == 1
        short = result["shorts"][0]
        assert short["net_a"] == "+3V3"
        assert short["net_b"] == "GND"
        assert short["severity"] == "critical"
        assert "U1.4" in short["shared_pins"]
        assert short["pin_count"] == 3

    @patch("kicad_agent.ops.net_short_detector._export_and_parse_netlist")
    @patch("kicad_agent.ops.erc_parser.parse_erc")
    def test_detects_ground_to_ground_short(self, mock_parse_erc, mock_netlist) -> None:
        mock_netlist.return_value = {
            "GNDA": {("R1", "1"), ("R2", "2")},
            "AGND": {("R1", "1")},
        }
        mock_parse_erc.return_value = [
            self._make_erc_violation("GNDA", "AGND"),
        ]

        result = detect_net_shorts(Path("test.kicad_sch"))

        assert result["total"] == 1
        assert result["medium"] == 1
        short = result["shorts"][0]
        assert short["severity"] == "medium"

    @patch("kicad_agent.ops.net_short_detector._export_and_parse_netlist")
    @patch("kicad_agent.ops.erc_parser.parse_erc")
    def test_filters_by_severity(self, mock_parse_erc, mock_netlist) -> None:
        mock_netlist.return_value = {
            "+3V3": {("U1", "4")},
            "GND": {("U1", "4")},
            "SDA": {("U2", "3")},
            "SCL": {("U2", "3")},
        }
        mock_parse_erc.return_value = [
            self._make_erc_violation("+3V3", "GND"),
            self._make_erc_violation("SDA", "SCL"),
        ]

        result = detect_net_shorts(Path("test.kicad_sch"), severity="critical")

        assert result["total"] == 1
        assert result["shorts"][0]["net_a"] == "+3V3"

    @patch("kicad_agent.ops.net_short_detector._export_and_parse_netlist")
    @patch("kicad_agent.ops.erc_parser.parse_erc")
    def test_filters_by_include(self, mock_parse_erc, mock_netlist) -> None:
        mock_netlist.return_value = {
            "+3V3": {("U1", "4")},
            "GND": {("U1", "4")},
            "SDA": {("U2", "3")},
            "SCL": {("U2", "3")},
        }
        mock_parse_erc.return_value = [
            self._make_erc_violation("+3V3", "GND"),
            self._make_erc_violation("SDA", "SCL"),
        ]

        result = detect_net_shorts(
            Path("test.kicad_sch"),
            include=["SDA", "SCL"],
        )

        assert result["total"] == 1
        assert result["shorts"][0]["net_a"] == "SDA"

    @patch("kicad_agent.ops.net_short_detector._export_and_parse_netlist")
    @patch("kicad_agent.ops.erc_parser.parse_erc")
    def test_no_shorts(self, mock_parse_erc, mock_netlist) -> None:
        mock_netlist.return_value = {"GND": {("R1", "1")}}
        mock_parse_erc.return_value = []

        result = detect_net_shorts(Path("test.kicad_sch"))

        assert result["total"] == 0
        assert result["shorts"] == []

    @patch("kicad_agent.ops.net_short_detector._export_and_parse_netlist")
    @patch("kicad_agent.ops.erc_parser.parse_erc")
    def test_deduplicates_pairs(self, mock_parse_erc, mock_netlist) -> None:
        """ERC may report the same short from different sheet views."""
        mock_netlist.return_value = {
            "+3V3": {("U1", "4")},
            "GND": {("U1", "4")},
        }
        mock_parse_erc.return_value = [
            self._make_erc_violation("+3V3", "GND", sheet="/Input Stage"),
            self._make_erc_violation("+3V3", "GND", sheet="/EQ Stage"),
        ]

        result = detect_net_shorts(Path("test.kicad_sch"))

        assert result["total"] == 1

    @patch("kicad_agent.ops.net_short_detector._export_and_parse_netlist")
    @patch("kicad_agent.ops.erc_parser.parse_erc")
    def test_sorted_by_severity(self, mock_parse_erc, mock_netlist) -> None:
        mock_netlist.return_value = {
            "+3V3": {("U1", "4")},
            "GND": {("U1", "4")},
            "GNDA": {("R1", "1")},
            "AGND": {("R1", "1")},
            "SDA": {("U2", "3")},
            "SCL": {("U2", "3")},
        }
        mock_parse_erc.return_value = [
            self._make_erc_violation("SDA", "SCL"),
            self._make_erc_violation("+3V3", "GND"),
            self._make_erc_violation("GNDA", "AGND"),
        ]

        result = detect_net_shorts(Path("test.kicad_sch"))

        # Critical first, then high, then medium
        assert result["shorts"][0]["severity"] == "critical"
        assert result["shorts"][1]["severity"] == "high"
        assert result["shorts"][2]["severity"] == "medium"

    @patch("kicad_agent.ops.net_short_detector._export_and_parse_netlist")
    def test_handles_kicad_cli_failure(self, mock_netlist) -> None:
        mock_netlist.return_value = {}  # kicad-cli failure returns empty

        result = detect_net_shorts(Path("nonexistent.kicad_sch"))

        # No netlist data, so no shared pins even if ERC reports shorts
        assert result["total"] == 0
