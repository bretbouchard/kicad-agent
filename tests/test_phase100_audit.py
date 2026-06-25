"""Phase 100 R-5: JSONL audit trail tests with fsync durability (H5).

Covers:
- RoutingAuditEntry frozen dataclass
- RoutingAuditLog.append writes JSONL with fsync
- query_by_net filters by net name
- router_used serialized as string (.value) not enum object
- H5: recovery from truncated final line (mid-write crash)
"""

from __future__ import annotations

import dataclasses
import json

import pytest

from kicad_agent.routing.audit import (
    RoutingAuditEntry,
    RoutingAuditLog,
    write_audit_entry,
)
from kicad_agent.routing.strategy import RouterBackend


def _make_entry(
    *,
    net_name: str = "VCC",
    router_used: RouterBackend = RouterBackend.ASTAR,
    result: str = "success",
    route_length_mm: float = 12.5,
    via_count: int = 0,
    drc_clean: bool = True,
    notes: str = "",
    dispatch_reason: str = "default astar",
    strategy: str = "deterministic",
) -> RoutingAuditEntry:
    return RoutingAuditEntry(
        timestamp="2026-06-25T00:00:00+00:00",
        net_name=net_name,
        router_used=router_used,
        strategy=strategy,
        dispatch_reason=dispatch_reason,
        result=result,
        route_length_mm=route_length_mm,
        via_count=via_count,
        drc_clean=drc_clean,
        notes=notes,
    )


# ---------------------------------------------------------------------------
# Frozen dataclass
# ---------------------------------------------------------------------------


class TestRoutingAuditEntryFrozen:
    def test_is_frozen(self) -> None:
        entry = _make_entry()
        with pytest.raises(dataclasses.FrozenInstanceError):
            entry.net_name = "GND"  # type: ignore[misc]

    def test_required_fields_present(self) -> None:
        field_names = {f.name for f in dataclasses.fields(RoutingAuditEntry)}
        assert field_names == {
            "timestamp",
            "net_name",
            "router_used",
            "strategy",
            "dispatch_reason",
            "result",
            "route_length_mm",
            "via_count",
            "drc_clean",
            "notes",
        }


# ---------------------------------------------------------------------------
# Append + JSONL format
# ---------------------------------------------------------------------------


class TestAppendJsonl:
    def test_three_entries_produce_three_lines(self, tmp_path) -> None:
        log = RoutingAuditLog(tmp_path / "audit.jsonl")
        for net in ("VCC", "GND", "SIG"):
            log.append(_make_entry(net_name=net))
        content = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
        lines = [ln for ln in content.split("\n") if ln.strip()]
        assert len(lines) == 3

    def test_each_line_is_valid_json_with_required_fields(self, tmp_path) -> None:
        log = RoutingAuditLog(tmp_path / "audit.jsonl")
        log.append(_make_entry(net_name="VCC"))
        content = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
        line = content.strip().split("\n")[0]
        data = json.loads(line)
        required = {
            "timestamp", "net_name", "router_used", "strategy",
            "dispatch_reason", "result", "route_length_mm",
            "via_count", "drc_clean", "notes",
        }
        assert required.issubset(data.keys())

    def test_creates_parent_directory(self, tmp_path) -> None:
        nested = tmp_path / "deep" / "nested" / "audit.jsonl"
        log = RoutingAuditLog(nested)
        log.append(_make_entry())
        assert nested.exists()


# ---------------------------------------------------------------------------
# Query by net name
# ---------------------------------------------------------------------------


class TestQueryByNet:
    def test_returns_matching_entries(self, tmp_path) -> None:
        log = RoutingAuditLog(tmp_path / "audit.jsonl")
        log.append(_make_entry(net_name="VCC"))
        log.append(_make_entry(net_name="GND"))
        log.append(_make_entry(net_name="VCC"))
        results = log.query_by_net("VCC")
        assert len(results) == 2
        assert all(r.net_name == "VCC" for r in results)

    def test_returns_empty_for_unknown_net(self, tmp_path) -> None:
        log = RoutingAuditLog(tmp_path / "audit.jsonl")
        log.append(_make_entry(net_name="VCC"))
        results = log.query_by_net("NONEXISTENT")
        assert results == []

    def test_reconstructs_router_backend_enum(self, tmp_path) -> None:
        log = RoutingAuditLog(tmp_path / "audit.jsonl")
        log.append(_make_entry(net_name="VCC", router_used=RouterBackend.FREEROUTING))
        results = log.query_by_net("VCC")
        assert len(results) == 1
        assert results[0].router_used == RouterBackend.FREEROUTING


# ---------------------------------------------------------------------------
# Serialization: router_used as string
# ---------------------------------------------------------------------------


class TestRouterUsedSerializedAsString:
    def test(self, tmp_path) -> None:
        log = RoutingAuditLog(tmp_path / "audit.jsonl")
        log.append(_make_entry(router_used=RouterBackend.ASTAR))
        content = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
        data = json.loads(content.strip())
        # Must be the string "astar", not an enum object/dict.
        assert data["router_used"] == "astar"
        assert isinstance(data["router_used"], str)


# ---------------------------------------------------------------------------
# H5: Recovery from truncated line (mid-write crash)
# ---------------------------------------------------------------------------


class TestRecoversFromTruncatedLine:
    def test_skips_partial_line_and_returns_valid_entries(self, tmp_path) -> None:
        audit_path = tmp_path / "audit.jsonl"
        log = RoutingAuditLog(audit_path)
        log.append(_make_entry(net_name="VCC"))
        log.append(_make_entry(net_name="GND"))

        # Simulate a crash mid-write: append a partial JSON line (no newline).
        with open(audit_path, "a", encoding="utf-8") as f:
            f.write('{"timestamp": "2026-06-25T00:00:00+00:00", "net_name": "PARTIAL"')  # no closing brace, no newline

        # query_by_net must skip the truncated line gracefully and return
        # the 2 valid entries. It should NOT raise.
        log2 = RoutingAuditLog(audit_path)
        results = log2.query_by_net("VCC")
        assert len(results) == 1
        assert results[0].net_name == "VCC"


# ---------------------------------------------------------------------------
# Standalone write_audit_entry function
# ---------------------------------------------------------------------------


class TestWriteAuditEntryStandalone:
    def test_appends_via_standalone_function(self, tmp_path) -> None:
        audit_path = tmp_path / "standalone.jsonl"
        write_audit_entry(audit_path, _make_entry(net_name="SIG"))
        content = audit_path.read_text(encoding="utf-8")
        data = json.loads(content.strip())
        assert data["net_name"] == "SIG"
