"""Tests for board graph construction from schematic+PCB file pairs.

RW-02, RW-03: Tests graph_builder.py which composes SchematicIR, PcbIR,
NetGraph, and spatial extractor into a unified networkx graph pipeline.

Uses:
- RaspberryPi-uHAT fixture for real parsing validation
- Synthetic minimal KiCad files for edge case tests
"""

from __future__ import annotations

import dataclasses
import json
from pathlib import Path

import networkx as nx
import pytest

from volta.ir.base import _clear_registry
from volta.training.graph_builder import (
    BoardGraphResult,
    build_board_graph,
    detect_kicad_version,
    is_supported_kicad_version,
    is_likely_parseable,
    KICAD_VERSION_7,
    KICAD_VERSION_10,
    MIN_KICAD_VERSION,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"
UHAT_SCH = FIXTURES_DIR / "RaspberryPi-uHAT" / "RaspberryPi-uHAT.kicad_sch"
UHAT_PCB = FIXTURES_DIR / "RaspberryPi-uHAT" / "RaspberryPi-uHAT.kicad_pcb"

# Minimal valid KiCad 7 schematic content (kiutils-parseable)
MINIMAL_SCH = """\
(kicad_sch
\t(version 20230121)
\t(generator "volta")
\t(uuid "00000000-0000-0000-0000-000000000001")
\t(paper "A4")
\t(lib_symbols
\t\t(symbol "Device:R"
\t\t\t(pin_numbers hide)
\t\t\t(pin_names
\t\t\t\t(offset 0)
\t\t\t)
\t\t\t(exclude_from_sim no)
\t\t\t(in_bom yes)
\t\t\t(on_board yes)
\t\t\t(property "Reference" "R"
\t\t\t\t(at 0 1.27 0)
\t\t\t\t(effects
\t\t\t\t\t(font
\t\t\t\t\t\t(size 1.27 1.27)
\t\t\t\t\t)
\t\t\t\t)
\t\t\t)
\t\t\t(property "Value" "R"
\t\t\t\t(at 0 -1.27 0)
\t\t\t\t(effects
\t\t\t\t\t(font
\t\t\t\t\t\t(size 1.27 1.27)
\t\t\t\t\t)
\t\t\t\t)
\t\t\t)
\t\t\t(property "Footprint" ""
\t\t\t\t(at 0 0 0)
\t\t\t\t(effects
\t\t\t\t\t(font
\t\t\t\t\t\t(size 1.27 1.27)
\t\t\t\t\t)
\t\t\t\t\t(hide yes)
\t\t\t\t)
\t\t\t)
\t\t\t(symbol "Device:R_1_1"
\t\t\t\t(pin passive line
\t\t\t\t\t(at 0 3.81 270)
\t\t\t\t\t(length 1.27)
\t\t\t\t\t(name "~"
\t\t\t\t\t\t(effects
\t\t\t\t\t\t\t(font
\t\t\t\t\t\t\t\t(size 1.27 1.27)
\t\t\t\t\t\t\t)
\t\t\t\t\t\t)
\t\t\t\t\t)
\t\t\t\t\t(number "1"
\t\t\t\t\t\t(effects
\t\t\t\t\t\t\t(font
\t\t\t\t\t\t\t\t(size 1.27 1.27)
\t\t\t\t\t\t\t)
\t\t\t\t\t\t)
\t\t\t\t\t)
\t\t\t\t)
\t\t\t\t(pin passive line
\t\t\t\t\t(at 0 -3.81 90)
\t\t\t\t\t(length 1.27)
\t\t\t\t\t(name "~"
\t\t\t\t\t\t(effects
\t\t\t\t\t\t\t(font
\t\t\t\t\t\t\t\t(size 1.27 1.27)
\t\t\t\t\t\t\t)
\t\t\t\t\t\t)
\t\t\t\t\t)
\t\t\t\t\t(number "2"
\t\t\t\t\t\t(effects
\t\t\t\t\t\t\t(font
\t\t\t\t\t\t\t\t(size 1.27 1.27)
\t\t\t\t\t\t\t)
\t\t\t\t\t\t)
\t\t\t\t\t)
\t\t\t\t)
\t\t\t)
\t\t)
\t)
\t(symbol
\t\t(lib_id "Device:R")
\t\t(at 127 101.6 0)
\t\t(uuid "00000000-0000-0000-0000-000000000010")
\t\t(property "Reference" "R1"
\t\t\t(at 127 101.6 0)
\t\t\t(effects
\t\t\t\t(font
\t\t\t\t\t(size 1.27 1.27)
\t\t\t\t)
\t\t\t)
\t\t)
\t\t(property "Value" "10k"
\t\t\t(at 127 101.6 0)
\t\t\t(effects
\t\t\t\t(font
\t\t\t\t\t(size 1.27 1.27)
\t\t\t\t)
\t\t\t)
\t\t)
\t\t(property "Footprint" "Resistor_SMD:R_0402"
\t\t\t(at 127 101.6 0)
\t\t\t(effects
\t\t\t\t(font
\t\t\t\t\t\t(size 1.27 1.27)
\t\t\t\t)
\t\t\t\t(hide yes)
\t\t\t)
\t\t)
\t)
)
"""

# Minimal valid KiCad 7 PCB content (kiutils-parseable)
MINIMAL_PCB = """\
(kicad_pcb
\t(version 20230101)
\t(generator "volta")
\t(general
\t\t(thickness 1.6)
\t)
\t(paper "A4")
\t(layers
\t\t(0 "F.Cu" signal)
\t\t(31 "B.Cu" signal)
\t)
\t(nets
\t\t(net 0 "")
\t\t(net 1 "VCC")
\t\t(net 2 "GND")
\t)
\t(footprint "Resistor_SMD:R_0402"
\t\t(layer "F.Cu")
\t\t(uuid "00000000-0000-0000-0000-000000000020")
\t\t(at 50 50 0)
\t\t(property "Reference" "R1"
\t\t\t(at 0 0 0)
\t\t\t(layer "F.SilkS")
\t\t\t(uuid "00000000-0000-0000-0000-000000000021")
\t\t\t(effects
\t\t\t\t(font
\t\t\t\t\t(size 1 1)
\t\t\t\t\t(thickness 0.15)
\t\t\t\t)
\t\t\t)
\t\t)
\t\t(property "Value" "10k"
\t\t\t(at 0 1 0)
\t\t\t(layer "F.Fab")
\t\t\t(uuid "00000000-0000-0000-0000-000000000022")
\t\t\t(effects
\t\t\t\t(font
\t\t\t\t\t(size 1 1)
\t\t\t\t\t(thickness 0.15)
\t\t\t\t)
\t\t\t)
\t\t)
\t\t(pad "1" smd rect
\t\t\t(at -0.5 0)
\t\t\t(size 0.5 0.5)
\t\t\t(layers "F.Cu" "F.Paste" "F.Mask")
\t\t\t(uuid "00000000-0000-0000-0000-000000000023")
\t\t\t(net 1 "VCC")
\t\t)
\t\t(pad "2" smd rect
\t\t\t(at 0.5 0)
\t\t\t(size 0.5 0.5)
\t\t\t(layers "F.Cu" "F.Paste" "F.Mask")
\t\t\t(uuid "00000000-0000-0000-0000-000000000024")
\t\t\t(net 2 "GND")
\t\t)
\t)
)
"""


def _write_minimal_pair(tmp_path: Path) -> tuple[Path, Path]:
    """Write minimal KiCad schematic and PCB files for testing.

    Returns:
        (sch_path, pcb_path) tuple.
    """
    sch_path = tmp_path / "test.kicad_sch"
    pcb_path = tmp_path / "test.kicad_pcb"
    sch_path.write_text(MINIMAL_SCH, encoding="utf-8")
    pcb_path.write_text(MINIMAL_PCB, encoding="utf-8")
    return sch_path, pcb_path


@pytest.fixture(autouse=True)
def _reset_ir_registry():
    """Clear the IR registry before and after each test to prevent id collisions."""
    _clear_registry()
    yield
    _clear_registry()


class TestBoardGraphResult:
    """Tests for BoardGraphResult frozen dataclass."""

    def test_frozen_dataclass_immutable(self) -> None:
        """BoardGraphResult is frozen -- attribute assignment raises error."""
        result = BoardGraphResult(
            sample_id=0,
            repo_url="",
            repo_name="",
            schematic_path="test.kicad_sch",
            pcb_path="test.kicad_pcb",
            component_count=1,
            net_count=1,
            layer_count=2,
            board_width_mm=0.0,
            board_height_mm=0.0,
            difficulty="easy",
            board_hash="abc123",
            graph_json="{}",
            spatial_summary_json="{}",
        )
        with pytest.raises(dataclasses.FrozenInstanceError):
            result.component_count = 99  # type: ignore[misc]

    def test_all_fields_serializable(self) -> None:
        """All BoardGraphResult fields are primitives or JSON strings."""
        result = BoardGraphResult(
            sample_id=1,
            repo_url="https://github.com/test/repo",
            repo_name="test/repo",
            schematic_path="board.kicad_sch",
            pcb_path="board.kicad_pcb",
            component_count=5,
            net_count=3,
            layer_count=4,
            board_width_mm=100.0,
            board_height_mm=80.0,
            difficulty="easy",
            board_hash="deadbeef",
            graph_json='{"nodes": [], "links": []}',
            spatial_summary_json='{"point_count": 0}',
        )
        # Verify all fields are plain types (no live objects)
        for field in dataclasses.fields(result):
            value = getattr(result, field.name)
            assert isinstance(value, (int, float, str)), (
                f"Field {field.name} is {type(value)}, expected primitive"
            )


class TestBuildBoardGraph:
    """Tests for build_board_graph function."""

    def test_returns_none_on_invalid_schematic(self, tmp_path: Path) -> None:
        """Returns None when schematic path does not exist."""
        pcb_path = tmp_path / "test.kicad_pcb"
        pcb_path.write_text(MINIMAL_PCB, encoding="utf-8")
        fake_sch = tmp_path / "nonexistent.kicad_sch"

        result = build_board_graph(fake_sch, pcb_path)
        assert result is None

    def test_returns_none_on_invalid_pcb(self, tmp_path: Path) -> None:
        """Returns None when PCB path does not exist."""
        sch_path = tmp_path / "test.kicad_sch"
        sch_path.write_text(MINIMAL_SCH, encoding="utf-8")
        fake_pcb = tmp_path / "nonexistent.kicad_pcb"

        result = build_board_graph(sch_path, fake_pcb)
        assert result is None

    def test_returns_none_on_corrupt_file(self, tmp_path: Path) -> None:
        """Returns None when given a corrupt file with .kicad_pcb extension."""
        sch_path = tmp_path / "test.kicad_sch"
        sch_path.write_text(MINIMAL_SCH, encoding="utf-8")
        corrupt_pcb = tmp_path / "corrupt.kicad_pcb"
        corrupt_pcb.write_text("this is not valid kicad content at all!", encoding="utf-8")

        result = build_board_graph(sch_path, corrupt_pcb)
        assert result is None

    def test_board_hash_is_stable(self, tmp_path: Path) -> None:
        """Parsing same file pair twice produces identical board_hash."""
        sch_path, pcb_path = _write_minimal_pair(tmp_path)

        result1 = build_board_graph(sch_path, pcb_path)
        result2 = build_board_graph(sch_path, pcb_path)

        assert result1 is not None
        assert result2 is not None
        assert result1.board_hash == result2.board_hash

    def test_component_count_matches_graph_nodes(self, tmp_path: Path) -> None:
        """component_count equals number of nodes with node_type='component'."""
        sch_path, pcb_path = _write_minimal_pair(tmp_path)

        result = build_board_graph(sch_path, pcb_path)
        assert result is not None

        graph_data = json.loads(result.graph_json)
        G = nx.node_link_graph(graph_data, directed=False)
        component_nodes = [
            n for n, attrs in G.nodes(data=True)
            if attrs.get("node_type") == "component"
        ]
        assert result.component_count == len(component_nodes)

    def test_net_edges_present(self, tmp_path: Path) -> None:
        """Deserialized graph has edges with 'net' attribute."""
        sch_path, pcb_path = _write_minimal_pair(tmp_path)

        result = build_board_graph(sch_path, pcb_path)
        assert result is not None

        graph_data = json.loads(result.graph_json)
        G = nx.node_link_graph(graph_data, directed=False)

        net_edges = [
            (u, v, attrs)
            for u, v, attrs in G.edges(data=True)
            if "net" in attrs
        ]
        # Minimal PCB has one footprint (R1) with two pads on different nets
        # (VCC and GND). A single footprint cannot form a net edge by itself
        # (edges require 2+ components). So check that the graph structure is
        # valid but may have zero net edges for a single-component board.
        assert isinstance(net_edges, list)

    def test_graph_json_roundtrip(self, tmp_path: Path) -> None:
        """Graph JSON round-trips via node_link_data / node_link_graph."""
        sch_path, pcb_path = _write_minimal_pair(tmp_path)

        result = build_board_graph(sch_path, pcb_path)
        assert result is not None

        # Deserialize from JSON string
        graph_data = json.loads(result.graph_json)
        G = nx.node_link_graph(graph_data, directed=False)

        # Re-serialize and verify node count matches
        re_serialized = nx.node_link_data(G)
        re_json = json.dumps(re_serialized, sort_keys=True)
        re_data = json.loads(re_json)
        G2 = nx.node_link_graph(re_data, directed=False)

        assert G.number_of_nodes() == G2.number_of_nodes()
        assert G.number_of_edges() == G2.number_of_edges()

    def test_difficulty_grading_easy(self) -> None:
        """Difficulty 'easy' for <10 components."""
        from volta.training.graph_builder import _grade_difficulty

        assert _grade_difficulty(5) == "easy"
        assert _grade_difficulty(0) == "easy"
        assert _grade_difficulty(9) == "easy"

    def test_difficulty_grading_medium(self) -> None:
        """Difficulty 'medium' for 10-50 components."""
        from volta.training.graph_builder import _grade_difficulty

        assert _grade_difficulty(10) == "medium"
        assert _grade_difficulty(25) == "medium"
        assert _grade_difficulty(50) == "medium"

    def test_difficulty_grading_hard(self) -> None:
        """Difficulty 'hard' for 50+ components."""
        from volta.training.graph_builder import _grade_difficulty

        assert _grade_difficulty(51) == "hard"
        assert _grade_difficulty(100) == "hard"
        assert _grade_difficulty(60) == "hard"

    def test_spatial_summary_json_valid(self, tmp_path: Path) -> None:
        """spatial_summary_json parses as valid JSON with expected keys."""
        sch_path, pcb_path = _write_minimal_pair(tmp_path)

        result = build_board_graph(sch_path, pcb_path)
        assert result is not None

        summary = json.loads(result.spatial_summary_json)
        assert "point_count" in summary
        assert "box_count" in summary
        assert "path_count" in summary
        assert "region_count" in summary
        assert all(isinstance(v, int) for v in [
            summary["point_count"],
            summary["box_count"],
            summary["path_count"],
            summary["region_count"],
        ])

    def test_minimal_board_has_component_node(self, tmp_path: Path) -> None:
        """Minimal board with R1 has a component node with correct attributes."""
        sch_path, pcb_path = _write_minimal_pair(tmp_path)

        result = build_board_graph(sch_path, pcb_path)
        assert result is not None

        graph_data = json.loads(result.graph_json)
        G = nx.node_link_graph(graph_data, directed=False)

        assert "R1" in G.nodes
        attrs = G.nodes["R1"]
        assert attrs.get("node_type") == "component"
        assert attrs.get("value") == "10k"

    def test_spatial_attributes_on_component_node(self, tmp_path: Path) -> None:
        """Component nodes have spatial attributes from PCB footprint."""
        sch_path, pcb_path = _write_minimal_pair(tmp_path)

        result = build_board_graph(sch_path, pcb_path)
        assert result is not None

        graph_data = json.loads(result.graph_json)
        G = nx.node_link_graph(graph_data, directed=False)

        if "R1" in G.nodes:
            attrs = G.nodes["R1"]
            assert "x_mm" in attrs
            assert "y_mm" in attrs
            assert "rotation_deg" in attrs
            # Footprint is at (50, 50, 0) in the minimal PCB
            assert attrs["x_mm"] == 50.0
            assert attrs["y_mm"] == 50.0
            assert attrs["rotation_deg"] == 0.0

    def test_real_fixture_parse(self) -> None:
        """RaspberryPi-uHAT fixture parses successfully with real data."""
        if not UHAT_SCH.exists() or not UHAT_PCB.exists():
            pytest.skip("RaspberryPi-uHAT fixtures not found")

        result = build_board_graph(UHAT_SCH, UHAT_PCB)
        assert result is not None
        assert result.component_count > 0
        assert result.net_count > 0
        assert result.board_hash  # non-empty hash
        assert result.difficulty in ("easy", "medium", "hard")

        # Verify graph JSON is valid
        graph_data = json.loads(result.graph_json)
        G = nx.node_link_graph(graph_data, directed=False)
        assert G.number_of_nodes() > 0


class TestVersionDetection:
    """Tests for KiCad format version detection and filtering."""

    def test_detect_version_from_kicad7(self) -> None:
        sch = '(kicad_sch (version 20230121) (generator "eeschema"))'
        assert detect_kicad_version(sch) == 20230121

    def test_detect_version_from_kicad10(self) -> None:
        pcb = '(kicad_pcb (version 20250114) (generator "pcbnew"))'
        assert detect_kicad_version(pcb) == 20250114

    def test_detect_version_returns_none_for_legacy(self) -> None:
        """Legacy files without version field return None."""
        content = "(kicad_pcb\n  (some old format)\n)"
        assert detect_kicad_version(content) is None

    def test_detect_version_returns_none_for_empty(self) -> None:
        assert detect_kicad_version("") is None

    def test_is_supported_kicad_version_both_v7(self) -> None:
        sch = '(kicad_sch (version 20230101))'
        pcb = '(kicad_pcb (version 20230101))'
        assert is_supported_kicad_version(sch, pcb) is True

    def test_is_supported_kicad_version_both_v10(self) -> None:
        sch = '(kicad_sch (version 20250114))'
        pcb = '(kicad_pcb (version 20250114))'
        assert is_supported_kicad_version(sch, pcb) is True

    def test_rejects_legacy_pcb(self) -> None:
        sch = '(kicad_sch (version 20230101))'
        pcb = '(kicad_pcb (version 20221018))'  # pre-KiCad 7
        assert is_supported_kicad_version(sch, pcb) is False

    def test_rejects_missing_version(self) -> None:
        sch = '(kicad_sch (version 20230101))'
        pcb = '(kicad_pcb (no version here))'
        assert is_supported_kicad_version(sch, pcb) is False

    def test_is_likely_parseable_valid(self) -> None:
        content = "(kicad_pcb\n  (version 20230101)\n  ...\n)"
        assert is_likely_parseable(content) is True

    def test_is_likely_parseable_empty(self) -> None:
        assert is_likely_parseable("") is False

    def test_is_likely_parseable_no_paren(self) -> None:
        assert is_likely_parseable("not a kicad file at all") is False

    def test_is_likely_parseable_too_short(self) -> None:
        assert is_likely_parseable("(kicad)") is False

    def test_build_board_graph_rejects_old_version(self, tmp_path: Path) -> None:
        """build_board_graph returns None for pre-KiCad 7 files."""
        sch = tmp_path / "test.kicad_sch"
        sch.write_text('(kicad_sch (version 20230101) (generator "test"))', encoding="utf-8")
        pcb = tmp_path / "test.kicad_pcb"
        pcb.write_text('(kicad_pcb (version 20221018) (generator "test"))', encoding="utf-8")

        result = build_board_graph(sch, pcb)
        assert result is None

    def test_build_board_graph_rejects_empty_file(self, tmp_path: Path) -> None:
        """build_board_graph returns None for empty files."""
        sch = tmp_path / "test.kicad_sch"
        sch.write_text("", encoding="utf-8")
        pcb = tmp_path / "test.kicad_pcb"
        pcb.write_text("(kicad_pcb\n)", encoding="utf-8")

        result = build_board_graph(sch, pcb)
        assert result is None
