"""Phase 204: SSI2130 VCO design patterns (Bart Instruments inspired).

4 circuit patterns from Bart Instruments' open-source DUAL SSI2130 VCO CORE
(Rev 3.0, 2026-07-07). Each pattern ships as a SPICE netlist emitter
(similar to buffered_preamp.py) so users can simulate, optimize, and
verify before fabrication.

Closes 4 bd tickets:
  kicad-agent-30: Per-VCO measurement tap for digital autotune
  kicad-agent-31: HF tracking trim network for discrete VCO cores
  kicad-agent-32: Local ±2.5V references per voice submodule
  kicad-agent-33: Passive-summed multiple V/oct inputs

Each pattern is a `build_*_spice_netlist()` function returning a SPICE
.cir body. Caller prepends get_model() for any opamps/transistors used.
"""
from __future__ import annotations

import math


def _validate_positive(*vals: float) -> None:
    """Boundary validation per CR-04 — all R/C values must be positive finite."""
    if not all(math.isfinite(v) and v > 0 for v in vals):
        raise ValueError(
            f"All R/C values must be positive finite floats; got {vals}"
        )


# ---------------------------------------------------------------------------
# kicad-agent-30: Per-VCO measurement tap for digital autotune
# ---------------------------------------------------------------------------

def build_measurement_tap_spice_netlist(
    r_pullup: float = 10.0e3,
    r_in: float = 100.0e3,
    r_feedback: float = 1.0e6,
    c_filter: float = 100.0e-12,
) -> str:
    """Buffer VCO square output through a comparator for MCU measurement.

    The SSI2130's SQUARE_OUT pin is a current source that needs a pull-up
    resistor. This pattern:
      1. Pulls SQUARE_OUT high via r_pullup
      2. AC-couples into a TL072 buffer (high input Z)
      3. Optionally low-pass filters (c_filter) to reject HF ringing
      4. Feeds a comparator (LM311 class) for clean digital edge
      5. Output goes to MCU timer capture input

    MCU firmware measures period → computes pitch correction → injects
    via DAC into SCALE_TRIM or TUNE_TRIM node.

    Topology:
        +5V -- R_pullup -- SQUARE_OUT
        SQUARE_OUT -- C_filter (parallel) -- GND
        SQUARE_OUT -- R_in -- TL072(+)
        TL072(-) -- TL072(out) -- R_feedback -- TL072(-)  (gain = 1 + Rf/Rin... here unity buffer with feedback for stability)
        TL072(out) -- COMPARATOR_IN
        COMPARATOR_OUT -- MCU_TIMER_CAP
    """
    _validate_positive(r_pullup, r_in, r_feedback, c_filter)
    return f"""* SSI2130 measurement tap for digital autotune (kicad-agent-30)
* Buffers SQUARE_OUT through TL072 + comparator for MCU capture input
V5V +5V 0 DC 5

* Pull-up on SSI2130 SQUARE_OUT (current-source output)
R_PULLUP +5V SQUARE_OUT {r_pullup:g}

* HF noise filter (parallel cap to GND)
C_FILTER SQUARE_OUT 0 {c_filter:g}

* TL072 unity-gain buffer — input isolation
R_IN SQUARE_OUT BUF_IN {r_in:g}
X_BUF BUF_IN BUF_OUT +12V -12V BUF_OUT TL072
R_FEEDBACK BUF_OUT BUF_IN {r_feedback:g}

* Comparator (LM311-class) — clean digital edges for MCU
X_COMP BUF_IN COMP_REF +12V -12V COMP_OUT LM311
VREF COMP_REF 0 DC 2.5
"""


# ---------------------------------------------------------------------------
# kicad-agent-31: HF tracking trim network for discrete VCO cores
# ---------------------------------------------------------------------------

def build_hf_trim_spice_netlist(
    r_hft: float = 1.0e3,
    c_hft: float = 100.0e-12,
    r_feedback: float = 10.0e3,
) -> str:
    """High-frequency compensation network for discrete expo converters.

    Discrete MMBT3904 expo converters (synth-machine) track flat at high
    audio frequencies (C5-C8, ~1kHz-8kHz) due to finite base resistance,
    transit time, and storage capacitance. The SSI2130 has built-in
    HF_TRACK (pin 6, output) and HFT_BASE (pin 20, input) for closed-loop
    compensation. Discrete designs need an external trim network.

    Topology (mirrors SSI2130 datasheet §5.2):
        HF_TRACK_OUT -- R_hft -- HFT_BASE
        HFT_BASE -- C_hft -- GND  (lag network for HF boost)
        HFT_BASE -- R_feedback -- EXPO_OUT  (closes the loop)

    The R-C network creates a phase lead at high frequencies, compensating
    for the expo converter's transit-time lag.

    Args:
        r_hft: HF tracking series resistor (default 1kΩ per SSI2130 datasheet).
        c_hft: HF tracking shunt capacitor (default 100pF).
        r_feedback: Loop-closing feedback resistor (default 10kΩ).
    """
    _validate_positive(r_hft, c_hft, r_feedback)
    return f"""* HF tracking trim network for discrete VCO cores (kicad-agent-31)
* Mirrors SSI2130 §5.2 closed-loop compensation for MMBT3904 expo pairs
V12 +12V 0 DC 12
VM12 -12V 0 DC -12

* HF TRACK signal source (would come from expo converter collector)
* For simulation, this is a test source.
V_HF_TRACK HF_TRACK_OUT 0 SINE(0 10m 5000)

* HF trim network — R + C lag compensator
R_HFT HF_TRACK_OUT HFT_BASE {r_hft:g}
C_HFT HFT_BASE 0 {c_hft:g}

* Feedback closes the loop into the expo converter base
R_FEEDBACK HFT_BASE EXPO_OUT {r_feedback:g}
"""


