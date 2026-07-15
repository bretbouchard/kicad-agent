"""Intervention tracker -- JSONL-based event logger for local/cloud fallback events."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_DEFAULT_LOG_DIR = ".volta_tracking"
_LOG_FILENAME = "interventions.jsonl"


@dataclass(frozen=True)
class InterventionEvent:
    """A single local/cloud fallback event."""

    timestamp: str  # ISO 8601
    stage: str  # "intent_parse", "error_fix", "critique", "component_suggest"
    local_output: str  # Raw local model output (truncated to 2048 chars)
    local_confidence: float  # 0.0-1.0
    local_latency_s: float
    fallback_triggered: bool  # True if cloud was called
    fallback_reason: str  # "low_confidence", "format_error", "schema_validation_failed", "timeout", "local_unavailable", ""
    cloud_output: str  # Raw cloud output (truncated to 2048 chars), empty if no fallback
    cloud_latency_s: float  # 0.0 if no fallback
    confidence_diff: float  # cloud_confidence - local_confidence (0.0 if no fallback)
    model_used: str  # "local" or "cloud" -- which result was ultimately used

    def to_dict(self) -> dict:
        """Serialize to a JSON-compatible dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> InterventionEvent:
        """Deserialize from a dictionary, ignoring unknown keys."""
        known_fields = {f.name for f in cls.__dataclass_fields__.values()}
        filtered = {k: v for k, v in data.items() if k in known_fields}
        return cls(**filtered)


class InterventionTracker:
    """Records intervention events to a rotating JSONL file.

    Each event is appended as a single JSON line. When the log file exceeds
    ``max_file_size_mb``, the file is rotated (up to ``rotation_count``
    historical files are kept).

    When ``enabled`` is False, all operations become no-ops with no file I/O.
    """

    def __init__(
        self,
        log_dir: str | Path | None = None,
        max_file_size_mb: float = 50.0,
        rotation_count: int = 5,
        enabled: bool = True,
    ) -> None:
        self._enabled = enabled
        self._max_file_size_bytes = max_file_size_mb * 1024 * 1024
        self._rotation_count = rotation_count

        if log_dir is None:
            self._log_dir = Path(_DEFAULT_LOG_DIR)
        else:
            self._log_dir = Path(log_dir)

        self._log_file = self._log_dir / _LOG_FILENAME

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def record(self, event: InterventionEvent) -> None:
        """Append *event* as a JSONL line, rotating if the file is too large."""
        if not self._enabled:
            return

        self._ensure_log_dir()
        self._rotate_if_needed()

        line = json.dumps(event.to_dict(), ensure_ascii=False) + "\n"
        with open(self._log_file, "a", encoding="utf-8") as fh:
            fh.write(line)

    def query(
        self,
        stage: str | None = None,
        since: datetime | None = None,
        fallback_only: bool = False,
        limit: int = 1000,
    ) -> list[InterventionEvent]:
        """Read and filter JSONL records from the current log file.

        Results are returned in chronological order (oldest first).
        """
        if not self._enabled:
            return []

        if not self._log_file.exists():
            return []

        events: list[InterventionEvent] = []
        with open(self._log_file, "r", encoding="utf-8") as fh:
            for line_no, raw_line in enumerate(fh, start=1):
                event = self._parse_line(raw_line, line_no)
                if event is None:
                    continue

                if stage is not None and event.stage != stage:
                    continue
                if since is not None:
                    try:
                        event_ts = datetime.fromisoformat(event.timestamp)
                    except (ValueError, TypeError):
                        continue
                    if event_ts < since:
                        continue
                if fallback_only and not event.fallback_triggered:
                    continue

                events.append(event)
                if len(events) >= limit:
                    break

        return events

    def get_all_events(self) -> list[InterventionEvent]:
        """Read all events from the current log file and all rotated files."""
        if not self._enabled:
            return []

        events: list[InterventionEvent] = []

        # Read rotated files in order (oldest first: N, N-1, ..., 1)
        for idx in range(self._rotation_count, 0, -1):
            rotated = self._log_dir / f"interventions.{idx}.jsonl"
            if rotated.exists():
                events.extend(self._read_file(rotated))

        # Read current file last
        if self._log_file.exists():
            events.extend(self._read_file(self._log_file))

        return events

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _ensure_log_dir(self) -> None:
        """Create the log directory if it does not exist."""
        self._log_dir.mkdir(parents=True, exist_ok=True)

    def _rotate_if_needed(self) -> None:
        """Rotate the log file when it exceeds the size limit."""
        if not self._log_file.exists():
            return

        try:
            file_size = self._log_file.stat().st_size
        except OSError:
            return

        if file_size < self._max_file_size_bytes:
            return

        # Delete the oldest rotated file if it would be pushed beyond the limit
        oldest = self._log_dir / f"interventions.{self._rotation_count}.jsonl"
        if oldest.exists():
            oldest.unlink()

        # Shift existing rotated files up by 1
        for idx in range(self._rotation_count, 1, -1):
            src = self._log_dir / f"interventions.{idx - 1}.jsonl"
            dst = self._log_dir / f"interventions.{idx}.jsonl"
            if src.exists():
                src.rename(dst)

        # Rename current file to .1
        self._log_file.rename(self._log_dir / "interventions.1.jsonl")

        # New empty current file will be created by the next write

    def _parse_line(self, raw_line: str, line_no: int) -> InterventionEvent | None:
        """Parse a single JSONL line into an InterventionEvent."""
        stripped = raw_line.strip()
        if not stripped:
            return None

        try:
            data = json.loads(stripped)
        except json.JSONDecodeError:
            logger.warning(
                "Skipping corrupted JSONL line %d in %s: %s",
                line_no,
                self._log_file,
                stripped[:120],
            )
            return None

        try:
            return InterventionEvent.from_dict(data)
        except TypeError:
            logger.warning(
                "Skipping line %d with invalid fields in %s: %s",
                line_no,
                self._log_file,
                stripped[:120],
            )
            return None

    def _read_file(self, path: Path) -> list[InterventionEvent]:
        """Read all events from a single JSONL file."""
        events: list[InterventionEvent] = []
        with open(path, "r", encoding="utf-8") as fh:
            for line_no, raw_line in enumerate(fh, start=1):
                event = self._parse_line(raw_line, line_no)
                if event is not None:
                    events.append(event)
        return events
