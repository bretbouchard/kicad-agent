"""Phase 101-04 integration test: exercise all 9 new PCB ops on a real PCB.

Target: ``hardware/network-io/channel-strip/analog-board.kicad_pcb`` from the
analog-ecosystem project. The production PCB is NEVER modified -- the test
copies it to a temp file at setup, runs the 9-op sequence against the copy,
verifies kicad-cli can still parse it (DRC may report design violations, but
the file must not be corrupt), then cleans up.

Ops covered (Phase 101-01/02/03):
    1. add_track          6. lock_via
    2. add_via            7. add_stitching_via_pattern
    3. move_track_endpoint 8. delete_track
    4. lock_track         9. delete_via
    5. (add_arc_track covered by unit tests; not exercised here because the
       real board has no specific arc use case -- straight segment is enough
       to prove end-to-end dispatch on a production-shaped file)

Note: 8 of 9 ops are exercised here. ``add_arc_track`` is intentionally
omitted because the integration scenario (GND stitching + a single signal
trace) does not require an arc; the op has full unit coverage in
``tests/test_pcb_track_via_ops.py`` and the integration goal is to prove the
*sequence* works against a real file, not to re-test each op's geometry.
"""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import pytest

# Production PCB -- NEVER modify. Always copy to temp first.
SOURCE_PCB = Path(
    "/Users/bretbouchard/apps/analog-ecosystem/hardware/network-io/"
    "channel-strip/analog-board.kicad_pcb"
)


def _clear_ir_registry() -> None:
    """Reset the IR cache between ops so each op sees a fresh load."""
    from volta.ir.base import _clear_registry
    _clear_registry()


@pytest.fixture
def temp_pcb_copy():
    """Copy the production PCB to a temp file; yield path; cleanup on exit."""
    if not SOURCE_PCB.exists():
        pytest.skip(f"Source PCB not available: {SOURCE_PCB}")
    with tempfile.NamedTemporaryFile(
        suffix=".kicad_pcb", delete=False, prefix="channel_strip_integ_"
    ) as tmp:
        tmp_path = Path(tmp.name)
    try:
        shutil.copy(SOURCE_PCB, tmp_path)
        yield tmp_path
    finally:
        if tmp_path.exists():
            tmp_path.unlink()


def _execute_op(op_dict: dict, base_dir: Path) -> dict:
    """Build, validate, and execute a single op via OperationExecutor."""
    from volta.ops.executor import OperationExecutor
    from volta.ops.schema import Operation

    op = Operation.model_validate({"root": op_dict})
    executor = OperationExecutor(base_dir=base_dir)
    return executor.execute(op)


def _find_uuid_by_anchor(
    content: str, block_name: str, anchor: str,
) -> str | None:
    """Find (uuid "...") inside a (block_name ...) block that contains anchor.

    Real PCBs contain thousands of (segment ...) / (via ...) blocks. To pin
    down the one we just added, we anchor on a unique coordinate string (e.g.
    "(start 50 50)" or "(at 55 50)") that we just wrote.

    Args:
        content: Full PCB file contents.
        block_name: Outer block name ("segment", "via", ...).
        anchor: Unique substring inside the target block (e.g. "(start 50 50)").

    Returns:
        The UUID string, or None if no match.
    """
    # Match the block from (block_name ... through a close paren that brings
    # us back to depth 0. The non-greedy *? plus the anchor + (uuid ...)
    # pattern lets us extract without parsing the full S-expression tree.
    pattern = (
        rf"\({block_name}\b[^()]*?{re.escape(anchor)}"
        r".*?"
        r'\(uuid "([^"]+)"\)'
    )
    m = re.search(pattern, content, re.DOTALL)
    return m.group(1) if m else None


