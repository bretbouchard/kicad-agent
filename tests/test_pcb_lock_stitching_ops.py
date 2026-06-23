"""Tests for lock_track, lock_via, and add_stitching_via_pattern ops (Phase 101-03).

Covers:
- PcbRawWriter.lock_segment / lock_via -- inject ``(locked)`` token
- Idempotency -- locking an already-locked block is a no-op
- ValueError on unknown UUIDs
- ``(locked)`` placement: BEFORE other properties (KiCad 10 format)
- PcbRawWriter.build_stitching_via_pattern -- grid generation
- Multi-layer via support (F.Cu + In1.Cu + B.Cu)
- UUID uniqueness across generated vias
- Handler dispatch via OperationExecutor
"""

import re
import tempfile
from pathlib import Path

import pytest

from kicad_agent.ops.pcb_raw_writer import PcbRawWriter


# ---------------------------------------------------------------------------
# Minimal PCB fixture (matches test_pcb_track_via_ops.py for consistency)
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
# PcbRawWriter.lock_segment unit tests
# ---------------------------------------------------------------------------

class TestLockSegment:
    """PcbRawWriter.lock_segment direct tests."""

    def test_lock_track_basic(self):
        """Locking a segment injects ``(locked)`` into the block."""
        uuid_a = "aaaaaaaa-0000-0000-0000-000000000001"
        content = MINIMAL_PCB + PcbRawWriter.build_segment_sexp(
            start=(0.0, 0.0), end=(10.0, 0.0),
            width=0.2, layer="F.Cu", net_name="GND", uuid_str=uuid_a,
        )

        assert "(locked)" not in content, "Precondition: no locked token yet"
        result = PcbRawWriter.lock_segment(content, uuid_a)

        assert "(locked)" in result, "Locked token must appear after lock_segment"
        assert uuid_a in result, "Segment must still be present"

    def test_lock_track_syntax_correctness(self):
        """``(locked)`` appears BEFORE other properties (KiCad 10 format).

        The format must be ``(segment (locked) (start ...) (end ...) ...)``
        -- the locked token goes immediately after the opening kind token.
        """
        uuid_a = "aaaaaaaa-0000-0000-0000-000000000001"
        content = MINIMAL_PCB + PcbRawWriter.build_segment_sexp(
            start=(0.0, 0.0), end=(10.0, 0.0),
            width=0.2, layer="F.Cu", net_name="GND", uuid_str=uuid_a,
        )

        result = PcbRawWriter.lock_segment(content, uuid_a)

        # Extract the segment block
        m = re.search(r"\(segment[^)]*\([^)]*\)[^)]*\)[^)]*\)", result, re.DOTALL)
        # Easier: find the line containing (segment and check it's followed by (locked)
        # The first occurrence of (segment should be immediately followed by (locked)
        seg_idx = result.find("(segment")
        assert seg_idx >= 0, "Segment must exist"
        # Look at the first 80 chars after the (segment token
        head = result[seg_idx:seg_idx + 30]
        assert "(locked)" in head, \
            f"(locked) must be in first 30 chars after (segment, got: {head!r}"

        # Also verify (locked) appears before (start ...)
        locked_idx = result.find("(locked)", seg_idx)
        start_idx = result.find("(start", seg_idx)
        assert 0 <= locked_idx < start_idx, \
            "(locked) must come before (start ...) in the segment block"

    def test_lock_track_idempotent(self):
        """Locking an already-locked segment is a no-op."""
        uuid_a = "aaaaaaaa-0000-0000-0000-000000000001"
        content = MINIMAL_PCB + PcbRawWriter.build_segment_sexp(
            start=(0.0, 0.0), end=(10.0, 0.0),
            width=0.2, layer="F.Cu", net_name="GND", uuid_str=uuid_a,
        )

        locked_once = PcbRawWriter.lock_segment(content, uuid_a)
        locked_twice = PcbRawWriter.lock_segment(locked_once, uuid_a)

        assert locked_twice == locked_once, \
            "Locking an already-locked segment must be a no-op"
        # Count occurrences -- exactly one (locked) for this segment
        assert locked_twice.count("(locked)") == 1

    def test_lock_track_not_found(self):
        """Unknown UUID raises ValueError."""
        with pytest.raises(ValueError, match="not found"):
            PcbRawWriter.lock_segment(MINIMAL_PCB, "no-such-uuid-anywhere")

    def test_lock_track_other_segments_untouched(self):
        """Locking one segment does not add (locked) to another."""
        uuid_a = "aaaaaaaa-0000-0000-0000-000000000001"
        uuid_b = "bbbbbbbb-0000-0000-0000-000000000002"
        content = MINIMAL_PCB + PcbRawWriter.build_segment_sexp(
            start=(0.0, 0.0), end=(10.0, 0.0),
            width=0.2, layer="F.Cu", net_name="GND", uuid_str=uuid_a,
        ) + PcbRawWriter.build_segment_sexp(
            start=(10.0, 0.0), end=(20.0, 0.0),
            width=0.2, layer="F.Cu", net_name="GND", uuid_str=uuid_b,
        )

        result = PcbRawWriter.lock_segment(content, uuid_a)

        assert result.count("(locked)") == 1, \
            "Only the target segment must be locked"


