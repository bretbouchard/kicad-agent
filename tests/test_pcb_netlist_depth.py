"""Tests for P-BUG-006: pcb_netlist depth pre-scan protection.

Validates that deeply nested S-expression content raises ValueError
instead of RecursionError, and oversized content is rejected.
"""
from __future__ import annotations

import pytest

from kicad_agent.parser.pcb_netlist import extract_pcb_netlist


# Valid minimal PCB content with one pad
_VALID_PCB = '''\
(kicad_pcb
  (footprint "Resistor_SMD:R_0603" (at 10 20)
    (property "Reference" "R1")
    (pad 1 smd rect (at 5 5) (net 1 "GND"))
  )
)
'''


class TestPcbNetlistDepthPBUG006:
    """P-BUG-006: depth pre-scan protects against RecursionError."""

    def test_normal_content_parses(self):
        """Normal PCB content still parses correctly."""
        result = extract_pcb_netlist(_VALID_PCB)
        assert "GND" in result
        assert result["GND"] == [(5.0, 5.0)]

    def test_deeply_nested_raises_value_error(self):
        """Content exceeding 200 nesting depth raises ValueError."""
        deep = "(kicad_pcb " + "(" * 210 + "content" + ")" * 210 + ")"
        with pytest.raises(ValueError, match="200"):
            extract_pcb_netlist(deep)

    def test_oversized_raises_value_error(self):
        """Content exceeding 50MB raises ValueError."""
        huge = "(kicad_pcb " + "x" * (51 * 1024 * 1024) + ")"
        with pytest.raises(ValueError, match="50MB"):
            extract_pcb_netlist(huge)

    def test_exactly_200_depth_ok(self):
        """Content at exactly 200 depth does not raise."""
        content = "(kicad_pcb " + "(" * 199 + "ok" + ")" * 199 + ")"
        # This should not raise ValueError (depth reaches 200 exactly which is allowed)
        # but it will fail sexpdata parsing for other reasons, which returns {}
        result = extract_pcb_netlist(content)
        # Either ValueError from depth > 200 or empty dict from parse failure
        assert isinstance(result, dict)