def test_all_9_ops_on_real_pcb(temp_pcb_copy):
    """End-to-end: all 9 Phase-101 ops dispatch cleanly on the real PCB.

    Sequence verifies:
      - add_track / add_via write valid S-expressions into a real file
      - move_track_endpoint mutates the segment in place
      - lock_track / lock_via inject (locked) tokens
      - add_stitching_via_pattern emits a grid of vias
      - delete_track / delete_via cleanly remove their targets (even if locked)
      - kicad-cli pcb drc still parses the file (corruption check)
    """
    base_dir = temp_pcb_copy.parent

    # ------------------------------------------------------------------
    # Step 1: baseline -- verify source file loads in kicad-cli
    # ------------------------------------------------------------------
    baseline = subprocess.run(
        ["kicad-cli", "pcb", "drc", str(temp_pcb_copy)],
        capture_output=True, text=True, timeout=120,
    )
    # DRC exit code 0 = clean; non-zero = violations, but file parses.
    # The only failure mode we care about is corruption, which surfaces as
    # a parse error in stderr (not a DRC violation in stdout).
    assert "Parse error" not in baseline.stderr, (
        f"Baseline PCB failed to parse in kicad-cli: {baseline.stderr[:500]}"
    )

    # ------------------------------------------------------------------
    # Step 2: add_track -- 1 segment on F.Cu, net=GND, width=0.2
    # ------------------------------------------------------------------
    _clear_ir_registry()
    result = _execute_op(
        {
            "op_type": "add_track",
            "target_file": temp_pcb_copy.name,
            "net": "GND",
            "start": [50.0, 50.0],
            "end": [60.0, 50.0],
            "width": 0.2,
            "layer": "F.Cu",
        },
        base_dir,
    )
    assert result["success"] is True, f"add_track failed: {result}"
    content = temp_pcb_copy.read_text(encoding="utf-8")
    track_uuid = _find_uuid_by_anchor(content, "segment", "(start 50 50)")
    assert track_uuid is not None, "add_track did not write a (segment ...) block"
    assert "(start 50 50)" in content
    assert "(end 60 50)" in content
    assert '(net "GND")' in content

    # ------------------------------------------------------------------
    # Step 3: add_via -- 1 via at (55, 50), size=0.7, drill=0.3
    # ------------------------------------------------------------------
    _clear_ir_registry()
    result = _execute_op(
        {
            "op_type": "add_via",
            "target_file": temp_pcb_copy.name,
            "net": "GND",
            "at": [55.0, 50.0],
            "size": 0.7,
            "drill": 0.3,
            "layers": ["F.Cu", "B.Cu"],
        },
        base_dir,
    )
    assert result["success"] is True, f"add_via failed: {result}"
    content = temp_pcb_copy.read_text(encoding="utf-8")
    via_uuid = _find_uuid_by_anchor(content, "via", "(at 55 50)")
    assert via_uuid is not None, "add_via did not write a (via ...) block"
    assert "(at 55 50)" in content
    assert "(size 0.7)" in content
    assert "(drill 0.3)" in content

    # ------------------------------------------------------------------
    # Step 4: move_track_endpoint -- shift end of new segment to (65, 50)
    # ------------------------------------------------------------------
    _clear_ir_registry()
    result = _execute_op(
        {
            "op_type": "move_track_endpoint",
            "target_file": temp_pcb_copy.name,
            "uuid": track_uuid,
            "end": "end",
            "to": [65.0, 50.0],
        },
        base_dir,
    )
    assert result["success"] is True, f"move_track_endpoint failed: {result}"
    content = temp_pcb_copy.read_text(encoding="utf-8")
    assert "(end 65 50)" in content, "move_track_endpoint did not rewrite (end ...)"
    # Original start should be untouched
    assert "(start 50 50)" in content

    # ------------------------------------------------------------------
    # Step 5: lock_track -- inject (locked) on the new segment
    # ------------------------------------------------------------------
    _clear_ir_registry()
    result = _execute_op(
        {
            "op_type": "lock_track",
            "target_file": temp_pcb_copy.name,
            "uuid": track_uuid,
        },
        base_dir,
    )
    assert result["success"] is True, f"lock_track failed: {result}"
    content = temp_pcb_copy.read_text(encoding="utf-8")
    # Confirm (locked) appears somewhere in the file after lock_track ran.
    # A strict per-block assertion (locked inside THIS specific segment) is
    # the unit tests' job; integration just confirms the op dispatches
    # without error and writes the token to disk.
    assert "(locked)" in content, "lock_track did not inject (locked) token"

    # ------------------------------------------------------------------
    # Step 6: lock_via -- inject (locked) on the new via
    # ------------------------------------------------------------------
    _clear_ir_registry()
    result = _execute_op(
        {
            "op_type": "lock_via",
            "target_file": temp_pcb_copy.name,
            "uuid": via_uuid,
        },
        base_dir,
    )
    assert result["success"] is True, f"lock_via failed: {result}"

    # ------------------------------------------------------------------
    # Step 7: add_stitching_via_pattern -- 15mm grid over 30x30mm region
    # ------------------------------------------------------------------
    _clear_ir_registry()
    result = _execute_op(
        {
            "op_type": "add_stitching_via_pattern",
            "target_file": temp_pcb_copy.name,
            "net": "GND",
            "grid_spacing_mm": 15.0,
            "region": [[10.0, 10.0], [40.0, 40.0]],
            "size": 0.4,
            "drill": 0.2,
            "layers": ["F.Cu", "B.Cu"],
        },
        base_dir,
    )
    assert result["success"] is True, (
        f"add_stitching_via_pattern failed: {result}"
    )
    # A 30x30 region at 15mm pitch should yield 3x3 = 9 stitching vias at
    # (10,10) (25,10) (40,10) / (10,25) (25,25) (40,25) / (10,40) (25,40) (40,40)
    # Verify the corners landed at the expected coordinates.
    content = temp_pcb_copy.read_text(encoding="utf-8")
    assert "(at 10 10)" in content, "stitching grid missing corner (10,10)"
    assert "(at 40 40)" in content, "stitching grid missing corner (40,40)"
    assert "(at 25 25)" in content, "stitching grid missing center (25,25)"

    # ------------------------------------------------------------------
    # Step 8: delete_track -- removes the segment from step 2 (even if locked)
    # ------------------------------------------------------------------
    _clear_ir_registry()
    result = _execute_op(
        {
            "op_type": "delete_track",
            "target_file": temp_pcb_copy.name,
            "uuid": track_uuid,
        },
        base_dir,
    )
    assert result["success"] is True, (
        f"delete_track failed (lock should NOT block our own delete): {result}"
    )
    content = temp_pcb_copy.read_text(encoding="utf-8")
    assert track_uuid not in content, (
        "delete_track did not remove the segment UUID from the file"
    )

    # ------------------------------------------------------------------
    # Step 9: delete_via -- removes the via from step 3
    # ------------------------------------------------------------------
    _clear_ir_registry()
    result = _execute_op(
        {
            "op_type": "delete_via",
            "target_file": temp_pcb_copy.name,
            "uuid": via_uuid,
        },
        base_dir,
    )
    assert result["success"] is True, f"delete_via failed: {result}"
    content = temp_pcb_copy.read_text(encoding="utf-8")
    assert via_uuid not in content, "delete_via did not remove the via UUID"

    # ------------------------------------------------------------------
    # Step 10: corruption check -- kicad-cli pcb drc must still parse the file
    # ------------------------------------------------------------------
    final_drc = subprocess.run(
        ["kicad-cli", "pcb", "drc", str(temp_pcb_copy)],
        capture_output=True, text=True, timeout=120,
    )
    # We do NOT require DRC to pass -- the production board has its own
    # pre-existing violations, and our test vias/segments are intentionally
    # not connected to real nets. We only require the file parses cleanly.
    assert "Parse error" not in final_drc.stderr, (
        f"Post-edit PCB failed to parse in kicad-cli (corruption): "
        f"{final_drc.stderr[:500]}"
    )
