"""R-1: Freerouting honors Specctra (wire (type fix)) and (type protect).

This is the make-or-break empirical test for the negotiation loop (Phase 105).
Phase 105's design depends on re-exporting DSN each round with successfully-
routed nets marked as fixed, so Freerouting preserves them and only re-routes
failed/ripped-up nets. If Freerouting ignores the lock, the loop must fall
back to full-re-route-per-round (functional but 3-5x slower).

Background — this build of Freerouting (build revision 20f1a72e, post-v2.2.4)
has a documented history of ignoring Specctra directives: the SC-5 workaround
in FreerouteBatch.java:181-206 shows (control (snap_angle ...)) is ignored and
worked around via the Java API. This test confirms whether (wire (type fix))
suffers the same fate.

Verdict (empirically established 2026-07-02): HONORED.
  - (type fix)     -> fixed wire survives, router does not rip up or reroute
  - (type protect) -> fixed wire survives, router does not rip up or reroute

Test design:
  NET_A connects R1-1 (9250, 10000) to C1-1 (49250, 10000) on smd_test_board.
  The natural route is a near-direct horizontal line at y~10000.
  We pre-route NET_A as a deliberately suboptimal U-detour that climbs to
  y=7000, spans the top, and descends. If the lock is honored, the SES output
  preserves the U-path (y_min ~7000). If ignored, the SES shows Freerouting's
  own direct route (y_min ~8500-10000).
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

import pytest

from volta.routing.freerouting import is_freerouting_available

pytestmark = pytest.mark.slow

_BASE_DSN = (
    Path(__file__).parent
    / "fixtures"
    / "freerouting"
    / "smd_test_board.dsn"
)
_JAR = Path.home() / ".volta" / "tools" / "freerouting.jar"
_BATCH_DIR = Path(__file__).resolve().parents[1] / "src" / "volta" / "routing"

# U-detour fixed wire for NET_A: up to y=7000, across, back down.
# Geometrically worse than the direct route, so survival proves the lock holds.
_FIX_WIRE = (
    '(wire (path F.Cu 250  9250 10000  9250 7000  49250 7000  49250 10000) '
    '(net "NET_A") {lock_type})'
)


def _skip_if_no_freerouting() -> None:
    if not is_freerouting_available():
        pytest.skip("Freerouting JAR or Java runtime not available")


def _inject_wiring(dsn_text: str, lock_type: str) -> str:
    """Insert (wiring ...) block after (network ...) closes, before final )."""
    wiring_block = f"\n  (wiring\n    {_FIX_WIRE.format(lock_type=lock_type)}\n  )\n"
    stripped = dsn_text.rstrip()
    last_close = stripped.rfind(")")
    return stripped[:last_close] + wiring_block + ")\n"


def _run_freerouting(dsn_path: Path, ses_path: Path, max_passes: int = 5) -> str:
    """Run FreerouteBatch on a DSN, return SES text."""
    cmd = [
        "java", "-Djava.awt.headless=true",
        "-cp", f"{_JAR}:{_BATCH_DIR}",
        "FreerouteBatch",
        str(dsn_path), str(ses_path), str(max_passes), "none",
    ]
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    assert result.returncode in (0, 1), (
        f"Freerouting exit {result.returncode}\nstderr: {result.stderr[:500]}"
    )
    assert ses_path.exists(), f"No SES produced\nstdout: {result.stdout[:500]}"
    return ses_path.read_text()


def _parse_ses_wires(ses_text: str) -> list[dict]:
    """Parse (wire ...) blocks from SES. Return list of {net, layer, coords}."""
    wires: list[dict] = []
    wire_re = re.compile(
        r"\(wire\s+\(polyline_path\s+(\S+)\s+([\d.]+)\s+(.*?)\)\s*"
        r'\(net\s+(?:"([^"]+)"|(\S+))\s+\d+\)',
        re.DOTALL,
    )
    for m in wire_re.finditer(ses_text):
        layer = m.group(1)
        coords_str = m.group(3).strip()
        net = m.group(4) or m.group(5)
        nums = re.findall(r"[-]?\d+\.?\d*", coords_str)
        coords = [
            (float(nums[i]), float(nums[i + 1]))
            for i in range(0, len(nums) - 1, 2)
        ]
        wires.append({"net": net, "layer": layer, "coords": coords})
    return wires


def _net_a_min_y(wires: list[dict]) -> float | None:
    """Return the minimum Y of NET_A wires, or None if unrouted."""
    ys = [
        y
        for w in wires
        if w["net"] == "NET_A"
        for _, y in w["coords"]
    ]
    return min(ys) if ys else None


@pytest.fixture
def workdir(tmp_path: Path) -> Path:
    return tmp_path


@pytest.fixture
def control_ses(workdir: Path) -> str:
    """Route the base board with no fixed wire — Freerouting's own choice."""
    _skip_if_no_freerouting()
    dsn = workdir / "control.dsn"
    ses = workdir / "control.ses"
    shutil.copy(_BASE_DSN, dsn)
    return _run_freerouting(dsn, ses)


