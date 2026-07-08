"""
test_snapshot.py — Snapshot helper tests.

Phase 170 — Verification Loop Integration (GOV-05).

Exercises snapshot.py directly: capture → mutate → restore → verify
content roundtrips. No daemon, no MCP.
"""

from __future__ import annotations

import json
import os
import tempfile
from pathlib import Path

import pytest

from snapshot import Snapshot, SnapshotError


# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def tmp_project(tmp_path: Path) -> Path:
    """Create a temp project dir with sample KiCad files."""
    sch = tmp_path / "board.kicad_sch"
    sch.write_text("(kicad_sch version 20250101) (original content)")
    pcb = tmp_path / "board.kicad_pcb"
    pcb.write_text("(kicad_pcb version 20250101) (original pcb)")
    return tmp_path


# =============================================================================
# Capture / restore roundtrip
# =============================================================================

class TestSnapshotRoundtrip:
    def test_capture_returns_snapshot_with_manifest(self, tmp_project: Path) -> None:
        sch = tmp_project / "board.kicad_sch"
        pcb = tmp_project / "board.kicad_pcb"
        snap = Snapshot.create([sch, pcb])
        assert len(snap.manifest) == 2
        assert str(sch) in snap.manifest
        assert str(pcb) in snap.manifest

    def test_restore_reverts_mutations(self, tmp_project: Path) -> None:
        sch = tmp_project / "board.kicad_sch"
        original = sch.read_text()
        snap = Snapshot.create([sch])

        # Mutate.
        sch.write_text("(kicad_sch version 20250101) (mutated by op)")
        assert sch.read_text() != original

        # Restore.
        summary = snap.restore()
        assert summary["restored"] == 1
        assert sch.read_text() == original

    def test_restore_removes_op_created_files(self, tmp_project: Path) -> None:
        sch = tmp_project / "board.kicad_sch"
        new_file = tmp_project / "new.kicad_sch"

        # Pre-op: new_file doesn't exist.
        snap = Snapshot.create([sch, new_file])
        assert snap.manifest[str(new_file)]["exists"] is False

        # Op creates new_file.
        new_file.write_text("(should be removed on restore)")

        # Restore should remove new_file.
        summary = snap.restore()
        assert summary["removed"] == 1
        assert not new_file.exists()

    def test_restore_idempotent_skip_if_no_change(self, tmp_project: Path) -> None:
        sch = tmp_project / "board.kicad_sch"
        new_file = tmp_project / "new.kicad_sch"
        snap = Snapshot.create([sch, new_file])

        # Don't create new_file — restore should skip it.
        summary = snap.restore()
        assert summary["restored"] == 1
        assert summary["skipped"] == 1
        assert summary["removed"] == 0


# =============================================================================
# Path traversal defense (T-170-06)
# =============================================================================

class TestPathTraversalDefense:
    def test_dotdot_segment_rejected(self, tmp_project: Path) -> None:
        sch = tmp_project / "board.kicad_sch"
        malicious = Path("../../../etc/passwd")
        with pytest.raises(SnapshotError, match="\\.\\."):
            Snapshot.create([sch, malicious])

    def test_outside_base_dir_rejected(self, tmp_path: Path) -> None:
        project = tmp_path / "project"
        project.mkdir()
        sch = project / "board.kicad_sch"
        sch.write_text("ok")
        outside = tmp_path / "outside.kicad_sch"
        outside.write_text("not in project")
        with pytest.raises(SnapshotError, match="outside base_dir"):
            Snapshot.create([outside], base_dir=project)


# =============================================================================
# Deduplication
# =============================================================================

class TestDeduplication:
    def test_identical_files_share_blob(self, tmp_project: Path) -> None:
        # Two files with identical content should share one blob.
        sch1 = tmp_project / "board.kicad_sch"
        sch2 = tmp_project / "board2.kicad_sch"
        sch2.write_text(sch1.read_text())

        snap = Snapshot.create([sch1, sch2])
        blobs_dir = snap.snapshot_dir / "blobs"
        blob_count = sum(1 for _ in blobs_dir.iterdir())
        assert blob_count == 1


# =============================================================================
# Cleanup
# =============================================================================

class TestCleanup:
    def test_close_removes_snapshot_dir(self, tmp_project: Path) -> None:
        sch = tmp_project / "board.kicad_sch"
        snap = Snapshot.create([sch])
        snap_dir = snap.snapshot_dir
        assert snap_dir.exists()
        snap.close()
        assert not snap_dir.exists()


# =============================================================================
# Non-regular files
# =============================================================================

class TestNonRegularFiles:
    def test_directory_rejected(self, tmp_project: Path) -> None:
        subdir = tmp_project / "subdir"
        subdir.mkdir()
        with pytest.raises(SnapshotError, match="non-regular"):
            Snapshot.create([subdir])
