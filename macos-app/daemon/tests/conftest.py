"""
conftest.py — pytest config for daemon tests.

Phase 162 — Python Daemon Bundling.

Adds the daemon directory to sys.path so test modules can import
`protocol`, `handlers`, `audit_log` directly. Without this, pytest
requires installation as a package, which conflicts with the
PyInstaller-frozen layout.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_DAEMON_ROOT = _HERE.parent
if str(_DAEMON_ROOT) not in sys.path:
    sys.path.insert(0, str(_DAEMON_ROOT))

# Also add the repo's src/ so `kicad_agent` is importable for handler tests.
_REPO_SRC = _DAEMON_ROOT.parents[1] / "src"
if _REPO_SRC.exists() and str(_REPO_SRC) not in sys.path:
    sys.path.insert(0, str(_REPO_SRC))
