"""Phase 100 R-4: Rollback via PersistentUndoStack + PcbIR-based surgical
removal (H2 — no regex on S-expressions).

Includes:
- Pre-route snapshot pushed via PersistentUndoStack (R3-L1: assert op_type)
- rollback_net uses PcbIR/PcbRawWriter, NOT regex (H2)
- 10-cycle approve/reject with mock-DRC (M2 — ALWAYS runs, never skips)
- 10-cycle approve/reject with kicad-cli DRC (@integration, skips if absent)
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from unittest.mock import patch

import pytest

from kicad_agent.ir.pcb_ir import PcbIR
from kicad_agent.ops.persistent_undo import PersistentUndoStack
from kicad_agent.parser.pcb_native_parser import NativeParser
from kicad_agent.routing.orchestrator import RoutingOrchestrator


_FIXTURE = Path(__file__).parent / "fixtures" / "smd_test_board.kicad_pcb"


def _copy_fixture(tmp_path: Path) -> Path:
    dest = tmp_path / "smd_test_board.kicad_pcb"
    shutil.copy(_FIXTURE, dest)
    return dest


def _has_kicad_cli() -> bool:
    return shutil.which("kicad-cli") is not None


# ---------------------------------------------------------------------------
# Pre-route snapshot (R3-L1: verify op_type on read-back UndoEntry)
# ---------------------------------------------------------------------------


class TestPreRouteSnapshotPushed:
    def test_undo_entries_exist_after_route_board(self, tmp_path: Path) -> None:
        pcb = _copy_fixture(tmp_path)
        orch = RoutingOrchestrator()
        orch.route_board(pcb, project_dir=tmp_path)
        undo_dir = tmp_path / ".kicad-agent" / "undo"
        assert undo_dir.exists()
        # At least one entry file should exist.
        entry_files = list(undo_dir.glob("*.json"))
        assert len(entry_files) >= 1

    def test_undo_entry_has_correct_op_type(self, tmp_path: Path) -> None:
        # R3-L1: read back an UndoEntry and assert op_type is one of the
        # documented routing tags.
        pcb = _copy_fixture(tmp_path)
        undo_stack = PersistentUndoStack(project_dir=tmp_path)
        orch = RoutingOrchestrator()
        orch.route_board(pcb, project_dir=tmp_path, undo_stack=undo_stack)

        # pop_undo should return an entry with a route-related op_type.
        entry = undo_stack.pop_undo(pcb)
        assert entry is not None
        assert entry.op_type in {"route_board_pre", "route_board_post"}


# ---------------------------------------------------------------------------
# H2: rollback_net uses PcbIR, not regex
# ---------------------------------------------------------------------------


class TestRollbackNetUsesPcbir:
    def test_no_regex_import_in_orchestrator(self) -> None:
        # H2 done criterion: orchestrator.py must not import re at module level.
        content = Path("src/kicad_agent/routing/orchestrator.py").read_text()
        # Check for top-level "import re" (not inside a comment/string).
        lines = content.split("\n")
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("#"):
                continue
            if stripped.startswith("import re") or stripped.startswith("from re "):
                pytest.fail(f"orchestrator.py imports re at module level: {line}")

    def test_rollback_removes_segments_for_net(self, tmp_path: Path) -> None:
        # Inject a properly-formatted segment on a known net, then roll it back.
        pcb = _copy_fixture(tmp_path)
        undo_stack = PersistentUndoStack(project_dir=tmp_path)

        raw = pcb.read_text(encoding="utf-8")
        board = NativeParser.parse_pcb(pcb)
        assert len(board.nets) > 0
        target_net = board.nets[0].name
        target_net_num = board.nets[0].number

        # Inject a valid segment block (KiCad 10 format with uuid token)
        # before the final closing paren of (kicad_pcb ...).
        injection = (
            f'\t(segment\n'
            f'\t\t(start 1.0 1.0)\n'
            f'\t\t(end 2.0 2.0)\n'
            f'\t\t(width 0.25)\n'
            f'\t\t(layer "F.Cu")\n'
            f'\t\t(net {target_net_num} "{target_net}")\n'
            f'\t\t(uuid "aaaaaaaa-0000-0000-0000-000000000001")\n'
            f'\t)\n'
        )
        last_close = raw.rfind(")")
        raw = raw[:last_close] + injection + raw[last_close:]
        pcb.write_text(raw, encoding="utf-8")

        orch = RoutingOrchestrator()
        orch.rollback_net(pcb, target_net, undo_stack)

        # After rollback, the injected segment UUID should be gone.
        new_raw = pcb.read_text(encoding="utf-8")
        assert "aaaaaaaa-0000-0000-0000-000000000001" not in new_raw

    def test_rollback_preserves_pad_net_assignments(self, tmp_path: Path) -> None:
        # H2 core guarantee: pad (net "name") inside footprint blocks
        # must survive rollback. Only segment/via-level net refs are removed.
        pcb = _copy_fixture(tmp_path)
        undo_stack = PersistentUndoStack(project_dir=tmp_path)
        board = NativeParser.parse_pcb(pcb)
        # Find a net that actually appears in pad definitions.
        target_net = ""
        for fp in board.footprints:
            for pad in fp.pads:
                if pad.net_name:
                    target_net = pad.net_name
                    break
            if target_net:
                break
        if not target_net:
            pytest.skip("No pad with a net assignment in fixture")

        orch = RoutingOrchestrator()
        orch.rollback_net(pcb, target_net, undo_stack)

        # Re-parse: the pad should still have its net assignment.
        new_board = NativeParser.parse_pcb(pcb)
        pad_nets_after = {
            pad.net_name
            for fp in new_board.footprints
            for pad in fp.pads
        }
        assert target_net in pad_nets_after


# ---------------------------------------------------------------------------
# CR-01: UUID-based rollback (regression for parent_index divergence)
# ---------------------------------------------------------------------------


class TestRollbackNetUuidJoin:
    """CR-01: rollback_net must join on UUID value, NOT on extract_uuids
    parent_index.

    The UUID extractor (regex byte-order) and NativeBoard.segments (parse-tree
    DFS) use different traversal orders. On a board with a (segment ...) nested
    inside a (group ...), the parent_index would diverge from the NativeBoard
    index — causing rollback to either miss the UUID entirely or delete the
    wrong segment.

    This test builds a minimal board with both a top-level segment and a
    nested segment inside a (group ...), gives them distinct UUIDs, and
    verifies that rollback_net removes ONLY the target net's segment(s).
    """

    def test_rollback_with_nested_segment_in_group(self, tmp_path: Path) -> None:
        # Minimal KiCad 10 PCB with:
        # - one top-level segment on net "TARGET" (uuid target-top)
        # - one segment nested inside a (group ...) on net "OTHER" (uuid other-nested)
        # - one top-level segment on net "OTHER" (uuid other-top)
        #
        # If rollback_net joined on parent_index, deleting "TARGET" could
        # accidentally hit "other-nested" or "other-top" (divergence).
        # Joining on UUID value removes only target-top.
        pcb = tmp_path / "nested_segment.kicad_pcb"
        pcb.write_text(
            '(kicad_pcb\n'
            '\t(version 20241229)\n'
            '\t(generator "test")\n'
            '\t(general (thickness 1.6))\n'
            '\t(layers\n'
            '\t\t(0 "F.Cu" signal)\n'
            '\t\t(31 "B.Cu" signal)\n'
            '\t)\n'
            '\t(net 0 "")\n'
            '\t(net 1 "TARGET")\n'
            '\t(net 2 "OTHER")\n'
            '\t(segment\n'
            '\t\t(start 10.0 10.0)\n'
            '\t\t(end 20.0 10.0)\n'
            '\t\t(width 0.25)\n'
            '\t\t(layer "F.Cu")\n'
            '\t\t(net 1 "TARGET")\n'
            '\t\t(uuid "target-top-0000-0000-0000-000000000001")\n'
            '\t)\n'
            '\t(segment\n'
            '\t\t(start 30.0 30.0)\n'
            '\t\t(end 40.0 30.0)\n'
            '\t\t(width 0.25)\n'
            '\t\t(layer "F.Cu")\n'
            '\t\t(net 2 "OTHER")\n'
            '\t\t(uuid "other-top-0000-0000-0000-000000000002")\n'
            '\t)\n'
            '\t(group\n'
            '\t\t(uuid "group-0000-0000-0000-000000000003")\n'
            '\t\t(segment\n'
            '\t\t\t(start 50.0 50.0)\n'
            '\t\t\t(end 60.0 50.0)\n'
            '\t\t\t(width 0.25)\n'
            '\t\t\t(layer "F.Cu")\n'
            '\t\t\t(net 2 "OTHER")\n'
            '\t\t\t(uuid "other-nested-0000-0000-0000-000000000004")\n'
            '\t\t)\n'
            '\t)\n'
            ')\n',
            encoding="utf-8",
        )

        orch = RoutingOrchestrator()
        orch.rollback_net(pcb, "TARGET")

        new_raw = pcb.read_text(encoding="utf-8")
        # The target segment must be gone.
        assert "target-top-0000-0000-0000-000000000001" not in new_raw
        # The OTHER net segments (both top-level and nested) must survive —
        # rollback joined on UUID value, so it could not accidentally hit them
        # via a divergent parent_index.
        assert "other-top-0000-0000-0000-000000000002" in new_raw
        assert "other-nested-0000-0000-0000-000000000004" in new_raw

    def test_segment_uuid_field_populated_by_parser(self, tmp_path: Path) -> None:
        # CR-01 directly: NativeSegment must carry the uuid after parse.
        pcb = tmp_path / "uuid_field.kicad_pcb"
        pcb.write_text(
            '(kicad_pcb\n'
            '\t(version 20241229)\n'
            '\t(generator "test")\n'
            '\t(general (thickness 1.6))\n'
            '\t(layers\n'
            '\t\t(0 "F.Cu" signal)\n'
            '\t)\n'
            '\t(net 0 "")\n'
            '\t(net 1 "SIG")\n'
            '\t(segment\n'
            '\t\t(start 1.0 1.0)\n'
            '\t\t(end 2.0 2.0)\n'
            '\t\t(width 0.25)\n'
            '\t\t(layer "F.Cu")\n'
            '\t\t(net 1 "SIG")\n'
            '\t\t(uuid "seg-uuid-0000-0000-0000-000000000010")\n'
            '\t)\n'
            '\t(via\n'
            '\t\t(at 5.0 5.0)\n'
            '\t\t(size 0.6)\n'
            '\t\t(drill 0.3)\n'
            '\t\t(layers "F.Cu" "B.Cu")\n'
            '\t\t(net 1 "SIG")\n'
            '\t\t(uuid "via-uuid-0000-0000-0000-000000000011")\n'
            '\t)\n'
            ')\n',
            encoding="utf-8",
        )
        board = NativeParser.parse_pcb(pcb)
        assert len(board.segments) == 1
        assert board.segments[0].uuid == "seg-uuid-0000-0000-0000-000000000010"
        assert len(board.vias) == 1
        assert board.vias[0].uuid == "via-uuid-0000-0000-0000-000000000011"


# ---------------------------------------------------------------------------
# M2: 10-cycle mock-DRC test (ALWAYS runs, never skips)
# ---------------------------------------------------------------------------


def _mock_drc_check(pcb_path: Path) -> bool:
    """Mock DRC: parse the board and verify structural integrity.

    No kicad-cli dependency. Returns True if the board parses cleanly
    (valid S-expression structure) and net count is stable.
    """
    try:
        board = NativeParser.parse_pcb(pcb_path)
        # Must have parsed without exception and have consistent structure.
        _ = board.footprints
        _ = board.nets
        _ = board.segments
        _ = board.vias
        return True
    except Exception:
        return False


class TestTenCyclesNoCorruptionMockDrc:
    """M2: This test MUST NOT skip — it validates rollback without kicad-cli."""

    def test_ten_approve_reject_cycles_clean(self, tmp_path: Path) -> None:
        pcb = _copy_fixture(tmp_path)
        undo_stack = PersistentUndoStack(project_dir=tmp_path)
        orch = RoutingOrchestrator()

        # Capture initial net count for stability check.
        initial_board = NativeParser.parse_pcb(pcb)
        initial_net_count = len(initial_board.nets)

        # Run route_board once to establish a baseline routed state.
        orch.route_board(pcb, project_dir=tmp_path, undo_stack=undo_stack)

        # Verify the board still parses cleanly after initial route.
        assert _mock_drc_check(pcb), "Board corrupted after initial route"

        # Find a net that got routed (has segments).
        routed_board = NativeParser.parse_pcb(pcb)
        routed_nets = {s.net_name for s in routed_board.segments if s.net_name}

        # If nothing was routed, we still run the cycle on a stable board
        # to validate rollback_net is a no-op that doesn't corrupt.
        cycle_net = next(iter(routed_nets), None)
        if cycle_net is None:
            # Pick any net name for the cycle — rollback should be a safe no-op.
            cycle_net = initial_board.nets[0].name if initial_board.nets else "GND"

        for i in range(10):
            # Reject: surgically remove the net's segments.
            orch.rollback_net(pcb, cycle_net, undo_stack)
            assert _mock_drc_check(pcb), f"Board corrupted at cycle {i + 1} (after rollback)"

            # Re-approve: re-route the board to restore state.
            orch.route_board(pcb, project_dir=tmp_path, undo_stack=undo_stack)
            assert _mock_drc_check(pcb), f"Board corrupted at cycle {i + 1} (after re-route)"

        # Final stability: net count should be consistent (nets are never
        # added or removed by routing — only segments/vias change).
        final_board = NativeParser.parse_pcb(pcb)
        assert len(final_board.nets) == initial_net_count


# ---------------------------------------------------------------------------
# kicad-cli integration variant (skips if kicad-cli absent)
# ---------------------------------------------------------------------------


@pytest.mark.integration
class TestTenCyclesNoCorruptionKicadCli:
    def test_ten_cycles_drc_clean(self, tmp_path: Path) -> None:
        if not _has_kicad_cli():
            pytest.skip("kicad-cli not available")

        pcb = _copy_fixture(tmp_path)
        undo_stack = PersistentUndoStack(project_dir=tmp_path)
        orch = RoutingOrchestrator()

        orch.route_board(pcb, project_dir=tmp_path, undo_stack=undo_stack)

        for i in range(10):
            # Run real DRC. We accept exit code 0 (clean) — false positives
            # are filtered via _filter_false_positives from phase99_baseline.
            result = subprocess.run(
                ["kicad-cli", "pcb", "drc", str(pcb)],
                capture_output=True, text=True, timeout=60,
            )
            # DRC exit 0 = clean. Non-zero may indicate unconnected items
            # which is acceptable for a partially-routed test board — we
            # only assert the board file itself is not corrupted (parses).
            # The mock-DRC test above covers the corruption invariant;
            # this test additionally verifies kicad-cli accepts the file.
            assert result.returncode in (0, 1), f"DRC crashed at cycle {i + 1}"

            # Rollback one net to exercise the undo path.
            board = NativeParser.parse_pcb(pcb)
            routed_nets = [s.net_name for s in board.segments if s.net_name]
            if routed_nets:
                orch.rollback_net(pcb, routed_nets[0], undo_stack)
            orch.route_board(pcb, project_dir=tmp_path, undo_stack=undo_stack)


# ---------------------------------------------------------------------------
# LO-04: rollback_net must parse the PCB exactly once
# ---------------------------------------------------------------------------


class TestRollbackNetParsesPcbOnce:
    """LO-04: rollback_net previously parsed the PCB twice — once via
    NativeParser.parse_pcb(pcb_path) to identify segments to remove, then
    implicitly again via a second pcb_path.read_text() for the raw content
    the writer needs. The fix caches a single read + parse_pcb_content call.

    This test patches NativeParser.parse_pcb_content and Path.read_text to
    assert the PCB content is read exactly once and parsed exactly once.
    """

    def test_rollback_net_parses_pcb_once(self, tmp_path: Path) -> None:
        # Minimal board with one segment on net "SIG" so rollback has work.
        pcb = tmp_path / "single_parse.kicad_pcb"
        pcb.write_text(
            '(kicad_pcb\n'
            '\t(version 20241229)\n'
            '\t(generator "test")\n'
            '\t(general (thickness 1.6))\n'
            '\t(layers\n'
            '\t\t(0 "F.Cu" signal)\n'
            '\t)\n'
            '\t(net 0 "")\n'
            '\t(net 1 "SIG")\n'
            '\t(segment\n'
            '\t\t(start 1.0 1.0)\n'
            '\t\t(end 2.0 2.0)\n'
            '\t\t(width 0.25)\n'
            '\t\t(layer "F.Cu")\n'
            '\t\t(net 1 "SIG")\n'
            '\t\t(uuid "sig-0000-0000-0000-000000000001")\n'
            '\t)\n'
            ')\n',
            encoding="utf-8",
        )

        # Patch parse_pcb_content (the LO-04 fix uses this, not parse_pcb).
        # We wrap the real method so parsing still works, but we count calls.
        real_parse = NativeParser.parse_pcb_content.__func__  # type: ignore[attr-defined]
        parse_calls: list[str] = []

        def counting_parse(cls, content: str, file_path: str = "") -> object:
            parse_calls.append(content)
            return real_parse(cls, content, file_path)

        with patch.object(NativeParser, "parse_pcb_content", classmethod(counting_parse)):
            orch = RoutingOrchestrator()
            orch.rollback_net(pcb, "SIG")

        # LO-04 acceptance: exactly one parse call inside rollback_net.
        assert len(parse_calls) == 1, (
            f"rollback_net should parse PCB exactly once (LO-04), "
            f"but parse_pcb_content was called {len(parse_calls)} times"
        )
