"""Tests for cross-file atomic operations -- XFILE-01.

Covers:
- Atomic commit on schematic + PCB pair succeeds on both
- Atomic commit returns AtomicResult with success=True and results for both files
- Rollback on uncommitted atomic operation restores both files
- Auto-rollback on exception restores both files
- Opening AtomicOperation with non-existent file rolls back already-opened Transactions
- AtomicOperation raises ValueError for empty file_paths list
- AtomicOperation raises FileNotFoundError for missing file
- AtomicOperation with single file path behaves like single Transaction
"""

import shutil
from pathlib import Path

import pytest

from kicad_agent.crossfile import AtomicOperation, AtomicResult


@pytest.fixture
def sch_pcb_pair(
    tmp_path: Path,
    arduino_mega_sch: Path,
    arduino_mega_pcb: Path,
) -> tuple[Path, Path]:
    """Copy Arduino Mega sch + pcb into tmp_path for isolated testing.

    Returns:
        Tuple of (schematic_path, pcb_path) in tmp_path.
    """
    sch = tmp_path / "Arduino_Mega.kicad_sch"
    pcb = tmp_path / "Arduino_Mega.kicad_pcb"
    shutil.copy2(arduino_mega_sch, sch)
    shutil.copy2(arduino_mega_pcb, pcb)
    return (sch, pcb)


class TestAtomicOperationCommit:
    """Happy path: open atomic on sch+pcb, commit both."""

    def test_atomic_commit_succeeds_on_both_files(
        self, sch_pcb_pair: tuple[Path, Path]
    ) -> None:
        """Atomic commit on two real KiCad files succeeds."""
        sch, pcb = sch_pcb_pair
        with AtomicOperation([sch, pcb]) as atomic:
            result = atomic.commit()
        assert result.success is True

    def test_atomic_commit_returns_results_for_both_files(
        self, sch_pcb_pair: tuple[Path, Path]
    ) -> None:
        """AtomicResult contains TransactionResults for both files."""
        sch, pcb = sch_pcb_pair
        with AtomicOperation([sch, pcb]) as atomic:
            result = atomic.commit()
        assert len(result.results) == 2
        assert all(r.success for r in result.results)
        assert result.results[0].target_file == sch.resolve()
        assert result.results[1].target_file == pcb.resolve()

    def test_atomic_commit_preserves_mutations(
        self, sch_pcb_pair: tuple[Path, Path]
    ) -> None:
        """Mutations to both files are preserved after commit."""
        sch, pcb = sch_pcb_pair
        sch_content = sch.read_text(encoding="utf-8")
        pcb_content = pcb.read_text(encoding="utf-8")
        with AtomicOperation([sch, pcb]) as atomic:
            # Write modified content to both files
            sch.write_text(sch_content + "\n# mutation", encoding="utf-8")
            pcb.write_text(pcb_content + "\n# mutation", encoding="utf-8")
            result = atomic.commit()
        assert result.success is True
        assert "# mutation" in sch.read_text(encoding="utf-8")
        assert "# mutation" in pcb.read_text(encoding="utf-8")


class TestAtomicOperationRollback:
    """Rollback restores both files to pre-transaction state."""

    def test_rollback_restores_both_files(
        self, sch_pcb_pair: tuple[Path, Path]
    ) -> None:
        """Rollback on uncommitted atomic operation restores both files."""
        sch, pcb = sch_pcb_pair
        sch_orig = sch.read_text(encoding="utf-8")
        pcb_orig = pcb.read_text(encoding="utf-8")
        with AtomicOperation([sch, pcb]) as atomic:
            sch.write_text("corrupted sch", encoding="utf-8")
            pcb.write_text("corrupted pcb", encoding="utf-8")
            result = atomic.rollback()
        assert result.success is False
        assert sch.read_text(encoding="utf-8") == sch_orig
        assert pcb.read_text(encoding="utf-8") == pcb_orig

    def test_rollback_returns_results_for_both_files(
        self, sch_pcb_pair: tuple[Path, Path]
    ) -> None:
        """Rollback returns AtomicResult with results for all files."""
        sch, pcb = sch_pcb_pair
        with AtomicOperation([sch, pcb]) as atomic:
            result = atomic.rollback()
        assert result.success is False
        assert len(result.results) == 2


