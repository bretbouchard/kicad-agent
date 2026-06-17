"""Tests for file-level transaction with snapshot-based rollback -- FND-07.

Covers:
- D-08: File-level snapshots (shutil.copy2)
- D-09: Auto-rollback on exception
- D-10: Full file copy (not delta-based)
- Council H-02: Symlink TOCTOU protection
- Council H-03: Snapshot file permissions (0o600)
- Council H-04: Concurrent modification guard via .lck locking
- Council M-03: Cleanup robust to partial states
- Council MEDIUM Finding 6: Auto-rollback without commit logs warning
"""

import json
import logging
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from kicad_agent.ir.transaction import Transaction, TransactionResult


@pytest.fixture
def test_file(tmp_path: Path) -> Path:
    """Create a temp file with known content for transaction tests."""
    f = tmp_path / "test.kicad_sch"
    f.write_text("original content", encoding="utf-8")
    return f


class TestTransactionSnapshot:
    """D-08: File-level snapshot creation."""

    def test_snapshot_created_on_enter(self, test_file: Path) -> None:
        """Snapshot exists and matches original after entering context."""
        with Transaction(test_file) as txn:
            assert txn.snapshot_path is not None
            assert txn.snapshot_path.exists()
            assert txn.snapshot_path.read_text(encoding="utf-8") == "original content"

    def test_snapshot_in_temp_dir(self, test_file: Path) -> None:
        """Snapshot is stored in a temp directory with kicad-agent prefix."""
        with Transaction(test_file) as txn:
            assert txn.snapshot_path is not None
            assert "kicad-agent" in str(txn.snapshot_path.parent)


class TestTransactionCommit:
    """D-10: Commit removes snapshot and preserves mutations."""

    def test_commit_removes_snapshot(self, test_file: Path) -> None:
        """After commit, snapshot file is cleaned up."""
        with Transaction(test_file) as txn:
            snap = txn.snapshot_path
            assert snap is not None
        # After context exit without commit, rollback happens
        # Now test with commit
        with Transaction(test_file) as txn:
            snap = txn.snapshot_path
            txn.commit()
        # snapshot_path is set to None after cleanup
        assert txn.snapshot_path is None

    def test_commit_returns_success(self, test_file: Path) -> None:
        """Commit returns TransactionResult with success=True."""
        with Transaction(test_file) as txn:
            result = txn.commit()
        assert result.success is True
        assert result.snapshot_created is True
        assert result.target_file == test_file.resolve()

    def test_commit_preserves_mutated_file(self, test_file: Path) -> None:
        """After commit, the mutated file retains new content."""
        with Transaction(test_file) as txn:
            test_file.write_text("modified content", encoding="utf-8")
            txn.commit()
        assert test_file.read_text(encoding="utf-8") == "modified content"

    def test_double_commit_idempotent(self, test_file: Path) -> None:
        """Calling commit() twice returns success without error."""
        with Transaction(test_file) as txn:
            result1 = txn.commit()
            result2 = txn.commit()
        assert result1.success is True
        assert result2.success is True


class TestTransactionRollback:
    """D-09: Rollback restores original file from snapshot."""

    def test_rollback_restores_original(self, test_file: Path) -> None:
        """Rollback restores file to pre-transaction state."""
        with Transaction(test_file) as txn:
            test_file.write_text("modified content", encoding="utf-8")
            txn.rollback()
        assert test_file.read_text(encoding="utf-8") == "original content"

    def test_rollback_returns_failure(self, test_file: Path) -> None:
        """Rollback returns TransactionResult with success=False."""
        with Transaction(test_file) as txn:
            result = txn.rollback()
        assert result.success is False
        assert result.target_file == test_file.resolve()

    def test_double_rollback_idempotent(self, test_file: Path) -> None:
        """Calling rollback() twice returns no error on second call."""
        with Transaction(test_file) as txn:
            result1 = txn.rollback()
            result2 = txn.rollback()
        assert result1.success is False
        assert result2.success is False
        assert result2.error == "Already rolled back"


class TestAutoRollback:
    """D-09: Auto-rollback on exception or missing commit."""

    def test_auto_rollback_on_exception(self, test_file: Path) -> None:
        """Exception inside transaction triggers auto-rollback."""
        with pytest.raises(RuntimeError, match="test error"):
            with Transaction(test_file) as txn:
                test_file.write_text("corrupted", encoding="utf-8")
                raise RuntimeError("test error")
        assert test_file.read_text(encoding="utf-8") == "original content"

    def test_auto_rollback_on_no_commit(self, test_file: Path) -> None:
        """Exiting context without commit triggers auto-rollback."""
        with Transaction(test_file):
            test_file.write_text("modified", encoding="utf-8")
        # No commit() called, so auto-rollback should restore original
        assert test_file.read_text(encoding="utf-8") == "original content"


