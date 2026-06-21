"""CLI test suite -- subprocess invocation of kicad-agent command."""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

VALID_ADD = json.dumps({
    "op_type": "add_component",
    "target_file": "tests/fixtures/Arduino_Mega/Arduino_Mega.kicad_sch",
    "library_id": "Device:R_Small_US",
    "position": {"x": 1.0, "y": 1.0},
})

INVALID_JSON_STR = "{bad json}"

PATH_TRAVERSAL = json.dumps({
    "op_type": "add_component",
    "target_file": "../../../etc/passwd",
    "library_id": "Device:R",
    "position": {"x": 1, "y": 1},
})

VALID_MOVE = json.dumps({
    "op_type": "move_component",
    "target_file": "tests/fixtures/Arduino_Mega/Arduino_Mega.kicad_sch",
    "reference": "J1",
    "position": {"x": 100.0, "y": 200.0},
})


def _run(*args: str, cwd: str | None = None) -> subprocess.CompletedProcess[str]:
    """Invoke the CLI via ``python -m kicad_agent.cli``."""
    cmd = [sys.executable, "-m", "kicad_agent.cli", *args]
    # Inherit PYTHONPATH so the uninstalled source tree (src/) is importable.
    env = None
    src_dir = str(Path(__file__).resolve().parent.parent / "src")
    import os
    env = dict(os.environ)
    env["PYTHONPATH"] = src_dir + os.pathsep + env.get("PYTHONPATH", "")
    return subprocess.run(cmd, capture_output=True, text=True, cwd=cwd, env=env)


# ---------------------------------------------------------------------------
# Test 1: --schema exits 0 and prints valid JSON Schema
# ---------------------------------------------------------------------------
def test_schema_flag_returns_valid_json_schema() -> None:
    result = _run("--schema")
    assert result.returncode == 0
    schema = json.loads(result.stdout)
    assert "properties" in schema


# ---------------------------------------------------------------------------
# Test 2: Valid inline JSON exits 0
# ---------------------------------------------------------------------------
def test_valid_inline_json_exits_zero() -> None:
    # Use a minimal schematic in a temp dir to avoid overlap with real fixture
    from kiutils.schematic import Schematic
    tmpdir = tempfile.mkdtemp()
    sch = Schematic.create_new()
    sch_path = Path(tmpdir) / "test.kicad_sch"
    sch.to_file(str(sch_path))
    op = json.dumps({
        "op_type": "add_component",
        "target_file": sch_path.name,
        "library_id": "Device:R_Small_US",
        "position": {"x": 50.0, "y": 50.0},
    })
    try:
        result = _run(op, cwd=tmpdir)
        assert result.returncode == 0
        assert "[OK]" in result.stdout or "add_component" in result.stdout
    finally:
        import shutil
        shutil.rmtree(tmpdir, ignore_errors=True)


# ---------------------------------------------------------------------------
# Test 3: Invalid JSON exits 1
# ---------------------------------------------------------------------------
def test_invalid_json_exits_nonzero() -> None:
    result = _run(INVALID_JSON_STR)
    assert result.returncode != 0
    assert result.stderr != "" or "[ERROR]" in result.stdout


# ---------------------------------------------------------------------------
# Test 4: --dry-run with valid JSON exits 0
# ---------------------------------------------------------------------------
def test_dry_run_valid_exits_zero() -> None:
    result = _run("--dry-run", VALID_ADD)
    assert result.returncode == 0


# ---------------------------------------------------------------------------
# Test 5: --dry-run with invalid operation exits 1
# ---------------------------------------------------------------------------
def test_dry_run_invalid_exits_nonzero() -> None:
    bad_op = json.dumps({"op_type": "nonexistent_op", "target_file": "x.kicad_sch"})
    result = _run("--dry-run", bad_op)
    assert result.returncode != 0


# ---------------------------------------------------------------------------
# Test 6: JSON file input exits 0
# ---------------------------------------------------------------------------
def test_json_file_input_exits_zero() -> None:
    with tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False
    ) as tmp:
        tmp.write(VALID_MOVE)
        tmp_path = tmp.name
    try:
        result = _run(tmp_path)
        assert result.returncode == 0
    finally:
        Path(tmp_path).unlink(missing_ok=True)


