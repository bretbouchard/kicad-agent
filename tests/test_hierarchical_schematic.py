"""Tests for hierarchical schematic parsing and multi-sheet tracing.

Covers: _parse_sheet_refs, from_hierarchy, _extract_sexp_block,
multi-sheet trace_net_from_label, missing files, max depth, circular refs,
and single-sheet no-regression.
"""

from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from kicad_agent.ops.net_tracer import trace_net_from_label
from kicad_agent.schematic_routing.schematic_graph import (
    HierarchicalSchematic,
    SchematicGraph,
    SheetPin,
    SheetRef,
    _extract_sexp_block,
    _parse_sheet_refs,
)

FIXTURE_DIR = Path(__file__).parent / "data" / "hierarchical"


# ---------------------------------------------------------------------------
# _extract_sexp_block
# ---------------------------------------------------------------------------

class TestExtractSexpBlock:
    """Tests for generic S-expression block extraction."""

    def test_extracts_single_block(self) -> None:
        body = '(sheet\n  (at 1 2)\n)'
        blocks = _extract_sexp_block(body, r'\(sheet\s')
        assert len(blocks) == 1
        start, end = blocks[0]
        assert body[start:end] == '(sheet\n  (at 1 2)\n)'

    def test_extracts_nested_blocks(self) -> None:
        body = '(sheet (pin "X" input (at 1 2 0)))'
        blocks = _extract_sexp_block(body, r'\(sheet\s')
        assert len(blocks) == 1
        assert body[blocks[0][0]:blocks[0][1]] == body

    def test_extracts_multiple_blocks(self) -> None:
        body = '(sheet A)(sheet B)'
        blocks = _extract_sexp_block(body, r'\(sheet\s')
        assert len(blocks) == 2

    def test_returns_empty_for_no_match(self) -> None:
        body = "(symbol\n  (at 1 2)\n)"
        blocks = _extract_sexp_block(body, r'\(sheet\s')
        assert blocks == []

    def test_handles_deeply_nested(self) -> None:
        body = '(sheet ((a (b (c)))) (d (e)))'
        blocks = _extract_sexp_block(body, r'\(sheet\s')
        assert len(blocks) == 1
        assert body[blocks[0][0]:blocks[0][1]] == body

    def test_custom_pattern(self) -> None:
        body = '(foo (x 1) (y 2))(bar (z 3))'
        blocks = _extract_sexp_block(body, r'\(foo\s')
        assert len(blocks) == 1
        assert "x 1" in body[blocks[0][0]:blocks[0][1]]


# ---------------------------------------------------------------------------
# _parse_sheet_refs
# ---------------------------------------------------------------------------

class TestParseSheetRefs:
    """Tests for (sheet ...) block parsing."""

    def test_parses_root_fixture(self) -> None:
        body = (FIXTURE_DIR / "root.kicad_sch").read_text()
        refs = _parse_sheet_refs(body)
        assert len(refs) == 2

        assert refs[0].name == "Sub A"
        assert refs[0].filepath == "sub_a.kicad_sch"
        assert refs[0].uuid == "11111111-1111-1111-1111-111111111111"
        assert refs[0].position == (10.0, 10.0)
        assert refs[0].size == (20.0, 5.0)

        assert refs[1].name == "Sub B"
        assert refs[1].filepath == "sub_b.kicad_sch"

    def test_parses_sheet_with_pins(self) -> None:
        body = """(sheet
    (at 30.48 199.39)
    (size 30 7.62)
    (uuid "test-uuid-1")
    (property "Sheetname" "EQ Stage"
      (at 30.48 199.39 0)
      (effects (font (size 1.27 1.27)))
    )
    (property "Sheetfile" "eq-stage.kicad_sch"
      (at 30.48 201.93 0)
      (effects (font (size 1.27 1.27)))
    )
    (pin "ADC1_L" output (at 60.48 201.93 0)
      (uuid "pin-uuid-1")
      (effects (font (size 0.762 0.762)))
    )
    (pin "EQ_IN" bidirectional (at 33.02 199.39 90)
      (uuid "pin-uuid-2")
      (effects (font (size 0.762 0.762)))
    )
)"""
        refs = _parse_sheet_refs(body)
        assert len(refs) == 1
        ref = refs[0]
        assert ref.name == "EQ Stage"
        assert ref.filepath == "eq-stage.kicad_sch"
        assert len(ref.pins) == 2
        assert ref.pins[0].name == "ADC1_L"
        assert ref.pins[0].direction == "output"
        assert ref.pins[0].position == (60.48, 201.93)
        assert ref.pins[0].angle == 0.0
        assert ref.pins[1].name == "EQ_IN"
        assert ref.pins[1].direction == "bidirectional"
        assert ref.pins[1].angle == 90.0

    def test_empty_body(self) -> None:
        refs = _parse_sheet_refs("")
        assert refs == []

    def test_sheet_without_name_or_file(self) -> None:
        body = "(sheet (at 1 2) (size 3 4) (uuid \"x\"))"
        refs = _parse_sheet_refs(body)
        assert len(refs) == 1
        assert refs[0].name == ""
        assert refs[0].filepath == ""


