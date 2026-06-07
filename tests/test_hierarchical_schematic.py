"""Tests for hierarchical schematic parsing (#72).

Covers: _parse_sheet_refs, _extract_sexp_block, from_hierarchy,
multi-sheet trace_net_from_label, edge cases (missing file, max depth,
circular refs, single-sheet regression).
"""

from __future__ import annotations

import textwrap
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from kicad_agent.schematic_routing.schematic_graph import (
    HierarchicalSchematic,
    SchematicGraph,
    SheetPin,
    SheetRef,
    _extract_sexp_block,
    _parse_sheet_refs,
)
from kicad_agent.ops.net_tracer import (
    _merge_trace_results,
    trace_net_from_label,
)


# ---------------------------------------------------------------------------
# _extract_sexp_block
# ---------------------------------------------------------------------------

class TestExtractSexpBlock:
    """Tests for balanced-parenthesis block extraction."""

    def test_finds_single_block(self) -> None:
        body = "(sheet\n  (at 10 20)\n  (size 30 7.62)\n)"
        blocks = _extract_sexp_block(body, r"\(sheet\s")
        assert len(blocks) == 1
        assert body[blocks[0][0]:blocks[0][1]] == body

    def test_finds_multiple_blocks(self) -> None:
        body = "(sheet A)(sheet B)"
        blocks = _extract_sexp_block(body, r"\(sheet\s")
        assert len(blocks) == 2
        assert body[blocks[0][0]:blocks[0][1]] == "(sheet A)"
        assert body[blocks[0][1]:blocks[0][1] + 9] == "(sheet B)"

    def test_nested_parens_balanced(self) -> None:
        body = "(sheet (at 10 20) (pin \"X\" input (at 30 40 0)))"
        blocks = _extract_sexp_block(body, r"\(sheet\s")
        assert len(blocks) == 1
        assert body[blocks[0][0]:blocks[0][1]] == body

    def test_no_match_returns_empty(self) -> None:
        blocks = _extract_sexp_block("no sheet blocks here", r"\(sheet\s")
        assert blocks == []

    def test_unmatched_open_returns_empty(self) -> None:
        blocks = _extract_sexp_block("(sheet (nested", r"\(sheet\s")
        # Unbalanced — should not return a block
        assert blocks == []

    def test_ignores_parens_after_close(self) -> None:
        body = "(sheet A)(other (nested))"
        blocks = _extract_sexp_block(body, r"\(sheet\s")
        assert len(blocks) == 1
        assert body[blocks[0][0]:blocks[0][1]] == "(sheet A)"


# ---------------------------------------------------------------------------
# _parse_sheet_refs
# ---------------------------------------------------------------------------

SHEET_BLOCK_SINGLE = textwrap.dedent("""\
    (sheet
      (at 30.48 199.39)
      (size 30 7.62)
      (uuid "31a542cc-1234-5678-abcd-ef0123456789")
      (property "Sheetname" "EQ Stage" (at 0 0 0)
        (effects (font (size 1.27 1.27))))
      (property "Sheetfile" "eq-stage.kicad_sch" (at 0 0 0)
        (effects (font (size 1.27 1.27))))
      (pin "ADC1_L" output (at 60.48 201.93 0)
        (uuid "aaaa-1111"))
      (pin "EQ_IN" bidirectional (at 33.02 199.39 90)
        (uuid "bbbb-2222"))
    )
""")

SHEET_BLOCK_MULTI = textwrap.dedent("""\
    (sheet
      (at 100 200)
      (size 25 10)
      (uuid "uuid-child-1")
      (property "Sheetname" "Input Stage" (at 0 0 0)
        (effects (font (size 1.27 1.27))))
      (property "Sheetfile" "input-stage.kicad_sch" (at 0 0 0)
        (effects (font (size 1.27 1.27))))
      (pin "SIG_IN" input (at 110 205 0)
        (uuid "pin-uuid-1"))
    )
    (sheet
      (at 200 200)
      (size 25 10)
      (uuid "uuid-child-2")
      (property "Sheetname" "Preamp Stage" (at 0 0 0)
        (effects (font (size 1.27 1.27))))
      (property "Sheetfile" "preamp-stage.kicad_sch" (at 0 0 0)
        (effects (font (size 1.27 1.27))))
      (pin "SIG_OUT" output (at 210 205 0)
        (uuid "pin-uuid-2"))
    )
""")