# ---------------------------------------------------------------------------
# PcbRawWriter.lock_via unit tests
# ---------------------------------------------------------------------------

class TestLockVia:
    """PcbRawWriter.lock_via direct tests."""

    def test_lock_via_basic(self):
        """Locking a via injects ``(locked)`` into the block."""
        uuid_a = "cccccccc-0000-0000-0000-000000000003"
        content = MINIMAL_PCB + PcbRawWriter.build_via_sexp(
            at=(10.0, 20.0), size=0.4, drill=0.2,
            layers=["F.Cu", "B.Cu"], net_name="GND", uuid_str=uuid_a,
        )

        assert "(locked)" not in content
        result = PcbRawWriter.lock_via(content, uuid_a)

        assert "(locked)" in result
        assert uuid_a in result, "Via must still be present"

    def test_lock_via_syntax_correctness(self):
        """``(locked)`` appears before (at ...) in the via block."""
        uuid_a = "cccccccc-0000-0000-0000-000000000003"
        content = MINIMAL_PCB + PcbRawWriter.build_via_sexp(
            at=(10.0, 20.0), size=0.4, drill=0.2,
            layers=["F.Cu", "B.Cu"], net_name="GND", uuid_str=uuid_a,
        )

        result = PcbRawWriter.lock_via(content, uuid_a)

        via_idx = result.find("(via")
        assert via_idx >= 0
        head = result[via_idx:via_idx + 25]
        assert "(locked)" in head, \
            f"(locked) must be in first 25 chars after (via, got: {head!r}"

        locked_idx = result.find("(locked)", via_idx)
        at_idx = result.find("(at", via_idx)
        assert 0 <= locked_idx < at_idx, \
            "(locked) must come before (at ...) in the via block"

    def test_lock_via_idempotent(self):
        """Locking an already-locked via is a no-op."""
        uuid_a = "cccccccc-0000-0000-0000-000000000003"
        content = MINIMAL_PCB + PcbRawWriter.build_via_sexp(
            at=(10.0, 20.0), size=0.4, drill=0.2,
            layers=["F.Cu", "B.Cu"], net_name="GND", uuid_str=uuid_a,
        )

        locked_once = PcbRawWriter.lock_via(content, uuid_a)
        locked_twice = PcbRawWriter.lock_via(locked_once, uuid_a)

        assert locked_twice == locked_once
        assert locked_twice.count("(locked)") == 1

    def test_lock_via_not_found(self):
        """Unknown UUID raises ValueError."""
        with pytest.raises(ValueError, match="not found"):
            PcbRawWriter.lock_via(MINIMAL_PCB, "no-such-uuid-anywhere")


# ---------------------------------------------------------------------------
# PcbRawWriter.build_stitching_via_pattern unit tests
# ---------------------------------------------------------------------------

