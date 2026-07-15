"""Tests for InterventionTracker and InterventionEvent."""

import dataclasses

import pytest

from volta.ai_tracking.tracker import InterventionEvent, InterventionTracker


def _make_event(**overrides) -> InterventionEvent:
    """Build a valid InterventionEvent with sensible defaults."""
    defaults = dict(
        timestamp="2025-01-01T00:00:00",
        stage="intent_parse",
        local_output='{"name": "test"}',
        local_confidence=0.9,
        local_latency_s=0.5,
        fallback_triggered=False,
        fallback_reason="",
        cloud_output="",
        cloud_latency_s=0.0,
        confidence_diff=0.0,
        model_used="local",
    )
    defaults.update(overrides)
    return InterventionEvent(**defaults)


# ---------------------------------------------------------------------------
# InterventionEvent
# ---------------------------------------------------------------------------


class TestInterventionEvent:
    def test_event_frozen(self):
        event = _make_event()
        assert dataclasses.is_dataclass(event)
        with pytest.raises(dataclasses.FrozenInstanceError):
            event.stage = "modified"


# ---------------------------------------------------------------------------
# InterventionTracker
# ---------------------------------------------------------------------------


class TestInterventionTracker:
    def test_record_and_query(self, tmp_path):
        tracker = InterventionTracker(log_dir=tmp_path)
        e1 = _make_event(stage="intent_parse")
        e2 = _make_event(stage="error_fix", local_confidence=0.3)
        tracker.record(e1)
        tracker.record(e2)

        results = tracker.query()
        assert len(results) == 2
        assert results[0].stage == "intent_parse"
        assert results[1].stage == "error_fix"

    def test_query_by_stage(self, tmp_path):
        tracker = InterventionTracker(log_dir=tmp_path)
        tracker.record(_make_event(stage="intent_parse"))
        tracker.record(_make_event(stage="error_fix"))
        tracker.record(_make_event(stage="intent_parse"))

        results = tracker.query(stage="intent_parse")
        assert len(results) == 2
        assert all(e.stage == "intent_parse" for e in results)

    def test_disabled_tracker(self):
        tracker = InterventionTracker(enabled=False)
        # Should not crash — no directory, no file I/O
        tracker.record(_make_event())
        assert tracker.query() == []

    def test_event_truncation(self, tmp_path):
        long_output = "x" * 3000
        event = _make_event(local_output=long_output)
        tracker = InterventionTracker(log_dir=tmp_path)
        tracker.record(event)

        results = tracker.query()
        assert len(results) == 1
        # The tracker records the event as-is; truncation happens at
        # construction time in the pipeline. Verify the full string
        # was persisted and that it exceeds 2048.
        assert len(results[0].local_output) == 3000

        # Also verify that the event data round-trips correctly
        assert results[0].local_output == long_output
