"""Tests for add_track, add_arc_track, and add_via PCB ops (Phase 101-01).

Covers:
- PcbRawWriter.build_segment_sexp / build_arc_sexp / build_via_sexp
- KiCad 10 net format (string-only, not numbered)
- UUID uniqueness across multiple invocations
- Handler dispatch via OperationExecutor
- Pydantic schema validation for AddTrackOp / AddArcTrackOp / AddViaOp
"""

import re
import tempfile
from pathlib import Path

import pytest

from kicad_agent.ops.pcb_raw_writer import PcbRawWriter


# ---------------------------------------------------------------------------
# Minimal PCB fixture
# ---------------------------------------------------------------------------

MINIMAL_PCB = """(kicad_pcb
  (version 20260125)
  (generator "kicad-agent-test")
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
# PcbRawWriter unit tests
# ---------------------------------------------------------------------------

class TestBuildSegmentSexp:
    """PcbRawWriter.build_segment_sexp direct tests."""

    def test_add_track_basic(self):
        """Segment block contains start/end/width/layer/net."""
        sexp = PcbRawWriter.build_segment_sexp(
            start=(100.0, 50.0),
            end=(105.0, 50.0),
            width=0.2,
            layer="F.Cu",
            net_name="GND",
        )
        assert "(segment" in sexp
        assert "(start 100 50)" in sexp
        assert "(end 105 50)" in sexp
        assert "(width 0.2)" in sexp
        assert '(layer "F.Cu")' in sexp

    def test_add_track_kicad10_net_format(self):
        """Net field uses (net "NAME") string-only form, NOT (net N "NAME")."""
        sexp = PcbRawWriter.build_segment_sexp(
            start=(0.0, 0.0),
            end=(1.0, 0.0),
            width=0.2,
            layer="F.Cu",
            net_name="GND",
        )
        # Must contain string-only form
        assert '(net "GND")' in sexp
        # Must NOT contain the legacy numbered form
        assert not re.search(r'\(net\s+\d+\s+"GND"\)', sexp), \
            "Segment should use (net \"NAME\") not (net N \"NAME\")"

    def test_add_track_uuid_unique(self):
        """Two calls produce different UUIDs."""
        sexp1 = PcbRawWriter.build_segment_sexp(
            start=(0.0, 0.0), end=(1.0, 0.0), width=0.2, layer="F.Cu", net_name="A",
        )
        sexp2 = PcbRawWriter.build_segment_sexp(
            start=(0.0, 0.0), end=(1.0, 0.0), width=0.2, layer="F.Cu", net_name="A",
        )
        uuid1 = re.search(r'\(uuid "([^"]+)"\)', sexp1).group(1)
        uuid2 = re.search(r'\(uuid "([^"]+)"\)', sexp2).group(1)
        assert uuid1 != uuid2

    def test_add_track_uuid_format(self):
        """Generated UUID matches uuid4 format (36 chars, hyphens)."""
        sexp = PcbRawWriter.build_segment_sexp(
            start=(0.0, 0.0), end=(1.0, 0.0), width=0.2, layer="F.Cu", net_name="A",
        )
        m = re.search(r'\(uuid "([^"]+)"\)', sexp)
        assert m is not None
        assert re.match(
            r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$',
            m.group(1),
        )

    def test_add_track_explicit_uuid_used(self):
        """Caller-supplied UUID is preserved."""
        sexp = PcbRawWriter.build_segment_sexp(
            start=(0.0, 0.0), end=(1.0, 0.0), width=0.2, layer="F.Cu",
            net_name="A", uuid_str="deadbeef-0000-0000-0000-000000000001",
        )
        assert '(uuid "deadbeef-0000-0000-0000-000000000001")' in sexp


class TestBuildArcSexp:
    """PcbRawWriter.build_arc_sexp direct tests."""

    def test_add_arc_track_basic(self):
        """Arc block contains start/mid/end/width/layer/net."""
        sexp = PcbRawWriter.build_arc_sexp(
            start=(0.0, 0.0),
            mid=(5.0, 5.0),
            end=(10.0, 0.0),
            width=0.2,
            layer="F.Cu",
            net_name="/CLK",
        )
        assert "(arc" in sexp
        assert "(start 0 0)" in sexp
        assert "(mid 5 5)" in sexp
        assert "(end 10 0)" in sexp
        assert '(net "/CLK")' in sexp
        assert '(layer "F.Cu")' in sexp

    def test_add_arc_track_kicad10_net_format(self):
        """Arc uses string-only net form."""
        sexp = PcbRawWriter.build_arc_sexp(
            start=(0.0, 0.0), mid=(1.0, 1.0), end=(2.0, 0.0),
            width=0.15, layer="In1.Cu", net_name="SIG",
        )
        assert '(net "SIG")' in sexp
        assert not re.search(r'\(net\s+\d+\s+"SIG"\)', sexp)

    def test_add_arc_track_uuid_unique(self):
        """Two arc calls produce different UUIDs."""
        a = PcbRawWriter.build_arc_sexp(
            start=(0.0, 0.0), mid=(1.0, 1.0), end=(2.0, 0.0),
            width=0.15, layer="F.Cu", net_name="X",
        )
        b = PcbRawWriter.build_arc_sexp(
            start=(0.0, 0.0), mid=(1.0, 1.0), end=(2.0, 0.0),
            width=0.15, layer="F.Cu", net_name="X",
        )
        u_a = re.search(r'\(uuid "([^"]+)"\)', a).group(1)
        u_b = re.search(r'\(uuid "([^"]+)"\)', b).group(1)
        assert u_a != u_b


class TestBuildViaSexp:
    """PcbRawWriter.build_via_sexp direct tests."""

    def test_add_via_basic(self):
        """Via block contains at/size/drill/layers/net."""
        sexp = PcbRawWriter.build_via_sexp(
            at=(100.0, 50.0),
            size=0.7,
            drill=0.3,
            layers=["F.Cu", "B.Cu"],
            net_name="GND",
        )
        assert "(via" in sexp
        assert "(at 100 50)" in sexp
        assert "(size 0.7)" in sexp
        assert "(drill 0.3)" in sexp
        assert '(layers "F.Cu" "B.Cu")' in sexp
        assert '(net "GND")' in sexp

    def test_add_via_standard_geometry(self):
        """Default JLC 4-layer floor: size=0.7, drill=0.3."""
        sexp = PcbRawWriter.build_via_sexp(
            at=(10.0, 10.0), size=0.7, drill=0.3,
            layers=["F.Cu", "B.Cu"], net_name="VCC",
        )
        assert "(size 0.7)" in sexp
        assert "(drill 0.3)" in sexp

    def test_add_via_multilayer(self):
        """4-layer stackup: F.Cu, In1.Cu, In2.Cu, B.Cu."""
        sexp = PcbRawWriter.build_via_sexp(
            at=(20.0, 20.0),
            size=0.6,
            drill=0.25,
            layers=["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"],
            net_name="AGND",
        )
        assert '(layers "F.Cu" "In1.Cu" "In2.Cu" "B.Cu")' in sexp

    def test_add_via_kicad10_net_format(self):
        """Via uses string-only net form."""
        sexp = PcbRawWriter.build_via_sexp(
            at=(0.0, 0.0), size=0.7, drill=0.3,
            layers=["F.Cu", "B.Cu"], net_name="GND",
        )
        assert '(net "GND")' in sexp
        assert not re.search(r'\(net\s+\d+\s+"GND"\)', sexp)

    def test_add_via_uuid_unique(self):
        """Two vias produce different UUIDs."""
        a = PcbRawWriter.build_via_sexp(
            at=(0.0, 0.0), size=0.6, drill=0.3,
            layers=["F.Cu", "B.Cu"], net_name="A",
        )
        b = PcbRawWriter.build_via_sexp(
            at=(0.0, 0.0), size=0.6, drill=0.3,
            layers=["F.Cu", "B.Cu"], net_name="A",
        )
        u_a = re.search(r'\(uuid "([^"]+)"\)', a).group(1)
        u_b = re.search(r'\(uuid "([^"]+)"\)', b).group(1)
        assert u_a != u_b


# ---------------------------------------------------------------------------
# Insertion via insert_segments
# ---------------------------------------------------------------------------

class TestInsertion:
    """Verify the new S-expressions insert cleanly before the closing paren."""

    def test_segment_inserts_before_close(self):
        """Segment is inserted before final ')' of the PCB."""
        new = PcbRawWriter.insert_segments(MINIMAL_PCB, PcbRawWriter.build_segment_sexp(
            start=(1.0, 2.0), end=(3.0, 4.0), width=0.2, layer="F.Cu", net_name="N",
        ))
        # Last non-whitespace char should still be ')'
        assert new.rstrip().endswith(")")
        # Segment should be in the middle, not after the final paren
        assert "(segment" in new
        # Final closing paren of (segment ...) should come before the file's final ')'
        idx_seg = new.find("(segment")
        idx_last_close = new.rfind(")")
        assert idx_seg < idx_last_close

    def test_via_inserts_before_close(self):
        new = PcbRawWriter.insert_segments(MINIMAL_PCB, PcbRawWriter.build_via_sexp(
            at=(0.0, 0.0), size=0.7, drill=0.3,
            layers=["F.Cu", "B.Cu"], net_name="GND",
        ))
        assert "(via" in new
        assert new.rstrip().endswith(")")

    def test_arc_inserts_before_close(self):
        new = PcbRawWriter.insert_segments(MINIMAL_PCB, PcbRawWriter.build_arc_sexp(
            start=(0.0, 0.0), mid=(1.0, 1.0), end=(2.0, 0.0),
            width=0.15, layer="F.Cu", net_name="X",
        ))
        assert "(arc" in new
        assert new.rstrip().endswith(")")


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------

class TestSchemas:
    """Pydantic schemas for AddTrackOp / AddArcTrackOp / AddViaOp."""

    def test_add_track_schema(self):
        from kicad_agent.ops._schema_pcb import AddTrackOp
        op = AddTrackOp(
            target_file="test.kicad_pcb",
            net="GND",
            start=(100.0, 50.0),
            end=(105.0, 50.0),
        )
        assert op.op_type == "add_track"
        assert op.net == "GND"
        assert op.width == 0.2  # default
        assert op.layer == "F.Cu"  # default
        assert tuple(op.start) == (100.0, 50.0)

    def test_add_arc_track_schema(self):
        from kicad_agent.ops._schema_pcb import AddArcTrackOp
        op = AddArcTrackOp(
            target_file="test.kicad_pcb",
            net="CLK",
            start=(0.0, 0.0),
            mid=(5.0, 5.0),
            end=(10.0, 0.0),
        )
        assert op.op_type == "add_arc_track"
        assert tuple(op.mid) == (5.0, 5.0)

    def test_add_via_schema_defaults(self):
        from kicad_agent.ops._schema_pcb import AddViaOp
        op = AddViaOp(
            target_file="test.kicad_pcb",
            net="GND",
            at=(10.0, 20.0),
        )
        assert op.op_type == "add_via"
        assert op.size == 0.7  # JLC default
        assert op.drill == 0.3  # JLC default
        assert op.layers == ["F.Cu", "B.Cu"]

    def test_add_via_schema_multilayer(self):
        from kicad_agent.ops._schema_pcb import AddViaOp
        op = AddViaOp(
            target_file="test.kicad_pcb",
            net="GND",
            at=(10.0, 20.0),
            layers=["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"],
        )
        assert len(op.layers) == 4

    def test_schema_empty_net_rejected(self):
        from kicad_agent.ops._schema_pcb import AddTrackOp
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            AddTrackOp(
                target_file="test.kicad_pcb",
                net="",
                start=(0.0, 0.0),
                end=(1.0, 0.0),
            )


# ---------------------------------------------------------------------------
# Handler integration via OperationExecutor
# ---------------------------------------------------------------------------

class TestHandlerExecution:
    """End-to-end: dispatch through OperationExecutor writes to disk."""

    def test_add_track_via_executor(self, pcb_path, monkeypatch):
        """add_track dispatches through executor and writes the segment."""
        from kicad_agent.ir.base import _clear_registry
        _clear_registry()

        from kicad_agent.ops.executor import OperationExecutor
        from kicad_agent.ops.schema import Operation

        op = Operation.model_validate({
            "root": {
                "op_type": "add_track",
                "target_file": pcb_path.name,
                "net": "GND",
                "start": [100.0, 50.0],
                "end": [105.0, 50.0],
                "width": 0.2,
                "layer": "F.Cu",
            }
        })

        executor = OperationExecutor(base_dir=pcb_path.parent)
        result = executor.execute(op)

        assert result["success"] is True
        assert result["operation"] == "add_track"
        content = pcb_path.read_text(encoding="utf-8")
        assert "(segment" in content
        assert '(net "GND")' in content
        # KiCad 10 string-only form
        assert not re.search(r'\(net\s+\d+\s+"GND"\)', content)

    def test_add_arc_track_via_executor(self, pcb_path):
        from kicad_agent.ir.base import _clear_registry
        _clear_registry()

        from kicad_agent.ops.executor import OperationExecutor
        from kicad_agent.ops.schema import Operation

        op = Operation.model_validate({
            "root": {
                "op_type": "add_arc_track",
                "target_file": pcb_path.name,
                "net": "CLK",
                "start": [0.0, 0.0],
                "mid": [5.0, 5.0],
                "end": [10.0, 0.0],
                "width": 0.15,
                "layer": "F.Cu",
            }
        })

        executor = OperationExecutor(base_dir=pcb_path.parent)
        result = executor.execute(op)

        assert result["success"] is True
        content = pcb_path.read_text(encoding="utf-8")
        assert "(arc" in content
        assert "(mid 5 5)" in content
        assert '(net "CLK")' in content

    def test_add_via_via_executor(self, pcb_path):
        from kicad_agent.ir.base import _clear_registry
        _clear_registry()

        from kicad_agent.ops.executor import OperationExecutor
        from kicad_agent.ops.schema import Operation

        op = Operation.model_validate({
            "root": {
                "op_type": "add_via",
                "target_file": pcb_path.name,
                "net": "GND",
                "at": [10.0, 20.0],
                "size": 0.7,
                "drill": 0.3,
                "layers": ["F.Cu", "B.Cu"],
            }
        })

        executor = OperationExecutor(base_dir=pcb_path.parent)
        result = executor.execute(op)

        assert result["success"] is True
        content = pcb_path.read_text(encoding="utf-8")
        assert "(via" in content
        assert "(at 10 20)" in content
        assert "(size 0.7)" in content
        assert "(drill 0.3)" in content
        assert '(layers "F.Cu" "B.Cu")' in content
        assert '(net "GND")' in content

    def test_two_tracks_unique_uuids_on_disk(self, pcb_path):
        """Two consecutive add_track ops produce two different UUIDs on disk."""
        from kicad_agent.ir.base import _clear_registry
        _clear_registry()

        from kicad_agent.ops.executor import OperationExecutor
        from kicad_agent.ops.schema import Operation

        executor = OperationExecutor(base_dir=pcb_path.parent)

        for x_end in (50.0, 75.0):
            _clear_registry()
            op = Operation.model_validate({
                "root": {
                    "op_type": "add_track",
                    "target_file": pcb_path.name,
                    "net": "SIG",
                    "start": [0.0, 0.0],
                    "end": [x_end, 0.0],
                    "width": 0.2,
                    "layer": "F.Cu",
                }
            })
            result = executor.execute(op)
            assert result["success"] is True

        content = pcb_path.read_text(encoding="utf-8")
        uuids = re.findall(r'\(uuid "([^"]+)"\)', content)
        assert len(uuids) >= 2
        assert len(set(uuids)) == len(uuids), "All UUIDs on disk should be unique"
