"""Tests for schematic graph analysis (schematic_graph.py).

Covers:
  - SchematicGraph dataclass construction and default values
  - Wire, PinPosition, Label dataclass construction
  - _round_pos utility function
  - SchematicGraph connectivity queries (get_connection_targets, is_connected)
  - trace_endpoint_to_net resolution via labels and pins
  - Edge cases: empty graph, missing wires, disconnected endpoints
  - _find_lib_symbols_range parsing helper
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

import pytest

from kicad_agent.schematic_routing.schematic_graph import (
    Label,
    PinPosition,
    Pos,
    SchematicGraph,
    SheetRef,
    Wire,
    _find_lib_symbols_range,
    _parse_junctions,
    _parse_labels,
    _parse_no_connects,
    _parse_sheet_refs,
    _parse_wires,
    _round_pos,
)


class TestRoundPos:
    """Tests for the _round_pos position normalization utility."""

    def test_rounds_two_decimals(self) -> None:
        assert _round_pos((1.234, 5.678)) == (1.23, 5.68)

    def test_rounds_exact_values(self) -> None:
        assert _round_pos((10.0, 20.0)) == (10.0, 20.0)

    def test_rounds_negative(self) -> None:
        assert _round_pos((-1.111, -2.222)) == (-1.11, -2.22)

    def test_zero(self) -> None:
        assert _round_pos((0.0, 0.0)) == (0.0, 0.0)


class TestWireDataclass:
    """Tests for Wire dataclass construction."""

    def test_construction(self) -> None:
        wire = Wire(start=(0.0, 0.0), end=(10.0, 5.0))
        assert wire.start == (0.0, 0.0)
        assert wire.end == (10.0, 5.0)
        assert wire.file_offset == 0
        assert wire.length == 0

    def test_with_offset_and_length(self) -> None:
        wire = Wire(start=(1.0, 2.0), end=(3.0, 4.0), file_offset=100, length=50)
        assert wire.file_offset == 100
        assert wire.length == 50


class TestPinPositionDataclass:
    """Tests for PinPosition dataclass construction."""

    def test_construction_defaults(self) -> None:
        pin = PinPosition(
            ref="U1", pin_number="1", pin_name="A",
            position=(10.0, 20.0), body_position=(10.0, 18.0),
        )
        assert pin.electrical_type == "passive"
        assert pin.ref == "U1"

    def test_custom_electrical_type(self) -> None:
        pin = PinPosition(
            ref="U1", pin_number="1", pin_name="OUT",
            position=(10.0, 20.0), body_position=(10.0, 18.0),
            electrical_type="output",
        )
        assert pin.electrical_type == "output"


class TestLabelDataclass:
    """Tests for Label dataclass construction."""

    def test_global_label(self) -> None:
        label = Label(name="VCC", position=(50.0, 60.0), label_type="global")
        assert label.name == "VCC"
        assert label.label_type == "global"

    def test_local_label(self) -> None:
        label = Label(name="SDA", position=(30.0, 40.0), label_type="local")
        assert label.label_type == "local"


class TestSchematicGraphDefaults:
    """Tests for SchematicGraph default construction."""

    def test_empty_graph(self) -> None:
        graph = SchematicGraph()
        assert graph.wires == []
        assert graph.pins == []
        assert graph.labels == []
        assert graph.junctions == set()
        assert graph.no_connects == set()
        assert graph.ref_to_libid == {}

    def test_empty_graph_connection_targets(self) -> None:
        graph = SchematicGraph()
        targets = graph.get_connection_targets()
        assert targets == set()

    def test_empty_graph_not_connected(self) -> None:
        graph = SchematicGraph()
        assert graph.is_connected((10.0, 20.0)) is False

    def test_empty_graph_trace_returns_none(self) -> None:
        graph = SchematicGraph()
        result = graph.trace_endpoint_to_net((10.0, 20.0), {})
        assert result is None

    def test_empty_graph_sheet_refs(self) -> None:
        graph = SchematicGraph()
        assert graph.get_sheet_refs() == set()

    def test_empty_graph_no_wire(self) -> None:
        graph = SchematicGraph()
        assert graph.find_wire_at((10.0, 20.0)) is None


class TestSchematicGraphWithElements:
    """Tests for SchematicGraph populated with wires, pins, labels, junctions."""

    def _build_graph(self) -> SchematicGraph:
        """Build a small graph with two connected wires and a label."""
        graph = SchematicGraph()
        graph.wires = [
            Wire(start=(0.0, 0.0), end=(10.0, 0.0)),
            Wire(start=(10.0, 0.0), end=(20.0, 0.0)),
        ]
        graph._build_wire_endpoint_index()
        graph.labels = [Label(name="VCC", position=(20.0, 0.0), label_type="global")]
        for label in graph.labels:
            graph._label_pos_index[_round_pos(label.position)] = label
        return graph

    def test_connection_targets_includes_labels_only(self) -> None:
        """get_connection_targets only returns pin, label, junction positions."""
        graph = self._build_graph()
        targets = graph.get_connection_targets()
        # Wire endpoints alone are NOT targets -- only labels/pins/junctions
        assert (0.0, 0.0) not in targets
        assert (10.0, 0.0) not in targets
        # The label at (20,0) IS a target
        assert (20.0, 0.0) in targets

    def test_shared_endpoint_is_connected(self) -> None:
        graph = self._build_graph()
        # (10, 0) is shared by two wires -- junction-like connection
        assert graph.is_connected((10.0, 0.0)) is True

    def test_unshared_endpoint_not_connected(self) -> None:
        graph = self._build_graph()
        # (0, 0) only has one wire -- not a junction
        assert graph.is_connected((0.0, 0.0)) is False

    def test_label_position_is_connected(self) -> None:
        graph = self._build_graph()
        assert graph.is_connected((20.0, 0.0)) is True

    def test_trace_to_label(self) -> None:
        graph = self._build_graph()
        net = graph.trace_endpoint_to_net((0.0, 0.0), {})
        assert net == "VCC"

    def test_trace_disconnected_returns_none(self) -> None:
        graph = self._build_graph()
        net = graph.trace_endpoint_to_net((100.0, 100.0), {})
        assert net is None

    def test_find_wire_at(self) -> None:
        graph = self._build_graph()
        wire = graph.find_wire_at((0.0, 0.0))
        assert wire is not None
        assert wire.start == (0.0, 0.0)

    def test_find_wire_at_missing(self) -> None:
        graph = self._build_graph()
        assert graph.find_wire_at((100.0, 100.0)) is None


class TestSchematicGraphWithPins:
    """Tests for graph pin connectivity and net tracing."""

    def _build_graph_with_pin(self) -> SchematicGraph:
        graph = SchematicGraph()
        graph.wires = [
            Wire(start=(0.0, 0.0), end=(10.0, 0.0)),
        ]
        graph._build_wire_endpoint_index()
        graph.pins = [
            PinPosition(
                ref="U1", pin_number="1", pin_name="CLK",
                position=(10.0, 0.0), body_position=(10.0, -2.54),
            ),
        ]
        for pin in graph.pins:
            graph._pin_pos_index[_round_pos(pin.position)] = pin
        return graph

    def test_pin_is_connected(self) -> None:
        graph = self._build_graph_with_pin()
        assert graph.is_connected((10.0, 0.0)) is True

    def test_pin_in_connection_targets(self) -> None:
        graph = self._build_graph_with_pin()
        targets = graph.get_connection_targets()
        assert (10.0, 0.0) in targets

    def test_trace_to_pin_via_index(self) -> None:
        graph = self._build_graph_with_pin()
        pin_index = {("U1", "1"): "CLK_NET"}
        net = graph.trace_endpoint_to_net((0.0, 0.0), pin_index)
        assert net == "CLK_NET"

    def test_trace_to_pin_missing_index_returns_none(self) -> None:
        graph = self._build_graph_with_pin()
        net = graph.trace_endpoint_to_net((0.0, 0.0), {})
        assert net is None


class TestParseHelpers:
    """Tests for standalone parsing helper functions."""

    def test_find_lib_symbols_range_present(self) -> None:
        content = "prefix(lib_symbols (sym1))(sym2))(body)"
        start, end = _find_lib_symbols_range(content)
        assert start == 6
        assert end > start

    def test_find_lib_symbols_range_missing(self) -> None:
        content = "no lib_symbols here"
        start, end = _find_lib_symbols_range(content)
        assert start == 0
        assert end == 0

    def test_parse_wires_extracts_correctly(self) -> None:
        body = '(wire (pts (xy 10.0 20.0) (xy 30.0 40.0)) (width 0.25))'
        wires = _parse_wires(body)
        assert len(wires) == 1
        assert wires[0].start == (10.0, 20.0)
        assert wires[0].end == (30.0, 40.0)

    def test_parse_wires_empty_body(self) -> None:
        wires = _parse_wires("no wires here")
        assert wires == []

    def test_parse_junctions(self) -> None:
        body = '(junction (at 15.5 25.5)) other stuff'
        junctions = _parse_junctions(body)
        assert (15.5, 25.5) in junctions

    def test_parse_junctions_empty(self) -> None:
        assert _parse_junctions("no junctions") == set()

    def test_parse_no_connects(self) -> None:
        body = '(no_connect (at 5.0 10.0)) end'
        nc = _parse_no_connects(body)
        assert (5.0, 10.0) in nc

    def test_parse_no_connects_empty(self) -> None:
        assert _parse_no_connects("no no_connects") == set()


class TestSchematicGraphJunctionBFS:
    """Tests for BFS tracing through junction points."""

    def test_bfs_through_junction(self) -> None:
        """Wire A -> junction point -> Wire B -> label."""
        graph = SchematicGraph()
        graph.wires = [
            Wire(start=(0.0, 0.0), end=(10.0, 0.0)),
            Wire(start=(10.0, 0.0), end=(20.0, 0.0)),
        ]
        graph._build_wire_endpoint_index()
        graph.junctions = {(10.0, 0.0)}
        graph.labels = [Label(name="OUT", position=(20.0, 0.0), label_type="global")]
        for label in graph.labels:
            graph._label_pos_index[_round_pos(label.position)] = label

        net = graph.trace_endpoint_to_net((0.0, 0.0), {})
        assert net == "OUT"


class TestSheetPinParsing:
    """Tests for R-BUG-007: hierarchical sheet pin support."""

    def test_sheet_pins_parsed_as_hierarchical_labels(self) -> None:
        """Sheet pins are parsed and appear in labels list as hierarchical type."""
        body = """
        (wire (pts (xy 50 100) (xy 100 100)))
        (sheet_pin "AUDIO_IN" (at 100 100 0)
          (effects (font (size 1.27 1.27)))
        )
        """
        labels = _parse_labels(body)
        sheet_pin_labels = [l for l in labels if l.name == "AUDIO_IN" and l.label_type == "hierarchical"]
        assert len(sheet_pin_labels) == 1, f"Expected 1 sheet_pin label, got {len(sheet_pin_labels)}"
        assert sheet_pin_labels[0].position == (100.0, 100.0)

    def test_sheet_pin_in_connection_targets(self) -> None:
        """Sheet pin positions appear as connection targets for wire routing."""
        graph = SchematicGraph()
        graph.wires = [Wire(start=(50.0, 100.0), end=(100.0, 100.0))]
        graph._build_wire_endpoint_index()
        graph.labels = [
            Label(name="AUDIO_IN", position=(100.0, 100.0), label_type="hierarchical"),
        ]
        for label in graph.labels:
            graph._label_pos_index[_round_pos(label.position)] = label

        targets = graph.get_connection_targets()
        assert (100.0, 100.0) in targets

    def test_wire_connects_to_sheet_pin(self) -> None:
        """A wire endpoint at a sheet pin position is traced to the sheet pin name."""
        graph = SchematicGraph()
        graph.wires = [Wire(start=(50.0, 100.0), end=(100.0, 100.0))]
        graph._build_wire_endpoint_index()
        graph.labels = [
            Label(name="AUDIO_IN", position=(100.0, 100.0), label_type="hierarchical"),
        ]
        for label in graph.labels:
            graph._label_pos_index[_round_pos(label.position)] = label

        # Trace from the wire start to the sheet pin
        net = graph.trace_endpoint_to_net((50.0, 100.0), {})
        assert net == "AUDIO_IN"

    def test_no_sheet_pins_when_none_present(self) -> None:
        """_parse_labels returns empty when no sheet pins exist."""
        labels = _parse_labels("(wire (pts (xy 10 20) (xy 30 40)))")
        sheet_pin_labels = [l for l in labels if l.label_type == "hierarchical"]
        assert len(sheet_pin_labels) == 0


class TestSheetRefUuidParsing:
    """Tests for CR-01 (Phase 102.1): _parse_sheet_refs accepts both KiCad 10
    unquoted UUIDs and legacy quoted UUIDs. Without this, SheetRef.uuid is
    empty for all KiCad 10 fixtures, breaking EXEC-03 sort tie-break."""

    def test_unquoted_uuid_extracted_kicad10(self) -> None:
        """KiCad 10 form (uuid aaaa-...) is parsed, not returned as empty."""
        body = """
        (sheet (at 100 100) (size 50 20)
          (uuid bbbbbbbb-0001-0000-0000-000000000001)
          (property "Sheetname" "Child A" (at 100 97.5 0))
          (property "Sheetfile" "child_a.kicad_sch" (at 100 125 0))
        )
        """
        refs = _parse_sheet_refs(body)
        assert len(refs) == 1
        assert refs[0].uuid == "bbbbbbbb-0001-0000-0000-000000000001"
        assert refs[0].name == "Child A"
        assert refs[0].filepath == "child_a.kicad_sch"

    def test_quoted_uuid_extracted_legacy(self) -> None:
        """Legacy quoted form (uuid "aaaa-...") still works (backward compat)."""
        body = """
        (sheet (at 100 100) (size 50 20)
          (uuid "cccccccc-0002-0000-0000-000000000002")
          (property "Sheetname" "Child B" (at 100 97.5 0))
          (property "Sheetfile" "child_b.kicad_sch" (at 100 125 0))
        )
        """
        refs = _parse_sheet_refs(body)
        assert len(refs) == 1
        assert refs[0].uuid == "cccccccc-0002-0000-0000-000000000002"

    def test_no_uuid_returns_empty_string(self) -> None:
        """Sheet block without a UUID returns empty string (no crash)."""
        body = """
        (sheet (at 100 100) (size 50 20)
          (property "Sheetname" "Orphan" (at 100 97.5 0))
          (property "Sheetfile" "orphan.kicad_sch" (at 100 125 0))
        )
        """
        refs = _parse_sheet_refs(body)
        assert len(refs) == 1
        assert refs[0].uuid == ""

    def test_multiple_sheets_each_get_own_uuid(self) -> None:
        """Two sheets in a root file each get their own UUID (not shared)."""
        body = """
        (sheet (at 100 100) (size 50 20)
          (uuid dddddddd-0001-0000-0000-000000000001)
          (property "Sheetname" "First" (at 100 97.5 0))
          (property "Sheetfile" "first.kicad_sch" (at 100 125 0))
        )
        (sheet (at 200 100) (size 50 20)
          (uuid dddddddd-0002-0000-0000-000000000002)
          (property "Sheetname" "Second" (at 200 97.5 0))
          (property "Sheetfile" "second.kicad_sch" (at 200 125 0))
        )
        """
        refs = _parse_sheet_refs(body)
        assert len(refs) == 2
        uuids = {r.uuid for r in refs}
        assert uuids == {
            "dddddddd-0001-0000-0000-000000000001",
            "dddddddd-0002-0000-0000-000000000002",
        }

