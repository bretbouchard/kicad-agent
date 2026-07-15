"""Unit tests for design rules and net class management.

Tests parse/serialize round-trip for .kicad_dru files,
plus add/remove operations on DesignRulesFile.
"""

from pathlib import Path

import pytest

from volta.project.design_rules import (
    DesignRule,
    DesignRulesFile,
    NetClassDef,
    parse_design_rules,
    serialize_design_rules,
)

# ---------------------------------------------------------------------------
# Test fixtures
# ---------------------------------------------------------------------------

DRU_CONTENT = """(version 20240517)
(net_class "Default" ""
  (clearance 0.2)
  (trace_width 0.25)
  (via_dia 0.8)
  (via_drill 0.4)
)
(net_class "Power" "Power nets"
  (clearance 0.3)
  (trace_width 0.5)
  (via_dia 1.0)
  (via_drill 0.6)
)
(rule "HV_clearance"
  (constraint clearance (min 0.5))
  (condition "A.NetClass == 'HV'")
)"""

DRU_CONTENT_WITH_RULES = """(version 20240517)
(net_class "Default" ""
  (clearance 0.2)
  (trace_width 0.25)
  (via_dia 0.8)
  (via_drill 0.4)
)
(net_class "Power" "Power nets"
  (clearance 0.3)
  (trace_width 0.5)
  (via_dia 1.0)
  (via_drill 0.6)
)
(net_class "HighSpeed" "High-speed signals"
  (clearance 0.15)
  (trace_width 0.15)
  (via_dia 0.6)
  (via_drill 0.3)
)
(rule "HV_clearance"
  (constraint clearance (min 0.5))
  (condition "A.NetClass == 'HV'")
)"""

EMPTY_DRU_CONTENT = """(version 20240517)
"""


@pytest.fixture
def dru_file(tmp_path: Path) -> Path:
    """Create a temporary .kicad_dru file."""
    path = tmp_path / "board.kicad_dru"
    path.write_text(DRU_CONTENT, encoding="utf-8")
    return path


@pytest.fixture
def dru_with_3_classes(tmp_path: Path) -> Path:
    """Create a DRU file with 3 net classes."""
    path = tmp_path / "board.kicad_dru"
    path.write_text(DRU_CONTENT_WITH_RULES, encoding="utf-8")
    return path


@pytest.fixture
def empty_dru_file(tmp_path: Path) -> Path:
    """Create an empty .kicad_dru file."""
    path = tmp_path / "empty.kicad_dru"
    path.write_text(EMPTY_DRU_CONTENT, encoding="utf-8")
    return path


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestParseDesignRules:
    """Tests for parsing .kicad_dru files."""

    def test_parse_empty_dru(self, empty_dru_file: Path) -> None:
        """Parse file with just version, verify 0 net classes and rules."""
        dru = parse_design_rules(empty_dru_file)
        assert len(dru.net_classes) == 0
        assert len(dru.custom_rules) == 0

    def test_parse_net_classes(self, dru_with_3_classes: Path) -> None:
        """Parse DRU with 3 net classes, verify all fields."""
        dru = parse_design_rules(dru_with_3_classes)
        assert len(dru.net_classes) == 3

        default = next(nc for nc in dru.net_classes if nc.name == "Default")
        assert default.clearance == 0.2
        assert default.track_width == 0.25
        assert default.via_diameter == 0.8
        assert default.via_drill == 0.4
        assert default.description == ""

        power = next(nc for nc in dru.net_classes if nc.name == "Power")
        assert power.description == "Power nets"
        assert power.clearance == 0.3
        assert power.track_width == 0.5

        high_speed = next(nc for nc in dru.net_classes if nc.name == "HighSpeed")
        assert high_speed.clearance == 0.15
        assert high_speed.track_width == 0.15

    def test_parse_custom_rule(self, dru_file: Path) -> None:
        """Parse DRU with custom clearance rule, verify constraint and condition."""
        dru = parse_design_rules(dru_file)
        assert len(dru.custom_rules) == 1

        rule = dru.custom_rules[0]
        assert rule.name == "HV_clearance"
        assert rule.constraint_type == "clearance"
        assert rule.constraint_values.get("min") is not None
        assert rule.condition == "A.NetClass == 'HV'"


class TestDesignRulesEditing:
    """Tests for add/remove operations on DesignRulesFile."""

    def test_add_net_class(self) -> None:
        """Add a Differential net class with pair width/gap, verify retrieval."""
        dru = DesignRulesFile()
        diff = NetClassDef(
            name="Differential",
            description="Diff pair signals",
            clearance=0.15,
            track_width=0.12,
            diff_pair_width=0.12,
            diff_pair_gap=0.08,
        )
        dru.add_net_class(diff)

        assert len(dru.net_classes) == 1
        assert dru.net_classes[0].name == "Differential"
        assert dru.net_classes[0].diff_pair_width == 0.12
        assert dru.net_classes[0].diff_pair_gap == 0.08

    def test_add_custom_rule(self) -> None:
        """Add an HV_clearance rule with constraint and condition, verify."""
        dru = DesignRulesFile()
        rule = DesignRule(
            name="HV_clearance",
            constraint_type="clearance",
            constraint_values={"min": "0.5"},
            condition="A.NetClass == 'HV'",
        )
        dru.add_rule(rule)

        assert len(dru.custom_rules) == 1
        assert dru.custom_rules[0].name == "HV_clearance"
        assert dru.custom_rules[0].constraint_type == "clearance"

    def test_remove_net_class(self, dru_file: Path) -> None:
        """Remove a Power net class, verify count decreased."""
        dru = parse_design_rules(dru_file)
        initial_count = len(dru.net_classes)

        removed = dru.remove_net_class("Power")
        assert removed.name == "Power"
        assert len(dru.net_classes) == initial_count - 1


class TestRoundTrip:
    """Tests for parse -> serialize -> re-parse fidelity."""

    def test_round_trip(self, dru_file: Path, tmp_path: Path) -> None:
        """Parse, serialize, re-parse and verify identical content."""
        dru = parse_design_rules(dru_file)

        output_path = tmp_path / "board-out.kicad_dru"
        serialize_design_rules(dru, output_path)

        re_parsed = parse_design_rules(output_path)
        assert len(re_parsed.net_classes) == len(dru.net_classes)
        assert len(re_parsed.custom_rules) == len(dru.custom_rules)

        for orig, reparsed in zip(dru.net_classes, re_parsed.net_classes):
            assert orig.name == reparsed.name
            assert orig.clearance == reparsed.clearance
            assert orig.track_width == reparsed.track_width

        for orig, reparsed in zip(dru.custom_rules, re_parsed.custom_rules):
            assert orig.name == reparsed.name
            assert orig.constraint_type == reparsed.constraint_type


class TestDimensions:
    """Tests for dimension parsing and validation."""

    def test_net_class_dimensions(self, dru_file: Path) -> None:
        """Verify track_width, via_diameter, clearance are parsed as floats."""
        dru = parse_design_rules(dru_file)

        default = next(nc for nc in dru.net_classes if nc.name == "Default")
        assert isinstance(default.track_width, float)
        assert isinstance(default.via_diameter, float)
        assert isinstance(default.clearance, float)
        assert default.track_width == 0.25
        assert default.via_diameter == 0.8
        assert default.clearance == 0.2