class TestBuildStitchingViaPattern:
    """PcbRawWriter.build_stitching_via_pattern direct tests."""

    def test_add_stitching_via_pattern_basic(self):
        """30x30mm region with 15mm spacing produces 4 vias (corners + center).

        Grid: x in {10, 25, 40}? No -- 30mm wide with 15mm spacing:
        x in {10, 25, 40} means x_max=40 -> only 10, 25 fit if region
        ends at 40. Let me recompute: region=[[10,10],[40,40]] gives
        x in {10, 25, 40} -> 3 points each axis -> 9 vias.

        For 4 vias: region=[[10,10],[25,25]] with 15mm -> x in {10, 25}
        -> 2x2 = 4 vias at corners. Wait -- 25-10=15=step, so it fits.
        """
        blocks = PcbRawWriter.build_stitching_via_pattern(
            net_name="GND",
            region=((10.0, 10.0), (25.0, 25.0)),
            grid_spacing=15.0,
            size=0.4,
            drill=0.2,
            layers=["F.Cu", "B.Cu"],
        )

        via_count = blocks.count("(via\n") + blocks.count("(via ")
        assert via_count == 4, f"Expected 4 vias in 2x2 grid, got {via_count}"

        # Verify corners are at expected positions
        assert "(at 10 10)" in blocks
        assert "(at 25 10)" in blocks
        assert "(at 10 25)" in blocks
        assert "(at 25 25)" in blocks

    def test_add_stitching_via_pattern_count(self):
        """45x45mm region with 15mm spacing produces 9 vias (3x3 grid).

        x in {10, 25, 40}, y in {10, 25, 40} -> 3 x 3 = 9.
        """
        blocks = PcbRawWriter.build_stitching_via_pattern(
            net_name="GND",
            region=((10.0, 10.0), (40.0, 40.0)),
            grid_spacing=15.0,
        )

        via_count = blocks.count("(via\n") + blocks.count("(via ")
        assert via_count == 9, f"Expected 9 vias in 3x3 grid, got {via_count}"

    def test_add_stitching_via_pattern_multilayer(self):
        """Multi-layer via support: layers appear in every generated via."""
        layers = ["F.Cu", "In1.Cu", "B.Cu"]
        blocks = PcbRawWriter.build_stitching_via_pattern(
            net_name="GND",
            region=((10.0, 10.0), (25.0, 25.0)),
            grid_spacing=15.0,
            size=0.4,
            drill=0.2,
            layers=layers,
        )

        # Every via must contain the multi-layer form
        expected_layers_str = '(layers "F.Cu" "In1.Cu" "B.Cu")'
        layer_count = blocks.count(expected_layers_str)
        assert layer_count == 4, \
            f"All 4 vias must have 3-layer spec, got {layer_count}"

    def test_add_stitching_via_pattern_default_geometry(self):
        """Default size=0.4 and drill=0.2 are applied to all vias."""
        blocks = PcbRawWriter.build_stitching_via_pattern(
            net_name="GND",
            region=((10.0, 10.0), (25.0, 25.0)),
            grid_spacing=15.0,
            # size and drill default -- but function signature requires them
            # as keyword defaults; call without to verify defaults.
        )

        # Default size=0.4, drill=0.2 per the function signature
        assert blocks.count("(size 0.4)") == 4
        assert blocks.count("(drill 0.2)") == 4

    def test_add_stitching_via_pattern_uuids_unique(self):
        """Every generated via has a unique UUID."""
        blocks = PcbRawWriter.build_stitching_via_pattern(
            net_name="GND",
            region=((10.0, 10.0), (40.0, 40.0)),
            grid_spacing=15.0,
        )

        uuids = re.findall(r'\(uuid "([^"]+)"\)', blocks)
        assert len(uuids) == 9, "Should be 9 vias in 3x3 grid"
        assert len(set(uuids)) == 9, \
            f"All UUIDs must be unique, got {len(set(uuids))} unique out of {len(uuids)}"

    def test_add_stitching_via_pattern_net_assignment(self):
        """All vias carry the requested net name."""
        blocks = PcbRawWriter.build_stitching_via_pattern(
            net_name="GND",
            region=((10.0, 10.0), (25.0, 25.0)),
            grid_spacing=15.0,
        )

        # 4 vias, each must have (net "GND")
        assert blocks.count('(net "GND")') == 4

    def test_add_stitching_via_pattern_kicad10_net_format(self):
        """Net field uses (net "NAME") string-only form, not numbered."""
        blocks = PcbRawWriter.build_stitching_via_pattern(
            net_name="GND",
            region=((10.0, 10.0), (25.0, 25.0)),
            grid_spacing=15.0,
        )

        assert '(net "GND")' in blocks
        assert not re.search(r'\(net\s+\d+\s+"GND"\)', blocks), \
            "Vias must use (net \"NAME\") not (net N \"NAME\")"

    def test_add_stitching_via_pattern_flipped_region(self):
        """Region with min/max swapped is normalized -- still produces grid."""
        # Caller passes max-corner first; function should handle it
        blocks = PcbRawWriter.build_stitching_via_pattern(
            net_name="GND",
            region=((25.0, 25.0), (10.0, 10.0)),  # flipped
            grid_spacing=15.0,
        )

        via_count = blocks.count("(via\n") + blocks.count("(via ")
        assert via_count == 4, "Flipped region must still produce 4 vias"
        assert "(at 10 10)" in blocks
        assert "(at 25 25)" in blocks


