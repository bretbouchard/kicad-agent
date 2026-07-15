"""Tests for place_component PCB op (Phase 101-05).

Covers:
- PcbRawWriter.build_footprint_sexp for 0402/0603/0805 caps and resistors
- KiCad 10 string-only (net "NAME") pad format
- B.Cu layer mirroring and B-prefixed layer names
- Rotation via (at X Y ANGLE)
- Net injection from net_pad_map
- Unknown net handling (pad emitted without (net ...) field)
- UUID uniqueness across footprint + properties + pads
- Unsupported footprint ID raises ValueError
- Handler dispatch via OperationExecutor
- Pydantic schema validation for PlaceComponentOp
- Round-trip: place a component, then strip it
"""

import re
import tempfile
from pathlib import Path

import pytest

from volta.ops.pcb_raw_writer import PcbRawWriter


# ---------------------------------------------------------------------------
# Minimal PCB fixture
# ---------------------------------------------------------------------------

MINIMAL_PCB = """(kicad_pcb
  (version 20260125)
  (generator "volta-test")
  (general (thickness 1.6))
  (layers
    (0 "F.Cu" signal)
    (31 "B.Cu" signal)
  )
)
"""


@pytest.fixture
def pcb_path():
    """Write a minimal PCB file to a temp dir and return its Path."""
    with tempfile.TemporaryDirectory() as tmpdir:
        path = Path(tmpdir) / "test.kicad_pcb"
        path.write_text(MINIMAL_PCB, encoding="utf-8")
        yield path


# ---------------------------------------------------------------------------
# PcbRawWriter.build_footprint_sexp unit tests
# ---------------------------------------------------------------------------