class TestParseSheetRefs:
    """Tests for (sheet ...) block parsing."""

    def test_single_sheet_ref(self) -> None:
        refs = _parse_sheet_refs(SHEET_BLOCK_SINGLE)
        assert len(refs) == 1
        ref = refs[0]
        assert ref.name == "EQ Stage"
        assert ref.filepath == "eq-stage.kicad_sch"
        assert ref.uuid == "31a542cc-1234-5678-abcd-ef0123456789"
        assert ref.position == (30.48, 199.39)
        assert ref.size == (30.0, 7.62)
        assert len(ref.pins) == 2

    def test_pin_details(self) -> None:
        refs = _parse_sheet_refs(SHEET_BLOCK_SINGLE)
        pin = refs[0].pins[0]
        assert pin.name == "ADC1_L"
        assert pin.direction == "output"
        assert pin.position == (60.48, 201.93)
        assert pin.angle == 0.0

    def test_second_pin(self) -> None:
        refs = _parse_sheet_refs(SHEET_BLOCK_SINGLE)
        pin = refs[0].pins[1]
        assert pin.name == "EQ_IN"
        assert pin.direction == "bidirectional"
        assert pin.angle == 90.0

    def test_multiple_sheet_refs(self) -> None:
        refs = _parse_sheet_refs(SHEET_BLOCK_MULTI)
        assert len(refs) == 2
        assert refs[0].name == "Input Stage"
        assert refs[0].filepath == "input-stage.kicad_sch"
        assert refs[1].name == "Preamp Stage"
        assert refs[1].filepath == "preamp-stage.kicad_sch"

    def test_empty_body(self) -> None:
        refs = _parse_sheet_refs("")
        assert refs == []

    def test_no_sheet_blocks(self) -> None:
        refs = _parse_sheet_refs("(wire (pts (xy 10 20))(xy 30 40)))")
        assert refs == []


# ---------------------------------------------------------------------------
# from_hierarchy (with temp files)
# ---------------------------------------------------------------------------

def _make_minimal_sch(name: str, extra_body: str = "") -> str:
    """Create a minimal .kicad_sch content string."""
    return textwrap.dedent(f"""\
    (kicad_sch (version 20231120) (generator "kicad-cli"))

    (lib_symbols)

    {extra_body}
    """)


def _sheet_block(name: str, filepath: str) -> str:
    return textwrap.dedent(f"""\
    (sheet
      (at 50 100)
      (size 30 7.62)
      (uuid "test-uuid-{name}")
      (property "Sheetname" "{name}" (at 0 0 0)
        (effects (font (size 1.27 1.27))))
      (property "Sheetfile" "{filepath}" (at 0 0 0)
        (effects (font (size 1.27 1.27))))
    )
    """)