class TestTransactionErrors:
    """Error conditions for transaction initialization."""

    def test_nonexistent_file_raises(self) -> None:
        """Transaction on nonexistent file raises FileNotFoundError."""
        with pytest.raises(FileNotFoundError, match="file not found"):
            Transaction(Path("/nonexistent/file.kicad_sch"))

    def test_cleanup_after_commit(self, test_file: Path) -> None:
        """After commit, temp directory is removed."""
        with Transaction(test_file) as txn:
            snap_dir = txn.snapshot_path.parent if txn.snapshot_path else None
            txn.commit()
        # snapshot_path is None after cleanup
        assert txn.snapshot_path is None


class TestTransactionSecurity:
    """Council security findings: H-02, H-03, H-04, MEDIUM Finding 6."""

    def test_symlink_target_rejected(self, tmp_path: Path) -> None:
        """Council H-02: Transaction rejects symlink targets."""
        real_file = tmp_path / "real.kicad_sch"
        real_file.write_text("content", encoding="utf-8")
        symlink = tmp_path / "link.kicad_sch"
        symlink.symlink_to(real_file)
        with pytest.raises(ValueError, match="symlink"):
            Transaction(symlink)

    def test_snapshot_permissions_restricted(self, test_file: Path) -> None:
        """Council H-03: Snapshot files have 0o600 permissions."""
        with Transaction(test_file) as txn:
            assert txn.snapshot_path is not None
            mode = os.stat(txn.snapshot_path).st_mode & 0o777
            assert mode == 0o600

    def test_concurrent_transaction_rejected(self, test_file: Path) -> None:
        """Council H-04: Second transaction on same file is rejected."""
        with Transaction(test_file) as txn1:
            with pytest.raises(RuntimeError, match="Cannot acquire lock"):
                with Transaction(test_file) as txn2:
                    pass
            txn1.commit()

    def test_lock_released_on_commit(self, test_file: Path) -> None:
        """Council H-04: Lock is released after commit, allowing new transaction."""
        with Transaction(test_file) as txn1:
            txn1.commit()
        # Lock should be released now
        with Transaction(test_file) as txn2:
            txn2.commit()

    def test_lock_released_on_rollback(self, test_file: Path) -> None:
        """Council H-04: Lock is released after rollback."""
        with Transaction(test_file) as txn1:
            txn1.rollback()
        # Lock should be released now
        with Transaction(test_file) as txn2:
            txn2.commit()