class TestBuildFootprintSexp:
    """PcbRawWriter.build_footprint_sexp direct tests."""

    def test_place_component_cap_0402_basic(self):
        """0402 cap at (50,50) F.Cu produces a valid footprint block."""
        sexp = PcbRawWriter.build_footprint_sexp(
            footprint_id="Capacitor_SMD:C_0402_1005Metric",
            ref="C42", value="", at=(50.0, 50.0),
            layer="F.Cu", rotation=0,
            net_pad_map={"1": "+3V3", "2": "GND"},
        )
        assert '(footprint "C_0402_1005Metric"' in sexp
        assert "(at 50 50)" in sexp
        assert '(layer "F.Cu")' in sexp
        assert '(property "Reference" "C42"' in sexp
        # 0402 pad dims
        assert "(size 0.56 0.5)" in sexp
        assert "(at -0.22 0)" in sexp  # pad 1 X
        assert "(at 0.22 0)" in sexp   # pad 2 X

    def test_place_component_cap_0603(self):
        """0603 cap uses different pad dimensions than 0402."""
        sexp = PcbRawWriter.build_footprint_sexp(
            footprint_id="Capacitor_SMD:C_0603_1608Metric",
            ref="C23", value="2.2uF", at=(0.0, 0.0),
            layer="F.Cu", rotation=0,
            net_pad_map={},
        )
        assert '(footprint "C_0603_1608Metric"' in sexp
        # 0603 pad dims: 0.80 x 0.95, pitch 0.80 -> pad X = +/- 0.4
        assert "(size 0.8 0.95)" in sexp
        assert "(at -0.4 0)" in sexp
        assert "(at 0.4 0)" in sexp

    def test_place_component_resistor_0402(self):
        """Resistor 0402 has same pad geometry as cap 0402."""
        sexp = PcbRawWriter.build_footprint_sexp(
            footprint_id="Resistor_SMD:R_0402_1005Metric",
            ref="R15", value="100", at=(0.0, 0.0),
            layer="F.Cu", rotation=0,
            net_pad_map={},
        )
        assert '(footprint "R_0402_1005Metric"' in sexp
        assert '(tags "resistor")' in sexp
        assert '(property "Value" "100"' in sexp

    def test_place_component_unsupported_footprint(self):
        """Unsupported footprint ID raises ValueError with helpful message."""
        with pytest.raises(ValueError, match="Unsupported footprint"):
            PcbRawWriter.build_footprint_sexp(
                footprint_id="LED_SMD:LED_0603",
                ref="D1", value="", at=(0.0, 0.0),
            )
        # Also verify message lists supported IDs
        with pytest.raises(ValueError, match=r"Capacitor_SMD:C_0402_1005Metric"):
            PcbRawWriter.build_footprint_sexp(
                footprint_id="Inductor_SMD:L_0805",
                ref="L1", value="", at=(0.0, 0.0),
            )

    def test_place_component_b_cu_mirrored(self):
        """B.Cu footprint uses B-prefixed layers."""
        sexp = PcbRawWriter.build_footprint_sexp(
            footprint_id="Capacitor_SMD:C_0402_1005Metric",
            ref="C42", value="", at=(0.0, 0.0),
            layer="B.Cu", rotation=0,
            net_pad_map={},
        )
        assert '(layer "B.Cu")' in sexp
        assert '(layers "B.Cu" "B.Mask" "B.Paste")' in sexp
        assert '(layer "B.SilkS")' in sexp
        assert '(layer "B.Fab")' in sexp
        # Must NOT contain F.Cu-prefixed layers
        assert '"F.Cu" "F.Mask" "F.Paste"' not in sexp

    def test_place_component_rotation_90(self):
        """Rotation=90 produces (at X Y 90)."""
        sexp = PcbRawWriter.build_footprint_sexp(
            footprint_id="Capacitor_SMD:C_0805_2012Metric",
            ref="C1", value="", at=(10.0, 20.0),
            layer="F.Cu", rotation=90,
            net_pad_map={},
        )
        assert "(at 10 20 90)" in sexp

    def test_place_component_rotation_zero_omits_angle(self):
        """Rotation=0 omits the angle (KiCad convention)."""
        sexp = PcbRawWriter.build_footprint_sexp(
            footprint_id="Capacitor_SMD:C_0402_1005Metric",
            ref="C1", value="", at=(5.0, 5.0),
            layer="F.Cu", rotation=0,
            net_pad_map={},
        )
        # Should have (at 5 5) NOT (at 5 5 0)
        assert "(at 5 5)" in sexp
        assert "(at 5 5 0)" not in sexp

    def test_place_component_net_injection(self):
        """net_pad_map injects (net "NAME") into both pads."""
        sexp = PcbRawWriter.build_footprint_sexp(
            footprint_id="Capacitor_SMD:C_0402_1005Metric",
            ref="C42", value="", at=(0.0, 0.0),
            layer="F.Cu", rotation=0,
            net_pad_map={"1": "+3V3", "2": "GND"},
        )
        assert '(net "+3V3")' in sexp
        assert '(net "GND")' in sexp
        # Must NOT contain the legacy numbered form
        assert not re.search(r'\(net\s+\d+\s+"[^"]+"\)', sexp), \
            "Pad nets should use (net \"NAME\") not (net N \"NAME\")"

    def test_place_component_unknown_net_skipped(self):
        """Unknown net name still emits (net "NAME") -- lookups happen at DRC time.

        However, pads NOT in net_pad_map are emitted without (net ...) at all.
        """
        # Pad 1 has a net, pad 2 has no entry -> should have no (net ...) for pad 2
        sexp = PcbRawWriter.build_footprint_sexp(
            footprint_id="Capacitor_SMD:C_0402_1005Metric",
            ref="C42", value="", at=(0.0, 0.0),
            layer="F.Cu", rotation=0,
            net_pad_map={"1": "UNKNOWN_NET"},
        )
        # Pad 1 has the unknown net name verbatim (DRC will catch it)
        assert '(net "UNKNOWN_NET")' in sexp
        # Pad 2 should have no (net ...)
        # Extract pad 2 block
        pad2_match = re.search(
            r'\(pad "2"[^)]*(?:\([^)]*\)[^)]*)*\)', sexp, re.DOTALL,
        )
        assert pad2_match is not None, "Pad 2 block should exist"
        # Count net occurrences in pad 2 block specifically -- split on pads
        pad_blocks = re.split(r'\(pad "\d"', sexp)
        if len(pad_blocks) >= 3:
            pad2_block = pad_blocks[2]
            assert "(net " not in pad2_block, \
                "Pad 2 (not in net_pad_map) should have no (net ...) field"

    def test_place_component_unique_uuids(self):
        """Each call generates fresh UUIDs (footprint, ref, value, 2 pads = 5)."""
        sexp1 = PcbRawWriter.build_footprint_sexp(
            footprint_id="Capacitor_SMD:C_0402_1005Metric",
            ref="C1", value="", at=(0.0, 0.0),
        )
        sexp2 = PcbRawWriter.build_footprint_sexp(
            footprint_id="Capacitor_SMD:C_0402_1005Metric",
            ref="C2", value="", at=(0.0, 0.0),
        )
        uuids1 = re.findall(r'\(uuid "([^"]+)"\)', sexp1)
        uuids2 = re.findall(r'\(uuid "([^"]+)"\)', sexp2)
        # Should have 5 UUIDs each (footprint, ref prop, value prop, pad 1, pad 2)
        assert len(uuids1) == 5, f"Expected 5 UUIDs, got {len(uuids1)}"
        assert len(uuids2) == 5
        # All UUIDs unique within a single call
        assert len(set(uuids1)) == 5
        assert len(set(uuids2)) == 5
        # All UUIDs unique across calls
        assert not (set(uuids1) & set(uuids2))

    def test_place_component_no_lib_prefix_in_name(self):
        """Footprint name embedded in PCB has no library prefix.

        KiCad stores footprints as e.g. "C_0402_1005Metric" not
        "Capacitor_SMD:C_0402_1005Metric".
        """
        sexp = PcbRawWriter.build_footprint_sexp(
            footprint_id="Capacitor_SMD:C_0402_1005Metric",
            ref="C1", value="", at=(0.0, 0.0),
        )
        assert '(footprint "C_0402_1005Metric"' in sexp
        assert "Capacitor_SMD:" not in sexp


