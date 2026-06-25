"""Routing audit trail: JSONL writer with fsync durability (H5).

Every routing decision is logged as one JSONL line in
``<project_dir>/.kicad-agent/audit/routing_<timestamp>.jsonl``. The file
is append-only, streaming-friendly (tail -f), and grep-friendly.

H5 durability: writes use os.fsync after each line to flush kernel buffers.
In the rare event of a mid-write crash, the last line may be truncated;
query_by_net skips invalid JSON lines with a logged warning (tested in
test_phase100_audit.py::TestRecoversFromTruncatedLine).

Threat model (T-100-02-03 Repudiation): the audit trail provides a durable,
queryable record of every routing decision with ISO 8601 timestamps. The
fsync durability means the record survives process crashes, preventing
an attacker (or a buggy router) from denying a routing decision was made.
"""

from __future__ import annotations

import json
import logging
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path

from kicad_agent.routing.strategy import RouterBackend

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class RoutingAuditEntry:
    """One routing decision in the audit trail.

    Attributes:
        timestamp: ISO 8601 UTC string (e.g., "2026-06-25T06:42:13+00:00").
        net_name: Name of the net that was routed.
        router_used: Which backend handled it (ASTAR or FREEROUTING).
        strategy: Strategy name ("deterministic" | "ai_advisor_v1" in Phase 98).
        dispatch_reason: Human-readable why this router was chosen.
        result: Outcome ("success" | "failed" | "rejected" | "approved").
        route_length_mm: Total route length in mm (0.0 if failed).
        via_count: Number of vias in the route (0 if none or failed).
        drc_clean: True if the route passes DRC.
        notes: Free-text rationale (e.g., "user rejected: too close to GND").
        strategy_notes: Notes from the RoutingStrategyResult.routing_notes
            field. For DeterministicStrategy this is a static string. For
            AiRoutingStrategy it carries the ``ai_fallback:`` prefix when
            the model failed and the deterministic fallback was used (H-1 /
            ME-05). Persisted to JSONL so the audit trail can reconstruct
            whether AI contributed or fell back — previously this prefix
            only landed in the in-memory result and Python logger.warning.
    """

    timestamp: str
    net_name: str
    router_used: RouterBackend
    strategy: str
    dispatch_reason: str
    result: str
    route_length_mm: float
    via_count: int
    drc_clean: bool
    notes: str
    strategy_notes: str = ""


def _entry_to_dict(entry: RoutingAuditEntry) -> dict:
    """Serialize a RoutingAuditEntry to a JSON-safe dict.

    RouterBackend (a str Enum) is converted to its string value so the
    JSON line contains "astar"/"freerouting" rather than an enum object.
    """
    return {
        "timestamp": entry.timestamp,
        "net_name": entry.net_name,
        "router_used": entry.router_used.value,
        "strategy": entry.strategy,
        "dispatch_reason": entry.dispatch_reason,
        "result": entry.result,
        "route_length_mm": entry.route_length_mm,
        "via_count": entry.via_count,
        "drc_clean": entry.drc_clean,
        "notes": entry.notes,
        "strategy_notes": entry.strategy_notes,
    }


def _dict_to_entry(data: dict) -> RoutingAuditEntry:
    """Reconstruct a RoutingAuditEntry from a parsed JSON dict.

    Converts the router_used string back to a RouterBackend enum value.

    strategy_notes is optional (defaults to "") for backward compatibility
    with audit lines written before the H-1 / ME-05 fix added the field.
    """
    router_str = data.get("router_used", "")
    try:
        router_used = RouterBackend(router_str)
    except ValueError:
        # Unknown backend string (e.g., a future variant). Default to ASTAR
        # so query_by_net doesn't crash on historical entries.
        logger.warning(
            "Unknown router_used value %r in audit line; defaulting to ASTAR",
            router_str,
        )
        router_used = RouterBackend.ASTAR
    return RoutingAuditEntry(
        timestamp=data.get("timestamp", ""),
        net_name=data.get("net_name", ""),
        router_used=router_used,
        strategy=data.get("strategy", ""),
        dispatch_reason=data.get("dispatch_reason", ""),
        result=data.get("result", ""),
        route_length_mm=float(data.get("route_length_mm", 0.0)),
        via_count=int(data.get("via_count", 0)),
        drc_clean=bool(data.get("drc_clean", False)),
        notes=data.get("notes", ""),
        strategy_notes=data.get("strategy_notes", ""),
    )


class RoutingAuditLog:
    """Append-only JSONL audit log with fsync durability (H5).

    Writes one JSON line per entry. Each write is flushed via f.flush()
    followed by os.fsync(f.fileno()) to force the kernel buffer to disk.
    This guarantees the entry survives a process crash (T-100-02-03).

    On read (query_by_net), lines that fail JSON parsing (e.g., a
    truncated final line from a mid-write crash) are skipped with a
    logged warning. This graceful recovery is tested in
    test_phase100_audit.py::TestRecoversFromTruncatedLine.

    Thread safety: NOT thread-safe. The file handle races under
    concurrent append. Create one RoutingAuditLog (or one
    RoutingOrchestrator) per thread. If Phase 98 requires concurrency,
    add a threading.Lock to append().
    """

    def __init__(self, audit_path: Path) -> None:
        self._path = audit_path
        audit_path.parent.mkdir(parents=True, exist_ok=True)

    @property
    def path(self) -> Path:
        """Path to the JSONL audit file."""
        return self._path

    def append(self, entry: RoutingAuditEntry) -> None:
        """Append one entry as a JSONL line with fsync durability (H5).

        Opens in append-binary mode, writes the JSON line plus a newline,
        flushes the Python buffer, then fsyncs the OS buffer to disk.
        """
        line = json.dumps(_entry_to_dict(entry))
        # O_APPEND ensures atomic appends for small writes on POSIX.
        with open(self._path, "ab") as f:
            f.write((line + "\n").encode("utf-8"))
            f.flush()
            os.fsync(f.fileno())

    def query_by_net(self, net_name: str) -> list[RoutingAuditEntry]:
        """Return all entries matching net_name, skipping invalid lines.

        H5 recovery: if a line fails JSON parsing (e.g., truncated final
        line from a mid-write crash), it is skipped with a logged warning
        rather than raising. This ensures a partial write doesn't poison
        the entire audit trail.
        """
        if not self._path.exists():
            return []

        results: list[RoutingAuditEntry] = []
        with open(self._path, "r", encoding="utf-8") as f:
            for line_num, raw_line in enumerate(f, start=1):
                stripped = raw_line.strip()
                if not stripped:
                    continue
                try:
                    data = json.loads(stripped)
                except json.JSONDecodeError:
                    # H5: truncated/corrupt line — skip with warning.
                    logger.warning(
                        "Skipping invalid JSON at %s:%d (truncated line?)",
                        self._path, line_num,
                    )
                    continue
                if not isinstance(data, dict):
                    logger.warning(
                        "Skipping non-object JSON at %s:%d",
                        self._path, line_num,
                    )
                    continue
                if data.get("net_name") == net_name:
                    results.append(_dict_to_entry(data))
        return results


def write_audit_entry(audit_path: Path, entry: RoutingAuditEntry) -> None:
    """Append one entry to the audit log (standalone convenience function).

    Uses RoutingAuditLog internally so fsync durability (H5) applies.
    """
    log = RoutingAuditLog(audit_path)
    log.append(entry)


def now_iso() -> str:
    """Current UTC time as ISO 8601 string (helper for entry construction)."""
    return datetime.now(timezone.utc).isoformat()
