"""Plan 01 Task 3: Dual JSON + markdown serializers (D-04).

D-04: JSON for machine (Phase 110 GRPO), markdown for human review.
T-48-01 cap: markdown truncates at 500 violations.
atomic_write: file reports use atomic_write (never raw open/write).
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from kicad_agent.conventions.base import Violation
from kicad_agent.conventions.serializers import (
    violations_to_json,
    violations_to_markdown,
    write_json_report,
    write_markdown_report,
)


def _v(severity: str = "warning", rule_id: str = "TEST_RULE_01", ref: str = "R1") -> Violation:
    return Violation(
        rule_id=rule_id,
        severity=severity,  # type: ignore[arg-type]
        message=f"{ref} violates {rule_id}",
        component_refs=(ref,),
        suggestion_relative="adjust position",
    )


def test_empty_violations_to_json_structure():
    j = violations_to_json([])
    assert j == {
        "schematic_path": "",
        "violations": [],
        "count": 0,
        "summary": {"error": 0, "warning": 0, "info": 0},
    }


def test_empty_violations_with_schematic_path():
    j = violations_to_json([], schematic_path="board.kicad_sch")
    assert j["schematic_path"] == "board.kicad_sch"


def test_json_summary_counts_by_severity():
    violations = [
        _v("error", "ERR_01", "R1"),
        _v("error", "ERR_02", "R2"),
        _v("warning", "WARN_01", "R3"),
        _v("info", "INFO_01", "R4"),
    ]
    j = violations_to_json(violations)
    assert j["count"] == 4
    assert j["summary"] == {"error": 2, "warning": 1, "info": 1}
    assert len(j["violations"]) == 4


def test_empty_violations_to_markdown_no_violations_message():
    md = violations_to_markdown([])
    assert md.startswith("# Convention Violations")
    assert "*No violations found.*" in md
    assert md.endswith("\n")


def test_markdown_groups_by_severity_with_headers():
    violations = [
        _v("info", "INFO_01", "R1"),
        _v("error", "ERR_01", "R2"),
        _v("warning", "WARN_01", "R3"),
        _v("error", "ERR_02", "R4"),
    ]
    md = violations_to_markdown(violations)
    # All severity sections present
    assert "## Errors" in md
    assert "## Warnings" in md
    assert "## Info" in md
    # Errors section appears before warnings (most actionable first)
    assert md.index("## Errors") < md.index("## Warnings")
    assert md.index("## Warnings") < md.index("## Info")
    # Each violation is a markdown bullet
    assert "- [ERROR] ERR_01" in md
    assert "- [ERROR] ERR_02" in md
    assert "- [WARNING] WARN_01" in md
    assert "- [INFO] INFO_01" in md


def test_json_output_round_trips_through_json_loads():
    violations = [_v("error", "ERR_01", "R1"), _v("warning", "WARN_01", "R2")]
    j = violations_to_json(violations, schematic_path="board.kicad_sch")
    # Must be json.dumps-serializable (no Pydantic objects leak through)
    s = json.dumps(j)
    restored = json.loads(s)
    assert restored["count"] == 2
    assert restored["schematic_path"] == "board.kicad_sch"
    assert restored["violations"][0]["rule_id"] == "ERR_01"


def test_markdown_ends_with_newline_no_trailing_whitespace_per_line():
    violations = [_v("warning", "WARN_01", "R1")]
    md = violations_to_markdown(violations)
    assert md.endswith("\n")
    for line in md.splitlines():
        # Allow trailing newline at end of file, but no trailing spaces on content lines
        assert line == line.rstrip(), f"Trailing whitespace on line: {line!r}"


def test_markdown_truncates_large_lists_at_500_with_notice():
    """T-48-01 cap: markdown truncates at 500 violations with showing N of M notice."""
    violations = [_v("warning", "WARN_01", f"R{i}") for i in range(1000)]
    md = violations_to_markdown(violations)
    assert "showing 500 of 1000" in md
    # Count actual bullets (lines starting with "- [")
    bullet_count = sum(1 for line in md.splitlines() if line.startswith("- ["))
    assert bullet_count <= 500, f"markdown cap violated: {bullet_count} bullets"


def test_json_does_not_truncate_large_lists():
    """JSON is for machines — no truncation."""
    violations = [_v("warning", "WARN_01", f"R{i}") for i in range(1000)]
    j = violations_to_json(violations)
    assert j["count"] == 1000
    assert len(j["violations"]) == 1000


def test_write_json_report_uses_atomic_write(tmp_path):
    """File reports must use atomic_write (never raw open/write)."""
    out = tmp_path / "report.json"
    write_json_report([_v("warning", "WARN_01", "R1")], out, schematic_path="board.kicad_sch")
    assert out.is_file()
    data = json.loads(out.read_text())
    assert data["count"] == 1
    assert data["schematic_path"] == "board.kicad_sch"


def test_write_markdown_report_uses_atomic_write(tmp_path):
    out = tmp_path / "report.md"
    write_markdown_report([_v("warning", "WARN_01", "R1")], out, schematic_path="board.kicad_sch")
    assert out.is_file()
    text = out.read_text()
    assert "# Convention Violations" in text
    assert "WARN_01" in text


def test_serializers_source_uses_atomic_write_for_file_reports():
    """Grep-enforced: serializers.py imports atomic_write for file reports."""
    src = Path(__file__).resolve().parent.parent / "src" / "kicad_agent" / "conventions" / "serializers.py"
    text = src.read_text()
    assert "from kicad_agent.io.atomic_write import atomic_write" in text, (
        "atomic_write not imported in serializers.py"
    )
