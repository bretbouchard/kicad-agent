"""Tests for Issue #14: connectivity inference engine.

Verifies infer_nets() confidence scoring, power pin inference,
and output format compatibility with batch_wiring.
"""

import json
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from kiutils.items.common import Position
from kiutils.schematic import Schematic

from volta.schematic_routing.net_inference import (
    _score_net,
    _suggest_net,
    infer_nets,
)


class TestScoreNet:
    """Unit tests for net confidence scoring."""

    def test_named_net_high_confidence(self):
        """Explicit label name → high confidence."""
        confidence, source = _score_net("VCC_3V3", [{"ref": "U1", "pin_number": "5"}])
        assert confidence == "high"
        assert source == "label"

    def test_auto_named_multi_pin_medium(self):
        """Auto-named net with 2+ pins → medium confidence."""
        pins = [
            {"ref": "U1", "pin_number": "1"},
            {"ref": "U2", "pin_number": "3"},
        ]
        confidence, source = _score_net("Net_42", pins)
        assert confidence == "medium"
        assert source == "wire_trace"

    def test_auto_named_single_pin_low(self):
        """Auto-named net with 1 pin → low confidence."""
        confidence, source = _score_net("Net_7", [{"ref": "U1", "pin_number": "2"}])
        assert confidence == "low"
        assert source == "single_pin"

    def test_named_net_with_special_chars(self):
        """Named net with special chars is still high confidence."""
        confidence, source = _score_net("I2C1_SDA", [])
        assert confidence == "high"

    def test_net_0_is_auto_named(self):
        """Net_0 is auto-named (digit suffix)."""
        confidence, _ = _score_net("Net_0", [{"ref": "R1", "pin_number": "1"}])
        assert confidence == "low"

    def test_net_layer_is_not_auto(self):
        """'Net_Layer' is NOT auto-named (non-digit suffix)."""
        confidence, _ = _score_net("Net_Layer", [])
        assert confidence == "high"


class TestSuggestNet:
    """Unit tests for pin map suggestion lookup."""

    def test_matching_pin_returns_net(self):
        """Pin in mapping returns suggested net name."""
        mapping = {"AK4619VN": {"TVDD": "VCC_3V3", "SCL": "I2C1_SCL"}}
        pin = {"pin_name": "TVDD", "pin_number": "5"}
        result = _suggest_net("U1", pin, {"U1": "Audio_Codec:AK4619VN"}, mapping)
        assert result == "VCC_3V3"

    def test_pin_mapped_to_none(self):
        """Pin mapped to None (no-connect) returns None."""
        mapping = {"AK4619VN": {"AIN1": None}}
        pin = {"pin_name": "AIN1", "pin_number": "3"}
        result = _suggest_net("U1", pin, {"U1": "Audio_Codec:AK4619VN"}, mapping)
        assert result is None

    def test_pin_not_in_mapping(self):
        """Pin not in mapping returns None."""
        mapping = {"AK4619VN": {"TVDD": "VCC_3V3"}}
        pin = {"pin_name": "UNKNOWN", "pin_number": "99"}
        result = _suggest_net("U1", pin, {"U1": "Audio_Codec:AK4619VN"}, mapping)
        assert result is None

    def test_no_lib_id(self):
        """Component with no lib_id returns None."""
        mapping = {"AK4619VN": {"TVDD": "VCC_3V3"}}
        pin = {"pin_name": "TVDD", "pin_number": "5"}
        result = _suggest_net("U1", pin, {"U1": ""}, mapping)
        assert result is None

    def test_unknown_ic(self):
        """IC not in mapping returns None."""
        mapping = {"AK4619VN": {"TVDD": "VCC_3V3"}}
        pin = {"pin_name": "VCC", "pin_number": "1"}
        result = _suggest_net("U2", pin, {"U2": "Unknown:IC999"}, mapping)
        assert result is None