# ---------------------------------------------------------------------------
# Schema validation
# ---------------------------------------------------------------------------

class TestSchema:
    """Pydantic schema validation for the three new ops."""

    def test_lock_track_schema(self):
        from kicad_agent.ops._schema_pcb import LockTrackOp
        op = LockTrackOp(
            target_file="test.kicad_pcb",
            uuid="aaaaaaaa-0000-0000-0000-000000000001",
        )
        assert op.op_type == "lock_track"
        assert op.uuid == "aaaaaaaa-0000-0000-0000-000000000001"

    def test_lock_via_schema(self):
        from kicad_agent.ops._schema_pcb import LockViaOp
        op = LockViaOp(
            target_file="test.kicad_pcb",
            uuid="cccccccc-0000-0000-0000-000000000003",
        )
        assert op.op_type == "lock_via"

    def test_add_stitching_via_pattern_schema_defaults(self):
        from kicad_agent.ops._schema_pcb import AddStitchingViaPatternOp
        op = AddStitchingViaPatternOp(
            target_file="test.kicad_pcb",
            net="GND",
            grid_spacing_mm=15.0,
            region=((10.0, 10.0), (40.0, 40.0)),
        )
        assert op.op_type == "add_stitching_via_pattern"
        assert op.size == 0.4  # stitching default (smaller than add_via)
        assert op.drill == 0.2
        assert op.layers == ["F.Cu", "B.Cu"]

    def test_add_stitching_via_pattern_schema_multilayer(self):
        from kicad_agent.ops._schema_pcb import AddStitchingViaPatternOp
        op = AddStitchingViaPatternOp(
            target_file="test.kicad_pcb",
            net="GND",
            grid_spacing_mm=15.0,
            region=((10.0, 10.0), (40.0, 40.0)),
            layers=["F.Cu", "In1.Cu", "In2.Cu", "B.Cu"],
        )
        assert len(op.layers) == 4

    def test_add_stitching_via_pattern_schema_rejects_zero_spacing(self):
        from kicad_agent.ops._schema_pcb import AddStitchingViaPatternOp
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            AddStitchingViaPatternOp(
                target_file="test.kicad_pcb",
                net="GND",
                grid_spacing_mm=0.0,  # invalid
                region=((10.0, 10.0), (40.0, 40.0)),
            )

    def test_schema_empty_uuid_rejected(self):
        from kicad_agent.ops._schema_pcb import LockTrackOp
        from pydantic import ValidationError
        with pytest.raises(ValidationError):
            LockTrackOp(target_file="test.kicad_pcb", uuid="")


