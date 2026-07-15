"""Tests for delete_track, delete_via, and move_track_endpoint ops (Phase 101-02).

Covers:
- PcbRawWriter.delete_segment / delete_via / move_segment_endpoint
- UUID-based block lookup with string-safety (uuid-like text inside a
  quoted property value must not be matched)
- Handler dispatch through OperationExecutor
- Round-trip add -> move -> delete
"""

import re
import tempfile
from pathlib import Path

import pytest

from volta.ops.pcb_raw_writer import PcbRawWriter


# ---------------------------------------------------------------------------
# Minimal PCB fixture (matches test_pcb_track_via_ops.py for consistency)
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
# PcbRawWriter.delete_segment unit tests
# ---------------------------------------------------------------------------

class TestDeleteSegment:
    """PcbRawWriter.delete_segment direct tests."""

    def test_delete_track_basic(self):
        """Delete removes the matching segment block."""
        uuid_a = "aaaaaaaa-0000-0000-0000-000000000001"
        uuid_b = "bbbbbbbb-0000-0000-0000-000000000002"
        content = MINIMAL_PCB + PcbRawWriter.build_segment_sexp(
            start=(0.0, 0.0), end=(10.0, 0.0),
            width=0.2, layer="F.Cu", net_name="GND", uuid_str=uuid_a,
        ) + PcbRawWriter.build_segment_sexp(
            start=(10.0, 0.0), end=(20.0, 0.0),
            width=0.2, layer="F.Cu", net_name="GND", uuid_str=uuid_b,
        )

        result = PcbRawWriter.delete_segment(content, uuid_a)

        assert uuid_a not in result, "Deleted UUID must not appear in result"
        assert uuid_b in result, "Other segment must remain"
        # Segment block count should drop by one
        assert result.count("(segment") == 1

    def test_delete_track_not_found_raises(self):
        """Unknown UUID raises ValueError."""
        with pytest.raises(ValueError, match="not found"):
            PcbRawWriter.delete_segment(MINIMAL_PCB, "no-such-uuid-anywhere")

    def test_delete_track_uuid_in_string_safe(self):
        """UUID text appearing inside a quoted property is not deleted.

        A footprint or text property might legitimately contain text that
        looks like a UUID. The matcher must only match the real ``(uuid
        "...")`` field of a segment block, not arbitrary substrings.
        """
        real_uuid = "11111111-1111-1111-1111-111111111111"
        decoy_uuid = "22222222-2222-2222-2222-222222222222"

        # Put the decoy UUID inside a (text ...) quoted value -- not as a
        # real (uuid "...") field of any block.
        content_with_decoy = MINIMAL_PCB.replace(
            '  (generator "volta-test")',
            f'  (generator "volta-test")\n'
            f'  (gr_text (at 5 5) (uuid "{decoy_uuid}") '
            f'(effects (font (size 1 1))) "label-{decoy_uuid}")',
        )
        # Add the real target segment
        content_with_decoy += PcbRawWriter.build_segment_sexp(
            start=(0.0, 0.0), end=(5.0, 0.0),
            width=0.2, layer="F.Cu", net_name="GND", uuid_str=real_uuid,
        )

        # Delete the real one -- the decoy inside gr_text must survive
        result = PcbRawWriter.delete_segment(content_with_decoy, real_uuid)
        assert real_uuid not in result
        assert decoy_uuid in result, "Decoy UUID inside text must survive"
        assert "(segment" not in result, "All segments should be gone"


# ---------------------------------------------------------------------------
# PcbRawWriter.delete_via unit tests
# ---------------------------------------------------------------------------