# ---------------------------------------------------------------------------
# SchematicGraph.from_hierarchy
# ---------------------------------------------------------------------------

class TestFromHierarchy:
    """Tests for recursive hierarchical parsing."""

    def test_parses_two_level_hierarchy(self) -> None:
        hier = SchematicGraph.from_hierarchy(FIXTURE_DIR / "root.kicad_sch")
        assert isinstance(hier, HierarchicalSchematic)
        assert len(hier.sheet_refs) == 2
        assert len(hier.children) == 2
        assert hier.depth == 0

        # Children are parsed
        child_a = hier.children[0]
        assert "sub_a" in child_a.filepath
        assert child_a.depth == 1
        assert len(child_a.graph.pins) == 2  # R1, R2

        child_b = hier.children[1]
        assert "sub_b" in child_b.filepath
        assert child_b.depth == 1
        assert len(child_b.graph.pins) == 2  # R3, R4

    def test_root_sheet_refs_populated(self) -> None:
        hier = SchematicGraph.from_hierarchy(FIXTURE_DIR / "root.kicad_sch")
        assert hier.sheet_refs[0].name == "Sub A"
        assert hier.sheet_refs[0].filepath == "sub_a.kicad_sch"
        assert hier.sheet_refs[1].name == "Sub B"
        assert hier.sheet_refs[1].filepath == "sub_b.kicad_sch"

    def test_single_sheet_fallback(self) -> None:
        hier = SchematicGraph.from_hierarchy(FIXTURE_DIR / "single_sheet.kicad_sch")
        assert isinstance(hier, HierarchicalSchematic)
        assert len(hier.sheet_refs) == 0
        assert len(hier.children) == 0
        assert hier.depth == 0
        assert len(hier.graph.pins) == 1  # R5

    def test_missing_child_file_skipped(self) -> None:
        """Child file that doesn't exist is silently skipped."""
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "root.kicad_sch"
            root.write_text("""(kicad_sch
  (version 20231120)
  (generator "test")
  (lib_symbols)
  (sheet_instances (path "/" (page "1")))
  (sheet
    (at 10 10)
    (size 20 5)
    (uuid "missing-uuid")
    (property "Sheetname" "Missing"
      (at 10 10 0)
      (effects (font (size 1.27 1.27)))
    )
    (property "Sheetfile" "nonexistent.kicad_sch"
      (at 10 12.54 0)
      (effects (font (size 1.27 1.27)))
    )
)
""")
            hier = SchematicGraph.from_hierarchy(root)
            assert len(hier.sheet_refs) == 1
            assert len(hier.children) == 0

    def test_max_depth_stops_recursion(self) -> None:
        hier = SchematicGraph.from_hierarchy(
            FIXTURE_DIR / "root.kicad_sch", max_depth=0,
        )
        # max_depth=0 means root at depth 0, children can't go deeper
        assert hier.depth == 0
        assert len(hier.children) == 0  # children would be at depth 1

    def test_circular_reference_skipped(self) -> None:
        """If a child references its own ancestor, it's skipped."""
        with TemporaryDirectory() as tmpdir:
            root = Path(tmpdir) / "root.kicad_sch"
            child = Path(tmpdir) / "child.kicad_sch"

            root.write_text(f"""(kicad_sch
  (version 20231120)
  (generator "test")
  (lib_symbols)
  (sheet_instances (path "/" (page "1")))
  (sheet
    (at 10 10)
    (size 20 5)
    (uuid "circ-uuid")
    (property "Sheetname" "Child"
      (at 10 10 0)
      (effects (font (size 1.27 1.27)))
    )
    (property "Sheetfile" "child.kicad_sch"
      (at 10 12.54 0)
      (effects (font (size 1.27 1.27)))
    )
)
""")
            # Child references root back (circular)
            child.write_text(f"""(kicad_sch
  (version 20231120)
  (generator "test")
  (lib_symbols)
  (sheet_instances (path "/" (page "1")))
  (sheet
    (at 10 10)
    (size 20 5)
    (uuid "circ-child-uuid")
    (property "Sheetname" "Back to Root"
      (at 10 10 0)
      (effects (font (size 1.27 1.27)))
    )
    (property "Sheetfile" "root.kicad_sch"
      (at 10 12.54 0)
      (effects (font (size 1.27 1.27)))
    )
)
""")
            hier = SchematicGraph.from_hierarchy(root)
            # Root parsed, child parsed, but child's reference to root is skipped
            assert len(hier.children) == 1
            assert len(hier.children[0].children) == 0