# ---------------------------------------------------------------------------
# Handler integration via OperationExecutor
# ---------------------------------------------------------------------------

class TestHandlerExecution:
    """End-to-end: dispatch through OperationExecutor writes to disk."""

    def test_lock_track_via_executor(self, pcb_path):
        """lock_track dispatches through executor and modifies the file."""
        from kicad_agent.ir.base import _clear_registry
        _clear_registry()

        from kicad_agent.ops.executor import OperationExecutor
        from kicad_agent.ops.schema import Operation

        # First, add a track so we have something to lock
        add_op = Operation.model_validate({
            "root": {
                "op_type": "add_track",
                "target_file": pcb_path.name,
                "net": "GND",
                "start": [0.0, 0.0],
                "end": [10.0, 0.0],
                "width": 0.2,
                "layer": "F.Cu",
            }
        })
        executor = OperationExecutor(base_dir=pcb_path.parent)
        result = executor.execute(add_op)
        assert result["success"] is True

        # Read UUID back from disk
        content = pcb_path.read_text(encoding="utf-8")
        uuid_match = re.search(r'\(uuid "([^"]+)"\)', content)
        assert uuid_match is not None, "Added track must have a UUID"
        track_uuid = uuid_match.group(1)

        # Now lock it
        _clear_registry()
        lock_op = Operation.model_validate({
            "root": {
                "op_type": "lock_track",
                "target_file": pcb_path.name,
                "uuid": track_uuid,
            }
        })
        result = executor.execute(lock_op)
        assert result["success"] is True
        assert result["operation"] == "lock_track"

        # Verify on disk
        final_content = pcb_path.read_text(encoding="utf-8")
        assert "(locked)" in final_content
        # Verify position: (segment (locked) ...
        seg_idx = final_content.find("(segment")
        head = final_content[seg_idx:seg_idx + 30]
        assert "(locked)" in head, \
            f"(locked) must be at head of segment, got: {head!r}"

    def test_lock_via_via_executor(self, pcb_path):
        """lock_via dispatches through executor."""
        from kicad_agent.ir.base import _clear_registry
        _clear_registry()

        from kicad_agent.ops.executor import OperationExecutor
        from kicad_agent.ops.schema import Operation

        # Add a via first
        add_op = Operation.model_validate({
            "root": {
                "op_type": "add_via",
                "target_file": pcb_path.name,
                "net": "GND",
                "at": [10.0, 20.0],
            }
        })
        executor = OperationExecutor(base_dir=pcb_path.parent)
        assert executor.execute(add_op)["success"] is True

        content = pcb_path.read_text(encoding="utf-8")
        via_uuid = re.search(r'\(uuid "([^"]+)"\)', content).group(1)

        # Lock the via
        _clear_registry()
        lock_op = Operation.model_validate({
            "root": {
                "op_type": "lock_via",
                "target_file": pcb_path.name,
                "uuid": via_uuid,
            }
        })
        result = executor.execute(lock_op)
        assert result["success"] is True

        final = pcb_path.read_text(encoding="utf-8")
        assert "(locked)" in final

    def test_add_stitching_via_pattern_via_executor(self, pcb_path):
        """add_stitching_via_pattern dispatches through executor."""
        from kicad_agent.ir.base import _clear_registry
        _clear_registry()

        from kicad_agent.ops.executor import OperationExecutor
        from kicad_agent.ops.schema import Operation

        op = Operation.model_validate({
            "root": {
                "op_type": "add_stitching_via_pattern",
                "target_file": pcb_path.name,
                "net": "GND",
                "grid_spacing_mm": 15.0,
                "region": [[10.0, 10.0], [40.0, 40.0]],
                "size": 0.4,
                "drill": 0.2,
                "layers": ["F.Cu", "In1.Cu", "B.Cu"],
            }
        })

        executor = OperationExecutor(base_dir=pcb_path.parent)
        result = executor.execute(op)

        assert result["success"] is True
        assert result["operation"] == "add_stitching_via_pattern"
        assert result["details"]["vias_added"] == 9

        content = pcb_path.read_text(encoding="utf-8")
        # 9 vias on disk
        via_count = content.count("(via\n") + content.count("(via ")
        # Subtract any "(via " that appears in the layers section header
        # (none expected in this minimal fixture, but defensive)
        assert via_count >= 9

        # All 9 should have multi-layer spec
        assert content.count('(layers "F.Cu" "In1.Cu" "B.Cu")') == 9

        # All 9 UUIDs unique
        uuids = re.findall(r'\(uuid "([^"]+)"\)', content)
        assert len(uuids) == 9
        assert len(set(uuids)) == 9

    def test_lock_track_unknown_uuid_fails(self, pcb_path):
        """lock_track with non-existent UUID raises ValueError via executor.

        The handler raises ValueError when the segment is not found. The
        executor surfaces this directly (with auto-rollback of any pending
        transaction state). Callers must catch the exception.
        """
        from kicad_agent.ir.base import _clear_registry
        _clear_registry()

        from kicad_agent.ops.executor import OperationExecutor
        from kicad_agent.ops.schema import Operation

        op = Operation.model_validate({
            "root": {
                "op_type": "lock_track",
                "target_file": pcb_path.name,
                "uuid": "nonexistent-uuid-0000-0000-000000000000",
            }
        })

        executor = OperationExecutor(base_dir=pcb_path.parent)
        with pytest.raises(ValueError, match="not found"):
            executor.execute(op)

        # File must be unchanged (rollback)
        assert pcb_path.read_text(encoding="utf-8") == MINIMAL_PCB

    def test_lock_track_via_executor_details(self, pcb_path):
        """lock_track result details contain uuid and locked=segment."""
        from kicad_agent.ir.base import _clear_registry
        _clear_registry()

        from kicad_agent.ops.executor import OperationExecutor
        from kicad_agent.ops.schema import Operation

        # Add a track first
        add_op = Operation.model_validate({
            "root": {
                "op_type": "add_track",
                "target_file": pcb_path.name,
                "net": "GND",
                "start": [0.0, 0.0],
                "end": [10.0, 0.0],
                "width": 0.2,
                "layer": "F.Cu",
            }
        })
        executor = OperationExecutor(base_dir=pcb_path.parent)
        executor.execute(add_op)

        content = pcb_path.read_text(encoding="utf-8")
        track_uuid = re.search(r'\(uuid "([^"]+)"\)', content).group(1)

        _clear_registry()
        lock_op = Operation.model_validate({
            "root": {
                "op_type": "lock_track",
                "target_file": pcb_path.name,
                "uuid": track_uuid,
            }
        })
        result = executor.execute(lock_op)
        assert result["details"]["locked"] == "segment"
        assert result["details"]["uuid"] == track_uuid


# ---------------------------------------------------------------------------
# Registry / metadata
# ---------------------------------------------------------------------------

class TestRegistry:
    """Verify ops are registered with correct metadata."""

    def test_lock_track_in_registry(self):
        from kicad_agent.ops.registry import OPERATION_REGISTRY
        assert "lock_track" in OPERATION_REGISTRY
        meta = OPERATION_REGISTRY["lock_track"]
        assert meta.category == "pcb"
        assert meta.is_readonly is False
        assert ".kicad_pcb" in meta.file_types

    def test_lock_via_in_registry(self):
        from kicad_agent.ops.registry import OPERATION_REGISTRY
        assert "lock_via" in OPERATION_REGISTRY
        meta = OPERATION_REGISTRY["lock_via"]
        assert meta.category == "pcb"

    def test_add_stitching_via_pattern_in_registry(self):
        from kicad_agent.ops.registry import OPERATION_REGISTRY
        assert "add_stitching_via_pattern" in OPERATION_REGISTRY
        meta = OPERATION_REGISTRY["add_stitching_via_pattern"]
        assert meta.category == "pcb"
        assert meta.is_readonly is False
