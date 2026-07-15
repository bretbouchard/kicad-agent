"""Phase 158: SPICE testbench generators.

Generates .cir testbenches for AC, transient, noise, and THD analysis
from a SKIDL CircuitIR or raw netlist.
"""
from __future__ import annotations

from volta.spice.types import AnalysisType


def generate_ac_testbench(
    netlist: str,
    input_node: str = "in",
    output_node: str = "out",
    freq_start: float = 1.0,
    freq_stop: float = 1e9,
    points_per_decade: int = 50,
    output_load_ohms: float = 100e3,
    include_op: bool = True,
) -> str:
    """Generate an AC analysis testbench.

    Args:
        netlist: SPICE netlist (from skidl generate_netlist or manual).
        input_node: Input node name for stimulus.
        output_node: Output node name for measurement.
        freq_start: Start frequency in Hz.
        freq_stop: Stop frequency in Hz. Default 1 GHz — wide enough to
            capture the high-frequency roll-off of a typical CE preamp
            (2N3904 fT ~300 MHz; CE bandwidth lands in the 1-50 MHz range).
            A 1 MHz ceiling leaves the -3 dB point "out of interval" for
            ngspice's .MEASURE WHEN, which then returns no bandwidth.
        points_per_decade: Number of points per decade.
        output_load_ohms: Load resistor from output_node to ground (Ohms).
            Default 100 kΩ. Required when the output is AC-coupled via a
            series capacitor — without a DC path to ground, ngspice reports
            "singular matrix: check node <out>" because the output node
            floats at DC.
        include_op: Also run .OP (operating point) analysis. Default True
            per kicad-agent-8vv fix — produces a second "Operating Point"
            plot in the .raw file with node voltages + supply currents.
            _parse_ac extracts i(vcc) as the measured collector current,
            replacing the optimizer's heuristic. Set False for pure AC
            analysis where OP data isn't needed.

    Returns:
        Complete .cir file content.
    """
    op_line = "\n.OP\n" if include_op else ""
    return f"""* AC Analysis Testbench
* Input: {input_node}, Output: {output_node}

{netlist}

* AC stimulus
VAC_IN {input_node} 0 DC 0 AC 1

* Output load — DC path to ground for AC-coupled outputs (fixes
* singular-matrix convergence failure on coupling-cap topologies).
RLOAD {output_node} 0 {output_load_ohms:g}

* AC analysis: {freq_start:.1f}Hz to {freq_stop:.0f}Hz
.AC DEC {points_per_decade} {freq_start} {freq_stop}
{op_line}
* Control block: compute gain and bandwidth from AC results
* ngspice's .MEASURE WHEN clause cannot reference prior measurement
* results, so we use the control language to compute the -3dB threshold.
.CONTROL
run
let gain_vector = vdb({output_node})
let gain_max = maximum(gain_vector)
let threshold = gain_max - 3.0
meas ac gain_db MAX gain_vector
meas ac bw_3db when gain_vector=threshold fall=1
.ENDC

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