class TestDeleteVia:
    """PcbRawWriter.delete_via direct tests."""

    def test_delete_via_basic(self):
        """Delete removes the matching via block."""
        uuid_a = "cccccccc-0000-0000-0000-000000000001"
        uuid_b = "dddddddd-0000-0000-0000-000000000002"
        content = MINIMAL_PCB + PcbRawWriter.build_via_sexp(
            at=(10.0, 10.0), size=0.7, drill=0.3,
            layers=["F.Cu", "B.Cu"], net_name="GND", uuid_str=uuid_a,
        ) + PcbRawWriter.build_via_sexp(
            at=(20.0, 20.0), size=0.7, drill=0.3,
            layers=["F.Cu", "B.Cu"], net_name="GND", uuid_str=uuid_b,
        )

        result = PcbRawWriter.delete_via(content, uuid_a)

        assert uuid_a not in result
        assert uuid_b in result
        # Only via-at 20 20 should remain
        assert "(at 10 10)" not in result
        assert "(at 20 20)" in result

    def test_delete_via_not_found_raises(self):
        """Unknown UUID raises ValueError."""
        with pytest.raises(ValueError, match="not found"):
            PcbRawWriter.delete_via(MINIMAL_PCB, "no-such-via-uuid")


# ---------------------------------------------------------------------------
# PcbRawWriter.move_segment_endpoint unit tests
# ---------------------------------------------------------------------------

class TestMoveSegmentEndpoint:
    """PcbRawWriter.move_segment_endpoint direct tests."""

    def test_move_track_endpoint_start(self):
        """Moving the start point rewrites only the (start X Y) field."""
        uuid_s = "eeeeeeee-0000-0000-0000-000000000001"
        content = MINIMAL_PCB + PcbRawWriter.build_segment_sexp(
            start=(0.0, 0.0), end=(10.0, 0.0),
            width=0.2, layer="F.Cu", net_name="SIG", uuid_str=uuid_s,
        )

        result = PcbRawWriter.move_segment_endpoint(
            content, uuid_s, "start", (5.0, 5.0),
        )

        assert "(start 5 5)" in result
        # End must be unchanged
        assert "(end 10 0)" in result
        # Only one start field should exist
        assert len(re.findall(r"\(start\s+[\d.]+\s+[\d.]+\)", result)) == 1

    def test_move_track_endpoint_end(self):
        """Moving the end point rewrites only the (end X Y) field."""
        uuid_s = "ffffffff-0000-0000-0000-000000000001"
        content = MINIMAL_PCB + PcbRawWriter.build_segment_sexp(
            start=(0.0, 0.0), end=(10.0, 0.0),
            width=0.2, layer="F.Cu", net_name="SIG", uuid_str=uuid_s,
        )

        result = PcbRawWriter.move_segment_endpoint(
            content, uuid_s, "end", (25.0, 7.5),
        )

        assert "(end 25 7.5)" in result
        # Start must be unchanged
        assert "(start 0 0)" in result

    def test_move_track_endpoint_not_found_raises(self):
        """Unknown segment UUID raises ValueError."""
        with pytest.raises(ValueError, match="not found"):
            PcbRawWriter.move_segment_endpoint(
                MINIMAL_PCB, "nope", "start", (1.0, 1.0),
            )

    def test_move_track_endpoint_invalid_end_kind_raises(self):
        """Invalid end_kind raises ValueError before any disk work."""
        uuid_s = "12345678-0000-0000-0000-000000000001"
        content = MINIMAL_PCB + PcbRawWriter.build_segment_sexp(
            start=(0.0, 0.0), end=(10.0, 0.0),
            width=0.2, layer="F.Cu", net_name="SIG", uuid_str=uuid_s,
        )
        with pytest.raises(ValueError, match="end_kind"):
            PcbRawWriter.move_segment_endpoint(
                content, uuid_s, "middle", (1.0, 1.0),
            )


# ---------------------------------------------------------------------------
# Handler dispatch through OperationExecutor
# ---------------------------------------------------------------------------

