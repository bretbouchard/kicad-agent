"""Tests for net_short_fixer -- targeted repair of shorted net pairs.

Covers: safety constraints, remove_wire strategy, disconnect strategies,
dry_run behavior, schema validation, and integration with mock IR.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from volta.ops.net_short_fixer import (
    _find_wires_touching_net,
    _is_safe_to_auto_fix,
    fix_net_short,
)


# ---------------------------------------------------------------------------
# Safety checks
# ---------------------------------------------------------------------------

class TestIsSafeToAutoFix:
    """Tests for auto-fix safety gate."""

    def test_signal_to_signal_is_safe(self) -> None:
        safe, reason = _is_safe_to_auto_fix("SDA", "SCL")
        assert safe is True
        assert reason == "signal-to-signal"

    def test_signal_to_signal_unnamed_is_safe(self) -> None:
        safe, reason = _is_safe_to_auto_fix("SIG_COLD", "SIG_COLD_CH2")
        assert safe is True

    # Critical: power-to-power or power-to-ground
    @pytest.mark.parametrize("a,b", [
        ("+3V3", "GND"),
        ("+5V", "GND"),
        ("+9V", "AGND"),
        ("+3V3", "+5V"),
        ("VCC", "VDD"),
    ])
    def test_critical_is_unsafe(self, a: str, b: str) -> None:
        safe, reason = _is_safe_to_auto_fix(a, b)
        assert safe is False
        assert "critical" in reason

    # Medium: ground-to-ground
    @pytest.mark.parametrize("a,b", [
        ("GND", "AGND"),
        ("GND", "DGND"),
        ("GNDA", "AGND"),
    ])
    def test_ground_to_ground_is_unsafe(self, a: str, b: str) -> None:
        safe, reason = _is_safe_to_auto_fix(a, b)
        assert safe is False
        assert "medium" in reason

    # Power-to-signal is also unsafe
    def test_power_to_signal_is_unsafe(self) -> None:
        safe, reason = _is_safe_to_auto_fix("+3V3", "SDA")
        assert safe is False
        assert "power-to-signal" in reason

    def test_signal_to_power_is_unsafe(self) -> None:
        safe, reason = _is_safe_to_auto_fix("SDA", "+5V")
        assert safe is False
        assert "power-to-signal" in reason


# ---------------------------------------------------------------------------
# Wire finding helpers
# ---------------------------------------------------------------------------

class TestFindWiresTouchingNet:
    """Tests for _find_wires_touching_net."""

    def _make_mock_ir(
        self,
        label_positions: list[dict] | None = None,
        wire_endpoints: list[dict] | None = None,
    ) -> MagicMock:
        ir = MagicMock()
        ir.get_label_positions.return_value = label_positions or []
        ir.get_wire_endpoints.return_value = wire_endpoints or []
        return ir

    def test_finds_wires_at_label_positions(self) -> None:
        ir = self._make_mock_ir(
            label_positions=[
                {"name": "SDA", "x": 10.0, "y": 20.0},
            ],
            wire_endpoints=[
                {"wire_index": 0, "start_x": 10.0, "start_y": 20.0, "end_x": 30.0, "end_y": 20.0},
                {"wire_index": 1, "start_x": 50.0, "start_y": 60.0, "end_x": 70.0, "end_y": 60.0},
            ],
        )
        result = _find_wires_touching_net(ir, "SDA")
        assert result == [0]

    def test_finds_wires_at_end_position(self) -> None:
        ir = self._make_mock_ir(
            label_positions=[
                {"name": "SDA", "x": 30.0, "y": 20.0},
            ],
            wire_endpoints=[
                {"wire_index": 0, "start_x": 10.0, "start_y": 20.0, "end_x": 30.0, "end_y": 20.0},
            ],
        )
        result = _find_wires_touching_net(ir, "SDA")
        assert result == [0]

    def test_excludes_other_nets(self) -> None:
        ir = self._make_mock_ir(
            label_positions=[
                {"name": "SDA", "x": 10.0, "y": 20.0},
            ],
            wire_endpoints=[
                {"wire_index": 0, "start_x": 50.0, "start_y": 60.0, "end_x": 70.0, "end_y": 60.0},
            ],
        )
        result = _find_wires_touching_net(ir, "SDA")
        assert result == []

    def test_no_labels_for_net(self) -> None:
        ir = self._make_mock_ir(
            label_positions=[
                {"name": "SCL", "x": 10.0, "y": 20.0},
            ],
            wire_endpoints=[
                {"wire_index": 0, "start_x": 10.0, "start_y": 20.0, "end_x": 30.0, "end_y": 20.0},
            ],
        )
        result = _find_wires_touching_net(ir, "SDA")
        assert result == []


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------

class TestFixNetShortOpSchema:
    """Tests for FixNetShortOp Pydantic schema validation."""

    def test_defaults(self) -> None:
        from volta.ops._schema_repair import FixNetShortOp
        op = FixNetShortOp(
            target_file="test.kicad_sch",
            net_a="SDA",
            net_b="SCL",
        )
        assert op.op_type == "fix_net_short"
        assert op.dry_run is False
        assert op.remove_strategy == "remove_wire"

    def test_custom_fields(self) -> None:
        from volta.ops._schema_repair import FixNetShortOp
        op = FixNetShortOp(
            target_file="test.kicad_sch",
            net_a="SDA",
            net_b="SCL",
            dry_run=True,
            remove_strategy="disconnect_a",
        )
        assert op.dry_run is True
        assert op.remove_strategy == "disconnect_a"

    def test_invalid_strategy(self) -> None:
        from volta.ops._schema_repair import FixNetShortOp
        with pytest.raises(Exception):
            FixNetShortOp(
                target_file="test.kicad_sch",
                net_a="SDA",
                net_b="SCL",
                remove_strategy="explode",
            )

    def test_empty_net_names(self) -> None:
        from volta.ops._schema_repair import FixNetShortOp
        with pytest.raises(Exception):
            FixNetShortOp(
                target_file="test.kicad_sch",
                net_a="",
                net_b="SCL",
            )

    def test_rejects_absolute_path(self) -> None:
        from volta.ops._schema_repair import FixNetShortOp
        with pytest.raises(Exception):
            FixNetShortOp(
                target_file="/etc/passwd.kicad_sch",
                net_a="SDA",
                net_b="SCL",
            )


# ---------------------------------------------------------------------------
# Integration (mocked IR)
# ---------------------------------------------------------------------------

class TestFixNetShortIntegration:
    """Integration tests with mocked IR and netlist."""

    def _make_mock_ir(
        self,
        label_positions: list[dict] | None = None,
        wire_endpoints: list[dict] | None = None,
    ) -> MagicMock:
        ir = MagicMock()
        ir.get_label_positions.return_value = label_positions or []
        ir.get_wire_endpoints.return_value = wire_endpoints or []
        ir._record_mutation = MagicMock()
        ir.schematic = MagicMock()
        ir.schematic.graphicalItems = [MagicMock()] * 10
        return ir

    @patch("volta.ops.net_short_detector._export_and_parse_netlist")
    def test_refuses_critical_short(self, mock_netlist) -> None:
        mock_netlist.return_value = {
            "+3V3": {("U1", "4")},
            "GND": {("U1", "4")},
        }

        ir = self._make_mock_ir()
        result = fix_net_short(
            ir, Path("test.kicad_sch"),
            net_a="+3V3", net_b="GND",
        )

        assert result["fixed"] is False
        assert result["action"] == "refused"
        assert "critical" in result["reason"]
        assert len(ir.schematic.graphicalItems) == 10

    @patch("volta.ops.net_short_detector._export_and_parse_netlist")
    def test_refuses_medium_short(self, mock_netlist) -> None:
        mock_netlist.return_value = {
            "GND": {("R1", "1")},
            "AGND": {("R1", "1")},
        }

        ir = self._make_mock_ir()
        result = fix_net_short(
            ir, Path("test.kicad_sch"),
            net_a="GND", net_b="AGND",
        )

        assert result["fixed"] is False
        assert result["action"] == "refused"
        assert "medium" in result["reason"]

    @patch("volta.ops.net_short_detector._export_and_parse_netlist")
    def test_refuses_power_to_signal(self, mock_netlist) -> None:
        mock_netlist.return_value = {
            "+3V3": {("U1", "4")},
            "SDA": {("U1", "4")},
        }

        ir = self._make_mock_ir()
        result = fix_net_short(
            ir, Path("test.kicad_sch"),
            net_a="+3V3", net_b="SDA",
        )

        assert result["fixed"] is False
        assert result["action"] == "refused"
        assert "power-to-signal" in result["reason"]

    @patch("volta.ops.net_short_detector._export_and_parse_netlist")
    @patch("volta.ops.repair_wires.find_bridge_wires")
    @patch("volta.ops.repair_nets._verify_clean_break")
    def test_removes_bridge_wire_signal_short(
        self, mock_verify, mock_find, mock_netlist,
    ) -> None:
        mock_netlist.return_value = {
            "SDA": {("U1", "5"), ("U2", "3")},
            "SCL": {("U1", "5"), ("U2", "4")},
        }
        mock_find.return_value = [
            {
                "wire_index": 3,
                "start": [10.0, 20.0],
                "end": [10.0, 40.0],
                "length": 20.0,
                "nets": ["SDA", "SCL"],
            },
        ]
        mock_verify.return_value = True

        ir = self._make_mock_ir(
            label_positions=[
                {"name": "SDA", "x": 10.0, "y": 20.0},
                {"name": "SCL", "x": 10.0, "y": 40.0},
            ],
            wire_endpoints=[
                {"wire_index": 0, "start_x": 5.0, "start_y": 20.0, "end_x": 10.0, "end_y": 20.0},
                {"wire_index": 1, "start_x": 10.0, "start_y": 40.0, "end_x": 20.0, "end_y": 40.0},
                {"wire_index": 2, "start_x": 50.0, "start_y": 50.0, "end_x": 60.0, "end_y": 50.0},
                {"wire_index": 3, "start_x": 10.0, "start_y": 20.0, "end_x": 10.0, "end_y": 40.0},
            ],
        )

        result = fix_net_short(
            ir, Path("test.kicad_sch"),
            net_a="SDA", net_b="SCL",
            remove_strategy="remove_wire",
        )

        assert result["fixed"] is True
        assert result["action"] == "remove_wire"
        assert result["severity"] == "high"
        assert result["shared_pins"] == ["U1.5"]
        assert result["wire_count"] == 1
        assert result["wires"][0]["wire_index"] == 3
        assert len(ir.schematic.graphicalItems) == 9  # 10 - 1 removed

    @patch("volta.ops.net_short_detector._export_and_parse_netlist")
    @patch("volta.ops.repair_wires.find_bridge_wires")
    @patch("volta.ops.repair_nets._verify_clean_break")
    def test_dry_run_reports_without_modifying(
        self, mock_verify, mock_find, mock_netlist,
    ) -> None:
        mock_netlist.return_value = {
            "SDA": {("U1", "5")},
            "SCL": {("U1", "5")},
        }
        mock_find.return_value = [
            {
                "wire_index": 3,
                "start": [10.0, 20.0],
                "end": [10.0, 40.0],
                "length": 20.0,
                "nets": ["SDA", "SCL"],
            },
        ]
        mock_verify.return_value = True

        ir = self._make_mock_ir(
            label_positions=[
                {"name": "SDA", "x": 10.0, "y": 20.0},
                {"name": "SCL", "x": 10.0, "y": 40.0},
            ],
            wire_endpoints=[
                {"wire_index": 3, "start_x": 10.0, "start_y": 20.0, "end_x": 10.0, "end_y": 40.0},
            ],
        )

        result = fix_net_short(
            ir, Path("test.kicad_sch"),
            net_a="SDA", net_b="SCL",
            dry_run=True,
            remove_strategy="remove_wire",
        )

        assert result["fixed"] is False
        assert result["action"] == "dry_run"
        assert result["dry_run"] is True
        assert result["wire_count"] == 1
        assert len(ir.schematic.graphicalItems) == 10  # unchanged

    @patch("volta.ops.net_short_detector._export_and_parse_netlist")
    @patch("volta.ops.repair_wires.find_bridge_wires")
    def test_no_bridge_found(
        self, mock_find, mock_netlist,
    ) -> None:
        mock_netlist.return_value = {
            "SDA": {("U1", "5")},
            "SCL": {("U2", "3")},
        }
        mock_find.return_value = []

        ir = self._make_mock_ir()

        result = fix_net_short(
            ir, Path("test.kicad_sch"),
            net_a="SDA", net_b="SCL",
            remove_strategy="remove_wire",
        )

        assert result["fixed"] is False
        assert result["action"] == "no_bridge_found"
        assert result["shared_pins"] == []

    @patch("volta.ops.net_short_detector._export_and_parse_netlist")
    def test_disconnect_a_removes_wires(self, mock_netlist) -> None:
        mock_netlist.return_value = {
            "ADC1_L": {("U1", "1")},
            "OUT_IN_CH1": {("U1", "1")},
        }

        ir = self._make_mock_ir(
            label_positions=[
                {"name": "ADC1_L", "x": 10.0, "y": 20.0},
                {"name": "OUT_IN_CH1", "x": 10.0, "y": 40.0},
            ],
            wire_endpoints=[
                {"wire_index": 0, "start_x": 10.0, "start_y": 20.0, "end_x": 30.0, "end_y": 20.0},
                {"wire_index": 1, "start_x": 10.0, "start_y": 20.0, "end_x": 10.0, "end_y": 40.0},
                {"wire_index": 2, "start_x": 50.0, "start_y": 50.0, "end_x": 60.0, "end_y": 50.0},
            ],
        )

        result = fix_net_short(
            ir, Path("test.kicad_sch"),
            net_a="ADC1_L", net_b="OUT_IN_CH1",
            remove_strategy="disconnect_a",
        )

        assert result["fixed"] is True
        assert result["action"] == "disconnect_a"
        assert result["wire_count"] == 2  # wires 0 and 1 touch ADC1_L label
        assert len(ir.schematic.graphicalItems) == 8  # 10 - 2 removed

    @patch("volta.ops.net_short_detector._export_and_parse_netlist")
    def test_disconnect_b_removes_wires(self, mock_netlist) -> None:
        mock_netlist.return_value = {
            "ADC1_L": {("U1", "1")},
            "OUT_IN_CH1": {("U1", "1")},
        }

        ir = self._make_mock_ir(
            label_positions=[
                {"name": "ADC1_L", "x": 10.0, "y": 20.0},
                {"name": "OUT_IN_CH1", "x": 10.0, "y": 40.0},
            ],
            wire_endpoints=[
                {"wire_index": 0, "start_x": 10.0, "start_y": 20.0, "end_x": 30.0, "end_y": 20.0},
                {"wire_index": 1, "start_x": 10.0, "start_y": 20.0, "end_x": 10.0, "end_y": 40.0},
                {"wire_index": 2, "start_x": 10.0, "start_y": 40.0, "end_x": 30.0, "end_y": 40.0},
            ],
        )

        result = fix_net_short(
            ir, Path("test.kicad_sch"),
            net_a="ADC1_L", net_b="OUT_IN_CH1",
            remove_strategy="disconnect_b",
        )

        assert result["fixed"] is True
        assert result["action"] == "disconnect_b"
        assert result["wire_count"] == 2  # wires 1 and 2 touch OUT_IN_CH1 label

    @patch("volta.ops.net_short_detector._export_and_parse_netlist")
    def test_disconnect_no_wires_for_net(self, mock_netlist) -> None:
        mock_netlist.return_value = {
            "SDA": {("U1", "5")},
            "SCL": {("U1", "5")},
        }

        ir = self._make_mock_ir(
            label_positions=[
                {"name": "SDA", "x": 10.0, "y": 20.0},
                {"name": "SCL", "x": 50.0, "y": 60.0},
            ],
            wire_endpoints=[
                {"wire_index": 0, "start_x": 50.0, "start_y": 60.0, "end_x": 70.0, "end_y": 60.0},
            ],
        )

        result = fix_net_short(
            ir, Path("test.kicad_sch"),
            net_a="SDA", net_b="SCL",
            remove_strategy="disconnect_a",
        )

        assert result["fixed"] is False
        assert result["action"] == "no_wires_found"

    @patch("volta.ops.net_short_detector._export_and_parse_netlist")
    @patch("volta.ops.repair_wires.find_bridge_wires")
    @patch("volta.ops.repair_nets._verify_clean_break")
    def test_skips_dirty_break(
        self, mock_verify, mock_find, mock_netlist,
    ) -> None:
        mock_netlist.return_value = {
            "SDA": {("U1", "5")},
            "SCL": {("U1", "5")},
        }
        mock_find.return_value = [
            {
                "wire_index": 3,
                "start": [10.0, 20.0],
                "end": [10.0, 40.0],
                "length": 20.0,
                "nets": ["SDA", "SCL"],
            },
        ]
        mock_verify.return_value = False  # dirty break

        ir = self._make_mock_ir(
            label_positions=[
                {"name": "SDA", "x": 10.0, "y": 20.0},
                {"name": "SCL", "x": 10.0, "y": 40.0},
            ],
            wire_endpoints=[
                {"wire_index": 3, "start_x": 10.0, "start_y": 20.0, "end_x": 10.0, "end_y": 40.0},
            ],
        )

        result = fix_net_short(
            ir, Path("test.kicad_sch"),
            net_a="SDA", net_b="SCL",
            remove_strategy="remove_wire",
        )

        assert result["fixed"] is False
        assert result["action"] == "no_action"
        assert len(ir.schematic.graphicalItems) == 10  # unchanged

    @patch("volta.ops.net_short_detector._export_and_parse_netlist")
    @patch("volta.ops.repair_wires.find_bridge_wires")
    @patch("volta.ops.repair_nets._verify_clean_break")
    def test_removes_in_reverse_order(
        self, mock_verify, mock_find, mock_netlist,
    ) -> None:
        """Multiple wires should be removed in reverse index order."""
        mock_netlist.return_value = {
            "SDA": {("U1", "5")},
            "SCL": {("U2", "3")},
        }
        mock_verify.return_value = True
        mock_find.return_value = [
            {"wire_index": 5, "start": [10.0, 20.0], "end": [10.0, 30.0], "length": 10.0, "nets": ["SDA", "SCL"]},
        ]

        ir = self._make_mock_ir(
            label_positions=[
                {"name": "SDA", "x": 10.0, "y": 20.0},
                {"name": "SCL", "x": 10.0, "y": 30.0},
            ],
            wire_endpoints=[
                {"wire_index": 5, "start_x": 10.0, "start_y": 20.0, "end_x": 10.0, "end_y": 30.0},
            ],
        )
        # Ensure 6 items so index 5 is valid
        ir.schematic.graphicalItems = [MagicMock()] * 6

        result = fix_net_short(
            ir, Path("test.kicad_sch"),
            net_a="SDA", net_b="SCL",
            remove_strategy="remove_wire",
        )

        assert result["fixed"] is True
        assert len(ir.schematic.graphicalItems) == 5  # 6 - 1 removed
