"""Gap analyzer -- turns intervention events into actionable training gap reports."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass

from volta.ai_tracking.tracker import InterventionEvent

# Threshold: stages with a fallback rate above this are flagged as training gaps.
_FALLBACK_RATE_THRESHOLD = 0.30
_MAX_EXAMPLE_INPUTS = 5
_EXAMPLE_TRUNCATION = 200


# ---------------------------------------------------------------------------
# Data types
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class StageStats:
    """Aggregate statistics for a single pipeline stage."""

    total_attempts: int
    local_successes: int
    fallback_count: int
    local_success_rate: float  # 0.0-1.0
    avg_local_confidence: float
    avg_cloud_confidence: float
    avg_latency_local_s: float
    avg_latency_cloud_s: float


@dataclass(frozen=True)
class TrainingGap:
    """A stage where the local model struggles, needing more training data."""

    stage: str
    description: str
    frequency: int
    example_inputs: tuple[str, ...]  # Up to 5 sample inputs that failed
    suggested_training_data: str


@dataclass(frozen=True)
class CostSavings:
    """Estimated cost savings from local-first inference."""

    total_cloud_calls_avoided: int
    total_cloud_calls: int
    local_success_rate: float
    avg_latency_improvement_s: float


@dataclass(frozen=True)
class GapReport:
    """Complete analysis of local-model performance across all stages."""

    stage_breakdown: dict[str, StageStats]
    top_fallback_reasons: tuple[tuple[str, int], ...]  # reason -> count, sorted desc
    training_gaps: tuple[TrainingGap, ...]
    cost_savings: CostSavings
    total_events: int


# ---------------------------------------------------------------------------
# Stage-specific gap descriptions and suggestions
# ---------------------------------------------------------------------------

_STAGE_GAP_INFO: dict[str, tuple[str, str]] = {
    "intent_parse": (
        "Intent parsing failures -- model does not produce valid structured intent",
        "Generate training data with diverse natural-language PCB design commands",
    ),
    "error_fix": (
        "Multi-step error fixes -- model fails to chain ERC violation corrections",
        "Generate training data with complex ERC violation chains",
    ),
    "critique": (
        "Design critique failures -- model produces shallow or invalid critiques",
        "Generate training data with detailed design review examples",
    ),
    "component_suggest": (
        "Component suggestion failures -- model picks wrong or unavailable parts",
        "Generate training data with parametric component selection examples",
    ),
}


def _default_gap_info(stage: str) -> tuple[str, str]:
    """Return a generic gap description and suggestion for unknown stages."""
    return (
        f"Local model struggles at stage '{stage}'",
        f"Generate training data targeting the '{stage}' pipeline stage",
    )


# ---------------------------------------------------------------------------
# Analyzer
# ---------------------------------------------------------------------------


class GapAnalyzer:
    """Analyzes intervention events and produces a gap report."""

    def analyze(self, events: list[InterventionEvent]) -> GapReport:
        """Analyze *events* and produce a :class:`GapReport`."""
        total = len(events)

        # --- 1. Per-stage stats ---------------------------------------------------
        stage_groups = _group_by_stage(events)
        stage_breakdown: dict[str, StageStats] = {
            stage: _compute_stage_stats(group) for stage, group in stage_groups.items()
        }

        # --- 2. Top fallback reasons ----------------------------------------------
        fallback_events = [e for e in events if e.fallback_triggered]
        reason_counts = Counter(e.fallback_reason for e in fallback_events if e.fallback_reason)
        top_reasons = tuple(reason_counts.most_common())

        # --- 3. Training gaps -----------------------------------------------------
        training_gaps = _identify_training_gaps(stage_groups)

        # --- 4. Cost savings ------------------------------------------------------
        local_successes = [e for e in events if not e.fallback_triggered]
        total_cloud_calls = len(fallback_events)
        total_cloud_avoided = len(local_successes)

        local_success_rate = (total_cloud_avoided / total) if total > 0 else 0.0

        latency_improvements = [
            e.cloud_latency_s - e.local_latency_s
            for e in local_successes
            if e.cloud_latency_s > 0.0
        ]
        # If we have no cloud latency data, estimate based on local-only latency
        avg_latency_improvement = (
            sum(latency_improvements) / len(latency_improvements)
            if latency_improvements
            else 0.0
        )

        cost_savings = CostSavings(
            total_cloud_calls_avoided=total_cloud_avoided,
            total_cloud_calls=total_cloud_calls,
            local_success_rate=local_success_rate,
            avg_latency_improvement_s=avg_latency_improvement,
        )

        return GapReport(
            stage_breakdown=stage_breakdown,
            top_fallback_reasons=top_reasons,
            training_gaps=training_gaps,
            cost_savings=cost_savings,
            total_events=total,
        )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _group_by_stage(events: list[InterventionEvent]) -> dict[str, list[InterventionEvent]]:
    """Group events by their ``stage`` field."""
    groups: dict[str, list[InterventionEvent]] = {}
    for event in events:
        groups.setdefault(event.stage, []).append(event)
    return groups


def _compute_stage_stats(events: list[InterventionEvent]) -> StageStats:
    """Compute aggregate stats for a list of events in the same stage."""
    total = len(events)
    if total == 0:
        return StageStats(
            total_attempts=0,
            local_successes=0,
            fallback_count=0,
            local_success_rate=0.0,
            avg_local_confidence=0.0,
            avg_cloud_confidence=0.0,
            avg_latency_local_s=0.0,
            avg_latency_cloud_s=0.0,
        )

    fallbacks = [e for e in events if e.fallback_triggered]
    local_successes = total - len(fallbacks)

    avg_local_conf = sum(e.local_confidence for e in events) / total

    # Cloud confidence: only meaningful when fallback was triggered
    cloud_conf_values = [e.local_confidence + e.confidence_diff for e in fallbacks]
    avg_cloud_conf = (
        sum(cloud_conf_values) / len(cloud_conf_values) if cloud_conf_values else 0.0
    )

    avg_local_latency = sum(e.local_latency_s for e in events) / total

    cloud_latency_values = [e.cloud_latency_s for e in fallbacks]
    avg_cloud_latency = (
        sum(cloud_latency_values) / len(cloud_latency_values) if cloud_latency_values else 0.0
    )

    return StageStats(
        total_attempts=total,
        local_successes=local_successes,
        fallback_count=len(fallbacks),
        local_success_rate=local_successes / total,
        avg_local_confidence=avg_local_conf,
        avg_cloud_confidence=avg_cloud_conf,
        avg_latency_local_s=avg_local_latency,
        avg_latency_cloud_s=avg_cloud_latency,
    )


def _identify_training_gaps(
    stage_groups: dict[str, list[InterventionEvent]],
) -> tuple[TrainingGap, ...]:
    """Identify stages where the fallback rate exceeds the threshold."""
    gaps: list[TrainingGap] = []

    for stage, events in stage_groups.items():
        fallbacks = [e for e in events if e.fallback_triggered]
        fallback_rate = len(fallbacks) / len(events) if events else 0.0

        if fallback_rate <= _FALLBACK_RATE_THRESHOLD:
            continue

        description, suggestion = _STAGE_GAP_INFO.get(stage, _default_gap_info(stage))

        example_inputs = tuple(
            e.local_output[:_EXAMPLE_TRUNCATION] for e in fallbacks[:_MAX_EXAMPLE_INPUTS]
        )

        gaps.append(
            TrainingGap(
                stage=stage,
                description=description,
                frequency=len(fallbacks),
                example_inputs=example_inputs,
                suggested_training_data=suggestion,
            )
        )

    # Sort by frequency descending
    gaps.sort(key=lambda g: g.frequency, reverse=True)
    return tuple(gaps)
