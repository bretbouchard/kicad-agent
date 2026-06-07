"""Tests for power_unit_placer.py -- power unit placement for schematic routing.

Tests cover:
  1. _find_schematic_block_end correctly finds (schematic ...) closing paren
  2. _find_schematic_block_end returns -1 when no schematic block exists
  3. _find_schematic_block_end distinguishes (schematic ...) from (kicad_sch ...)
  4. IC_POWER_CONFIG has required keys for known ICs
"""

import pytest

from kicad_agent.schematic_routing.power_unit_placer import (
    _find_schematic_block_end,
    IC_POWER_CONFIG,
)


class TestFindSchematicBlockEnd:
    """Tests for _find_schematic_block_end -- R-BUG-001 fix."""

    def test_finds_schematic_closing_paren(self):
        """Finds the ')' closing the (schematic ...) block, not (kicad_sch ...)."""
        content = """(kicad_sch (version 20250114) (generator "test")
  (uuid "00000000-0000-0000-0000-000000000001")
  (paper "A4")
  (lib_symbols
    (symbol "Device:R" (in_bom yes) (on_board yes))
  )
  (schematic
    (symbol (lib_id "Device:R") (at 50 50 0))
  )
)"""
        pos = _find_schematic_block_end(content)
        # The ')' closing (schematic ...) should be found
        assert pos > 0
        # The character at pos should be ')'
        assert content[pos] == ')'
        # It should NOT be the last ')' in the file (that's kicad_sch closing)
        assert pos < content.rfind(')')

    def test_returns_negative_when_no_schematic_block(self):
        """Returns -1 when there is no (schematic ...) block."""
        content = """(kicad_sch (version 20250114))
)"""
        pos = _find_schematic_block_end(content)
        assert pos == -1

    def test_returns_negative_for_empty_content(self):
        """Returns -1 for empty content."""
        assert _find_schematic_block_end("") == -1

    def test_distinguishes_nested_schematic_from_kicad_sch(self):
        """For a file with both (kicad_sch ...) and (schematic ...), finds schematic.

        The (schematic ...) block closes BEFORE the (kicad_sch ...) block.
        rfind(')') would incorrectly find the kicad_sch closing paren.
        """
        content = """(kicad_sch (version 20250114)
  (schematic
    (wire (pts (xy 10 20) (xy 30 40)))
  )
  (sheet_instances)
)"""
        pos = _find_schematic_block_end(content)
        assert pos > 0
        # Verify it's the schematic closing paren, not the kicad_sch one
        # The content after schematic's ')' should contain "(sheet_instances)"
        after_schematic = content[pos + 1:].strip()
        assert "(sheet_instances)" in after_schematic or "sheet_instances" in after_schematic

    def test_handles_nested_parens_within_schematic(self):
        """Correctly depth-tracks nested parens within (schematic ...)."""
        content = """(kicad_sch (version 20250114)
  (schematic
    (symbol (lib_id "Device:R") (at 50 50 0)
      (property "Reference" "R1" (at 0 0 0)
        (effects (font (size 1.27 1.27)))
      )
    )
    (wire (pts (xy 10 20) (xy 30 40)))
  )
  (sheet_instances)
)"""
        pos = _find_schematic_block_end(content)
        assert pos > 0
        # After schematic's closing paren, we should still have sheet_instances
        after = content[pos + 1:].strip()
        assert "sheet_instances" in after


class TestICPowerConfig:
    """Tests for IC_POWER_CONFIG completeness."""

    def test_cd4066be_has_required_keys(self):
        """CD4066BE config has all required keys."""
        config = IC_POWER_CONFIG["CD4066BE"]
        assert "power_unit" in config
        assert "pins" in config
        assert "all_pin_numbers" in config
        assert len(config["pins"]) == 2  # VDD and VSS

    def test_cd4066be_pins_have_required_fields(self):
        """Each pin config has name, pin_number, power_sym, conn_offset, wire_dir."""
        config = IC_POWER_CONFIG["CD4066BE"]
        for pin in config["pins"]:
            assert "name" in pin
            assert "pin_number" in pin
            assert "power_sym" in pin
            assert "conn_offset" in pin
            assert "wire_dir" in pin
