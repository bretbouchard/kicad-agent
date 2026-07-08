"""Phase 204 w1f fix: JFET-input buffered Eurorack preamp.

The original CE preamp in eurorack.py has input impedance ~R2‖R3 ≈ 8.7 kΩ
(bias network). Real ~1 MΩ high-Z input for guitar/synth pickups requires
either a JFET-input opamp buffer in front, OR a discrete JFET source
follower.

This module ships a TL072-buffered CE preamp topology. TL072 has JFET
inputs with input bias current ~65 pA and input impedance ~10^12 Ω —
effectively infinite for audio purposes. Input Z is set by R_BIAS = 1 MΩ
to ground at the buffer's non-inverting input.

Topology:
    +12V --R1-- collector
                  |
                  Q1
                  |
    +12V --R2-- base --R3-- GND
    emitter --R4-- GND
    emitter --C_emitter-- GND

    Input stage (NEW):
    in -- R_BIAS (1M) -- GND       (sets input Z)
    in -- TL072(+in)               (JFET-input opamp buffer)
    TL072(-in) -- TL072(out)       (unity-gain feedback)
    TL072(out) -- C_in -- base     (couples into existing CE stage)
    collector -- C_out -- out

Why this works:
- TL072 input impedance ~10^12 Ω >> R_BIAS (1 MΩ)
- AC input current flows almost entirely through R_BIAS
- Input Z = R_BIAS = 1 MΩ by construction
- CE preamp gain, bias, bandwidth unchanged from build_preamp_circuit

This module emits SPICE directly (no skidl.Circuit) because skidl's symbol
library doesn't ship TL072 as a Part with the right SPICE subckt pins.
The TL072 macromodel from src/kicad_agent/spice/model_registry.py is
concatenated to the netlist by the caller via get_model("TL072").
"""
from __future__ import annotations

import math
from typing import Any


def build_buffered_preamp_spice_netlist(
    r_bias: float = 1.0e6,
    r1: float = 4.7e3,
    r2: float = 68.0e3,
    r3: float = 10.0e3,
    r4: float = 470.0,
    c_in: float = 10.0e-6,
    c_out: float = 1.0e-6,
    c_emitter: float = 100.0e-6,
) -> str:
    """Emit SPICE netlist for TL072-buffered CE preamp.

    Args:
        r_bias: Input bias resistor to GND (sets input Z). Default 1 MΩ.
        r1-r4, c_in, c_out, c_emitter: CE preamp component values (same
            role as in eurorack.build_preamp_circuit).

    Returns:
        SPICE netlist body as a string (no .MODEL — caller must prepend
        get_model("TL072") + get_model("2N3904") before simulation).

    Raises:
        ValueError: if any value is non-finite or non-positive (CR-04
            boundary validation per coding-style.md).
    """
    if not all(math.isfinite(v) and v > 0 for v in (r_bias, r1, r2, r3, r4, c_in, c_out, c_emitter)):
        raise ValueError(
            f"All R/C values must be positive finite floats; got "
            f"r_bias={r_bias}, r1={r1}, r2={r2}, r3={r3}, r4={r4}, "
            f"c_in={c_in}, c_out={c_out}, c_emitter={c_emitter}"
        )

    return f"""* TL072-buffered CE preamp (kicad-agent-w1f)
* Input Z = R_BIAS = {_sci(r_bias)} (TL072 JFET input Z ~10^12 Ω)
VCC +12V 0 DC 12
VEE -12V 0 DC -12

* Input stage — TL072 unity-gain buffer
R_BIAS in 0 {r_bias:g}
* TL072 subckt signature: X<n> IN+ IN- VCC VEE OUT NAME (per model_registry)
* Unity-gain buffer: IN- = OUT for feedback.
X_BUF in out_buf +12V -12V out_buf TL072

* Coupling cap into CE preamp base
C1 out_buf base {c_in:g}

* CE preamp (same topology as build_preamp_circuit)
Q1 collector base emitter 2N3904
R1 collector +12V {r1:g}
R2 base +12V {r2:g}
R3 base 0 {r3:g}
R4 emitter 0 {r4:g}
C2 collector out {c_out:g}
C3 emitter 0 {c_emitter:g}
"""


def _sci(v: float) -> str:
    """Format a float in SPICE engineering notation (mirror of eurorack._sci)."""
    if v >= 1e12: return f"{v/1e12:g}T"
    if v >= 1e9:  return f"{v/1e9:g}G"
    if v >= 1e6:  return f"{v/1e6:g}Meg"
    if v >= 1e3:  return f"{v/1e3:g}k"
    if v >= 1:    return f"{v:g}"
    if v >= 1e-3: return f"{v*1e3:g}m"
    if v >= 1e-6: return f"{v*1e6:g}u"
    if v >= 1e-9: return f"{v*1e9:g}n"
    return f"{v*1e12:g}p"


def compute_input_impedance_kohm(
    r_bias: float = 1.0e6,
    tl072_input_z_ohm: float = 1.0e12,
) -> float:
    """Compute input Z from R_BIAS and TL072 input Z (parallel combination).

    For TL072 input Z = 10^12 Ω and R_BIAS = 10^6 Ω:
        Z_in = R_BIAS || TL072_input_Z ≈ R_BIAS (TL072 contributes <0.1%)

    Args:
        r_bias: Input bias resistor value in Ohms.
        tl072_input_z_ohm: TL072 datasheet input impedance (default 10^12).

    Returns:
        Input impedance in kΩ.
    """
    z_parallel = (r_bias * tl072_input_z_ohm) / (r_bias + tl072_input_z_ohm)
    return z_parallel / 1000.0