# ---------------------------------------------------------------------------
# Test 7: Nonexistent file exits 1
# ---------------------------------------------------------------------------
def test_nonexistent_file_exits_nonzero() -> None:
    result = _run("/no/such/path/op.json")
    assert result.returncode != 0
    assert "not found" in result.stderr.lower() or "error" in result.stderr.lower()


# ---------------------------------------------------------------------------
# Test 8: Path traversal in target_file exits 1
# ---------------------------------------------------------------------------
def test_path_traversal_exits_nonzero() -> None:
    result = _run(PATH_TRAVERSAL)
    assert result.returncode != 0
    assert "[ERROR]" in result.stdout or "traversal" in result.stdout.lower() or "traversal" in result.stderr.lower()


# ---------------------------------------------------------------------------
# Analyze subcommand tests (in-process for mocking)
# ---------------------------------------------------------------------------


def _make_mock_result(**overrides) -> MagicMock:
    """Create a mock ScoredChain-like result for analyze tests."""
    defaults = dict(
        chain_text="Observation: Board has 50 components",
        format_score=0.85,
        quality_score=0.72,
        accuracy_score=0.78,
        composite_score=0.783,
        generation_time_s=1.2,
    )
    defaults.update(overrides)
    m = MagicMock()
    for k, v in defaults.items():
        setattr(m, k, v)
    return m


def test_analyze_subcommand_calls_generate_analysis(tmp_path: Path, capsys) -> None:
    """`kicad-agent analyze board.kicad_pcb` calls generate_analysis and prints chain."""
    pcb_file = tmp_path / "board.kicad_pcb"
    pcb_file.write_text("(kicad_pcb (version 20221018))")

    mock_result = _make_mock_result()

    with patch("kicad_agent.inference.wrapper.generate_analysis", return_value=mock_result) as mock_gen:
        from kicad_agent.cli import main
        main(["analyze", str(pcb_file)])

    captured = capsys.readouterr()
    assert "Observation" in captured.out
    mock_gen.assert_called_once()


def test_analyze_n_best_flag(tmp_path: Path, capsys) -> None:
    """`kicad-agent analyze board.kicad_pcb --n-best 8` passes n_best=8."""
    pcb_file = tmp_path / "board.kicad_pcb"
    pcb_file.write_text("(kicad_pcb (version 20221018))")

    mock_result = _make_mock_result()

    with patch("kicad_agent.inference.wrapper.generate_analysis", return_value=mock_result) as mock_gen:
        from kicad_agent.cli import main
        main(["analyze", str(pcb_file), "--n-best", "8"])

    _, call_kwargs = mock_gen.call_args
    assert call_kwargs.get("n_best") == 8


def test_analyze_missing_file_exits_nonzero() -> None:
    """`kicad-agent analyze missing.kicad_pcb` exits with error code 1."""
    result = _run("analyze", "/nonexistent/path.kicad_pcb")
    assert result.returncode != 0
    assert "not found" in result.stderr.lower() or "error" in result.stderr.lower()


def test_analyze_verbose_shows_scores(tmp_path: Path, capsys) -> None:
    """`kicad-agent analyze board.kicad_pcb --verbose` prints per-chain scores."""
    pcb_file = tmp_path / "board.kicad_pcb"
    pcb_file.write_text("(kicad_pcb (version 20221018))")

    mock_result = _make_mock_result(
        chain_text="Detailed analysis with coordinates",
        format_score=0.9,
        quality_score=0.8,
        accuracy_score=0.7,
        composite_score=0.8,
        generation_time_s=1.8,
    )

    with patch("kicad_agent.inference.wrapper.generate_analysis", return_value=mock_result):
        from kicad_agent.cli import main
        main(["analyze", str(pcb_file), "--verbose"])

    captured = capsys.readouterr()
    assert "Score" in captured.out