# ---------------------------------------------------------------------------
# list_supported_footprints
# ---------------------------------------------------------------------------

class TestListSupportedFootprints:
    """PcbRawWriter.list_supported_footprints tests."""

    def test_six_supported_footprints(self):
        """Target: 6 footprints (0402/0603/0805 cap + resistor)."""
        supported = PcbRawWriter.list_supported_footprints()
        assert len(supported) == 6

    def test_expected_set(self):
        """All 6 expected IDs are present."""
        supported = set(PcbRawWriter.list_supported_footprints())
        expected = {
            "Capacitor_SMD:C_0402_1005Metric",
            "Capacitor_SMD:C_0603_1608Metric",
            "Capacitor_SMD:C_0805_2012Metric",
            "Resistor_SMD:R_0402_1005Metric",
            "Resistor_SMD:R_0603_1608Metric",
            "Resistor_SMD:R_0805_2012Metric",
        }
        assert supported == expected


# ---------------------------------------------------------------------------
# Pydantic schema validation
# ---------------------------------------------------------------------------

class TestPlaceComponentSchema:
    """PlaceComponentOp Pydantic validation."""

    def test_valid_op(self):
        from volta.ops._schema_pcb import PlaceComponentOp
        op = PlaceComponentOp(
            op_type="place_component",
            target_file="test.kicad_pcb",
            ref="C42",
            footprint="Capacitor_SMD:C_0402_1005Metric",
            at=(50.0, 50.0),
            layer="F.Cu",
            rotation=0,
            net_pad_map={"1": "+3V3", "2": "GND"},
        )
        assert op.ref == "C42"
        assert op.footprint == "Capacitor_SMD:C_0402_1005Metric"
        assert op.layer == "F.Cu"

    def test_invalid_layer_rejected(self):
        from volta.ops._schema_pcb import PlaceComponentOp
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            PlaceComponentOp(
                op_type="place_component",
                target_file="test.kicad_pcb",
                ref="C42",
                footprint="Capacitor_SMD:C_0402_1005Metric",
                at=(0.0, 0.0),
                layer="In1.Cu",  # invalid
            )

    def test_invalid_ref_rejected(self):
        """Reference designator cannot contain parens/quotes."""
        from volta.ops._schema_pcb import PlaceComponentOp
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            PlaceComponentOp(
                op_type="place_component",
                target_file="test.kicad_pcb",
                ref='C42"(evil)',  # unsafe chars
                footprint="Capacitor_SMD:C_0402_1005Metric",
                at=(0.0, 0.0),
            )

    def test_defaults_layer_and_rotation(self):
        from volta.ops._schema_pcb import PlaceComponentOp
        op = PlaceComponentOp(
            op_type="place_component",
            target_file="test.kicad_pcb",
            ref="C42",
            footprint="Capacitor_SMD:C_0402_1005Metric",
            at=(0.0, 0.0),
        )
        assert op.layer == "F.Cu"
        assert op.rotation == 0.0
        assert op.net_pad_map == {}


# ---------------------------------------------------------------------------
# OperationExecutor integration
# ---------------------------------------------------------------------------

