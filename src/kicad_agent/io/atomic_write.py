"""Atomic file write with fsync and cleanup.

Shared function used by executor, PcbIR, handlers, and serializer
to avoid duplicating the write pattern and breaking circular dependencies
(IR -> executor -> IR).
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def atomic_write(file_path: Path, content: str) -> None:
    """Write content to file atomically via temp file + fsync + rename.

    Uses tempfile.mkstemp for an unpredictable name (prevents collisions),
    os.fsync for durability (prevents data loss on crash), and try/except
    cleanup (prevents orphaned temp files on failure).

    Args:
        file_path: Target file path.
        content: Content to write.
    """
    fd, tmp_path = tempfile.mkstemp(
        dir=file_path.parent,
        prefix=".kicad_",
        suffix=".tmp",
    )
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp_path, str(file_path))
    except BaseException:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise
