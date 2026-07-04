"""Phase 158: SPICE testbench generators.

Generates .cir testbenches for AC, transient, noise, and THD analysis
from a SKIDL CircuitIR or raw netlist.
"""
from __future__ import annotations

from kicad_agent.spice.types import AnalysisType


def generate_ac_testbench(
    netlist: str,
    input_node: str = "in",
    output_node: str = "out",
    freq_start: float = 1.0,
    freq_stop: float = 10e6,
    points_per_decade: int = 50,
) -> str:
    """Generate an AC analysis testbench.

    Args:
        netlist: SPICE netlist (from skidl generate_netlist or manual).
        input_node: Input node name for stimulus.
        output_node: Output node name for measurement.
        freq_start: Start frequency in Hz.
        freq_stop: Stop frequency in Hz.
        points_per_decade: Number of points per decade.

    Returns:
        Complete .cir file content.
    """
    return f"""* AC Analysis Testbench
* Input: {input_node}, Output: {output_node}

{netlist}

* AC stimulus
VAC_IN {input_node} 0 DC 0 AC 1

* AC analysis: {freq_start:.1f}Hz to {freq_stop:.0f}Hz
.AC DEC {points_per_decade} {freq_start} {freq_stop}

* Measure gain
.MEAS AC gain_db MAX vdb({output_node})
* Measure bandwidth (-3dB point)
.MEAS AC bandwidth WHEN vdb({output_node})='gain_db-3' FALL=1

.PRINT AC vdb({output_node}) vp({output_node})

.END
"""


def generate_tran_testbench(
    netlist: str,
    input_node: str = "in",
    output_node: str = "out",
    duration: float = 1e-3,
    step: float = 1e-6,
    amplitude: float = 1.0,
    freq: float = 1000.0,
) -> str:
    """Generate a transient analysis testbench.

    Args:
        netlist: SPICE netlist.
        input_node: Input node for stimulus.
        output_node: Output node for measurement.
        duration: Simulation duration in seconds.
        step: Time step in seconds.
        amplitude: Input sine wave amplitude in Volts.
        freq: Input sine wave frequency in Hz.

    Returns:
        Complete .cir file content.
    """
    return f"""* Transient Analysis Testbench
* Input: {input_node}, Output: {output_node}

{netlist}

* Sine wave stimulus
VSIN_IN {input_node} 0 SINE(0 {amplitude} {freq})

* Transient analysis
.TRAN {step} {duration}

* Measure step response characteristics
.MEAS TRAN vout_max MAX v({output_node})
.MEAS TRAN vout_min MIN v({output_node})

.PRINT TRAN v({input_node}) v({output_node})

.END
"""


def generate_noise_testbench(
    netlist: str,
    input_node: str = "in",
    output_node: str = "out",
    freq_start: float = 10.0,
    freq_stop: float = 100e3,
    points_per_decade: int = 30,
) -> str:
    """Generate a noise analysis testbench.

    Args:
        netlist: SPICE netlist.
        input_node: Input node (noise reference).
        output_node: Output node for noise measurement.

    Returns:
        Complete .cir file content.
    """
    return f"""* Noise Analysis Testbench
* Input: {input_node}, Output: {output_node}

{netlist}

* AC input for noise analysis
VAC_IN {input_node} 0 DC 0 AC 1

* Noise analysis
.NOISE V({output_node}) VAC_IN DEC {points_per_decade} {freq_start} {freq_stop}

* Measure total integrated noise
.MEAS NOISE onoise_total INTEG onoise

.PRINT NOISE onoise inoise

.END
"""


def generate_thd_testbench(
    netlist: str,
    input_node: str = "in",
    output_node: str = "out",
    freq: float = 1000.0,
    amplitude: float = 1.0,
    duration: float = 10e-3,
    step: float = 1e-6,
) -> str:
    """Generate a THD (Total Harmonic Distortion) testbench.

    Uses transient analysis + Fourier analysis.

    Args:
        netlist: SPICE netlist.
        input_node: Input node.
        output_node: Output node.
        freq: Fundamental frequency in Hz.
        amplitude: Input amplitude.

    Returns:
        Complete .cir file content.
    """
    return f"""* THD Analysis Testbench
* Input: {input_node} ({freq}Hz sine), Output: {output_node}

{netlist}

* Sine wave stimulus
VSIN_IN {input_node} 0 SINE(0 {amplitude} {freq})

* Transient + Fourier analysis
.TRAN {step} {duration} 0 {step}
.FOUR {freq} v({output_node})

.PRINT TRAN v({output_node})

.END
"""


def generate_testbench(
    netlist: str,
    analysis_type: AnalysisType | str,
    **kwargs,
) -> str:
    """Generate a testbench for any analysis type.

    Args:
        netlist: SPICE netlist.
        analysis_type: AC, TRAN, NOISE, or DISTO.
        **kwargs: Analysis-specific parameters.

    Returns:
        Complete .cir file content.
    """
    if isinstance(analysis_type, str):
        analysis_type = AnalysisType(analysis_type)

    if analysis_type == AnalysisType.AC:
        return generate_ac_testbench(netlist, **kwargs)
    elif analysis_type == AnalysisType.TRAN:
        return generate_tran_testbench(netlist, **kwargs)
    elif analysis_type == AnalysisType.NOISE:
        return generate_noise_testbench(netlist, **kwargs)
    elif analysis_type == AnalysisType.DISTO:
        return generate_thd_testbench(netlist, **kwargs)
    else:
        raise ValueError(f"Unsupported analysis type: {analysis_type}")
