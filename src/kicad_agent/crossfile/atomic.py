"""Atomic cross-file operations with multi-file transaction coordination.

XFILE-01: Wraps multiple file-level Transactions in a single atomic unit.
If any file's transaction fails (on open, commit, or during mutation),
all previously opened/committed transactions are rolled back.

Usage:
    from kicad_agent.crossfile import AtomicOperation

    with AtomicOperation([schematic_path, pcb_path]) as atomic:
        # ... perform mutations on both files ...
        result = atomic.commit()
    # If exception occurs, all files auto-rollback

Security (inherited from Transaction):
- T-06-01: Symlink check on each path before opening Transaction
- T-06-02: fcntl locking inherited from Transaction per-file
- T-06-03: ValueError raised for empty file_paths list
- T-06-04: Snapshot permissions 0o600 inherited from Transaction
- T-06-05: If Nth commit fails, rollback all N-1 already-committed Transactions
"""

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

from kicad_agent.ir.transaction import Transaction, TransactionResult

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AtomicResult:
    """Result of an atomic operation commit or rollback.

    Attributes:
        success: True if all per-file transactions succeeded.
        results: List of TransactionResult for each file.
        error: Error message if any transaction failed.
    """

    success: bool
    results: list[TransactionResult]
    error: Optional[str] = None


class AtomicOperation:
    """Atomic coordinator for multi-file KiCad mutations.

    Wraps N files in a single all-or-nothing transaction:
    - __enter__ opens a Transaction for each file path
    - If any Transaction fails to open, all previously opened are rolled back
    - commit() commits all Transactions; if any fails, all are rolled back
    - rollback() rolls back all Transactions in reverse order
    - __exit__ auto-rolls back on exception if not committed
    """

    def __init__(self, file_paths: list[Path]) -> None:
        """Initialize atomic operation with file paths.

        Args:
            file_paths: List of KiCad file paths to include in the atomic operation.

        Raises:
            ValueError: If file_paths is empty.
        """
        if not file_paths:
            raise ValueError("AtomicOperation requires at least one file path")
        # T-06-01: Validate all paths exist (early fail before opening Transactions)
        for fp in file_paths:
            if fp.is_symlink():
                raise ValueError(f"Refusing to operate on symlink: {fp}")
            resolved = fp.resolve()
            if not resolved.exists():
                raise FileNotFoundError(
                    f"Cannot start atomic operation: file not found: {resolved}"
                )
        self._file_paths = list(file_paths)
        self._transactions: list[Transaction] = []
        self._committed = False
        self._rolled_back = False

    def __enter__(self) -> "AtomicOperation":
        """Open a Transaction for each file path.

        If the Nth Transaction fails to open, rolls back all N-1
        already-opened Transactions and raises the error.

        Returns:
            Self for use as context manager.
        """
        for i, file_path in enumerate(self._file_paths):
            try:
                txn = Transaction(file_path)
                txn.__enter__()
                self._transactions.append(txn)
            except (FileNotFoundError, ValueError, RuntimeError):
                # Roll back all already-opened Transactions in reverse order
                self._rollback_opened()
                raise
        return self

    def commit(self) -> AtomicResult:
        """Commit all Transactions. If any fails, roll back all.

        Returns:
            AtomicResult with success status and per-file results.
        """
        if self._committed:
            return AtomicResult(
                success=True,
                results=[t.commit() for t in self._transactions],
            )

        results: list[TransactionResult] = []
        for i, txn in enumerate(self._transactions):
            try:
                result = txn.commit()
                results.append(result)
            except Exception as e:
                # T-06-05: Nth commit failed -- rollback all N-1 already-committed
                error_msg = f"Commit failed on file {i+1}/{len(self._transactions)}: {e}"
                logger.error(error_msg)
                # Roll back all Transactions (including already-committed ones)
                rollback_results = self._rollback_all()
                self._rolled_back = True
                return AtomicResult(
                    success=False,
                    results=results + rollback_results,
                    error=error_msg,
                )

        self._committed = True
        return AtomicResult(success=True, results=results)

    def rollback(self) -> AtomicResult:
        """Roll back all Transactions in reverse order.

        Returns:
            AtomicResult with success=False and per-file rollback results.
        """
        if self._rolled_back:
            return AtomicResult(
                success=False,
                results=[],
                error="Already rolled back",
            )

        results = self._rollback_all()
        self._rolled_back = True
        return AtomicResult(
            success=False,
            results=results,
            error="Rolled back to pre-mutation state",
        )

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        """Auto-rollback on exception if not committed.

        If an exception occurred and the operation was not committed,
        roll back all Transactions to restore original file state.
        """
        if exc_type is not None and not self._committed:
            logger.warning(
                "AtomicOperation auto-rollback triggered by exception: %s",
                exc_val,
            )
            self._rollback_all()
            self._rolled_back = True
        elif not self._committed and not self._rolled_back:
            logger.warning(
                "AtomicOperation exited without commit or rollback. "
                "Auto-rolling back all files."
            )
            self._rollback_all()
            self._rolled_back = True
        return False  # Don't suppress exceptions

    def _rollback_all(self) -> list[TransactionResult]:
        """Roll back all Transactions in reverse order.

        Returns:
            List of TransactionResult from each rollback.
        """
        results: list[TransactionResult] = []
        for txn in reversed(self._transactions):
            try:
                result = txn.rollback()
                results.append(result)
            except Exception as e:
                logger.error("Rollback failed for %s: %s", txn._file_path, e)
        return results

    def _rollback_opened(self) -> None:
        """Roll back all already-opened Transactions (for __enter__ failure)."""
        for txn in reversed(self._transactions):
            try:
                txn.__exit__(None, None, None)
            except Exception as e:
                logger.error("Rollback during __enter__ cleanup failed: %s", e)
        self._transactions.clear()
