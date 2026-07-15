"""Tests for ai_tracking module: tracker, gap_analyzer, and stats."""

import json
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

import pytest

from volta.ai_tracking import (
    GapAnalyzer,
    GapReport,
    InterventionEvent,
    InterventionTracker,
)
from volta.ai_tracking.stats import format_stats_report


def _make_event(
    stage: str = "intent_parse",
    confidence: float = 0.95,
    fallback: bool = False,
    reason: str = "",
) -> InterventionEvent:
    """Create a test InterventionEvent."""
    return InterventionEvent(
        timestamp=datetime(2026, 1, 15, 12, 0, 0).isoformat(),
        stage=stage,
        local_output="test output content" * 20,
        local_confidence=confidence,
        local_latency_s=0.5,
        fallback_triggered=fallback,
        fallback_reason=reason,
        cloud_output="cloud output" if fallback else "",
        cloud_latency_s=1.2 if fallback else 0.0,
        confidence_diff=0.1 if fallback else 0.0,
        model_used="cloud" if fallback else "local",
    )


class TestInterventionEvent:
    """Tests for InterventionEvent dataclass."""

    def test_serialization_round_trip(self):
        """Event serializes to dict and back without loss."""
        event = _make_event()
        d = event.to_dict()
        restored = InterventionEvent.from_dict(d)
        assert restored == event

    def test_from_dict_ignores_unknown_keys(self):
        """from_dict ignores unknown keys without error."""
        event = _make_event()
        d = event.to_dict()
        d["unknown_field"] = "should be ignored"
        restored = InterventionEvent.from_dict(d)
        assert restored == event

    def test_frozen(self):
        """InterventionEvent is frozen (immutable)."""
        event = _make_event()
        with pytest.raises(AttributeError):
            event.stage = "other"


class TestInterventionTracker:
    """Tests for InterventionTracker JSONL event logger."""

    def test_record_and_query(self):
        """Tracker records events and queries them back."""
        with tempfile.TemporaryDirectory() as tmp:
            tracker = InterventionTracker(log_dir=tmp)
            event = _make_event(stage="intent_parse")
            tracker.record(event)

            results = tracker.query()
            assert len(results) == 1
            assert results[0].stage == "intent_parse"

    def test_record_multiple_events(self):
        """Tracker records and retrieves multiple events."""
        with tempfile.TemporaryDirectory() as tmp:
            tracker = InterventionTracker(log_dir=tmp)
            for i in range(10):
                tracker.record(_make_event(stage=f"stage_{i}"))

            results = tracker.query()
            assert len(results) == 10

    def test_query_by_stage(self):
        """Query filters events by stage."""
        with tempfile.TemporaryDirectory() as tmp:
            tracker = InterventionTracker(log_dir=tmp)
            tracker.record(_make_event(stage="intent_parse"))
            tracker.record(_make_event(stage="error_fix"))
            tracker.record(_make_event(stage="intent_parse"))

            results = tracker.query(stage="intent_parse")
            assert len(results) == 2

    def test_query_fallback_only(self):
        """Query filters to only fallback events."""
        with tempfile.TemporaryDirectory() as tmp:
            tracker = InterventionTracker(log_dir=tmp)
            tracker.record(_make_event(fallback=False))
            tracker.record(_make_event(fallback=True, reason="low_confidence"))
            tracker.record(_make_event(fallback=False))

            results = tracker.query(fallback_only=True)
            assert len(results) == 1

    def test_query_limit(self):
        """Query respects limit parameter."""
        with tempfile.TemporaryDirectory() as tmp:
            tracker = InterventionTracker(log_dir=tmp)
            for _ in range(50):
                tracker.record(_make_event())

            results = tracker.query(limit=10)
            assert len(results) == 10

    def test_disabled_tracker_no_ops(self):
        """Disabled tracker does not write or read."""
        with tempfile.TemporaryDirectory() as tmp:
            tracker = InterventionTracker(log_dir=tmp, enabled=False)
            tracker.record(_make_event())
            assert tracker.query() == []
            assert tracker.get_all_events() == []

    def test_empty_log_dir(self):
        """Query on non-existent log dir returns empty list."""
        tracker = InterventionTracker(log_dir="/nonexistent/path/that/does/not/exist")
        assert tracker.query() == []

    def test_get_all_events(self):
        """get_all_events reads from current log file."""
        with tempfile.TemporaryDirectory() as tmp:
            tracker = InterventionTracker(log_dir=tmp)
            tracker.record(_make_event(stage="a"))
            tracker.record(_make_event(stage="b"))

            events = tracker.get_all_events()
            assert len(events) == 2

    def test_corrupted_line_skipped(self):
        """Corrupted JSONL lines are skipped, valid lines parsed."""
        with tempfile.TemporaryDirectory() as tmp:
            tracker = InterventionTracker(log_dir=tmp)
            tracker.record(_make_event(stage="valid"))

            # Append a corrupted line manually
            log_file = Path(tmp) / "interventions.jsonl"
            with open(log_file, "a") as f:
                f.write("this is not json\n")

            results = tracker.query()
            assert len(results) == 1
            assert results[0].stage == "valid"


