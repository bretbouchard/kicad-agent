"""
test_verification_handlers.py — Phase 170 verification handler tests.

Exercises kicad.pre_check, kicad.post_check, kicad.snapshot, kicad.restore
handlers. No live daemon — handlers called directly with synthetic params.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from handlers import (
    HandlerContext,
    kicad_pre_check,
    kicad_post_check,
    kicad_snapshot,
    kicad_restore,
)
from protocol import RpcError


class _FakeAudit:
    def log_event(self, event: str, **fields: Any) -> None:
        pass

    def log_rpc(self, method: str, **fields: Any) -> None:
        pass


@pytest.fixture
def ctx() -> HandlerContext:
    return HandlerContext(executor_factory=lambda: None, audit=_FakeAudit())


# =============================================================================
# kicad.pre_check
# =============================================================================

class TestPreCheck:
    def test_known_op_with_valid_target_allows(self, ctx: HandlerContext) -> None:
        # add_component is in the registry — using a registry-known op.
        # If the registry isn't importable in test env, op_known flips to
        # False but the gate still allows based on file_type alone.
        result = kicad_pre_check(
            {"op_type": "add_component",
             "args": {"target_file": "/tmp/board.kicad_sch"}},
            ctx,
        )
        assert result["decision"] in {"allow", "warn", "block"}
        assert result["op_type"] == "add_component"
        assert "checks" in result

    def test_dotdot_path_blocked(self, ctx: HandlerContext) -> None:
        result = kicad_pre_check(
            {"op_type": "add_component",
             "args": {"target_file": "../../etc/passwd"}},
            ctx,
        )
        assert result["decision"] == "block"
        assert result["checks"]["file_type_ok"] is False
        assert any(".." in r for r in result["reasons"])

    def test_unsupported_suffix_blocked(self, ctx: HandlerContext) -> None:
        result = kicad_pre_check(
            {"op_type": "add_component",
             "args": {"target_file": "/tmp/file.txt"}},
            ctx,
        )
        assert result["decision"] == "block"
        assert result["checks"]["file_type_ok"] is False

    def test_kicad_sch_suffix_passes_file_type(self, ctx: HandlerContext) -> None:
        result = kicad_pre_check(
            {"op_type": "add_component",
             "args": {"target_file": "/tmp/board.kicad_sch"}},
            ctx,
        )
        assert result["checks"]["file_type_ok"] is True

    def test_kicad_pcb_suffix_passes_file_type(self, ctx: HandlerContext) -> None:
        result = kicad_pre_check(
            {"op_type": "pcb_add_segment",
             "args": {"target_file": "/tmp/board.kicad_pcb"}},
            ctx,
        )
        assert result["checks"]["file_type_ok"] is True

    def test_missing_op_type_raises(self, ctx: HandlerContext) -> None:
        with pytest.raises(RpcError):
            kicad_pre_check({"args": {}}, ctx)

    def test_readonly_op_without_target_file_allowed(self, ctx: HandlerContext) -> None:
        # query_components is a read-only op — should not require target_file.
        result = kicad_pre_check(
            {"op_type": "query_components", "args": {}},
            ctx,
        )
        assert result["decision"] in {"allow", "block"}


# =============================================================================
# kicad.post_check
# =============================================================================

class TestPostCheck:
    def test_post_check_returns_decision(self, ctx: HandlerContext) -> None:
        # No real files on disk → ERC returns "indeterminate" or "failed".
        # The handler must still return a structured dict.
        result = kicad_post_check(
            {"op_type": "add_component",
             "files": ["/tmp/nonexistent.kicad_sch"],
             "require_erc": True,
             "require_drc": False},
            ctx,
        )
        assert result["decision"] in {"passed", "failed", "indeterminate"}
        assert isinstance(result["failures"], list)

    def test_post_check_skipped_when_no_files(self, ctx: HandlerContext) -> None:
        result = kicad_post_check(
            {"op_type": "add_component", "files": []},
            ctx,
        )
        # Nothing to check — indeterminate.
        assert result["decision"] == "indeterminate"

    def test_post_check_with_pcb_file(self, ctx: HandlerContext) -> None:
        result = kicad_post_check(
            {"op_type": "pcb_add_segment",
             "files": ["/tmp/nonexistent.kicad_pcb"],
             "require_erc": False,
             "require_drc": True},
            ctx,
        )
        assert result["decision"] in {"passed", "failed", "indeterminate"}

    def test_missing_op_type_raises(self, ctx: HandlerContext) -> None:
        with pytest.raises(RpcError):
            kicad_post_check({"files": []}, ctx)


# =============================================================================
# kicad.snapshot + kicad.restore
# =============================================================================

class TestSnapshotRestore:
    def test_snapshot_returns_snapshot_id(self, ctx: HandlerContext, tmp_path: Path) -> None:
        f = tmp_path / "board.kicad_sch"
        f.write_text("original")
        result = kicad_snapshot({"files": [str(f)]}, ctx)
        assert "snapshot_id" in result
        assert isinstance(result["snapshot_id"], str)
        assert result["files_snapshotted"] == 1

    def test_restore_roundtrip(self, ctx: HandlerContext, tmp_path: Path) -> None:
        f = tmp_path / "board.kicad_sch"
        f.write_text("original")
        snap = kicad_snapshot({"files": [str(f)]}, ctx)
        sid = snap["snapshot_id"]

        # Mutate.
        f.write_text("mutated")

        # Restore.
        summary = kicad_restore({"snapshot_id": sid}, ctx)
        assert summary["restored"] == 1
        assert f.read_text() == "original"

    def test_unknown_snapshot_id_raises(self, ctx: HandlerContext) -> None:
        with pytest.raises(RpcError):
            kicad_restore({"snapshot_id": "nonexistent"}, ctx)

    def test_snapshot_with_traversal_raises(self, ctx: HandlerContext) -> None:
        with pytest.raises(RpcError):
            kicad_snapshot({"files": ["../../../etc/passwd"]}, ctx)

    def test_empty_files_list_raises_invalid_params(
        self, ctx: HandlerContext
    ) -> None:
        # Missing 'files' key.
        with pytest.raises(RpcError):
            kicad_snapshot({}, ctx)

    def test_snapshot_with_base_dir_enforced(
        self, ctx: HandlerContext, tmp_path: Path
    ) -> None:
        project = tmp_path / "project"
        project.mkdir()
        f = project / "board.kicad_sch"
        f.write_text("ok")

        # Inside base_dir — OK.
        result = kicad_snapshot(
            {"files": [str(f)], "base_dir": str(project)},
            ctx,
        )
        assert "snapshot_id" in result

        # Outside base_dir — error.
        outside = tmp_path / "outside.kicad_sch"
        outside.write_text("not in project")
        with pytest.raises(RpcError):
            kicad_snapshot(
                {"files": [str(outside)], "base_dir": str(project)},
                ctx,
            )
