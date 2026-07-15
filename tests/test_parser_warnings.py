"""Tests for _UNSUPPORTED_ELEMENTS constant and parser warning logging.

TDD RED phase: These tests define the expected behavior for the unsupported
element tracking in pcb_native_parser.py. The constant and warning logging
do not yet exist.
"""

import logging

import pytest

from volta.parser.pcb_native_parser import (
    NativeParser,
    _UNSUPPORTED_ELEMENTS,
    _check_unsupported,
)


# ---------------------------------------------------------------------------
# Tests 1-9: _UNSUPPORTED_ELEMENTS constant
# ---------------------------------------------------------------------------


class TestUnsupportedElementsConstant:
    """Verify _UNSUPPORTED_ELEMENTS frozenset contains expected element types."""

    def test_constant_is_frozenset(self):
        """_UNSUPPORTED_ELEMENTS should be a frozenset[str]."""
        assert isinstance(_UNSUPPORTED_ELEMENTS, frozenset)

    def test_constant_has_at_least_9_elements(self):
        """_UNSUPPORTED_ELEMENTS should contain at least 9 elements."""
        assert len(_UNSUPPORTED_ELEMENTS) >= 9

    def test_contains_thermal_relief_pads(self):
        assert "thermal_relief_pads" in _UNSUPPORTED_ELEMENTS

    def test_contains_keepout_areas(self):
        assert "keepout_areas" in _UNSUPPORTED_ELEMENTS

    def test_contains_soldermask_expansion(self):
        assert "soldermask_expansion" in _UNSUPPORTED_ELEMENTS

    def test_contains_paste_expansion(self):
        assert "paste_expansion" in _UNSUPPORTED_ELEMENTS

    def test_contains_fp_text(self):
        assert "fp_text" in _UNSUPPORTED_ELEMENTS

    def test_contains_3d_model_refs(self):
        assert "3d_model_refs" in _UNSUPPORTED_ELEMENTS

    def test_contains_page_info(self):
        assert "page_info" in _UNSUPPORTED_ELEMENTS

    def test_contains_title_block(self):
        assert "title_block" in _UNSUPPORTED_ELEMENTS


# ---------------------------------------------------------------------------
# Tests 10-11: Warning logging behavior
# ---------------------------------------------------------------------------

# Minimal valid PCB content with all supported elements for test 11
_MINIMAL_PCB_SUPPORTED = """\
(kicad_pcb
  (version 20231010)
  (generator "kicad")
  (general (thickness 1.6))
  (net 0 "")
  (net 1 "GND")
  (segment (start 0 0) (end 10 10) (width 0.25) (layer "F.Cu") (net 1))
  (via (at 5 5) (size 0.8) (drill 0.4) (net 1) (layers "F.Cu" "B.Cu"))
  (gr_line (start 0 0) (end 100 0) (layer "Edge.Cuts") (width 0.1))
  (zone (net 1) (net_name "GND") (layer "F.Cu") (uuid "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
    (filled_polygon (layer "F.Cu") (pts (xy 0 0) (xy 100 0) (xy 100 100) (xy 0 100))))
)
"""

# PCB content containing an unsupported element (title_block) for test 10
_PCB_WITH_UNSUPPORTED = """\
(kicad_pcb
  (version 20231010)
  (generator "kicad")
  (general (thickness 1.6))
  (title_block
    (title "Test Board")
    (rev "1.0")
    (company "ACME")
  )
)
"""


class TestUnsupportedElementWarnings:
    """Verify parser logs warnings when encountering unsupported elements."""

    def test_unsupported_element_triggers_warning(self, caplog):
        """Parsing a PCB with title_block should emit a warning."""
        with caplog.at_level(logging.WARNING, logger="volta.parser.pcb_native_parser"):
            NativeParser.parse_pcb_content(_PCB_WITH_UNSUPPORTED)

        assert any(
            "Unsupported element" in record.message
            for record in caplog.records
        ), f"Expected 'Unsupported element' warning. Got: {[r.message for r in caplog.records]}"

    def test_supported_elements_no_warning(self, caplog):
        """Parsing a PCB with only supported elements should NOT emit unsupported warnings."""
        with caplog.at_level(logging.WARNING, logger="volta.parser.pcb_native_parser"):
            NativeParser.parse_pcb_content(_MINIMAL_PCB_SUPPORTED)

        unsupported_msgs = [
            record.message
            for record in caplog.records
            if "Unsupported element" in record.message
        ]
        assert len(unsupported_msgs) == 0, (
            f"Expected no unsupported warnings. Got: {unsupported_msgs}"
        )


# ---------------------------------------------------------------------------
# Test for _check_unsupported helper function directly
# ---------------------------------------------------------------------------


class TestCheckUnsupportedHelper:
    """Verify _check_unsupported helper function behavior."""

    def test_unsupported_element_logs_warning(self, caplog):
        """_check_unsupported should log warning for unsupported elements."""
        with caplog.at_level(logging.WARNING, logger="volta.parser.pcb_native_parser"):
            _check_unsupported("thermal_relief_pads")

        assert any(
            "Unsupported element" in record.message
            for record in caplog.records
        )

    def test_unsupported_element_with_context(self, caplog):
        """_check_unsupported should include context in warning message."""
        with caplog.at_level(logging.WARNING, logger="volta.parser.pcb_native_parser"):
            _check_unsupported("keepout_areas", "footprint U1")

        assert any(
            "in footprint U1" in record.message
            for record in caplog.records
        )

    def test_supported_element_no_warning(self, caplog):
        """_check_unsupported should NOT log for supported elements."""
        with caplog.at_level(logging.WARNING, logger="volta.parser.pcb_native_parser"):
            _check_unsupported("net")

        unsupported_msgs = [
            record.message
            for record in caplog.records
            if "Unsupported element" in record.message
        ]
        assert len(unsupported_msgs) == 0

    def test_warning_message_references_constant(self, caplog):
        """Warning message should reference _UNSUPPORTED_ELEMENTS for discoverability."""
        with caplog.at_level(logging.WARNING, logger="volta.parser.pcb_native_parser"):
            _check_unsupported("fp_text")

        assert any(
            "_UNSUPPORTED_ELEMENTS" in record.message
            for record in caplog.records
        ), "Warning should reference _UNSUPPORTED_ELEMENTS constant"