@pytest.fixture
def fix_ses(workdir: Path) -> str:
    """Route with NET_A pre-routed as (type fix)."""
    _skip_if_no_freerouting()
    dsn = workdir / "type_fix.dsn"
    ses = workdir / "type_fix.ses"
    dsn.write_text(_inject_wiring(_BASE_DSN.read_text(), "(type fix)"))
    return _run_freerouting(dsn, ses)


@pytest.fixture
def protect_ses(workdir: Path) -> str:
    """Route with NET_A pre-routed as (type protect)."""
    _skip_if_no_freerouting()
    dsn = workdir / "type_protect.dsn"
    ses = workdir / "type_protect.ses"
    dsn.write_text(_inject_wiring(_BASE_DSN.read_text(), "(type protect)"))
    return _run_freerouting(dsn, ses)


class TestTypeFixHonored:
    """R-1: Freerouting honors Specctra wire locking directives."""

    def test_type_fix_preserves_pre_routed_wire(self, fix_ses: str) -> None:
        """(type fix) wire survives — router does not rip it up."""
        wires = _parse_ses_wires(fix_ses)
        net_a_min = _net_a_min_y(wires)
        assert net_a_min is not None, "NET_A not routed in output"
        # The U-detour climbs to y=7000. If honored, min_y stays near 7000.
        assert net_a_min < 8500, (
            f"NET_A min_y={net_a_min} — (type fix) IGNORED "
            f"(wire was rerouted to a direct path)"
        )

    def test_type_protect_preserves_pre_routed_wire(self, protect_ses: str) -> None:
        """(type protect) wire survives — router does not rip it up."""
        wires = _parse_ses_wires(protect_ses)
        net_a_min = _net_a_min_y(wires)
        assert net_a_min is not None, "NET_A not routed in output"
        assert net_a_min < 8500, (
            f"NET_A min_y={net_a_min} — (type protect) IGNORED "
            f"(wire was rerouted to a direct path)"
        )

    def test_control_routs_net_a(self, control_ses: str) -> None:
        """Sanity: control run routes NET_A (baseline for comparison)."""
        wires = _parse_ses_wires(control_ses)
        net_a_min = _net_a_min_y(wires)
        assert net_a_min is not None, "NET_A not routed in control"

    def test_fix_diverges_from_control(self, fix_ses: str, control_ses: str) -> None:
        """The fixed-wire path must differ from Freerouting's own choice.

        This is the core signal: if (type fix) is honored, the fixed U-detour
        survives; if ignored, both runs produce the same direct route.
        """
        fix_min = _net_a_min_y(_parse_ses_wires(fix_ses))
        ctrl_min = _net_a_min_y(_parse_ses_wires(control_ses))
        assert fix_min is not None and ctrl_min is not None
        # Fixed path goes to y=7000; control stays near y=8500-10000.
        # They must diverge by at least 500um to prove the fix survived.
        assert abs(fix_min - ctrl_min) > 500, (
            f"fix_min={fix_min} vs ctrl_min={ctrl_min} — paths identical, "
            f"(type fix) had no effect (likely ignored)"
        )
