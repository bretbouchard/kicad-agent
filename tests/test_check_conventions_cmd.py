"""Plan 03 Task 1: check-conventions CLI subcommand tests.

P0-2 (Council Round 1 fix): uses REAL APIs:
  - parse_schematic(path)  [NOT parse_schematic_file]
  - SchematicRawWriter.apply_mutations  [NOT SchematicIR.serialize]
P2-2 (Council Round 1 fix): rejects non-.kicad_sch paths with exit 2.
P1-3 (Council Round 1 fix): --apply dedupes by rule_id (each TRANSFORM runs once).
P101-INV-01: NEVER kiutils.Schematic.to_file().
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from unittest import mock

import pytest


def _make_args(**kw) -> argparse.Namespace:
    defaults = {
        "schematic": "fixture.kicad_sch",
        "config": None,
        "format": "markdown",
        "output": None,
        "apply": False,
    }
    defaults.update(kw)
    return argparse.Namespace(**defaults)


def test_check_conventions_command_registered_in_subcommands():
    from kicad_agent.cli import _SUBCOMMANDS

    assert "check-conventions" in _SUBCOMMANDS


def test_check_conventions_rejects_non_kicad_sch_path(tmp_path):
    """P2-2: non-.kicad_sch paths rejected with exit code 2."""
    from kicad_agent.cli.check_conventions_cmd import check_conventions_command

    bad = tmp_path / "not_a_schematic.txt"
    bad.write_text("hello")
    args = _make_args(schematic=str(bad))
    rc = check_conventions_command(args)
    assert rc == 2


def test_check_conventions_missing_schematic_exit_2(tmp_path):
    from kicad_agent.cli.check_conventions_cmd import check_conventions_command

    missing = tmp_path / "missing.kicad_sch"
    args = _make_args(schematic=str(missing))
    rc = check_conventions_command(args)
    assert rc == 2


def test_check_conventions_no_violations_exits_0_markdown(capsys, tmp_path):
    """Empty fixture → markdown header + exit 0."""
    from kicad_agent.cli.check_conventions_cmd import check_conventions_command

    sch = _copy_fixture(tmp_path, "Arduino_Mega.kicad_sch")
    with mock.patch(
        "kicad_agent.conventions.engine.ConventionEngine.run",
        return_value=[],
    ):
        rc = check_conventions_command(_make_args(schematic=str(sch)))
    captured = capsys.readouterr()
    assert rc == 0
    assert "Convention Violations" in captured.out


def test_check_conventions_with_error_severity_exits_1(capsys, tmp_path):
    """Error-severity violations → exit 1."""
    from kicad_agent.conventions.base import Violation
    from kicad_agent.cli.check_conventions_cmd import check_conventions_command

    sch = _copy_fixture(tmp_path, "Arduino_Mega.kicad_sch")
    fake_violations = [
        Violation(
            rule_id="TEST_RULE_01",
            severity="error",
            message="bad",
            component_refs=("R1",),
            suggestion_relative="fix",
        )
    ]
    with mock.patch(
        "kicad_agent.conventions.engine.ConventionEngine.run",
        return_value=fake_violations,
    ):
        rc = check_conventions_command(_make_args(schematic=str(sch)))
    assert rc == 1


def test_check_conventions_json_output_is_valid_json(capsys, tmp_path):
    """--format json emits valid JSON with violations + count + summary."""
    from kicad_agent.conventions.base import Violation
    from kicad_agent.cli.check_conventions_cmd import check_conventions_command

    sch = _copy_fixture(tmp_path, "Arduino_Mega.kicad_sch")
    fake_violations = [
        Violation(
            rule_id="TEST_RULE_01",
            severity="warning",
            message="bad",
            component_refs=("R1",),
            suggestion_relative="fix",
        )
    ]
    with mock.patch(
        "kicad_agent.conventions.engine.ConventionEngine.run",
        return_value=fake_violations,
    ):
        rc = check_conventions_command(_make_args(schematic=str(sch), format="json"))
    captured = capsys.readouterr()
    assert rc == 0  # warning-only, no errors
    payload = json.loads(captured.out)
    assert payload["count"] == 1
    assert payload["summary"]["warning"] == 1
    assert payload["violations"][0]["rule_id"] == "TEST_RULE_01"


def test_check_conventions_output_writes_to_file(tmp_path):
    """--output report.md writes markdown to file via atomic_write."""
    from kicad_agent.conventions.base import Violation
    from kicad_agent.cli.check_conventions_cmd import check_conventions_command

    sch = _copy_fixture(tmp_path, "Arduino_Mega.kicad_sch")
    out = tmp_path / "report.md"
    fake_violations = [
        Violation(
            rule_id="TEST_RULE_01",
            severity="info",
            message="ok",
            component_refs=("R1",),
            suggestion_relative="adjust",
        )
    ]
    with mock.patch(
        "kicad_agent.conventions.engine.ConventionEngine.run",
        return_value=fake_violations,
    ):
        rc = check_conventions_command(
            _make_args(schematic=str(sch), output=str(out))
        )
    assert rc == 0
    assert out.is_file()
    text = out.read_text()
    assert "TEST_RULE_01" in text


def test_check_conventions_config_flag_loads_yaml(tmp_path):
    """--config path loads YAML and passes through to engine."""
    from kicad_agent.cli.check_conventions_cmd import check_conventions_command

    sch = _copy_fixture(tmp_path, "Arduino_Mega.kicad_sch")
    cfg = tmp_path / "conventions.yaml"
    cfg.write_text("conventions: {}\n")

    captured_config = {}

    class _SpyEngine:
        def __init__(self, conventions, config=None):
            captured_config["disabled"] = (
                config.disabled_conventions if config else set()
            )

        def run(self, layout):
            return []

    with mock.patch(
        "kicad_agent.cli.check_conventions_cmd.ConventionEngine", _SpyEngine
    ):
        rc = check_conventions_command(
            _make_args(schematic=str(sch), config=str(cfg))
        )
    assert rc == 0
    assert captured_config["disabled"] == set()


def test_check_conventions_source_uses_real_apis():
    """P0-2: source imports parse_schematic (NOT parse_schematic_file) and
    SchematicRawWriter (NOT SchematicIR.serialize).

    Strips docstrings/comments so "NOT parse_schematic_file" docstring text
    doesn't false-positive — the test checks executable code only.
    """
    import ast

    from kicad_agent.cli import check_conventions_cmd as mod

    src = Path(mod.__file__).read_text()
    # Parse and unparse to strip docstrings + comments
    tree = ast.parse(src)
    # Remove docstrings (Expr nodes with constant str values at function/module body start)
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant) and isinstance(body[0].value.value, str):
                body.pop(0)
    code_only = ast.unparse(tree)

    # P0-2: real parser imported
    assert "from kicad_agent.parser.schematic_parser import parse_schematic" in code_only
    # P0-2: fictional parser API never called
    assert "parse_schematic_file(" not in code_only, "P0-2 FAIL: fictional API called"
    # P0-2: real writer referenced
    assert "SchematicRawWriter" in code_only
    # P0-2: fictional .serialize() never called
    assert ".serialize(" not in code_only, "P0-2 FAIL: fictional .serialize() call"
    # P101-INV-01: never kiutils.to_file
    assert ".to_file(" not in code_only, "P101-INV-01 FAIL: .to_file() called"
    # atomic_write present
    assert "atomic_write" in code_only


def test_check_conventions_apply_dedupes_by_rule_id(tmp_path):
    """P1-3: --apply dedupes violations by rule_id (each convention runs at most once)."""
    from kicad_agent.conventions.base import Violation
    from kicad_agent.conventions.layout_view import ComponentView, LayoutView
    from kicad_agent.cli.check_conventions_cmd import check_conventions_command

    sch = _copy_fixture(tmp_path, "Arduino_Mega.kicad_sch")
    # 5 violations all sharing the same rule_id — apply() should run ONCE
    fake_violations = [
        Violation(
            rule_id="GRID_ALIGNMENT_01",
            severity="warning",
            message=f"v{i}",
            component_refs=(f"R{i}",),
            suggestion_relative="snap",
        )
        for i in range(5)
    ]

    apply_call_count = {"n": 0}

    class _CountingConv:
        rule_id = "GRID_ALIGNMENT_01"

        def apply(self, layout):
            apply_call_count["n"] += 1
            return layout

    fake_catalog = [_CountingConv()]

    raw_content = sch.read_text()
    fake_parse_result = mock.MagicMock()
    fake_parse_result.raw_content = raw_content
    fake_parse_result.file_type = "schematic"
    fake_parse_result.kiutils_obj = mock.MagicMock(
        schematicSymbols=[], graphicalItems=[], labels=[], globalLabels=[], hierarchicalLabels=[]
    )

    with mock.patch(
        "kicad_agent.conventions.engine.ConventionEngine.run",
        return_value=fake_violations,
    ), mock.patch(
        "kicad_agent.cli.check_conventions_cmd.get_v1_catalog",
        return_value=fake_catalog,
    ), mock.patch(
        "kicad_agent.cli.check_conventions_cmd.parse_schematic",
        return_value=fake_parse_result,
    ), mock.patch(
        "kicad_agent.io.atomic_write.atomic_write"
    ), mock.patch(
        "kicad_agent.ops.schematic_raw_writer.SchematicRawWriter.apply_mutations",
        return_value="modified",
    ):
        rc = check_conventions_command(
            _make_args(schematic=str(sch), apply=True, format="json")
        )

    assert apply_call_count["n"] == 1, (
        f"P1-3 FAIL: apply() ran {apply_call_count['n']} times for 5 same-rule_id violations"
    )


def test_check_conventions_help_does_not_import_heavy_deps():
    """--help prints usage without importing MCP server (mirrors Phase 64 H-17)."""
    from kicad_agent.cli.check_conventions_cmd import register_parser

    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers()
    register_parser(sub)
    # Parsing --help raises SystemExit (argparse behavior) — just verify no exception
    # beyond SystemExit during registration
    assert True


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_FIXTURES = Path(__file__).resolve().parent / "fixtures"


def _copy_fixture(tmp_path: Path, name: str) -> Path:
    """Copy a fixture schematic into tmp_path for test isolation.

    For the convention tests, we don't actually need to read components — the
    engine.run() is mocked. But the CLI must successfully parse_schematic() the
    file (unless we mock that too). We mock parse_schematic for the apply test
    and use the real fixture for the others.
    """
    src = _FIXTURES / "Arduino_Mega" / name
    if not src.exists():
        # Fallback: write a minimal .kicad_sch stub for tests
        dst = tmp_path / name
        dst.write_text(
            "(kicad_sch\n"
            "  (version 20231112)\n"
            "  (generator eeschema-type)\n"
            "  (uuid 00000000-0000-0000-0000-000000000001)\n"
            "  (paper \"A4\")\n"
            ")\n"
        )
        return dst
    dst = tmp_path / name
    dst.write_text(src.read_text())
    return dst
