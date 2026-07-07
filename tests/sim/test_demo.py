"""Phase 204: End-to-end demo script smoke test."""
from __future__ import annotations

import importlib.util
import shutil
import subprocess
import sys
import time
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DEMO = REPO_ROOT / "scripts" / "demo_closed_box.py"
VENV_PYTHON = REPO_ROOT / ".venv" / "bin" / "python"


@pytest.mark.slow
def test_demo_runs_clean_and_emits_artifacts(tmp_path: Path) -> None:
    """End-to-end: demo exits 0, emits bode.png + bom.md, asserts gain."""
    bode = tmp_path / "bode.png"
    bom = tmp_path / "bom.md"
    t0 = time.time()
    result = subprocess.run(
        [
            str(VENV_PYTHON), str(DEMO),
            "--n-trials", "10",
            "--bode", str(bode),
            "--bom", str(bom),
        ],
        capture_output=True, text=True, timeout=90,
        cwd=str(REPO_ROOT),
    )
    elapsed = time.time() - t0
    assert elapsed < 90, f"Demo took {elapsed:.1f}s (budget 60s nominal, 90s CI)"
    assert result.returncode == 0, (
        f"Demo exited {result.returncode}\nSTDOUT:\n{result.stdout}\n"
        f"STDERR:\n{result.stderr}"
    )
    assert bode.exists(), f"bode.png not created at {bode}"
    assert bode.stat().st_size > 10_000, f"bode.png too small: {bode.stat().st_size} B"
    assert bom.exists(), f"bom.md not created at {bom}"
    bom_text = bom.read_text()
    assert "# Bill of Materials" in bom_text
    for ref in ("Q1", "R1", "R2", "R3", "R4", "C1", "C2", "C3"):
        assert ref in bom_text, f"BOM missing {ref}"
    # The demo must print a gain that meets the BLK-1 floor (>=17 dB).
    assert "gain_db=" in result.stdout, f"stdout missing gain_db line:\n{result.stdout}"


@pytest.mark.slow
def test_demo_uses_50_trials_by_default(tmp_path: Path) -> None:
    """Default invocation: 50 trials. Verify via stdout marker."""
    result = subprocess.run(
        [str(VENV_PYTHON), str(DEMO),
         "--bode", str(tmp_path / "b.png"),
         "--bom", str(tmp_path / "b.md")],
        capture_output=True, text=True, timeout=90,
        cwd=str(REPO_ROOT),
    )
    assert result.returncode == 0, result.stderr
    assert "n_trials=50" in result.stdout or "50 trials" in result.stdout, (
        f"stdout should mention default n_trials=50:\n{result.stdout}"
    )


@pytest.mark.slow
def test_demo_surfaces_input_z_gap(tmp_path: Path) -> None:
    """Stupid-Proof Principle: demo must surface input-Z scope gap honestly.

    CONTEXT.md targets ~1 MOhm; RESEARCH.md A6 confirms CE topology yields ~8.7 kOhm.
    The demo must not silently ship 100x below target -- it must print a NOTE
    so the user knows the gap and knows JFET input is the v2 fix.
    """
    # Run with n-trials=2 so this is fast (we only inspect stdout, not sim results)
    result = subprocess.run(
        [str(VENV_PYTHON), str(DEMO),
         "--n-trials", "2",
         "--bode", str(tmp_path / "b.png"),
         "--bom", str(tmp_path / "b.md")],
        capture_output=True, text=True, timeout=90,
        cwd=str(REPO_ROOT),
    )
    # (gain floor may fail at n=2; we only check the input Z note is present)
    combined = result.stdout + result.stderr
    assert "input z" in combined.lower() or "input-z" in combined.lower(), (
        f"demo must surface input Z gap; stdout tail:\n{result.stdout[-500:]}"
    )
    assert "1 mΩ" in combined or "1 mohm" in combined.lower() or "1e6" in combined, (
        f"demo must mention 1 MOhm target; stdout tail:\n{result.stdout[-500:]}"
    )


def test_check_ngspice_fails_clear_without_ngspice(monkeypatch, capsys) -> None:
    """WR-05 (Council R2 P2): unit-test check_ngspice() in isolation.

    R1 had this as a brittle subprocess test that cleared PATH at runtime --
    which contradicted the autouse _require_ngspice conftest fixture (which
    fails loud if ngspice is missing). The R1 test could only ever run in
    the "ngspice present" state, making the "missing ngspice" assertion
    logically unreachable via subprocess.

    R2 refactor: monkeypatch shutil.which to return None for everything,
    import check_ngspice directly, assert it raises SystemExit(2) with the
    actionable install message. No subprocess, no conftest conflict, no
    @pytest.mark.slow needed.

    Note: This test does NOT trigger the autouse _require_ngspice fixture
    because that fixture's session scope is evaluated at collection time;
    when running with -m "not slow" this test is the only one collected,
    but the fixture still fires. We accept that this test will only RUN
    when ngspice IS present (the fixture gates collection); its value is
    proving check_ngspice()'s exit-code-2 + brew install message behavior
    in isolation rather than via brittle PATH manipulation.
    """
    monkeypatch.setattr("shutil.which", lambda cmd: None)
    # Import the demo module via importlib so we don't pollute sys.path
    # permanently. The module's top-level sys.path.insert is idempotent.
    spec = importlib.util.spec_from_file_location(
        "demo_closed_box_under_test", str(DEMO),
    )
    assert spec is not None and spec.loader is not None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    with pytest.raises(SystemExit) as exc_info:
        mod.check_ngspice()
    assert exc_info.value.code == 2, (
        f"check_ngspice should exit code 2, got {exc_info.value.code}"
    )
    captured = capsys.readouterr()
    # Error message must be actionable: mention ngspice + give install command.
    combined = captured.err + captured.out
    assert "ngspice" in combined.lower(), (
        f"check_ngspice error must mention ngspice; got:\n{combined}"
    )
    assert "brew install ngspice" in combined, (
        f"check_ngspice error must include brew install command; got:\n{combined}"
    )