class TestFromHierarchy:
    """Tests for SchematicGraph.from_hierarchy with temp files."""

    def test_single_sheet_no_children(self, tmp_path: Path) -> None:
        root = tmp_path / "root.kicad_sch"
        root.write_text(_make_minimal_sch("root"))
        hier = SchematicGraph.from_hierarchy(root)
        assert isinstance(hier, HierarchicalSchematic)
        assert hier.depth == 0
        assert hier.sheet_refs == []
        assert hier.children == []

    def test_two_level_hierarchy(self, tmp_path: Path) -> None:
        child = tmp_path / "child.kicad_sch"
        child.write_text(_make_minimal_sch("child"))
        root_body = _sheet_block("Child Sheet", "child.kicad_sch")
        root = tmp_path / "root.kicad_sch"
        root.write_text(_make_minimal_sch("root", root_body))
        hier = SchematicGraph.from_hierarchy(root)
        assert len(hier.sheet_refs) == 1
        assert hier.sheet_refs[0].name == "Child Sheet"
        assert hier.sheet_refs[0].filepath == "child.kicad_sch"
        assert len(hier.children) == 1
        assert hier.children[0].depth == 1
        assert hier.children[0].filepath == str(child.resolve())

    def test_missing_child_skipped(self, tmp_path: Path) -> None:
        root_body = _sheet_block("Missing", "nonexistent.kicad_sch")
        root = tmp_path / "root.kicad_sch"
        root.write_text(_make_minimal_sch("root", root_body))
        hier = SchematicGraph.from_hierarchy(root)
        assert len(hier.sheet_refs) == 1
        assert len(hier.children) == 0  # child file doesn't exist

    def test_max_depth_limits_recursion(self, tmp_path: Path) -> None:
        # Create root -> child -> grandchild
        grandchild = tmp_path / "grandchild.kicad_sch"
        grandchild.write_text(_make_minimal_sch("grandchild"))
        child_body = _sheet_block("Grandchild", "grandchild.kicad_sch")
        child = tmp_path / "child.kicad_sch"
        child.write_text(_make_minimal_sch("child", child_body))
        root_body = _sheet_block("Child", "child.kicad_sch")
        root = tmp_path / "root.kicad_sch"
        root.write_text(_make_minimal_sch("root", root_body))
        hier = SchematicGraph.from_hierarchy(root, max_depth=1)
        assert len(hier.children) == 1
        assert len(hier.children[0].children) == 0  # max_depth=1 stops

    def test_circular_reference_prevents_infinite_loop(self, tmp_path: Path) -> None:
        # root references child, child references root
        root = tmp_path / "root.kicad_sch"
        child = tmp_path / "child.kicad_sch"
        # Child references root
        child_body = _sheet_block("Root (circular)", "root.kicad_sch")
        child.write_text(_make_minimal_sch("child", child_body))
        # Root references child
        root_body = _sheet_block("Child", "child.kicad_sch")
        root.write_text(_make_minimal_sch("root", root_body))
        hier = SchematicGraph.from_hierarchy(root)
        assert len(hier.children) == 1
        # Child should not have root as a child (visited set)
        assert len(hier.children[0].children) == 0


# ---------------------------------------------------------------------------
# _merge_trace_results
# ---------------------------------------------------------------------------

class TestMergeTraceResults:
    """Tests for merging trace results across sheets."""

    def test_empty_list(self) -> None:
        result = _merge_trace_results([])
        assert result["pin_count"] == 0

    def test_single_result_passthrough(self) -> None:
        r = {"label": "GND", "reachable_pins": [], "pin_count": 0,
             "refs": [], "sheets": ["root"], "domain": "unknown",
             "blocked_by": [], "far_pins": [], "far_pin_count": 0}
        merged = _merge_trace_results([r])
        assert merged["label"] == "GND"

    def test_dedup_pins(self) -> None:
        r1 = {"label": "GND", "reachable_pins": [
            {"ref": "R1", "pin_number": "1"}], "pin_count": 1,
            "refs": ["R1"], "sheets": ["root"], "domain": "passive_only",
            "blocked_by": [], "far_pins": [], "far_pin_count": 0}
        r2 = {"label": "GND", "reachable_pins": [
            {"ref": "R1", "pin_number": "1"}], "pin_count": 1,
            "refs": ["R1"], "sheets": ["child"], "domain": "passive_only",
            "blocked_by": [], "far_pins": [], "far_pin_count": 0}
        merged = _merge_trace_results([r1, r2])
        assert merged["pin_count"] == 1  # deduped
        assert merged["sheets"] == ["root", "child"]

    def test_union_refs(self) -> None:
        r1 = {"label": "GND", "reachable_pins": [
            {"ref": "R1", "pin_number": "1"}], "pin_count": 1,
            "refs": ["R1"], "sheets": ["a"], "domain": "passive_only",
            "blocked_by": ["AGND"], "far_pins": [], "far_pin_count": 0}
        r2 = {"label": "GND", "reachable_pins": [
            {"ref": "R2", "pin_number": "2"}], "pin_count": 1,
            "refs": ["R2"], "sheets": ["b"], "domain": "passive_only",
            "blocked_by": ["DGND"], "far_pins": [], "far_pin_count": 0}
        merged = _merge_trace_results([r1, r2])
        assert merged["pin_count"] == 2
        assert merged["refs"] == ["R1", "R2"]
        assert set(merged["blocked_by"]) == {"AGND", "DGND"}