class TestHandlerExecution:
    """End-to-end: dispatch through OperationExecutor writes to disk."""

    def test_delete_track_via_executor(self, pcb_path):
        """add_track then delete_track leaves the PCB segment-free."""
        from volta.ir.base import _clear_registry
        _clear_registry()

        from volta.ops.executor import OperationExecutor
        from volta.ops.schema import Operation

        executor = OperationExecutor(base_dir=pcb_path.parent)

        add_op = Operation.model_validate({
            "root": {
                "op_type": "add_track",
                "target_file": pcb_path.name,
                "net": "GND",
                "start": [1.0, 2.0],
                "end": [3.0, 4.0],
                "width": 0.2,
                "layer": "F.Cu",
            }
        })
        assert executor.execute(add_op)["success"] is True

        content_before_delete = pcb_path.read_text(encoding="utf-8")
        uuids = re.findall(r'\(uuid "([^"]+)"\)', content_before_delete)
        track_uuids = [
            u for u in uuids
            if _segment_uuid(pcb_path, u)
        ]
        assert track_uuids, "add_track should have produced a segment UUID"
        target_uuid = track_uuids[0]

        delete_op = Operation.model_validate({
            "root": {
                "op_type": "delete_track",
                "target_file": pcb_path.name,
                "uuid": target_uuid,
            }
        })
        result = executor.execute(delete_op)

        assert result["success"] is True
        assert result["operation"] == "delete_track"
        final = pcb_path.read_text(encoding="utf-8")
        assert target_uuid not in final
        assert "(segment" not in final

    def test_delete_via_via_executor(self, pcb_path):
        """add_via then delete_via leaves the PCB via-free."""
        from volta.ir.base import _clear_registry
        _clear_registry()

        from volta.ops.executor import OperationExecutor
        from volta.ops.schema import Operation

        executor = OperationExecutor(base_dir=pcb_path.parent)

        add_op = Operation.model_validate({
            "root": {
                "op_type": "add_via",
                "target_file": pcb_path.name,
                "net": "GND",
                "at": [11.0, 22.0],
                "size": 0.7,
                "drill": 0.3,
                "layers": ["F.Cu", "B.Cu"],
            }
        })
        assert executor.execute(add_op)["success"] is True

        content = pcb_path.read_text(encoding="utf-8")
        # The only uuid on disk belongs to the via we just added
        via_uuid = re.search(r'\(via[^)]*\)[\s\S]*?\(uuid "([^"]+)"\)', content)
        assert via_uuid, "add_via should have produced a via UUID"
        target_uuid = via_uuid.group(1)

        delete_op = Operation.model_validate({
            "root": {
                "op_type": "delete_via",
                "target_file": pcb_path.name,
                "uuid": target_uuid,
            }
        })
        result = executor.execute(delete_op)

        assert result["success"] is True
        assert result["operation"] == "delete_via"
        final = pcb_path.read_text(encoding="utf-8")
        assert target_uuid not in final
        assert "(via" not in final

    def test_move_track_endpoint_via_executor(self, pcb_path):
        """move_track_endpoint rewrites the (start X Y) on disk."""
        from volta.ir.base import _clear_registry
        _clear_registry()

        from volta.ops.executor import OperationExecutor
        from volta.ops.schema import Operation

        executor = OperationExecutor(base_dir=pcb_path.parent)

        add_op = Operation.model_validate({
            "root": {
                "op_type": "add_track",
                "target_file": pcb_path.name,
                "net": "SIG",
                "start": [0.0, 0.0],
                "end": [10.0, 0.0],
                "width": 0.2,
                "layer": "F.Cu",
            }
        })
        assert executor.execute(add_op)["success"] is True

        content = pcb_path.read_text(encoding="utf-8")
        seg_uuid = re.search(
            r'\(segment[\s\S]*?\(uuid "([^"]+)"\)', content,
        )
        assert seg_uuid, "add_track should have produced a segment UUID"
        target_uuid = seg_uuid.group(1)

        move_op = Operation.model_validate({
            "root": {
                "op_type": "move_track_endpoint",
                "target_file": pcb_path.name,
                "uuid": target_uuid,
                "end": "start",
                "to": [42.0, 17.5],
            }
        })
        result = executor.execute(move_op)

        assert result["success"] is True
        assert result["operation"] == "move_track_endpoint"
        final = pcb_path.read_text(encoding="utf-8")
        assert "(start 42 17.5)" in final
        assert "(end 10 0)" in final

    def test_delete_track_not_found_via_executor(self, pcb_path):
        """delete_track with unknown UUID raises through the executor.

        The executor propagates handler ValueError exceptions (this matches
        the behavior of every other PCB op -- only pre-flight gates return
        ``success: False``). The Transaction auto-rollback restores the
        file content, so the PCB on disk is left untouched.
        """
        from volta.ir.base import _clear_registry
        _clear_registry()

        from volta.ops.executor import OperationExecutor
        from volta.ops.schema import Operation

        delete_op = Operation.model_validate({
            "root": {
                "op_type": "delete_track",
                "target_file": pcb_path.name,
                "uuid": "nonexistent-uuid-abc",
            }
        })
        executor = OperationExecutor(base_dir=pcb_path.parent)

        with pytest.raises(ValueError, match="not found"):
            executor.execute(delete_op)

        # File must be untouched after auto-rollback
        assert pcb_path.read_text(encoding="utf-8") == MINIMAL_PCB

    def test_round_trip_add_move_delete(self, pcb_path):
        """add -> move -> delete leaves the PCB segment-free."""
        from volta.ir.base import _clear_registry
        _clear_registry()

        from volta.ops.executor import OperationExecutor
        from volta.ops.schema import Operation

        executor = OperationExecutor(base_dir=pcb_path.parent)

        # 1. add
        add_op = Operation.model_validate({
            "root": {
                "op_type": "add_track",
                "target_file": pcb_path.name,
                "net": "RT",
                "start": [0.0, 0.0],
                "end": [10.0, 0.0],
                "width": 0.2,
                "layer": "F.Cu",
            }
        })
        assert executor.execute(add_op)["success"] is True
        content_after_add = pcb_path.read_text(encoding="utf-8")
        assert "(segment" in content_after_add

        seg_uuid = re.search(
            r'\(segment[\s\S]*?\(uuid "([^"]+)"\)', content_after_add,
        ).group(1)

        # 2. move
        move_op = Operation.model_validate({
            "root": {
                "op_type": "move_track_endpoint",
                "target_file": pcb_path.name,
                "uuid": seg_uuid,
                "end": "end",
                "to": [99.0, 88.0],
            }
        })
        assert executor.execute(move_op)["success"] is True
        moved = pcb_path.read_text(encoding="utf-8")
        assert "(end 99 88)" in moved

        # 3. delete
        delete_op = Operation.model_validate({
            "root": {
                "op_type": "delete_track",
                "target_file": pcb_path.name,
                "uuid": seg_uuid,
            }
        })
        assert executor.execute(delete_op)["success"] is True
        final = pcb_path.read_text(encoding="utf-8")

        # PCB should have no segment, no trace of the UUID, and no (end 99 88)
        assert "(segment" not in final
        assert seg_uuid not in final
        assert "(end 99 88)" not in final


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _segment_uuid(pcb_path: Path, uuid_str: str) -> bool:
    """Return True if a (segment ...) block with the given UUID exists on disk."""
    content = pcb_path.read_text(encoding="utf-8")
    for match in re.finditer(r"\(segment\b", content):
        start = match.start()
        # Find the close paren by simple depth counting
        depth = 0
        i = start
        in_string = False
        while i < len(content):
            c = content[i]
            if in_string:
                if c == '"':
                    if i + 1 < len(content) and content[i + 1] == '"':
                        i += 2
                        continue
                    in_string = False
                i += 1
                continue
            if c == '"':
                in_string = True
            elif c == "(":
                depth += 1
            elif c == ")":
                depth -= 1
                if depth == 0:
                    break
            i += 1
        block = content[start : i + 1]
        if re.search(r'\(uuid\s+"' + re.escape(uuid_str) + r'"', block):
            return True
    return False
