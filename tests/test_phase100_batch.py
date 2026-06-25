"""Phase 100 R-7: End-to-end batch route test.

Validates the single-call batch API: RoutingOrchestrator().route_board(pcb_path)
returns a RoutingOrchestrationResult with per-net results and an audit trail.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from kicad_agent.routing.freerouting import is_freerouting_available
from kicad_agent.routing.orchestrator import (
    RoutingOrchestrationResult,
    RoutingOrchestrator,
)


_FIXTURE = Path(__file__).parent / "fixtures" / "smd_test_board.kicad_pcb"


@pytest.mark.skipif(
    not is_freerouting_available(),
    reason="Freerouting not available",
)
class TestBatchRoutesFullBoard:
    def test_route_board_returns_results(self, tmp_path: Path) -> None:
        pcb = _copy_fixture(tmp_path)
        orch = RoutingOrchestrator()
        result = orch.route_board(pcb, project_dir=tmp_path)

        assert isinstance(result, RoutingOrchestrationResult)
        # Per-net dict should be non-empty (board has nets).
        assert len(result.per_net) > 0
        # Audit JSONL should exist with at least one line per dispatched net.
        assert result.audit_path.exists()
        audit_lines = [
            ln for ln in result.audit_path.read_text(encoding="utf-8").split("\n")
            if ln.strip()
        ]
        assert len(audit_lines) >= len(result.per_net)

    def test_audit_lines_are_valid_json(self, tmp_path: Path) -> None:
        pcb = _copy_fixture(tmp_path)
        orch = RoutingOrchestrator()
        result = orch.route_board(pcb, project_dir=tmp_path)

        for line in result.audit_path.read_text(encoding="utf-8").split("\n"):
            if line.strip():
                data = json.loads(line)
                assert "net_name" in data
                assert "router_used" in data
                assert "result" in data


def _copy_fixture(tmp_path: Path) -> Path:
    dest = tmp_path / "smd_test_board.kicad_pcb"
    shutil.copy(_FIXTURE, dest)
    return dest
