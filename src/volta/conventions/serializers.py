"""Dual JSON + markdown serializers for Convention violations (Plan 01 Task 3).

D-04 (CONTEXT): JSON for Phase 110 GRPO + programmatic analysis; markdown for
                CLI display + human review. Both share the Violation model.
T-48-01 cap: Markdown output truncates at 500 violations (DoS prevention,
             mirrors Phase 48 rule_report.py).
atomic_write: All file reports use atomic_write (tempfile + fsync + os.replace).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Iterable

from volta.conventions.base import Violation
from volta.io.atomic_write import atomic_write

# T-48-01 cap — mirrors Phase 48 rule_report.py markdown truncation.
_MAX_MARKDOWN_VIOLATIONS = 500


def violations_to_json(
    violations: Iterable[Violation],
    schematic_path: str | None = None,
) -> dict:
    """D-04 JSON output. Consumed by Phase 110 GRPO and programmatic analysis.

    Returns a dict with shape:
        {
            "schematic_path": str,
            "violations": list[dict],
            "count": int,
            "summary": {"error": int, "warning": int, "info": int},
        }

    JSON is for machines — no truncation applied.
    """
    vlist = list(violations)
    summary = {"error": 0, "warning": 0, "info": 0}
    for v in vlist:
        summary[v.severity] += 1
    return {
        "schematic_path": schematic_path or "",
        "violations": [v.to_json() for v in vlist],
        "count": len(vlist),
        "summary": summary,
    }


def violations_to_markdown(
    violations: Iterable[Violation],
    schematic_path: str | None = None,
) -> str:
    """D-04 markdown output. Consumed by CLI display and human review.

    Groups violations by severity (Errors → Warnings → Info). Each violation
    is rendered as a markdown bullet via Violation.to_markdown(). Caps at
    _MAX_MARKDOWN_VIOLATIONS bullets with a "(showing N of M)" notice when
    truncated (T-48-01).
    """
    vlist = list(violations)
    lines: list[str] = ["# Convention Violations", ""]

    if schematic_path:
        lines.append(f"Schematic: `{schematic_path}`")
        lines.append("")

    if not vlist:
        lines.append("*No violations found.*")
        lines.append("")
        return "\n".join(lines)

    by_severity: dict[str, list[Violation]] = {"error": [], "warning": [], "info": []}
    for v in vlist:
        by_severity[v.severity].append(v)

    section_titles = {
        "error": "## Errors",
        "warning": "## Warnings",
        "info": "## Info",
    }

    total_rendered = 0
    truncated = False
    for sev in ("error", "warning", "info"):
        bucket = by_severity[sev]
        if not bucket:
            continue
        lines.append(section_titles[sev])
        lines.append("")
        for v in bucket:
            if total_rendered >= _MAX_MARKDOWN_VIOLATIONS:
                truncated = True
                continue
            lines.append(v.to_markdown())
            total_rendered += 1
        lines.append("")

    if truncated:
        lines.append(
            f"(showing {_MAX_MARKDOWN_VIOLATIONS} of {len(vlist)} violations — "
            "see JSON output for the full list)"
        )
        lines.append("")

    return "\n".join(lines)


def write_json_report(
    violations: Iterable[Violation],
    path: Path,
    schematic_path: str | None = None,
) -> None:
    """Write JSON report to disk via atomic_write (Phase 48 atomic_write pattern)."""
    payload = violations_to_json(violations, schematic_path=schematic_path)
    atomic_write(Path(path), json.dumps(payload, indent=2))


def write_markdown_report(
    violations: Iterable[Violation],
    path: Path,
    schematic_path: str | None = None,
) -> None:
    """Write markdown report to disk via atomic_write."""
    atomic_write(Path(path), violations_to_markdown(violations, schematic_path=schematic_path))