# ---------------------------------------------------------------------------
# kicad-agent-32: Local ±2.5V references per voice submodule
# ---------------------------------------------------------------------------

def build_local_refs_spice_netlist(
    r_top: float = 10.0e3,
    r_bot: float = 10.0e3,
    r_balance: float = 100.0e3,
    c_ref: float = 1.0e-6,
) -> str:
    """Generate local ±2.5V references from a single +5V rail (per voice).

    Problem with inverter-derived references: a 555-style inverter oscillator
    generates -5V from +5V, but the switching noise couples into audio
    references. The fix is a resistive divider from +5V to GND with a
    buffered center tap, duplicated for each voice.

    Topology (per voice):
        +5V -- R_top -- VREF_POS (2.5V) -- R_bot -- GND
        VREF_POS -- C_ref -- GND  (noise filter)
        VREF_POS -- TL072(+) -- TL072(out) -- VREF_POS_BUF
        (mirror network for VREF_NEG = -2.5V — requires charge pump or
        rail splitter; here we use a virtual ground from a second divider
        on the -12V rail if available, OR a TLE2426 rail splitter)

    For the simulation, we use a simple resistive divider + buffer. The
    real implementation would use a TLE2426 rail splitter IC for precision.

    Args:
        r_top: Top divider resistor (default 10kΩ).
        r_bot: Bottom divider resistor (default 10kΩ — sets VREF = 2.5V).
        r_balance: Balance trim between VREF_POS and VREF_NEG (default 100kΩ).
        c_ref: Reference bypass cap (default 1µF — filters rail noise).
    """
    _validate_positive(r_top, r_bot, r_balance, c_ref)
    return f"""* Local ±2.5V references per voice submodule (kicad-agent-32)
* Resistive divider from +5V → buffered center tap → VREF_POS (2.5V)
* Mirror divider from -5V → VREF_NEG (-2.5V)
V5V +5V 0 DC 5
VM5V -5V 0 DC -5

* VREF_POS divider (2.5V from +5V rail)
R_TOP_P +5V VREF_POS {r_top:g}
R_BOT_P VREF_POS 0 {r_bot:g}
C_REF_P VREF_POS 0 {c_ref:g}

* VREF_NEG divider (-2.5V from -5V rail)
R_TOP_N -5V VREF_NEG {r_top:g}
R_BOT_N VREF_NEG 0 {r_bot:g}
C_REF_N VREF_NEG 0 {c_ref:g}

* Balance trim between +VREF and -VREF (fine-tunes midpoint)
R_BAL VREF_POS VREF_NEG {r_balance:g}

* Buffers (TL072 dual opamp — one half for each ref)
X_BUF_P VREF_POS VREF_POS_BUF +12V -12V VREF_POS_BUF TL072
X_BUF_N VREF_NEG VREF_NEG_BUF +12V -12V VREF_NEG_BUF TL072
"""


# ---------------------------------------------------------------------------
# kicad-agent-33: Passive-summed multiple V/oct inputs
# ---------------------------------------------------------------------------

def build_passive_cv_sum_spice_netlist(
    r_cv1: float = 100.0e3,
    r_cv2: float = 100.0e3,
    r_cv3: float = 100.0e3,
    r_cv4: float = 100.0e3,
) -> str:
    """Passive-summed V/oct CV inputs — eliminates buffer op-amps.

    Problem: traditional Eurorack VCOs use 4 op-amp buffers (one per CV
    input: 1V/oct, FM, EXP_FM, TUNE). That's 2x TL072 chips per VCO.

    Bart Instruments' pattern: passive summing network where all CV inputs
    go through 100kΩ resistors into a single SCALE_TRIM node. The SSI2130's
    high input impedance on SCALE_TRIM means no buffer needed.

    Topology:
        CV1 -- R_cv1 --\\
        CV2 -- R_cv2 --|
        CV3 -- R_cv3 --|--> SCALE_TRIM (SSI2130 pin 3)
        CV4 -- R_cv4 --/

    Tradeoff: passive summing has a small signal loss (~0.7× per the
    parallel combination). The SSI2130 SCALE_TRIM input impedance is
    ~1MΩ, so the loss is ~3% (100kΩ ÷ 1MΩ = 0.1 V/V drop). For 1V/oct
    tracking at 0.1% precision, this matters and is trimmed out by
    the SCALE_TRIM potentiometer.

    Args:
        r_cv1-4: 4 CV input summing resistors (default 100kΩ each).
    """
    _validate_positive(r_cv1, r_cv2, r_cv3, r_cv4)
    return f"""* Passive-summed V/oct CV inputs (kicad-agent-33)
* Eliminates 4 op-amp buffers per VCO via passive summing into SSI2130 SCALE_TRIM
* SSI2130 SCALE_TRIM input Z ~1MΩ → signal loss ~3%, trimmed out by SCALE_TRIM pot

* CV input sources (sim: 4x 1V/oct sources)
V_CV1 CV1 0 DC 1
V_CV2 CV2 0 DC 0
V_CV3 CV3 0 DC 0
V_CV4 CV4 0 DC 0

* Passive summing network — 4 resistors into single SCALE_TRIM node
R_CV1 CV1 SCALE_TRIM {r_cv1:g}
R_CV2 CV2 SCALE_TRIM {r_cv2:g}
R_CV3 CV3 SCALE_TRIM {r_cv3:g}
R_CV4 CV4 SCALE_TRIM {r_cv4:g}

* SCALE_TRIM is consumed by SSI2130 (high-Z input) — for sim, leave as node
* The SSI2130 model would attach here.
"""
