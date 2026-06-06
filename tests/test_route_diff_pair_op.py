"""Tests for route_diff_pair operation (#44)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError


class TestRouteDiffPairOpSchema:
    """Schema validation tests for RouteDiffPairOp."""

    def test_valid_minimal(self):
        from kicad_agent.ops._schema_pcb import RouteDiffPairOp

        op = RouteDiffPairOp(
            target_file="board.kicad_pcb",
            net_positive="USB_D+",
            net_negative="USB_D-",
        )
        assert op.op_type == "route_diff_pair"
        assert op.net_positive == "USB_D+"
        assert op.net_negative == "USB_D-"
        assert op.spacing_mm == 0.15
        assert op.impedance_target is None
        assert op.layer == "F.Cu"
        assert op.max_length_mismatch_mm == 0.5

    def test_valid_full(self):
        from kicad_agent.ops._schema_pcb import RouteDiffPairOp

        op = RouteDiffPairOp(
            target_file="board.kicad_pcb",
            net_positive="USB_D+",
            net_negative="USB_D-",
            spacing_mm=0.20,
            impedance_target=90.0,
            layer="B.Cu",
            via_layers=["F.Cu", "B.Cu"],
            max_length_mismatch_mm=0.25,
            dielectric_height_mm=0.15,
            dielectric_er=4.2,
            copper_thickness_mm=0.025,
            trace_width_mm=0.10,
        )
        assert op.impedance_target == 90.0
        assert op.via_layers == ["F.Cu", "B.Cu"]
        assert op.trace_width_mm == 0.10

    def test_invalid_spacing_too_small(self):
        from kicad_agent.ops._schema_pcb import RouteDiffPairOp

        with pytest.raises(ValidationError):
            RouteDiffPairOp(
                target_file="board.kicad_pcb",
                net_positive="D+",
                net_negative="D-",
                spacing_mm=0.01,
            )

    def test_invalid_impedance_out_of_range(self):
        from kicad_agent.ops._schema_pcb import RouteDiffPairOp

        with pytest.raises(ValidationError):
            RouteDiffPairOp(
                target_file="board.kicad_pcb",
                net_positive="D+",
                net_negative="D-",
                impedance_target=5.0,
            )

    def test_invalid_layer(self):
        from kicad_agent.ops._schema_pcb import RouteDiffPairOp

        with pytest.raises(ValidationError):
            RouteDiffPairOp(
                target_file="board.kicad_pcb",
                net_positive="D+",
                net_negative="D-",
                layer="Invalid.Cu",
            )

    def test_invalid_via_layers(self):
        from kicad_agent.ops._schema_pcb import RouteDiffPairOp

        with pytest.raises(ValidationError):
            RouteDiffPairOp(
                target_file="board.kicad_pcb",
                net_positive="D+",
                net_negative="D-",
                via_layers=["F.Cu", "BadLayer"],
            )

    def test_registry_entry_exists(self):
        from kicad_agent.ops.registry import OPERATION_REGISTRY

        assert "route_diff_pair" in OPERATION_REGISTRY
        meta = OPERATION_REGISTRY["route_diff_pair"]
        assert meta.category == "pcb"
        assert ".kicad_pcb" in meta.file_types
        assert meta.is_readonly is False

    def test_discriminated_union_accepts(self):
        from kicad_agent.ops.schema import Operation

        op = Operation.model_validate({
            "root": {
                "op_type": "route_diff_pair",
                "target_file": "board.kicad_pcb",
                "net_positive": "D+",
                "net_negative": "D-",
            },
        })
        assert op.root.op_type == "route_diff_pair"
