"""ae-26: safe_sync_pcb_from_schematic — non-destructive PCB sync from schematic.

Tests verify:
- Handler is registered and dispatches correctly
- Raw S-expression manipulation (no kiutils to_file)
- Routing/zones/placement preserved (the op's reason for existence)
- dry_run returns contract without mutation
- preserve_* invariants enforced via assertions
"""
from __future__ import annotations

import inspect
from pathlib import Path
from unittest.mock import MagicMock, patch
from volta.ir.pcb_ir import PcbIR
from volta.ir.schematic_ir import SchematicIR

import pytest


# ---------------------------------------------------------------------------
# Registration + dispatch
# ---------------------------------------------------------------------------


def test_safe_sync_registered_as_crossfile_handler():
    """The handler must be in _CROSSFILE_HANDLERS for execute() dispatch."""
    from volta.ops.handlers.crossfile import _CROSSFILE_HANDLERS
    assert "safe_sync_pcb_from_schematic" in _CROSSFILE_HANDLERS


def test_safe_sync_in_cross_file_op_types():
    """execution.py must route safe_sync through the cross_file path."""
    from volta.ops.execution import CROSS_FILE_OP_TYPES
    assert "safe_sync_pcb_from_schematic" in CROSS_FILE_OP_TYPES


def test_safe_sync_in_operation_registry():
    """registry.py must have the op metadata entry."""
    from volta.ops.registry import OPERATION_REGISTRY
    assert "safe_sync_pcb_from_schematic" in OPERATION_REGISTRY
    entry = OPERATION_REGISTRY["safe_sync_pcb_from_schematic"]
    assert entry.category == "crossfile"
    assert entry.is_readonly is False


def test_safe_sync_schema_validates_target_files():
    """Schema requires exactly one .kicad_pcb + one .kicad_sch in target_files."""
    from volta.ops._schema_crossfile import SafeSyncPcbFromSchematicOp
    import pydantic

    # Valid
    op = SafeSyncPcbFromSchematicOp(
        target_file="board.kicad_pcb",
        target_files=["board.kicad_pcb", "board.kicad_sch"],
    )
    assert op.update_references is True
    assert op.preserve_routing is True
    assert op.remove_orphans is False  # non-destructive default

    # Invalid: two .kicad_pcb
    with pytest.raises(pydantic.ValidationError):
        SafeSyncPcbFromSchematicOp(
            target_file="board.kicad_pcb",
            target_files=["board.kicad_pcb", "board2.kicad_pcb"],
        )


# ---------------------------------------------------------------------------
# Raw S-expr enforcement (no kiutils to_file)
# ---------------------------------------------------------------------------


def test_handler_does_not_use_kiutils_to_file():
    """Handler code must NOT call kiutils Board.to_file() — corrupts KiCad 10.

    Grep acceptance test per ae-26 spec.
    """
    from volta.ops.handlers.crossfile import _handle_safe_sync_pcb_from_schematic
    src = inspect.getsource(_handle_safe_sync_pcb_from_schematic)
    # Check for actual to_file() CALL (not mention in docstring/comments)
    import ast
    tree = ast.parse(src)
    calls = [n.func.attr for n in ast.walk(tree)
             if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)]
    assert "to_file" not in calls, (
        "Handler must NOT call to_file() — use raw S-expr via sync_pcb_from_netlist"
    )


def test_handler_uses_raw_sexpr_sync():
    """Handler must delegate to sync_pcb_from_netlist (raw S-expr manipulation)."""
    from volta.ops.handlers.crossfile import _handle_safe_sync_pcb_from_schematic
    src = inspect.getsource(_handle_safe_sync_pcb_from_schematic)
    assert "sync_pcb_from_netlist" in src, (
        "Handler must use sync_pcb_from_netlist for raw S-expr mutation"
    )


# ---------------------------------------------------------------------------
# Preserve_* invariants
# ---------------------------------------------------------------------------


