"""Tests for GapAnalyzer (volta.ai_tracking.gap_analyzer)."""

from __future__ import annotations

import dataclasses
from datetime import datetime, timezone

import pytest

from volta.ai_tracking.gap_analyzer import (
    CostSavings,
    GapAnalyzer,
    GapReport,
    StageStats,
    TrainingGap,
)
from volta.ai_tracking.tracker import InterventionEvent


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _event(
    *,
    stage: str = "intent_parse",
    fallback_triggered: bool = False,
    fallback_reason: str = "",
    local_confidence: float = 0.8,
    local_latency_s: float = 0.5,
    cloud_latency_s: float = 0.0,
    confidence_diff: float = 0.0,
    model_used: str = "local",
) -> InterventionEvent:
    """Build an InterventionEvent with sensible defaults."""
    return InterventionEvent(
        timestamp=datetime.now(timezone.utc).isoformat(),
        stage=stage,
        local_output="test output",
        local_confidence=local_confidence,
        local_latency_s=local_latency_s,
        fallback_triggered=fallback_triggered,
        fallback_reason=fallback_reason,
        cloud_output="",
        cloud_latency_s=cloud_latency_s,
        confidence_diff=confidence_diff,
        model_used=model_used,
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestEmptyEvents:
    def test_empty_events(self):
        report = GapAnalyzer().analyze([])
        assert report.total_events == 0
        assert report.stage_breakdown == {}
        assert report.training_gaps == ()
        assert report.cost_savings.total_cloud_calls_avoided == 0
        assert report.cost_savings.total_cloud_calls == 0
        assert report.cost_savings.local_success_rate == 0.0


class TestPerStageStats:
    def test_per_stage_stats(self):
        events = [
            _event(stage="intent_parse", fallback_triggered=False, local_confidence=0.9),
            _event(stage="intent_parse", fallback_triggered=False, local_confidence=0.7),
            _event(
                stage="intent_parse",
                fallback_triggered=True,
                fallback_reason="low_confidence",
                local_confidence=0.3,
                confidence_diff=0.5,
                cloud_latency_s=1.2,
                model_used="cloud",
            ),
        ]

        report = GapAnalyzer().analyze(events)
        stats = report.stage_breakdown["intent_parse"]

        assert stats.total_attempts == 3
        assert stats.local_successes == 2
        assert stats.fallback_count == 1
        assert stats.local_success_rate == pytest.approx(2 / 3)


class TestTrainingGapDetection:
    def test_training_gap_detection(self):
        """Stage with >30% fallback rate is flagged as a training gap."""
        # 4 fallbacks out of 5 = 80% fallback rate, well above 30% threshold
        events = [
            _event(stage="error_fix", fallback_triggered=True, fallback_reason="format_error"),
            _event(stage="error_fix", fallback_triggered=True, fallback_reason="low_confidence"),
            _event(stage="error_fix", fallback_triggered=True, fallback_reason="format_error"),
            _event(stage="error_fix", fallback_triggered=True, fallback_reason="schema_validation_failed"),
            _event(stage="error_fix", fallback_triggered=False),
        ]

        report = GapAnalyzer().analyze(events)

        assert len(report.training_gaps) == 1
        gap = report.training_gaps[0]
        assert gap.stage == "error_fix"
        assert gap.frequency == 4

    def test_no_gap_below_threshold(self):
        """Stage with <=30% fallback rate is not flagged."""
        events = [
            _event(stage="intent_parse", fallback_triggered=False),
            _event(stage="intent_parse", fallback_triggered=False),
            _event(stage="intent_parse", fallback_triggered=False),
            _event(stage="intent_parse", fallback_triggered=True, fallback_reason="timeout"),
        ]

        report = GapAnalyzer().analyze(events)
        assert len(report.training_gaps) == 0


class TestCostSavings:
    def test_cost_savings_all_local(self):
        """All local success = 100% savings."""
        events = [_event(fallback_triggered=False) for _ in range(5)]
        report = GapAnalyzer().analyze(events)

        assert report.cost_savings.local_success_rate == 1.0
        assert report.cost_savings.total_cloud_calls_avoided == 5
        assert report.cost_savings.total_cloud_calls == 0

    def test_cost_savings_mixed(self):
        """Mixed local/cloud = proportional savings."""
        events = [
            _event(fallback_triggered=False),
            _event(fallback_triggered=False),
            _event(
                fallback_triggered=True,
                fallback_reason="low_confidence",
                cloud_latency_s=2.0,
                model_used="cloud",
            ),
        ]
        report = GapAnalyzer().analyze(events)

        assert report.cost_savings.local_success_rate == pytest.approx(2 / 3)
        assert report.cost_savings.total_cloud_calls == 1
        assert report.cost_savings.total_cloud_calls_avoided == 2


class TestReportFrozen:
    def test_report_frozen(self):
        """GapReport is a frozen dataclass -- mutation raises FrozenInstanceError."""
        report = GapAnalyzer().analyze([])
        with pytest.raises(dataclasses.FrozenInstanceError):
            report.total_events = 99
