"""Phase 204: shared fixtures for tests/sim/.

BLK-1 strict: ngspice is a hard requirement. We DO NOT pytest.skip()
when it's missing — we pytest.fail() with an actionable message.
"""
from __future__ import annotations

import shutil
from typing import Any

import pytest


@pytest.fixture(scope="session", autouse=True)
def _require_ngspice() -> None:
    """Fail every test in tests/sim/ loudly if ngspice CLI is not on PATH.

    Install with:
      macOS:  brew install ngspice
      Linux:  apt install ngspice  (or dnf install ngspice)
    """
    if shutil.which("ngspice") is None:
        pytest.fail(
            "ngspice CLI not found on PATH. "
            "Install with: brew install ngspice (macOS) or apt install ngspice (Linux). "
            "Phase 204 tests/sim/ require ngspice to produce real simulation results "
            "(BLK-1 strict — no skip-guards).",
            pytrace=False,
        )


@pytest.fixture(scope="session")
def eurorack_preamp() -> tuple[Any, Any]:
    """Build + sim the canonical Eurorack preamp ONCE per session.

    BLK-1 strict — no skip-guards. Returns (circuit, SimulationResult).
    Starting values chosen so the circuit simulates successfully — gain may
    exceed 20 dB with full emitter bypass (C_emitter=100uF at audio band ≈
    1.6Ω, so R1/re ≈ 47 dB); the optimizer (Plan 03) will refine these down
    toward the 20 dB target. See council CR-03 (R2 P1) + test_fixture_gain_
    matches_hand_calc which bounds gain to 17..55 dB.
    """
    from kicad_agent.sim.eurorack import build_preamp_circuit, circuit_to_spice_netlist
    from kicad_agent.spice import (
        generate_ac_testbench, get_model, run_simulation,
    )

    circuit = build_preamp_circuit(
        r1=4.7e3, r2=68e3, r3=10e3, r4=470,
        c_in=10e-6, c_out=10e-6, c_emitter=100e-6,
    )
    model = get_model("2N3904")
    assert model is not None, "2N3904 model not in registry — run Plan 01 Task 2"
    netlist = model + "\n" + circuit_to_spice_netlist(circuit)
    cir = generate_ac_testbench(
        netlist=netlist,
        input_node="in",
        output_node="out",
        freq_start=10.0,
        freq_stop=1e9,
        points_per_decade=50,
    )
    result = run_simulation(cir, "eurorack_preamp", analyses=["ac"])
    return circuit, result