class TestInferNetsIntegration:
    """Integration tests using mocked extract_nets."""

    def test_empty_schematic(self):
        """Empty schematic → no nets, no unconnected pins."""
        with tempfile.TemporaryDirectory() as tmpdir:
            sch_path = Path(tmpdir) / "test.kicad_sch"
            sch = Schematic.create_new()
            sch.to_file(str(sch_path))

            with patch("volta.schematic_routing.net_inference.extract_nets",
                       return_value={"nets": {}, "stats": {"total_nets": 0}}):
                with patch("volta.schematic_routing.net_inference._find_unconnected_pins",
                           return_value=[]):
                    result = infer_nets(sch_path)

            assert result["nets"] == []
            assert result["unconnected_pins"] == []
            assert result["stats"]["total_nets"] == 0

    def test_high_confidence_named_net(self):
        """Named net appears as high confidence."""
        mock_nets = {
            "VCC_3V3": [
                {"ref": "U1", "pin_number": "5", "pin_name": "TVDD", "position": [10, 20]},
            ],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            sch_path = Path(tmpdir) / "test.kicad_sch"
            sch = Schematic.create_new()
            sch.to_file(str(sch_path))

            with patch("volta.schematic_routing.net_inference.extract_nets",
                       return_value={"nets": mock_nets, "stats": {"total_nets": 1}}):
                with patch("volta.schematic_routing.net_inference._find_unconnected_pins",
                           return_value=[]):
                    result = infer_nets(sch_path)

            assert len(result["nets"]) == 1
            assert result["nets"][0]["name"] == "VCC_3V3"
            assert result["nets"][0]["confidence"] == "high"
            assert result["nets"][0]["source"] == "label"
            assert result["stats"]["high_confidence"] == 1

    def test_medium_confidence_auto_named(self):
        """Auto-named net with 2 pins → medium confidence."""
        mock_nets = {
            "Net_1": [
                {"ref": "U1", "pin_number": "1", "pin_name": "A", "position": [0, 0]},
                {"ref": "U2", "pin_number": "2", "pin_name": "B", "position": [10, 10]},
            ],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            sch_path = Path(tmpdir) / "test.kicad_sch"
            sch = Schematic.create_new()
            sch.to_file(str(sch_path))

            with patch("volta.schematic_routing.net_inference.extract_nets",
                       return_value={"nets": mock_nets, "stats": {"total_nets": 1}}):
                with patch("volta.schematic_routing.net_inference._find_unconnected_pins",
                           return_value=[]):
                    result = infer_nets(sch_path)

            assert len(result["nets"]) == 1
            assert result["nets"][0]["confidence"] == "medium"
            assert result["stats"]["medium_confidence"] == 1

    def test_confidence_threshold_filters_low(self):
        """threshold='high' filters out medium and low confidence nets."""
        mock_nets = {
            "VCC_3V3": [{"ref": "U1", "pin_number": "1", "pin_name": "VDD"}],
            "Net_1": [
                {"ref": "U2", "pin_number": "1", "pin_name": "A"},
                {"ref": "U3", "pin_number": "1", "pin_name": "B"},
            ],
            "Net_2": [{"ref": "U4", "pin_number": "1", "pin_name": "C"}],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            sch_path = Path(tmpdir) / "test.kicad_sch"
            sch = Schematic.create_new()
            sch.to_file(str(sch_path))

            with patch("volta.schematic_routing.net_inference.extract_nets",
                       return_value={"nets": mock_nets, "stats": {"total_nets": 3}}):
                with patch("volta.schematic_routing.net_inference._find_unconnected_pins",
                           return_value=[]):
                    result = infer_nets(sch_path, confidence_threshold="high")

            # Only the named net passes
            assert len(result["nets"]) == 1
            assert result["nets"][0]["name"] == "VCC_3V3"

    def test_output_format_compatible_with_batch_wiring(self):
        """Output format has required keys for batch_wiring compatibility."""
        mock_nets = {
            "SDA": [
                {"ref": "U1", "pin_number": "3", "pin_name": "SDA", "position": [50, 50]},
            ],
        }
        with tempfile.TemporaryDirectory() as tmpdir:
            sch_path = Path(tmpdir) / "test.kicad_sch"
            sch = Schematic.create_new()
            sch.to_file(str(sch_path))

            with patch("volta.schematic_routing.net_inference.extract_nets",
                       return_value={"nets": mock_nets, "stats": {"total_nets": 1}}):
                with patch("volta.schematic_routing.net_inference._find_unconnected_pins",
                           return_value=[{
                               "ref": "U1", "pin": "AIN1", "pin_number": "5",
                               "electrical_type": "passive",
                               "suggested_net": None, "position": [30, 40],
                           }]):
                    result = infer_nets(sch_path)

            # Top-level keys
            assert "nets" in result
            assert "unconnected_pins" in result
            assert "stats" in result

            # Net entry format
            net = result["nets"][0]
            assert "name" in net
            assert "pins" in net
            assert "confidence" in net
            assert "source" in net

            # Unconnected pin format
            uc = result["unconnected_pins"][0]
            assert "ref" in uc
            assert "pin" in uc
            assert "pin_number" in uc
            assert "electrical_type" in uc
            assert "suggested_net" in uc
            assert "position" in uc

            # Stats format
            stats = result["stats"]
            assert "total_nets" in stats
            assert "high_confidence" in stats
            assert "medium_confidence" in stats
            assert "low_confidence" in stats
            assert "unconnected_pins" in stats


class TestSuggestNetFromProfile:
    """Test power pin inference with built-in profiles."""

    def test_backplane_profile_suggests_power(self):
        """Backplane profile suggests VCC_3V3 for AK4619VN TVDD pin."""
        from volta.ops.net_label_placer import _BUILTIN_PROFILES

        mapping = _BUILTIN_PROFILES["backplane"]
        pin = {"pin_name": "TVDD", "pin_number": "5"}
        result = _suggest_net("U1", pin, {"U1": "Audio_Codec:AK4619VN"}, mapping)
        assert result == "VCC_3V3"

    def test_backplane_profile_suggests_gnd(self):
        """Backplane profile suggests GND for MT8816 VSS pin."""
        from volta.ops.net_label_placer import _BUILTIN_PROFILES

        mapping = _BUILTIN_PROFILES["backplane"]
        pin = {"pin_name": "VSS", "pin_number": "20"}
        result = _suggest_net("U2", pin, {"U2": "Switch:MT8816"}, mapping)
        assert result == "GND"

    def test_channel_strip_15v(self):
        """Channel-strip profile suggests ±15V for NE5532."""
        from volta.ops.net_label_placer import _BUILTIN_PROFILES

        mapping = _BUILTIN_PROFILES["channel-strip"]
        pin = {"pin_name": "VCC", "pin_number": "8"}
        result = _suggest_net("U3", pin, {"U3": "OpAmp:NE5532"}, mapping)
        assert result == "VCC_15V"
