"""Tests for net_tracer -- per-label pin tracing through schematic graph.

Covers: pin-to-label assignment by nearest distance, boundary behavior,
far-pin threshold, schema validation, handler dispatch, and integration.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from kicad_agent.ops.net_tracer import (
    _assign_pins_to_labels,
    _MAX_LABEL_DISTANCE_MM,
    trace_net_from_label,
)
from kicad_agent.schematic_routing.schematic_graph import Label, PinPosition


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _pin(ref: str, pin_num: str, x: float = 10.0, y: float = 20.0,
        pin_name: str = "", electrical_type: str = "passive") -> PinPosition:
    return PinPosition(
        ref=ref, pin_number=pin_num, pin_name=pin_name,
        position=(x, y), body_position=(x, y),
        electrical_type=electrical_type,
    )


def _label(name: str, x: float, y: float, label_type: str = "global") -> Label:
    return Label(name=name, position=(x, y), label_type=label_type)


def _round(pos: tuple[float, float]) -> tuple[float, float]:
    return (round(pos[0], 2), round(pos[1], 2))


# ---------------------------------------------------------------------------
# _assign_pins_to_labels
# ---------------------------------------------------------------------------

class TestAssignPinsToLabels:
    """Tests for pin-to-label proximity assignment."""

    def test_single_pin_assigns_to_nearest_label(self) -> None:
        pin = _pin("R1", "1", 10.0, 20.0)
        label = _label("GND", 10.0, 30.0)
        pin_pos_map = {_round((10.0, 20.0)): [pin]}
        label_pos_map = {_round((10.0, 30.0)): label}
        label_pins, far_pins = _assign_pins_to_labels(
            pin_pos_map, label_pos_map,
            component_positions={_round((10.0, 20.0)), _round((10.0, 30.0))},
            target_label="GND",
        )
        assert "GND" in label_pins
        assert len(label_pins["GND"]) == 1

    def test_pin_assigns_to_nearest_of_multiple(self) -> None:
        pin = _pin("R1", "1", 10.0, 20.0)
        label_a = _label("GND", 10.0, 30.0)
        label_b = _label("AGND", 200.0, 200.0)
        pin_pos_map = {_round((10.0, 20.0)): [pin]}
        label_pos_map = {
            _round((10.0, 30.0)): label_a,
            _round((200.0, 200.0)): label_b,
        }
        label_pins, far_pins = _assign_pins_to_labels(
            pin_pos_map, label_pos_map,
            component_positions={
                _round((10.0, 20.0)), _round((10.0, 30.0)), _round((200.0, 200.0)),
            },
            target_label="GND",
        )
        assert len(label_pins["GND"]) == 1
        assert len(label_pins.get("AGND", [])) == 0

    def test_two_pins_assigned_to_different_labels(self) -> None:
        pin_a = _pin("R1", "1", 10.0, 20.0)
        pin_b = _pin("R2", "1", 200.0, 200.0)
        label_a = _label("GND", 15.0, 20.0)
        label_b = _label("AGND", 205.0, 200.0)
        pin_pos_map = {
            _round((10.0, 20.0)): [pin_a],
            _round((200.0, 200.0)): [pin_b],
        }
        label_pos_map = {
            _round((15.0, 20.0)): label_a,
            _round((205.0, 200.0)): label_b,
        }
        label_pins, far_pins = _assign_pins_to_labels(
            pin_pos_map, label_pos_map,
            component_positions={
                _round((10.0, 20.0)), _round((200.0, 200.0)),
                _round((15.0, 20.0)), _round((205.0, 200.0)),
            },
            target_label="GND",
        )
        assert len(label_pins["GND"]) == 1
        assert label_pins["GND"][0]["ref"] == "R1"
        assert len(label_pins["AGND"]) == 1
        assert label_pins["AGND"][0]["ref"] == "R2"

    def test_pin_far_from_all_labels_is_excluded(self) -> None:
        pin = _pin("R1", "1", 10.0, 20.0)
        label = _label("GND", 200.0, 200.0)  # 253mm away
        pin_pos_map = {_round((10.0, 20.0)): [pin]}
        label_pos_map = {_round((200.0, 200.0)): label}
        label_pins, far_pins = _assign_pins_to_labels(
            pin_pos_map, label_pos_map,
            component_positions={_round((10.0, 20.0)), _round((200.0, 200.0))},
            target_label="GND",
        )
        assert label_pins == {}
        assert len(far_pins) == 1  # pin too far, goes to far_pins

    def test_pin_just_within_threshold(self) -> None:
        """Pin exactly at _MAX_LABEL_DISTANCE_MM should be included."""
        pin = _pin("R1", "1", 0.0, 0.0)
        label = _label("GND", _MAX_LABEL_DISTANCE_MM, 0.0)
        pin_pos_map = {_round((0.0, 0.0)): [pin]}
        label_pos_map = {_round((_MAX_LABEL_DISTANCE_MM, 0.0)): label}
        label_pins, far_pins = _assign_pins_to_labels(
            pin_pos_map, label_pos_map,
            component_positions={_round((0.0, 0.0)), _round((_MAX_LABEL_DISTANCE_MM, 0.0))},
            target_label="GND",
        )
        assert "GND" in label_pins
        assert len(label_pins["GND"]) == 1

    def test_pin_just_beyond_threshold(self) -> None:
        """Pin just beyond _MAX_LABEL_DISTANCE_MM should be excluded."""
        pin = _pin("R1", "1", 0.0, 0.0)
        beyond = _MAX_LABEL_DISTANCE_MM + 0.1
        label = _label("GND", beyond, 0.0)
        pin_pos_map = {_round((0.0, 0.0)): [pin]}
        label_pos_map = {_round((beyond, 0.0)): label}
        label_pins, far_pins = _assign_pins_to_labels(
            pin_pos_map, label_pos_map,
            component_positions={_round((0.0, 0.0)), _round((beyond, 0.0))},
            target_label="GND",
        )
        assert label_pins == {}
        assert len(far_pins) == 1

    def test_label_type_filter(self) -> None:
        pin = _pin("R1", "1", 10.0, 20.0)
        local_label = _label("NET", 10.0, 30.0, label_type="local")
        global_label = _label("GND", 15.0, 20.0, label_type="global")
        pin_pos_map = {_round((10.0, 20.0)): [pin]}
        label_pos_map = {
            _round((10.0, 30.0)): local_label,
            _round((15.0, 20.0)): global_label,
        }
        label_pins, far_pins = _assign_pins_to_labels(
            pin_pos_map, label_pos_map,
            component_positions={_round((10.0, 20.0)), _round((10.0, 30.0)), _round((15.0, 20.0))},
            target_label="GND",
            label_type_filter="global",
        )
        assert "GND" in label_pins
        assert "NET" not in label_pins

    def test_empty_component_returns_empty(self) -> None:
        label_pins, far_pins = _assign_pins_to_labels({}, {}, set(), target_label="X")
        assert label_pins == {}
        assert far_pins == []

    def test_distance_recorded_in_pin_dict(self) -> None:
        pin = _pin("R1", "1", 10.0, 20.0)
        label = _label("GND", 15.0, 20.0)
        pin_pos_map = {_round((10.0, 20.0)): [pin]}
        label_pos_map = {_round((15.0, 20.0)): label}
        label_pins, far_pins = _assign_pins_to_labels(
            pin_pos_map, label_pos_map,
            component_positions={_round((10.0, 20.0)), _round((15.0, 20.0))},
            target_label="GND",
        )
        assert label_pins["GND"][0]["nearest_distance"] == 5.0
        assert label_pins["GND"][0]["nearest_label"] == "GND"


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------

class TestTraceNetFromLabelOpSchema:
    """Tests for TraceNetFromLabelOp Pydantic schema."""

    def test_default_fields(self) -> None:
        from kicad_agent.ops._schema_schematic_intel import TraceNetFromLabelOp
        op = TraceNetFromLabelOp(target_file="test.kicad_sch", label_name="GNDA")
        assert op.op_type == "trace_net_from_label"
        assert op.label_type == "all"
        assert op.stop_at_labels is True

    def test_all_fields(self) -> None:
        from kicad_agent.ops._schema_schematic_intel import TraceNetFromLabelOp
        op = TraceNetFromLabelOp(
            target_file="test.kicad_sch", label_name="GNDA",
            label_type="global", stop_at_labels=False,
        )
        assert op.label_type == "global"
        assert op.stop_at_labels is False

    @pytest.mark.parametrize("lt", ["label", "global", "hierarchical", "all"])
    def test_valid_label_types(self, lt: str) -> None:
        from kicad_agent.ops._schema_schematic_intel import TraceNetFromLabelOp
        op = TraceNetFromLabelOp(target_file="t.kicad_sch", label_name="X", label_type=lt)
        assert op.label_type == lt

    def test_empty_label_rejected(self) -> None:
        from kicad_agent.ops._schema_schematic_intel import TraceNetFromLabelOp
        import pydantic
        with pytest.raises(pydantic.ValidationError):
            TraceNetFromLabelOp(target_file="t.kicad_sch", label_name="")

    def test_path_traversal_rejected(self) -> None:
        from kicad_agent.ops._schema_schematic_intel import TraceNetFromLabelOp
        import pydantic
        with pytest.raises(pydantic.ValidationError):
            TraceNetFromLabelOp(target_file="../etc/passwd", label_name="X")


# ---------------------------------------------------------------------------
# Handler dispatch
# ---------------------------------------------------------------------------

class TestHandlerDispatch:
    """Tests for handler registration."""

    def test_handler_registered(self) -> None:
        from kicad_agent.ops.handlers.schematic_query import _SCHEMATIC_QUERY_HANDLERS
        assert "trace_net_from_label" in _SCHEMATIC_QUERY_HANDLERS


# ---------------------------------------------------------------------------
# Integration (mocked SchematicGraph + union-find)
# ---------------------------------------------------------------------------

class TestTraceNetFromLabelIntegration:
    """Integration tests with mocked SchematicGraph and union-find data."""

    @staticmethod
    def _make_uf_and_maps(
        pins: list[PinPosition],
        labels: list[Label],
        all_positions: set[tuple[float, float]],
    ) -> tuple[MagicMock, set[tuple[float, float]], dict, dict]:
        """Build a mock union-find where all positions are in one component."""
        from kicad_agent.schematic_routing.net_extractor import _UnionFind

        uf = _UnionFind()
        for pos in all_positions:
            uf.make_set(pos)
        positions_list = list(all_positions)
        for i in range(1, len(positions_list)):
            uf.union(positions_list[0], positions_list[i])

        pin_pos_map: dict[tuple[float, float], list[PinPosition]] = {}
        for pin in pins:
            key = _round(pin.position)
            pin_pos_map.setdefault(key, []).append(pin)

        label_pos_map: dict[tuple[float, float], Label] = {}
        for label in labels:
            key = _round(label.position)
            label_pos_map[key] = label

        return uf, all_positions, pin_pos_map, label_pos_map

    @patch("kicad_agent.ops.ground_topology._classify_ground_domain")
    @patch("kicad_agent.ops.net_tracer._build_union_find_components")
    @patch("kicad_agent.ops.net_tracer.SchematicGraph")
    def test_single_label_no_shorts(
        self, mock_graph_cls: MagicMock, mock_build: MagicMock,
        mock_domain: MagicMock,
    ) -> None:
        mock_graph = MagicMock()
        mock_graph.pins = []
        mock_graph.labels = []
        mock_graph.wires = []
        mock_graph.junctions = set()
        mock_graph_cls.from_file.return_value = mock_graph
        mock_domain.return_value = "analog"

        pin = _pin("R1", "1", 50.0, 60.0)
        label = _label("GND", 50.0, 70.0)
        positions = {_round((50.0, 60.0)), _round((50.0, 70.0))}
        uf, _, pin_pos_map, label_pos_map = self._make_uf_and_maps(
            [pin], [label], positions,
        )
        mock_build.return_value = (uf, positions, pin_pos_map, label_pos_map)

        result = trace_net_from_label(Path("test.kicad_sch"), label_name="GND")
        assert result["label"] == "GND"
        assert result["pin_count"] == 1
        assert result["reachable_pins"][0]["ref"] == "R1"
        assert result["blocked_by"] == []

    @patch("kicad_agent.ops.ground_topology._classify_ground_domain")
    @patch("kicad_agent.ops.net_tracer._build_union_find_components")
    @patch("kicad_agent.ops.net_tracer.SchematicGraph")
    def test_shorted_labels_with_boundary(
        self, mock_graph_cls: MagicMock, mock_build: MagicMock,
        mock_domain: MagicMock,
    ) -> None:
        mock_graph = MagicMock()
        mock_graph.pins = []
        mock_graph.labels = []
        mock_graph.wires = []
        mock_graph.junctions = set()
        mock_graph_cls.from_file.return_value = mock_graph
        mock_domain.return_value = "analog"

        pin_a = _pin("U1", "4", 50.0, 60.0)
        pin_b = _pin("U20", "1", 200.0, 60.0)
        label_a = _label("GNDA", 50.0, 80.0)
        label_b = _label("AGND", 200.0, 80.0)
        positions = {
            _round((50.0, 60.0)), _round((200.0, 60.0)),
            _round((50.0, 80.0)), _round((200.0, 80.0)),
        }
        uf, _, pin_pos_map, label_pos_map = self._make_uf_and_maps(
            [pin_a, pin_b], [label_a, label_b], positions,
        )
        mock_build.return_value = (uf, positions, pin_pos_map, label_pos_map)

        result = trace_net_from_label(Path("test.kicad_sch"), label_name="GNDA")
        assert result["label"] == "GNDA"
        assert result["pin_count"] == 1
        assert result["reachable_pins"][0]["ref"] == "U1"
        assert "AGND" in result["blocked_by"]
        # U20 pin assigned to AGND → goes to far_pins
        assert result["far_pin_count"] == 1
        assert result["far_pins"][0]["ref"] == "U20"

    @patch("kicad_agent.ops.ground_topology._classify_ground_domain")
    @patch("kicad_agent.ops.net_tracer._build_union_find_components")
    @patch("kicad_agent.ops.net_tracer.SchematicGraph")
    def test_label_not_found(
        self, mock_graph_cls: MagicMock, mock_build: MagicMock,
        mock_domain: MagicMock,
    ) -> None:
        mock_graph = MagicMock()
        mock_graph.pins = []
        mock_graph.labels = []
        mock_graph.wires = []
        mock_graph.junctions = set()
        mock_graph_cls.from_file.return_value = mock_graph
        mock_domain.return_value = "unknown"

        label = _label("OTHER", 10.0, 20.0)
        positions = {_round((10.0, 20.0))}
        uf, _, pin_pos_map, label_pos_map = self._make_uf_and_maps(
            [], [label], positions,
        )
        mock_build.return_value = (uf, positions, pin_pos_map, label_pos_map)

        result = trace_net_from_label(Path("test.kicad_sch"), label_name="MISSING")
        assert result["label"] == "MISSING"
        assert result["pin_count"] == 0

    @patch("kicad_agent.ops.ground_topology._classify_ground_domain")
    @patch("kicad_agent.ops.net_tracer._build_union_find_components")
    @patch("kicad_agent.ops.net_tracer.SchematicGraph")
    def test_stop_at_labels_false_returns_all(
        self, mock_graph_cls: MagicMock, mock_build: MagicMock,
        mock_domain: MagicMock,
    ) -> None:
        mock_graph = MagicMock()
        mock_graph.pins = []
        mock_graph.labels = []
        mock_graph.wires = []
        mock_graph.junctions = set()
        mock_graph_cls.from_file.return_value = mock_graph
        mock_domain.return_value = "analog"

        pin_a = _pin("U1", "4", 50.0, 60.0)
        pin_b = _pin("U20", "1", 200.0, 60.0)
        label_a = _label("GNDA", 50.0, 80.0)
        label_b = _label("AGND", 200.0, 80.0)
        positions = {
            _round((50.0, 60.0)), _round((200.0, 60.0)),
            _round((50.0, 80.0)), _round((200.0, 80.0)),
        }
        uf, _, pin_pos_map, label_pos_map = self._make_uf_and_maps(
            [pin_a, pin_b], [label_a, label_b], positions,
        )
        mock_build.return_value = (uf, positions, pin_pos_map, label_pos_map)

        result = trace_net_from_label(
            Path("test.kicad_sch"), label_name="GNDA", stop_at_labels=False,
        )
        assert result["pin_count"] == 2
        assert "AGND" in result["blocked_by"]  # still lists labels in component
        assert result["far_pin_count"] == 0  # no far pins when stop_at_labels=False

    @patch("kicad_agent.ops.ground_topology._classify_ground_domain")
    @patch("kicad_agent.ops.net_tracer._build_union_find_components")
    @patch("kicad_agent.ops.net_tracer.SchematicGraph")
    def test_far_pins_assigned_to_other_labels(
        self, mock_graph_cls: MagicMock, mock_build: MagicMock,
        mock_domain: MagicMock,
    ) -> None:
        """Pins assigned to other labels in the shorted component go to far_pins."""
        mock_graph = MagicMock()
        mock_graph.pins = []
        mock_graph.labels = []
        mock_graph.wires = []
        mock_graph.junctions = set()
        mock_graph_cls.from_file.return_value = mock_graph
        mock_domain.return_value = "passive_only"

        pin_close = _pin("R1", "1", 50.0, 60.0)
        pin_other = _pin("R20", "1", 200.0, 60.0)
        label_a = _label("GNDA", 50.0, 80.0)
        label_b = _label("AGND", 200.0, 80.0)
        positions = {
            _round((50.0, 60.0)), _round((200.0, 60.0)),
            _round((50.0, 80.0)), _round((200.0, 80.0)),
        }
        uf, _, pin_pos_map, label_pos_map = self._make_uf_and_maps(
            [pin_close, pin_other], [label_a, label_b], positions,
        )
        mock_build.return_value = (uf, positions, pin_pos_map, label_pos_map)

        result = trace_net_from_label(
            Path("test.kicad_sch"), label_name="GNDA", stop_at_labels=True,
        )
        assert result["pin_count"] == 1  # only R1 assigned to GNDA
        assert result["reachable_pins"][0]["ref"] == "R1"
        assert result["far_pin_count"] == 1  # R20 assigned to AGND
        assert result["far_pins"][0]["ref"] == "R20"