class TestAtomicOperationAutoRollback:
    """Auto-rollback on exception within context manager."""

    def test_auto_rollback_on_exception(
        self, sch_pcb_pair: tuple[Path, Path]
    ) -> None:
        """Exception inside atomic context triggers auto-rollback of both files."""
        sch, pcb = sch_pcb_pair
        sch_orig = sch.read_text(encoding="utf-8")
        pcb_orig = pcb.read_text(encoding="utf-8")
        with pytest.raises(RuntimeError, match="test error"):
            with AtomicOperation([sch, pcb]):
                sch.write_text("corrupted sch", encoding="utf-8")
                pcb.write_text("corrupted pcb", encoding="utf-8")
                raise RuntimeError("test error")
        assert sch.read_text(encoding="utf-8") == sch_orig
        assert pcb.read_text(encoding="utf-8") == pcb_orig


class TestAtomicOperationErrors:
    """Error cases: empty paths, non-existent files, partial open failure."""

    def test_empty_file_paths_raises_valueerror(self) -> None:
        """AtomicOperation raises ValueError for empty file_paths list."""
        with pytest.raises(ValueError, match="at least one"):
            AtomicOperation([])

    def test_nonexistent_file_raises_filenotfound(self, tmp_path: Path) -> None:
        """AtomicOperation raises FileNotFoundError for missing file."""
        sch = tmp_path / "exists.kicad_sch"
        sch.write_text("content", encoding="utf-8")
        pcb = tmp_path / "nonexistent.kicad_pcb"
        with pytest.raises(FileNotFoundError, match="file not found"):
            AtomicOperation([sch, pcb])

    def test_partial_open_rolls_back_already_opened(
        self, tmp_path: Path,
        arduino_mega_sch: Path,
    ) -> None:
        """Opening AtomicOperation with a non-existent file rolls back the first Transaction.

        The first file is valid and would get a snapshot. The second file
        doesn't exist. The __enter__ should roll back the first Transaction
        before raising.
        """
        sch = tmp_path / "test.kicad_sch"
        shutil.copy2(arduino_mega_sch, sch)
        sch_orig = sch.read_text(encoding="utf-8")
        pcb = tmp_path / "nonexistent.kicad_pcb"

        with pytest.raises(FileNotFoundError, match="file not found"):
            with AtomicOperation([sch, pcb]):
                pass

        # First file should be restored even though it was opened successfully
        assert sch.read_text(encoding="utf-8") == sch_orig


class TestAtomicOperationSingleFile:
    """Single file path: degenerate case behaves like single Transaction."""

    def test_single_file_commit(self, tmp_path: Path, arduino_mega_sch: Path) -> None:
        """AtomicOperation with one file commits successfully."""
        sch = tmp_path / "test.kicad_sch"
        shutil.copy2(arduino_mega_sch, sch)
        with AtomicOperation([sch]) as atomic:
            result = atomic.commit()
        assert result.success is True
        assert len(result.results) == 1
        assert result.results[0].success is True

    def test_single_file_rollback(self, tmp_path: Path, arduino_mega_sch: Path) -> None:
        """AtomicOperation with one file rolls back correctly."""
        sch = tmp_path / "test.kicad_sch"
        shutil.copy2(arduino_mega_sch, sch)
        sch_orig = sch.read_text(encoding="utf-8")
        with AtomicOperation([sch]) as atomic:
            sch.write_text("corrupted", encoding="utf-8")
            result = atomic.rollback()
        assert result.success is False
        assert sch.read_text(encoding="utf-8") == sch_orig