# ---------------------------------------------------------------------------
# Multi-sheet trace_net_from_label
# ---------------------------------------------------------------------------

class TestMultiSheetTracing:
    """Tests for trace_net_from_label across hierarchical sheets."""

    def test_global_label_traced_across_sheets(self) -> None:
        r = trace_net_from_label(FIXTURE_DIR / "root.kicad_sch", label_name="GNDA")
        assert r["label"] == "GNDA"
        assert r["pin_count"] == 4
        assert r["refs"] == ["R1", "R2", "R3", "R4"]
        assert "sub_a" in r["sheets"]
        assert "sub_b" in r["sheets"]

    def test_merged_pins_deduplicated(self) -> None:
        """Same (ref, pin) shouldn't appear twice even if in multiple sheets."""
        r = trace_net_from_label(FIXTURE_DIR / "root.kicad_sch", label_name="GNDA")
        pin_keys = [(p["ref"], p["pin_number"]) for p in r["reachable_pins"]]
        assert len(pin_keys) == len(set(pin_keys))

    def test_domain_classified_on_merged_pins(self) -> None:
        r = trace_net_from_label(FIXTURE_DIR / "root.kicad_sch", label_name="GNDA")
        # All pins are passives (R1-R4)
        assert r["domain"] == "passive_only"

    def test_nonexistent_label_empty(self) -> None:
        r = trace_net_from_label(FIXTURE_DIR / "root.kicad_sch", label_name="NONEXISTENT")
        assert r["label"] == "NONEXISTENT"
        assert r["pin_count"] == 0

    def test_label_in_child_only(self) -> None:
        """Label only exists in sub-sheets, not root. Should still be found."""
        r = trace_net_from_label(FIXTURE_DIR / "root.kicad_sch", label_name="GNDA")
        # Root has 0 labels, children have GNDA
        assert r["pin_count"] == 4

    def test_single_sheet_no_regression(self) -> None:
        """Single-sheet schematic returns same result as before #72."""
        r = trace_net_from_label(FIXTURE_DIR / "single_sheet.kicad_sch", label_name="GNDA")
        assert r["label"] == "GNDA"
        assert r["pin_count"] == 1
        assert r["refs"] == ["R5"]
        assert r["sheets"] == []


# ---------------------------------------------------------------------------
# Dataclass instantiation
# ---------------------------------------------------------------------------

class TestDataclasses:
    """Tests for dataclass construction."""

    def test_sheet_pin_defaults(self) -> None:
        pin = SheetPin(name="X", direction="input", position=(1.0, 2.0), angle=90.0)
        assert pin.uuid == ""

    def test_sheet_ref_defaults(self) -> None:
        ref = SheetRef(name="S", filepath="s.kicad_sch", uuid="u", position=(0, 0), size=(10, 5))
        assert ref.pins == []

    def test_hierarchical_schematic_defaults(self) -> None:
        g = SchematicGraph()
        hier = HierarchicalSchematic(filepath="test.kicad_sch", graph=g)
        assert hier.sheet_refs == []
        assert hier.children == []
        assert hier.depth == 0
        assert hier.warnings == []
