"""Phase 204: shared fixtures for tests/sim/.

BLK-1 strict: ngspice is a hard requirement. We DO NOT pytest.skip()
when it's missing — we pytest.fail() with an actionable message.
"""
from __future__ import annotations

import shutil

import pytest


@pytest.fixture(scope="session", autouse=True)
def _require_ngspice() -> None:
    """Fail every test in tests/sim/ loudly if ngspice CLI is not on PATH.

    Install with:
      macOS:  brew install ngspice
      Linux:  apt install ngspice  (or dnf install ngspice)
    """
    if shutil.which("ngspice") is None:
        pytest.fail(
            "ngspice CLI not found on PATH. "
            "Install with: brew install ngspice (macOS) or apt install ngspice (Linux). "
            "Phase 204 tests/sim/ require ngspice to produce real simulation results "
            "(BLK-1 strict — no skip-guards).",
            pytrace=False,
        )
