"""Design rule report generators -- JSON and Markdown output.

DOMAIN-04: Multi-format reporting for design rule results.

Usage:
    from volta.analysis.rule_report import generate_json_report, generate_markdown_report

    json_str = generate_json_report(report)
    md_str = generate_markdown_report(report)
"""
from __future__ import annotations

from volta.analysis.design_rules import (
    DesignRuleReport,
    RuleSeverity,
)


def generate_json_report(report: DesignRuleReport) -> str:
    """Generate JSON report from DesignRuleReport.

    Args:
        report: DesignRuleReport to serialize.

    Returns:
        JSON string with full report data.
    """
    return report.model_dump_json(indent=2)


_SEVERITY_BADGES = {
    RuleSeverity.CRITICAL: "[!!]",
    RuleSeverity.WARNING: "[!]",
    RuleSeverity.SUGGESTION: "[>]",
    RuleSeverity.INFO: "[i]",
}


def generate_markdown_report(report: DesignRuleReport) -> str:
    """Generate human-readable Markdown report.

    Sections:
    1. Header with schematic path and timing
    2. Summary table (severity counts, rules run)
    3. Violations grouped by severity (CRITICAL first)
    4. Per-violation details (location, suggestion, affected components)

    Args:
        report: DesignRuleReport to format.

    Returns:
        Markdown string.
    """
    lines: list[str] = []

    # Header
    lines.append("# Design Rule Report")
    lines.append("")
    lines.append(f"**Schematic:** `{report.schematic_path}`")
    lines.append(
        f"**Rules run:** {report.rules_run} "
        f"({report.rules_passed} passed, {report.rules_failed} failed)"
    )
    lines.append(f"**Total violations:** {len(report.violations)}")
    lines.append(f"**Elapsed:** {report.elapsed_ms:.1f}ms")
    lines.append("")

    # Summary table
    lines.append("## Summary")
    lines.append("")
    lines.append("| Severity | Count |")
    lines.append("|----------|-------|")
    for sev in RuleSeverity:
        count = report.summary.get(sev.value, 0)
        badge = _SEVERITY_BADGES[sev]
        lines.append(f"| {badge} {sev.value} | {count} |")
    lines.append("")

    # Violations by severity
    if report.violations:
        lines.append("## Violations")
        lines.append("")
        for i, v in enumerate(report.violations, 1):
            badge = _SEVERITY_BADGES[v.severity]
            lines.append(f"### {i}. {badge} [{v.rule_id}] {v.location}")
            lines.append("")
            lines.append(f"{v.description}")
            lines.append("")
            if v.suggestion:
                lines.append(f"**Suggestion:** {v.suggestion}")
                lines.append("")
            if v.affected_components:
                lines.append(f"**Affected:** {', '.join(v.affected_components)}")
                lines.append("")
            lines.append("---")
            lines.append("")
    else:
        lines.append("## No violations found")
        lines.append("")
        lines.append("All design rules passed. Circuit looks good!")
        lines.append("")

    return "\n".join(lines)
