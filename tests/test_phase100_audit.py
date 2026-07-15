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

from volta.routing.audit import (
    RoutingAuditEntry,
    RoutingAuditLog,
    write_audit_entry,
)
from volta.routing.strategy import RouterBackend


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
    strategy_notes: str = "",
    dead_end_point: tuple[float, float] | None = None,
    target_point: tuple[float, float] | None = None,
    failure_type: str = "",
    reachable_count: int = 0,
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
        strategy_notes=strategy_notes,
        dead_end_point=dead_end_point,
        target_point=target_point,
        failure_type=failure_type,
        reachable_count=reachable_count,
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
            "strategy_notes",
            # Phase 103: failure-location fields (optional, backward-compat).
            "dead_end_point",
            "target_point",
            "failure_type",
            "reachable_count",
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
            "via_count", "drc_clean", "notes", "strategy_notes",
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
# Phase 103: failure-location round-trip
# ---------------------------------------------------------------------------


class TestPhase103FailureLocation:
    """Phase 103: dead_end_point and failure_type survive JSONL round-trip."""

    def test_failure_fields_round_trip(self, tmp_path) -> None:
        log = RoutingAuditLog(tmp_path / "audit.jsonl")
        entry = _make_entry(
            net_name="FAILED_NET",
            result="failed",
            dead_end_point=(12.5, 34.7),
            target_point=(80.0, 90.0),
            failure_type="no_path",
            reachable_count=1542,
        )
        log.append(entry)
        results = log.query_by_net("FAILED_NET")
        assert len(results) == 1
        r = results[0]
        assert r.dead_end_point == (12.5, 34.7)
        assert r.target_point == (80.0, 90.0)
        assert r.failure_type == "no_path"
        assert r.reachable_count == 1542

    def test_success_entries_omit_failure_fields(self, tmp_path) -> None:
        """Success entries don't pollute JSONL with empty failure fields."""
        log = RoutingAuditLog(tmp_path / "audit.jsonl")
        log.append(_make_entry(net_name="OK_NET", result="success"))
        content = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
        data = json.loads(content.strip())
        # Success entries should not contain failure-location keys.
        assert "dead_end_point" not in data
        assert "target_point" not in data
        assert "failure_type" not in data
        assert "reachable_count" not in data

    def test_backward_compat_old_entries_without_failure_fields(self, tmp_path) -> None:
        """Pre-Phase-103 audit lines (no failure fields) still parse."""
        audit_path = tmp_path / "audit.jsonl"
        old_line = json.dumps({
            "timestamp": "2026-01-01T00:00:00+00:00",
            "net_name": "OLD_NET",
            "router_used": "astar",
            "strategy": "DeterministicStrategy",
            "dispatch_reason": "astar:no_path_found",
            "result": "failed",
            "route_length_mm": 0.0,
            "via_count": 0,
            "drc_clean": False,
            "notes": "",
            "strategy_notes": "",
        })
        audit_path.write_text(old_line + "\n", encoding="utf-8")
        log = RoutingAuditLog(audit_path)
        results = log.query_by_net("OLD_NET")
        assert len(results) == 1
        r = results[0]
        assert r.dead_end_point is None
        assert r.target_point is None
        assert r.failure_type == ""
        assert r.reachable_count == 0


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


# ---------------------------------------------------------------------------
# H-1 / ME-05: strategy_notes persists to durable JSONL audit trail
# ---------------------------------------------------------------------------


