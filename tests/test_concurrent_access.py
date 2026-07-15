"""Tests for O-BUG-008: Concurrent access warning mechanism.

Validates that a .volta.lock file triggers a warning
when another process is editing the same file.
"""
from __future__ import annotations

import logging
from pathlib import Path

import pytest

from volta.ops.execution import (
    _check_concurrent_access,
    _LOCK_FILE_NAME,
)


class TestConcurrentAccessOBUG008:
    """O-BUG-008: Concurrent access warning."""

    def test_lock_file_created(self, tmp_path: Path):
        """A lock file is created when checking access."""
        target = tmp_path / "test.kicad_sch"
        target.touch()

        _check_concurrent_access(target)

        lock_file = tmp_path / _LOCK_FILE_NAME
        assert lock_file.exists()
        content = lock_file.read_text(encoding="utf-8")
        assert "test.kicad_sch" in content
        assert "pid=" in content

    def test_warning_emitted_when_lock_exists(self, tmp_path: Path, caplog):
        """Warning emitted when lock file already exists."""
        target = tmp_path / "test.kicad_sch"
        target.touch()

        # Pre-create lock file from another "process"
        lock_file = tmp_path / _LOCK_FILE_NAME
        lock_file.write_text("test.kicad_sch:pid=99999", encoding="utf-8")

        with caplog.at_level(logging.WARNING, logger="volta.ops.execution"):
            _check_concurrent_access(target)

        assert any(
            "Concurrent access detected" in r.message
            for r in caplog.records
        )

    def test_no_warning_when_no_lock(self, tmp_path: Path, caplog):
        """No warning when no lock file exists."""
        target = tmp_path / "test.kicad_sch"
        target.touch()

        with caplog.at_level(logging.WARNING, logger="volta.ops.execution"):
            _check_concurrent_access(target)

        assert not any(
            "Concurrent access" in r.message
            for r in caplog.records
        )

    def test_lock_file_updated(self, tmp_path: Path):
        """Lock file is updated on subsequent access checks."""
        target = tmp_path / "test.kicad_sch"
        target.touch()

        _check_concurrent_access(target)
        _check_concurrent_access(target)

        lock_file = tmp_path / _LOCK_FILE_NAME
        assert lock_file.exists()
