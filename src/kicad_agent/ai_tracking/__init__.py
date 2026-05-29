"""AI intervention tracking -- records local/cloud fallback events for training gap analysis."""

from __future__ import annotations

from kicad_agent.ai_tracking.gap_analyzer import GapAnalyzer, GapReport
from kicad_agent.ai_tracking.tracker import InterventionEvent, InterventionTracker

__all__ = ["InterventionTracker", "InterventionEvent", "GapAnalyzer", "GapReport"]