class TestStrategyNotesPersistsToAudit:
    """H-1 / ME-05: RoutingAuditEntry must persist strategy_notes so the
    ``ai_fallback:`` prefix from AiRoutingStrategy reaches the durable JSONL
    file — not just the in-memory result and Python logger.warning.

    Previously the schema captured ``strategy=type(strategy).__name__`` but
    discarded ``RoutingStrategyResult.routing_notes``. The Phase 98 eval
    harness scanned net notes for the ``ai_fallback:`` marker in-memory, but
    the durable trail could not reconstruct whether AI contributed or fell
    back when analyzed post-hoc.
    """

    def test_audit_entry_includes_strategy_notes(self, tmp_path) -> None:
        """strategy_notes flows through to the JSONL file on append."""
        log = RoutingAuditLog(tmp_path / "audit.jsonl")
        log.append(_make_entry(
            net_name="VCC",
            strategy_notes="deterministic: Phase 99 baseline heuristics",
        ))
        content = (tmp_path / "audit.jsonl").read_text(encoding="utf-8")
        data = json.loads(content.strip())
        assert data["strategy_notes"] == "deterministic: Phase 99 baseline heuristics"

    def test_strategy_notes_round_trips_through_query_by_net(self, tmp_path) -> None:
        """strategy_notes survives serialize -> deserialize -> query."""
        log = RoutingAuditLog(tmp_path / "audit.jsonl")
        log.append(_make_entry(
            net_name="VCC",
            strategy_notes="ai_fallback: ValueError: missing N1 from net_priorities",
        ))
        log2 = RoutingAuditLog(tmp_path / "audit.jsonl")
        results = log2.query_by_net("VCC")
        assert len(results) == 1
        assert results[0].strategy_notes.startswith("ai_fallback:")
        assert "ValueError" in results[0].strategy_notes

    def test_strategy_notes_defaults_to_empty_string(self, tmp_path) -> None:
        """Entries constructed without strategy_notes serialize as empty string."""
        entry = RoutingAuditEntry(
            timestamp="2026-06-25T00:00:00+00:00",
            net_name="VCC",
            router_used=RouterBackend.ASTAR,
            strategy="deterministic",
            dispatch_reason="test",
            result="success",
            route_length_mm=1.0,
            via_count=0,
            drc_clean=False,
            notes="",
        )
        assert entry.strategy_notes == ""
        # Round-trip through JSONL: missing key in old lines defaults to "".
        log = RoutingAuditLog(tmp_path / "audit.jsonl")
        log.append(entry)
        # Manually rewrite the line WITHOUT strategy_notes to simulate a
        # pre-H-1 audit entry and confirm backward-compatible deserialization.
        raw = (tmp_path / "audit.jsonl").read_text(encoding="utf-8").strip()
        data = json.loads(raw)
        del data["strategy_notes"]
        with open(tmp_path / "audit.jsonl", "w", encoding="utf-8") as f:
            f.write(json.dumps(data) + "\n")
        log2 = RoutingAuditLog(tmp_path / "audit.jsonl")
        results = log2.query_by_net("VCC")
        assert len(results) == 1
        assert results[0].strategy_notes == ""


# ---------------------------------------------------------------------------
# H-1: AiRoutingStrategy fallback marker reaches audit trail via orchestrator
# ---------------------------------------------------------------------------


class TestAiFallbackMarkerPersistsToAudit:
    """H-1 end-to-end: when AiRoutingStrategy falls back to DeterministicStrategy
    on a model failure, the ``ai_fallback:`` prefix must reach the durable
    JSONL audit trail via the orchestrator's strategy_notes population.

    This test uses a minimal stub strategy that mimics AiRoutingStrategy's
    fallback behavior (broad except -> deterministic result with ai_fallback:
    prefix) and verifies the orchestrator persists the notes.
    """

    def test_ai_fallback_marker_persists_to_audit(self, tmp_path) -> None:
        from pathlib import Path

        from volta.routing.orchestrator import RoutingOrchestrator
        from volta.routing.strategy import (
            BoardState,
            DeterministicStrategy,
            Pin,
            RouterBackend,
            RoutingStrategyResult,
        )

        class StubAiFallbackStrategy:
            """Mimics AiRoutingStrategy's R-6 fallback: returns a
            deterministic result with routing_notes carrying the
            ``ai_fallback:`` prefix."""

            def strategize(
                self,
                board_state: BoardState,
                netlist: dict[str, list[Pin]],
            ) -> RoutingStrategyResult:
                det = DeterministicStrategy()
                det_result = det.strategize(board_state, netlist)
                # Replace notes with the ai_fallback marker (mirrors
                # ai_strategy.py line ~180).
                return RoutingStrategyResult(
                    net_priorities=det_result.net_priorities,
                    layer_hints=det_result.layer_hints,
                    keepouts=det_result.keepouts,
                    router_assignment=det_result.router_assignment,
                    routing_notes=(
                        "ai_fallback: _AiStrategyError: empty model output"
                    ),
                )

        # Minimal board with one net so route_board dispatches at least one net.
        fixture = Path(__file__).parent / "fixtures" / "smd_test_board.kicad_pcb"
        import shutil
        pcb = tmp_path / "smd_test_board.kicad_pcb"
        shutil.copy(fixture, pcb)

        orch = RoutingOrchestrator(strategy=StubAiFallbackStrategy())
        result = orch.route_board(pcb, project_dir=tmp_path)

        # Read the audit JSONL and confirm the ai_fallback marker persisted.
        audit_text = result.audit_path.read_text(encoding="utf-8")
        lines = [ln for ln in audit_text.strip().split("\n") if ln.strip()]
        assert len(lines) > 0
        for line in lines:
            data = json.loads(line)
            assert data["strategy_notes"].startswith("ai_fallback:"), (
                f"strategy_notes missing ai_fallback prefix in audit trail "
                f"(H-1 violation): {data['strategy_notes']!r}"
            )
            assert "_AiStrategyError" in data["strategy_notes"]
