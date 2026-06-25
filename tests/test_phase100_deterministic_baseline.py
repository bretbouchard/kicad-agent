"""Phase 100 R-6 / SC-5: Deterministic mode within +/-5% of Phase 99 baseline.

Phase 99-03 SUMMARY.md:67 established the smd_test_board baseline at 50%
completion (4 of 8 nets routed, DRC PASS). This test verifies the
DeterministicStrategy-based orchestrator achieves within +/-5% of that
baseline (i.e., 45-55% completion).

This test is slow (runs a real Freerouting subprocess) and gated behind
both Freerouting availability and the @slow marker.
"""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest

from kicad_agent.routing.freerouting import is_freerouting_available
from kicad_agent.routing.orchestrator import RoutingOrchestrator


_FIXTURE = Path(__file__).parent / "fixtures" / "smd_test_board.kicad_pcb"


@pytest.mark.slow
@pytest.mark.skipif(
    not is_freerouting_available(),
    reason="Freerouting not available",
)
class TestDeterministicWithinFivePercentOfBaseline:
    def test_completion_within_band(self, tmp_path: Path) -> None:
        pcb = _copy_fixture(tmp_path)
        orch = RoutingOrchestrator()
        result = orch.route_board(pcb, project_dir=tmp_path)

        total = len(result.per_net)
        if total == 0:
            pytest.skip("Board has no nets to route")

        routed = result.total_routed
        completion_pct = (routed / total) * 100.0

        # Phase 99 baseline: 50%. Allowed band: 45-55%.
        assert 45.0 <= completion_pct <= 55.0, (
            f"Deterministic completion {completion_pct:.1f}% outside "
            f"45-55% baseline band (baseline=50%)"
        )


def _copy_fixture(tmp_path: Path) -> Path:
    dest = tmp_path / "smd_test_board.kicad_pcb"
    shutil.copy(_FIXTURE, dest)
    return dest
