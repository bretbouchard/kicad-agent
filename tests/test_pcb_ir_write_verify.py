"""Tests for PcbIR commit_raw_content write verification (D-14).

Verifies that commit_raw_content reads back the written file and compares
SHA-256 hashes, raising IOError on mismatch.
"""

import hashlib
import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from volta.ir.pcb_ir import PcbIR
from volta.parser.types import ParseResult


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pcb_ir(tmp_path: Path, content: str = "(kicad_pcb\n  (version 20240101)\n)") -> PcbIR:
    """Create a PcbIR pointing to a temp file with given content."""
    file_path = tmp_path / "test.kicad_pcb"
    file_path.write_text(content, encoding="utf-8")
    parse_result = ParseResult(
        kiutils_obj=MagicMock(),
        raw_content=content,
        file_path=file_path,
        file_type="pcb",
    )
    return PcbIR(_parse_result=parse_result, _uuid_map=MagicMock())


# ---------------------------------------------------------------------------
# D-14: Write verification tests
# ---------------------------------------------------------------------------


class TestCommitWriteVerification:
    """D-14: commit_raw_content reads back and compares SHA-256."""

    def test_commit_verifies_write_by_hash(self, tmp_path):
        """D-14: commit_raw_content reads back file and compares SHA-256 hashes."""
        ir = _make_pcb_ir(tmp_path, "(kicad_pcb (version 20240101))")
        new_content = "(kicad_pcb (version 20240101) (general (thickness 1.6)))"

        # Let atomic_write actually write the file so read-back verification passes
        with patch("volta.io.atomic_write.atomic_write", side_effect=lambda fp, content: fp.write_text(content, encoding="utf-8")):
            ir.commit_raw_content(new_content)

        # Verify IR state was updated
        assert ir._parse_result.raw_content == new_content
        assert ir._raw_written is True

    def test_commit_raises_ioerror_on_hash_mismatch(self, tmp_path):
        """D-14: IOError raised when written content doesn't match expected."""
        ir = _make_pcb_ir(tmp_path, "(kicad_pcb (version 20240101))")
        new_content = "(kicad_pcb (version 20240101) (general (thickness 1.6)))"

        # Patch atomic_write (local import), then make read_text return corruption
        with patch("volta.io.atomic_write.atomic_write"):
            original_read = Path.read_text
            def fake_read(self_arg, encoding="utf-8", **kwargs):
                if "test.kicad_pcb" in str(self_arg):
                    return "(corrupted content)"
                return original_read(self_arg, encoding=encoding, **kwargs)
            with patch.object(Path, "read_text", fake_read):
                with pytest.raises(IOError, match="Write verification failed"):
                    ir.commit_raw_content(new_content)

    def test_commit_succeeds_when_hash_matches(self, tmp_path):
        """D-14: No error when write verification succeeds."""
        ir = _make_pcb_ir(tmp_path, "(kicad_pcb (version 20240101))")
        new_content = "(kicad_pcb (version 20240101) (general (thickness 1.6)))"

        # Patch atomic_write to actually write to the file, so read-back succeeds
        with patch("volta.io.atomic_write.atomic_write", side_effect=lambda fp, content: fp.write_text(content, encoding="utf-8")):
            # Should NOT raise -- file written correctly
            ir.commit_raw_content(new_content)

        # Verify IR state updated
        assert ir._raw_written is True
        assert ir._parse_result.raw_content == new_content
        # Verify file on disk matches
        assert ir._parse_result.file_path.read_text(encoding="utf-8") == new_content