def test_preserve_routing_assertion_fires_on_violation():
    """If sync_pcb_from_netlist accidentally adds/removes segments, handler must assert."""
    from volta.ops.handlers.crossfile import _handle_safe_sync_pcb_from_schematic
    from volta.crossfile.schematic_sync import SyncResult

    # Mock: sync returns content with DIFFERENT segment count (simulates bug)
    mock_pcb_ir = MagicMock(spec=PcbIR)
    mock_pcb_ir._parse_result = MagicMock()
    mock_pcb_ir._parse_result.raw_content = "(kicad_pcb (segment 1) (via 1) (zone 1))"
    mock_sch_ir = MagicMock(spec=SchematicIR)

    fake_sync_result = SyncResult(pad_net_updates=1, updated_nets=["GND"])

    with patch(
        "volta.ops.handlers.crossfile.sync_pcb_from_netlist"
    ) if False else patch(
        "volta.crossfile.schematic_sync.sync_pcb_from_netlist"
    ) as mock_sync:
        mock_sync.return_value = ("(kicad_pcb (segment 1) (segment 2))", fake_sync_result)
        op = MagicMock()
        op.update_pad_nets = True
        op.update_footprint_lib_ids = True
        op.add_missing_footprints = True
        op.remove_orphans = False
        op.update_references = False
        op.preserve_routing = True
        op.preserve_zones = True
        op.preserve_placement = True
        op.dry_run = False

        # Should assert because segments changed (1 → 2)
        with pytest.raises(AssertionError, match="PRESERVE ROUTING"):
            _handle_safe_sync_pcb_from_schematic(
                op,
                {Path("board.kicad_sch"): mock_sch_ir, Path("board.kicad_pcb"): mock_pcb_ir},
                Path("."),
            )


def test_preserve_zones_assertion_fires_on_violation():
    """If sync accidentally adds/removes zones, handler must assert."""
    from volta.ops.handlers.crossfile import _handle_safe_sync_pcb_from_schematic
    from volta.crossfile.schematic_sync import SyncResult

    mock_pcb_ir = MagicMock(spec=PcbIR)
    mock_pcb_ir._parse_result = MagicMock()
    mock_pcb_ir._parse_result.raw_content = "(kicad_pcb (zone 1) (segment 1) (via 1))"
    mock_sch_ir = MagicMock(spec=SchematicIR)

    fake_sync_result = SyncResult(pad_net_updates=1)

    with patch(
        "volta.crossfile.schematic_sync.sync_pcb_from_netlist"
    ) as mock_sync:
        mock_sync.return_value = ("(kicad_pcb (segment 1) (via 1))", fake_sync_result)
        op = MagicMock()
        op.update_pad_nets = True
        op.update_footprint_lib_ids = False
        op.add_missing_footprints = False
        op.remove_orphans = False
        op.update_references = False
        op.preserve_routing = True
        op.preserve_zones = True
        op.preserve_placement = True
        op.dry_run = False

        with pytest.raises(AssertionError, match="PRESERVE ZONES"):
            _handle_safe_sync_pcb_from_schematic(
                op,
                {Path("board.kicad_sch"): mock_sch_ir, Path("board.kicad_pcb"): mock_pcb_ir},
                Path("."),
            )


# ---------------------------------------------------------------------------
# Dry run
# ---------------------------------------------------------------------------


def test_dry_run_returns_contract_no_mutation():
    """dry_run=True returns has_changes status without committing."""
    from volta.ops.handlers.crossfile import _handle_safe_sync_pcb_from_schematic
    from volta.crossfile.schematic_sync import SyncResult

    mock_pcb_ir = MagicMock(spec=PcbIR)
    mock_pcb_ir._parse_result = MagicMock()
    mock_pcb_ir._parse_result.raw_content = "(kicad_pcb (segment 1) (via 1) (zone 1))"
    mock_sch_ir = MagicMock(spec=SchematicIR)

    fake_sync_result = SyncResult(pad_net_updates=5, updated_nets=["GND", "VCC"])

    with patch(
        "volta.crossfile.schematic_sync.sync_pcb_from_netlist"
    ) as mock_sync:
        mock_sync.return_value = ("(kicad_pcb (segment 1) (via 1) (zone 1))", fake_sync_result)
        op = MagicMock()
        op.update_pad_nets = True
        op.update_footprint_lib_ids = False
        op.add_missing_footprints = False
        op.remove_orphans = False
        op.update_references = False
        op.preserve_routing = True
        op.preserve_zones = True
        op.preserve_placement = True
        op.dry_run = True

        result = _handle_safe_sync_pcb_from_schematic(
            op,
            {Path("board.kicad_sch"): mock_sch_ir, Path("board.kicad_pcb"): mock_pcb_ir},
            Path("."),
        )

        assert result["dry_run"] is True
        assert result["has_changes"] is True
        assert result["pad_net_updates"] == 5
        # CRITICAL: commit_raw_content must NOT be called
        mock_pcb_ir.commit_raw_content.assert_not_called()
        mock_pcb_ir.mark_dirty.assert_not_called()


