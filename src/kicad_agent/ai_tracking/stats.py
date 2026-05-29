"""CLI formatting for AI tracking gap reports."""

from __future__ import annotations

from kicad_agent.ai_tracking.gap_analyzer import GapReport, StageStats

# Human-readable descriptions for known fallback reasons.
_REASON_DESCRIPTIONS: dict[str, str] = {
    "format_error": "Local model did not output valid JSON",
    "schema_validation_failed": "JSON did not match expected schema",
    "low_confidence": "Composite score below threshold",
    "timeout": "Local inference timed out",
    "local_unavailable": "Local model was not reachable",
}


def _percent(value: float) -> str:
    """Format a 0.0-1.0 ratio as a whole-number percent string."""
    return f"{value * 100:.0f}%"


def _fmt_int(value: int, width: int = 3) -> str:
    """Right-align an integer in *width* characters."""
    return str(value).rjust(width)


def format_stats_report(report: GapReport) -> str:
    """Format a :class:`GapReport` as a human-readable CLI output.

    Output format::

        === kicad-agent AI Performance Report ===
        Total events: 700

        --- Local Success Rate by Stage ---
          intent_parse:     72% (180/250 attempts,  70 fallbacks)
          error_fix:        45% ( 90/200 attempts, 110 fallbacks)
          ...

        --- Top Fallback Reasons ---
          1. format_error (85): Local model did not output valid JSON
          2. ...

        --- Training Gaps ---
          1. [error_fix] Multi-step error fixes (78 occurrences)
             Suggestion: Generate training data with complex ERC violation chains

        --- Cost Savings ---
          Cloud calls avoided: 448 of 700 total (64%)
          Average latency improvement: +3.2s (local is free but slower)
    """
    lines: list[str] = []

    # Header
    lines.append("=== kicad-agent AI Performance Report ===")
    lines.append(f"Total events: {report.total_events}")
    lines.append("")

    # Per-stage breakdown
    lines.append("--- Local Success Rate by Stage ---")
    for stage, stats in sorted(report.stage_breakdown.items()):
        pct = _percent(stats.local_success_rate)
        attempts = _fmt_int(stats.total_attempts)
        fb = _fmt_int(stats.fallback_count)
        lines.append(
            f"  {stage + ':':<18s}{pct:>4s} "
            f"({stats.local_successes}/{stats.total_attempts} attempts, {fb} fallbacks)"
        )
    lines.append("")

    # Top fallback reasons
    lines.append("--- Top Fallback Reasons ---")
    if report.top_fallback_reasons:
        for idx, (reason, count) in enumerate(report.top_fallback_reasons, start=1):
            desc = _REASON_DESCRIPTIONS.get(reason, reason)
            lines.append(f"  {idx}. {reason} ({count}): {desc}")
    else:
        lines.append("  (none)")
    lines.append("")

    # Training gaps
    lines.append("--- Training Gaps ---")
    if report.training_gaps:
        for idx, gap in enumerate(report.training_gaps, start=1):
            lines.append(
                f"  {idx}. [{gap.stage}] {gap.description} ({gap.frequency} occurrences)"
            )
            lines.append(f"     Suggestion: {gap.suggested_training_data}")
    else:
        lines.append("  (no significant gaps detected)")
    lines.append("")

    # Cost savings
    lines.append("--- Cost Savings ---")
    cs = report.cost_savings
    avoided_pct = _percent(cs.local_success_rate) if report.total_events > 0 else "0%"
    lines.append(
        f"  Cloud calls avoided: {cs.total_cloud_calls_avoided} of "
        f"{report.total_events} total ({avoided_pct})"
    )
    if cs.avg_latency_improvement_s > 0:
        improvement = f"+{cs.avg_latency_improvement_s:.1f}s"
    else:
        improvement = f"{cs.avg_latency_improvement_s:.1f}s"
    lines.append(f"  Average latency improvement: {improvement} (local is free but slower)")

    return "\n".join(lines)