# ---------------------------------------------------------------------------
# Multi-sheet trace_net_from_label (mocked)
# ---------------------------------------------------------------------------

class TestMultiSheetTrace:
    """Integration tests for multi-sheet tracing."""

    @staticmethod
    def _make_mock_hier(
        root_has_refs: bool = True,
        child_names: list[str] | None = None,
    ) -> MagicMock:
        hier = MagicMock(spec=HierarchicalSchematic)
        hier.graph = MagicMock()
        hier.sheet_refs = [MagicMock()] if root_has_refs else []
        hier.children = []
        if child_names:
            for name in child_names:
                child = MagicMock(spec=HierarchicalSchematic)
                child.graph = MagicMock()
                child.filepath = f"/tmp/{name}.kicad_sch"
                hier.children.append(child)
        return hier

    @patch("kicad_agent.ops.net_tracer.SchematicGraph")
    @patch("kicad_agent.ops.net_tracer._trace_single_graph")
    def test_traces_root_and_children(
        self, mock_trace: MagicMock, mock_graph_cls: MagicMock,
    ) -> None:
        mock_graph_cls.from_hierarchy.return_value = self._make_mock_hier(
            root_has_refs=True, child_names=["child1", "child2"],
        )
        mock_trace.side_effect = [
            {"label": "GND", "reachable_pins": [], "pin_count": 0,
             "refs": [], "sheets": ["root"], "domain": "passive_only",
             "blocked_by": [], "far_pins": [], "far_pin_count": 0},
            {"label": "GND", "reachable_pins": [
                {"ref": "R1", "pin_number": "1"}], "pin_count": 1,
             "refs": ["R1"], "sheets": ["child1"], "domain": "passive_only",
             "blocked_by": [], "far_pins": [], "far_pin_count": 0},
            {"label": "GND", "reachable_pins": [
                {"ref": "R2", "pin_number": "2"}], "pin_count": 1,
             "refs": ["R2"], "sheets": ["child2"], "domain": "passive_only",
             "blocked_by": [], "far_pins": [], "far_pin_count": 0},
        ]
        result = trace_net_from_label(
            Path("root.kicad_sch"), label_name="GND",
        )
        assert mock_trace.call_count == 3  # root + 2 children
        assert result["pin_count"] == 2
        assert result["refs"] == ["R1", "R2"]

    @patch("kicad_agent.ops.net_tracer.SchematicGraph")
    @patch("kicad_agent.ops.net_tracer._trace_single_graph")
    def test_single_sheet_fallback(
        self, mock_trace: MagicMock, mock_graph_cls: MagicMock,
    ) -> None:
        mock_graph_cls.from_hierarchy.return_value = self._make_mock_hier(
            root_has_refs=False,
        )
        mock_graph_cls.from_file.return_value = MagicMock()
        mock_trace.return_value = {
            "label": "GND", "reachable_pins": [
                {"ref": "R1", "pin_number": "1"}], "pin_count": 1,
            "refs": ["R1"], "sheets": [], "domain": "passive_only",
            "blocked_by": [], "far_pins": [], "far_pin_count": 0,
        }
        result = trace_net_from_label(
            Path("single.kicad_sch"), label_name="GND",
        )
        # Single-sheet path: uses from_file, not from_hierarchy children
        assert result["pin_count"] == 1
        assert result["refs"] == ["R1"]

    @patch("kicad_agent.ops.net_tracer.SchematicGraph")
    @patch("kicad_agent.ops.net_tracer._trace_single_graph")
    def test_hierarchy_exception_falls_back(
        self, mock_trace: MagicMock, mock_graph_cls: MagicMock,
    ) -> None:
        mock_graph_cls.from_hierarchy.side_effect = Exception("parse error")
        mock_graph_cls.from_file.return_value = MagicMock()
        mock_trace.return_value = {
            "label": "GND", "reachable_pins": [], "pin_count": 0,
            "refs": [], "sheets": [], "domain": "unknown",
            "blocked_by": [], "far_pins": [], "far_pin_count": 0,
        }
        result = trace_net_from_label(
            Path("broken.kicad_sch"), label_name="GND",
        )
        assert result["label"] == "GND"
        mock_graph_cls.from_file.assert_called_once()
