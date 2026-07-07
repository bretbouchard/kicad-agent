"""Phase 204: Closed-box simulation layer.

Optimization, dataframe adapter, BOM emit, Bode plot, and the Eurorack canonical
example. Built on top of Phase 158's src/kicad_agent/spice/ foundation.
"""
from kicad_agent.sim.eurorack import build_preamp_circuit, circuit_to_spice_netlist

__all__ = [
    "build_preamp_circuit",
    "circuit_to_spice_netlist",
]
