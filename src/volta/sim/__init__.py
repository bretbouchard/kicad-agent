"""Phase 204: Closed-box simulation layer.

Optimization, dataframe adapter, BOM emit, Bode plot, and the Eurorack canonical
example. Built on top of Phase 158's src/volta/spice/ foundation.
"""
from volta.sim.eurorack import build_preamp_circuit, circuit_to_spice_netlist
from volta.sim.dataframe import to_dataframe, study_to_dataframe
from volta.sim.bom import circuit_to_bom_markdown
from volta.sim.plot import plot_bode
from volta.sim.optimizer import objective, optimize_preamp

__all__ = [
    "build_preamp_circuit",
    "circuit_to_spice_netlist",
    "to_dataframe",
    "study_to_dataframe",
    "circuit_to_bom_markdown",
    "plot_bode",
    "objective",
    "optimize_preamp",
]