# ---------------------------------------------------------------------------
# Happy path (mocked sync)
# ---------------------------------------------------------------------------


def test_happy_path_commits_when_changes_exist():
    """When sync finds changes and dry_run=False, handler commits via commit_raw_content."""
    from volta.ops.handlers.crossfile import _handle_safe_sync_pcb_from_schematic
    from volta.crossfile.schematic_sync import SyncResult

    original = "(kicad_pcb (segment 1) (via 1) (zone 1))"
    modified = "(kicad_pcb (segment 1) (via 1) (zone 1) (net 5 \"GND\"))"
    mock_pcb_ir = MagicMock(spec=PcbIR)
    mock_pcb_ir._parse_result = MagicMock()
    mock_pcb_ir._parse_result.raw_content = original
    mock_sch_ir = MagicMock(spec=SchematicIR)

    fake_sync_result = SyncResult(
        pad_net_updates=3,
        updated_nets=["GND"],
        added_net_defs=["GND"],
    )

    with patch(
        "volta.crossfile.schematic_sync.sync_pcb_from_netlist"
    ) as mock_sync:
        mock_sync.return_value = (modified, fake_sync_result)
        op = MagicMock()
        op.update_pad_nets = True
        op.update_footprint_lib_ids = True
        op.add_missing_footprints = True
        op.remove_orphans = False
        op.update_references = False
        op.preserve_routing = True
        op.preserve_zones = True
        op.preserve_placement = True
        op.dry_run = False

        result = _handle_safe_sync_pcb_from_schematic(
            op,
            {Path("board.kicad_sch"): mock_sch_ir, Path("board.kicad_pcb"): mock_pcb_ir},
            Path("."),
        )

        assert result["has_changes"] is True
        assert result["pad_net_updates"] == 3
        assert result["routing_preserved"] is True
        assert result["zones_preserved"] is True
        assert result["references_updated"] == 0  # not yet implemented
        mock_pcb_ir.commit_raw_content.assert_called_once_with(modified)
        mock_pcb_ir.mark_dirty.assert_called_once_with("safe_sync_pcb_from_schematic")


def test_no_changes_no_commit():
    """When sync finds no changes, handler does NOT commit."""
    from volta.ops.handlers.crossfile import _handle_safe_sync_pcb_from_schematic
    from volta.crossfile.schematic_sync import SyncResult

    content = "(kicad_pcb (segment 1) (via 1) (zone 1))"
    mock_pcb_ir = MagicMock(spec=PcbIR)
    mock_pcb_ir._parse_result = MagicMock()
    mock_pcb_ir._parse_result.raw_content = content
    mock_sch_ir = MagicMock(spec=SchematicIR)

    empty_result = SyncResult()  # has_changes = False

    with patch(
        "volta.crossfile.schematic_sync.sync_pcb_from_netlist"
    ) as mock_sync:
        mock_sync.return_value = (content, empty_result)
        op = MagicMock()
        op.update_pad_nets = True
        op.update_footprint_lib_ids = True
        op.add_missing_footprints = True
        op.remove_orphans = False
        op.update_references = False
        op.preserve_routing = True
        op.preserve_zones = True
        op.preserve_placement = True
        op.dry_run = False

        result = _handle_safe_sync_pcb_from_schematic(
            op,
            {Path("board.kicad_sch"): mock_sch_ir, Path("board.kicad_pcb"): mock_pcb_ir},
            Path("."),
        )

        assert result["has_changes"] is False
        mock_pcb_ir.commit_raw_content.assert_not_called()


def test_missing_schematic_ir_raises():
    """Handler raises ValueError when no SchematicIR is provided."""
    from volta.ops.handlers.crossfile import _handle_safe_sync_pcb_from_schematic

    mock_pcb_ir = MagicMock(spec=PcbIR)
    mock_pcb_ir._parse_result = MagicMock()
    op = MagicMock()
    op.dry_run = False
    op.preserve_routing = True
    op.preserve_zones = True
    op.preserve_placement = True

    with pytest.raises(ValueError, match="requires both a schematic IR and a PCB IR"):
        _handle_safe_sync_pcb_from_schematic(
            op,
            {Path("board.kicad_pcb"): mock_pcb_ir},
            Path("."),
        )