class TestPlaceComponentExecutor:
    """End-to-end handler dispatch via OperationExecutor."""

    def test_place_component_via_executor(self, pcb_path):
        from volta.ir.base import _clear_registry
        _clear_registry()

        from volta.ops.executor import OperationExecutor
        from volta.ops.schema import Operation

        op = Operation.model_validate({
            "root": {
                "op_type": "place_component",
                "target_file": pcb_path.name,
                "ref": "C42",
                "footprint": "Capacitor_SMD:C_0402_1005Metric",
                "at": [50.0, 50.0],
                "layer": "F.Cu",
                "rotation": 0,
                "net_pad_map": {"1": "+3V3", "2": "GND"},
            }
        })

        executor = OperationExecutor(base_dir=pcb_path.parent)
        result = executor.execute(op)

        assert result["success"] is True
        assert result["operation"] == "place_component"
        content = pcb_path.read_text(encoding="utf-8")
        assert "(footprint" in content
        assert '(property "Reference" "C42"' in content
        assert '(net "+3V3")' in content
        assert '(net "GND")' in content

    def test_executor_unsupported_footprint_raises(self, pcb_path):
        """Unsupported footprint via executor propagates ValueError."""
        from volta.ir.base import _clear_registry
        _clear_registry()

        from volta.ops.executor import OperationExecutor
        from volta.ops.schema import Operation

        op = Operation.model_validate({
            "root": {
                "op_type": "place_component",
                "target_file": pcb_path.name,
                "ref": "D1",
                "footprint": "LED_SMD:LED_0603",  # unsupported
                "at": [0.0, 0.0],
            }
        })

        executor = OperationExecutor(base_dir=pcb_path.parent)
        with pytest.raises(ValueError, match="Unsupported footprint"):
            executor.execute(op)

    def test_two_components_unique_uuids_on_disk(self, pcb_path):
        """Two consecutive place_component ops produce all-unique UUIDs on disk."""
        from volta.ir.base import _clear_registry
        _clear_registry()

        from volta.ops.executor import OperationExecutor
        from volta.ops.schema import Operation

        executor = OperationExecutor(base_dir=pcb_path.parent)

        for ref, x in (("C42", 10.0), ("C43", 20.0)):
            _clear_registry()
            op = Operation.model_validate({
                "root": {
                    "op_type": "place_component",
                    "target_file": pcb_path.name,
                    "ref": ref,
                    "footprint": "Capacitor_SMD:C_0402_1005Metric",
                    "at": [x, 0.0],
                    "net_pad_map": {"1": "VCC", "2": "GND"},
                }
            })
            result = executor.execute(op)
            assert result["success"] is True

        content = pcb_path.read_text(encoding="utf-8")
        uuids = re.findall(r'\(uuid "([^"]+)"\)', content)
        assert len(uuids) >= 10  # 5 per footprint
        assert len(set(uuids)) == len(uuids), \
            "All UUIDs on disk should be unique"


# ---------------------------------------------------------------------------
# Round-trip: place a component, then strip it
# ---------------------------------------------------------------------------

class TestPlaceComponentRoundTrip:
    """Round-trip: place then strip via raw manipulation."""

    def test_round_trip_place_then_delete_via_strip(self, pcb_path):
        """Place a component, then strip all footprints by writing back the minimal PCB.

        This is a sanity round-trip -- we don't have a delete_footprint op yet,
        so we verify that placing a component adds bytes and stripping (by
        re-writing the original minimal PCB) removes them cleanly.
        """
        from volta.ir.base import _clear_registry
        _clear_registry()

        from volta.ops.executor import OperationExecutor
        from volta.ops.schema import Operation

        # Place
        op = Operation.model_validate({
            "root": {
                "op_type": "place_component",
                "target_file": pcb_path.name,
                "ref": "C42",
                "footprint": "Capacitor_SMD:C_0402_1005Metric",
                "at": [50.0, 50.0],
                "net_pad_map": {"1": "+3V3", "2": "GND"},
            }
        })

        executor = OperationExecutor(base_dir=pcb_path.parent)
        result = executor.execute(op)
        assert result["success"] is True

        content_after_place = pcb_path.read_text(encoding="utf-8")
        assert "(footprint" in content_after_place

        # Strip by re-writing the original minimal PCB (simulates a clean checkout)
        pcb_path.write_text(MINIMAL_PCB, encoding="utf-8")
        content_after_strip = pcb_path.read_text(encoding="utf-8")
        assert "(footprint" not in content_after_strip
        assert '(net "+3V3")' not in content_after_strip

    def test_round_trip_place_three_distinct_footprints(self, pcb_path):
        """Place three distinct footprints and verify all three are on disk."""
        from volta.ir.base import _clear_registry
        _clear_registry()

        from volta.ops.executor import OperationExecutor
        from volta.ops.schema import Operation

        executor = OperationExecutor(base_dir=pcb_path.parent)

        specs = [
            ("C1", "Capacitor_SMD:C_0402_1005Metric", 10.0),
            ("C2", "Capacitor_SMD:C_0603_1608Metric", 20.0),
            ("R1", "Resistor_SMD:R_0805_2012Metric",  30.0),
        ]
        for ref, fp, x in specs:
            _clear_registry()
            op = Operation.model_validate({
                "root": {
                    "op_type": "place_component",
                    "target_file": pcb_path.name,
                    "ref": ref,
                    "footprint": fp,
                    "at": [x, 0.0],
                }
            })
            result = executor.execute(op)
            assert result["success"] is True

        content = pcb_path.read_text(encoding="utf-8")
        assert '(footprint "C_0402_1005Metric"' in content
        assert '(footprint "C_0603_1608Metric"' in content
        assert '(footprint "R_0805_2012Metric"' in content
        # Three refs
        assert '(property "Reference" "C1"' in content
        assert '(property "Reference" "C2"' in content
        assert '(property "Reference" "R1"' in content