class TestGapAnalyzer:
    """Tests for GapAnalyzer gap analysis."""

    def test_analyze_empty_events(self):
        """Analyzing empty events produces empty report."""
        analyzer = GapAnalyzer()
        report = analyzer.analyze([])
        assert report.total_events == 0
        assert report.training_gaps == ()

    def test_analyze_all_local_success(self):
        """All local successes -- no training gaps."""
        analyzer = GapAnalyzer()
        events = [_make_event(confidence=0.9) for _ in range(20)]
        report = analyzer.analyze(events)
        assert report.total_events == 20
        assert len(report.training_gaps) == 0
        assert report.cost_savings.total_cloud_calls == 0

    def test_analyze_identifies_gap(self):
        """High fallback rate (>30%) triggers training gap detection."""
        analyzer = GapAnalyzer()
        events = []
        # 5 local successes (50%)
        for _ in range(5):
            events.append(_make_event(confidence=0.9, fallback=False))
        # 5 fallbacks (50% > 30% threshold)
        for _ in range(5):
            events.append(_make_event(confidence=0.3, fallback=True, reason="low_confidence"))

        report = analyzer.analyze(events)
        assert report.total_events == 10
        assert len(report.training_gaps) > 0
        assert report.training_gaps[0].stage == "intent_parse"

    def test_top_fallback_reasons(self):
        """Top fallback reasons are correctly identified."""
        analyzer = GapAnalyzer()
        events = [
            _make_event(fallback=True, reason="low_confidence"),
            _make_event(fallback=True, reason="low_confidence"),
            _make_event(fallback=True, reason="format_error"),
        ]
        report = analyzer.analyze(events)
        assert report.top_fallback_reasons[0] == ("low_confidence", 2)

    def test_stage_breakdown(self):
        """Stage breakdown contains correct stats."""
        analyzer = GapAnalyzer()
        events = [_make_event(stage="intent_parse"), _make_event(stage="error_fix")]
        report = analyzer.analyze(events)
        assert "intent_parse" in report.stage_breakdown
        assert "error_fix" in report.stage_breakdown

    def test_cost_savings(self):
        """Cost savings correctly counts avoided cloud calls."""
        analyzer = GapAnalyzer()
        events = [
            _make_event(fallback=False),  # avoided
            _make_event(fallback=False),  # avoided
            _make_event(fallback=True, reason="low_confidence"),  # cloud call
        ]
        report = analyzer.analyze(events)
        assert report.cost_savings.total_cloud_calls_avoided == 2
        assert report.cost_savings.total_cloud_calls == 1


class TestStatsReport:
    """Tests for stats formatting."""

    def test_format_empty_report(self):
        """Format empty report without errors."""
        analyzer = GapAnalyzer()
        report = analyzer.analyze([])
        output = format_stats_report(report)
        assert "kicad-agent AI Performance Report" in output
        assert "Total events: 0" in output

    def test_format_report_with_data(self):
        """Format report with data includes all sections."""
        analyzer = GapAnalyzer()
        events = [
            _make_event(fallback=False),
            _make_event(fallback=True, reason="low_confidence"),
        ]
        report = analyzer.analyze(events)
        output = format_stats_report(report)
        assert "Local Success Rate" in output
        assert "Fallback Reasons" in output
        assert "Cost Savings" in output

    def test_report_sections_present(self):
        """Report contains all expected section headers."""
        analyzer = GapAnalyzer()
        events = [
            _make_event(fallback=False),
            _make_event(fallback=True, reason="format_error"),
            _make_event(fallback=True, reason="format_error"),
            _make_event(fallback=True, reason="format_error"),
            _make_event(fallback=True, reason="format_error"),
        ]
        report = analyzer.analyze(events)
        output = format_stats_report(report)
        assert "Training Gaps" in output
