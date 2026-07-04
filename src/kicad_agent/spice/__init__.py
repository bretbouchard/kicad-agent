"""Phase 158: SPICE pipeline — ngspice integration.

Headless, scriptable simulation pipeline: SKIDL Circuit → ngspice →
structured JSON results. Serves as a reward signal for AI training (Phase 159).
"""
from kicad_agent.spice.types import (
    AnalysisResult,
    AnalysisType,
    DegradationReport,
    SimulationResult,
    Trace,
)
from kicad_agent.spice.ngspice_runner import run_simulation
from kicad_agent.spice.testbench import (
    generate_ac_testbench,
    generate_tran_testbench,
    generate_noise_testbench,
    generate_thd_testbench,
    generate_testbench,
)
from kicad_agent.spice.model_registry import (
    get_model,
    is_simulatable,
    get_all_models,
    UNSIMULATABLE,
)
from kicad_agent.spice.degradation import compute_degradation

__all__ = [
    "AnalysisResult",
    "AnalysisType",
    "DegradationReport",
    "SimulationResult",
    "Trace",
    "run_simulation",
    "generate_ac_testbench",
    "generate_tran_testbench",
    "generate_noise_testbench",
    "generate_thd_testbench",
    "generate_testbench",
    "get_model",
    "is_simulatable",
    "get_all_models",
    "UNSIMULATABLE",
    "compute_degradation",
]