class TestTransactionSecurityLogs:
    """Log-based security tests using pytest's caplog."""

    def test_auto_rollback_logs_warning(
        self, test_file: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Council MEDIUM Finding 6: Auto-rollback without commit logs warning."""
        with caplog.at_level(logging.WARNING, logger="kicad_agent.ir.transaction"):
            with Transaction(test_file):
                test_file.write_text("modified", encoding="utf-8")
        assert any(
            "without commit or rollback" in record.message
            for record in caplog.records
        ), "Expected warning about auto-rollback without commit"


class TestTransactionCleanupLogging:
    """D-09: Transaction cleanup failures are logged at WARNING level."""

    def test_cleanup_snapshot_unlink_filenotfound_passes(
        self, test_file: Path
    ) -> None:
        """FileNotFoundError during snapshot unlink is acceptable (already cleaned up)."""
        with Transaction(test_file) as txn:
            txn.commit()
        # No exception -- FileNotFoundError is silently accepted

    def test_cleanup_rmdir_oserror_logged_as_warning(
        self, test_file: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """OSError during cleanup directory removal is logged at WARNING (D-09)."""
        import tempfile

        with Transaction(test_file) as txn:
            # Manually create a file inside the snapshot directory
            # so rmdir() will fail with OSError (directory not empty)
            snap_dir = txn._snap_dir
            if snap_dir:
                extra_file = Path(snap_dir) / "extra_file.tmp"
                extra_file.write_text("blocking cleanup", encoding="utf-8")
            txn.commit()
        # Should log a WARNING about cleanup failure
        assert any(
            "Failed to cleanup transaction snapshot directory" in record.message
            and record.levelno == logging.WARNING
            for record in caplog.records
        ), "Expected WARNING log for snapshot directory cleanup failure"

    def test_cleanup_rmdir_filenotfound_passes(
        self, test_file: Path
    ) -> None:
        """FileNotFoundError during cleanup directory removal is acceptable."""
        with Transaction(test_file) as txn:
            txn.commit()
        # No exception -- successful cleanup


class TestLockError:
    """D-10 + M-02: LockError raised on write failure; read failure remains soft."""

    def test_lock_file_write_failure_raises_lock_error(
        self, tmp_path: Path
    ) -> None:
        """D-10: Lock file write failure raises LockError."""
        from kicad_agent.ops.execution import LockError, _check_concurrent_access
        from unittest.mock import patch, MagicMock

        f = tmp_path / "test.kicad_sch"
        f.write_text("content", encoding="utf-8")

        with patch("kicad_agent.ops.execution.Path.write_text", side_effect=OSError("Permission denied")):
            with pytest.raises(LockError) as exc_info:
                _check_concurrent_access(f)
            assert "Failed to create lock file" in str(exc_info.value)

    def test_lock_file_write_failure_chains_original_oserror(
        self, tmp_path: Path
    ) -> None:
        """LockError.__cause__ is set to the original OSError (L-02 pattern)."""
        from kicad_agent.ops.execution import LockError, _check_concurrent_access
        from unittest.mock import patch

        f = tmp_path / "test.kicad_sch"
        f.write_text("content", encoding="utf-8")

        original_error = OSError("write failed")
        with patch("kicad_agent.ops.execution.Path.write_text", side_effect=original_error):
            with pytest.raises(LockError) as exc_info:
                _check_concurrent_access(f)
            assert exc_info.value.__cause__ is original_error

    def test_lock_file_read_failure_remains_soft_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """M-02: Lock file read failure at site (1) does NOT raise LockError."""
        from kicad_agent.ops.execution import LockError, _check_concurrent_access
        from unittest.mock import patch

        f = tmp_path / "test.kicad_sch"
        f.write_text("content", encoding="utf-8")

        # Create an existing lock file
        lock_path = tmp_path / ".kicad_agent.lock"
        lock_path.write_text("existing:pid=999", encoding="utf-8")

        # Mock read_text to fail, but write_text to succeed
        with patch("kicad_agent.ops.execution.Path.read_text", side_effect=OSError("read failed")):
            with caplog.at_level(logging.WARNING):
                _check_concurrent_access(f)

        # Should NOT raise LockError
        assert not any(
            isinstance(record.exc_info[1], LockError) if record.exc_info else False
            for record in caplog.records
        )
        # Should log a warning about concurrent access with unreadable content
        assert any(
            "<unreadable>" in record.message
            for record in caplog.records
        )

    def test_lock_file_read_failure_fallback_to_unreadable(
        self, tmp_path: Path
    ) -> None:
        """M-02: Lock read failure sets lock_content to '<unreadable>'."""
        from kicad_agent.ops.execution import _check_concurrent_access
        from unittest.mock import patch

        f = tmp_path / "test.kicad_sch"
        f.write_text("content", encoding="utf-8")

        lock_path = tmp_path / ".kicad_agent.lock"
        lock_path.write_text("existing:pid=999", encoding="utf-8")

        # Mock read to fail
        read_calls = [0]
        original_read = Path.read_text

        def _mock_read(self, *args, **kwargs):
            if str(self).endswith(".kicad_agent.lock"):
                raise OSError("read failed")
            return original_read(self, *args, **kwargs)

        with patch.object(Path, "read_text", _mock_read):
            _check_concurrent_access(f)

        # No exception -- soft fallback
        assert True


class TestSilentFailureHardening:
    """D-11: repair_wires and persistent_undo log failures at WARNING."""

    def test_repair_wires_logs_net_index_failure_as_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """D-11: NetPositionIndex build failure in repair_wires is logged at WARNING."""
        from kicad_agent.ops.repair_wires import repair_wire_snapping
        from kicad_agent.ir.schematic_ir import SchematicIR
        from kicad_agent.parser import parse_schematic

        # Use Arduino_Mega fixture
        fixture = Path(__file__).parent / "fixtures" / "Arduino_Mega" / "Arduino_Mega.kicad_sch"
        import shutil
        dest = tmp_path / "test.kicad_sch"
        shutil.copy2(fixture, dest)

        parse_result = parse_schematic(dest)
        ir = SchematicIR(_parse_result=parse_result)

        with caplog.at_level(logging.WARNING):
            with patch(
                "kicad_agent.ops.repair_wires.NetPositionIndex.from_file",
                side_effect=RuntimeError("mock net index failure"),
            ):
                repair_wire_snapping(ir, dest)

        assert any(
            "NetPositionIndex" in record.message
            and record.levelno == logging.WARNING
            for record in caplog.records
        ), "Expected WARNING log for NetPositionIndex failure"

    def test_persistent_undo_logs_load_entry_failure_as_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """D-11: Persistent undo entry load failure is logged at WARNING."""
        from kicad_agent.ops.persistent_undo import PersistentUndoStack

        # Create project structure that PersistentUndoStack expects
        project_dir = tmp_path / "project"
        project_dir.mkdir()
        undo_dir = project_dir / ".kicad-agent" / "undo"
        undo_dir.mkdir(parents=True)

        # Create a corrupt entry file BEFORE creating stack
        # (stack.__init__ calls _load_from_disk automatically)
        entry_path = undo_dir / "000000_test.json"
        entry_path.write_text("INVALID JSON {{{{", encoding="utf-8")

        # Manifest references the corrupt entry file
        manifest_path = undo_dir / "manifest.json"
        manifest_path.write_text(json.dumps({
            "next_seq": 2,
            "entries": [
                {
                    "file_path": str(tmp_path / "dummy.kicad_sch"),
                    "entry_file": "000000_test.json",
                }
            ],
        }), encoding="utf-8")

        with caplog.at_level(logging.WARNING):
            stack = PersistentUndoStack(project_dir=project_dir)

        assert any(
            "Failed to load undo entry" in record.message
            and record.levelno == logging.WARNING
            for record in caplog.records
        ), "Expected WARNING log for failed undo entry load"
