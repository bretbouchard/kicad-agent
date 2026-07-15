"""Phase 204: Eurorack CE preamp circuit builder + SPICE netlist emitter.

The primary new capability: convert a skidl.Circuit into a SPICE netlist.
skidl 2.2.3's circuit.generate_netlist() emits KiCad .net format, NOT SPICE.
This module bridges skidl → ngspice.
"""
from __future__ import annotations

import math
from typing import Any

# CR-01 (Council R2 P0): Phase 156 pitfall #6 guard — KICAD_SYMBOL_DIR must be
# set BEFORE the first skidl symbol lookup, otherwise skidl silently produces
# no-pin Parts (see src/volta/circuit_ir/__init__.py). The guard runs at
# module import so any downstream `import skidl` resolves symbols correctly.
from volta.circuit_ir import _ensure_skidl_env
_ensure_skidl_env()

# Pin ordering per SPICE convention (ngspice manual v46 §3.3, §7.3.1).
# R/C: n+ n- ; Q: collector base emitter [substrate] modelname.
_PIN_ORDER: dict[str, tuple[Any, ...]] = {
    "R": (1, 2),
    "C": (1, 2),
    "Q": ("C", "B", "E"),
}
_POWER_RAILS = ("+12V", "-12V")  # GND is mapped to 0, not emitted as .GLOBAL


def build_preamp_circuit(
    r1: float,
    r2: float,
    r3: float,
    r4: float,
    c_in: float,
    c_out: float,
    c_emitter: float,
) -> Any:
    """Build a Eurorack common-emitter preamp as a skidl.Circuit.

    Topology (2N3904, ±12 V rails, audio bandwidth):
        +12V --R1-- collector
                      |
                      Q1
                      |
        +12V --R2-- base --R3-- GND
        in --C_in-- base
        collector --C_out-- out
        emitter --R4-- GND
        emitter --C_emitter-- GND

    Args:
        r1: Collector load (Ohms).
        r2: Base bias upper (Ohms).
        r3: Base bias lower (Ohms).
        r4: Emitter degeneration (Ohms).
        c_in: Input coupling (Farads).
        c_out: Output coupling (Farads).
        c_emitter: Emitter bypass (Farads).

    Returns:
        Live skidl.Circuit (context manager has exited; ckt.parts is iterable).

    Raises:
        ValueError: if any R/C value is non-finite or non-positive (CR-04 R2).
    """
    # CR-04 (Council R2 P1): validate at function boundary per coding-style.md.
    # Defense-in-depth so _sci(nan) -> "nan" never reaches the SPICE netlist.
    if not all(
        math.isfinite(v) and v > 0
        for v in (r1, r2, r3, r4, c_in, c_out, c_emitter)
    ):
        raise ValueError(
            f"All R/C values must be positive finite floats; got "
            f"r1={r1}, r2={r2}, r3={r3}, r4={r4}, "
            f"c_in={c_in}, c_out={c_out}, c_emitter={c_emitter}"
        )

    # CR-01 (Council R2 P0): re-ensure env on EVERY call so callers that
    # unset KICAD_SYMBOL_DIR between calls still get correct symbol lookup.
    # (Module-top guard covers first import; this covers subsequent calls.)
    _ensure_skidl_env()

    import skidl

    with skidl.Circuit() as ckt:
        ckt.name = "eurorack_preamp"
        vcc = skidl.Net("+12V")
        vee = skidl.Net("-12V")
        gnd = skidl.Net("GND")
        nin = skidl.Net("in")
        nout = skidl.Net("out")
        nbase = skidl.Net("base")
        ncol = skidl.Net("collector")
        nemit = skidl.Net("emitter")

        # Transistor (Device:Q_NPN — pins B/C/E by name AND number, verified)
        q1 = skidl.Part("Device", "Q_NPN", value="2N3904")
        q1.ref = "Q1"
        q1["B"] += nbase
        q1["C"] += ncol
        q1["E"] += nemit

        # Bias network
        r1p = skidl.Part("Device", "R", value=r1); r1p.ref = "R1"
        r1p[1] += vcc; r1p[2] += ncol

        r2p = skidl.Part("Device", "R", value=r2); r2p.ref = "R2"
        r2p[1] += vcc; r2p[2] += nbase

        r3p = skidl.Part("Device", "R", value=r3); r3p.ref = "R3"
        r3p[1] += nbase; r3p[2] += gnd

        r4p = skidl.Part("Device", "R", value=r4); r4p.ref = "R4"
        r4p[1] += nemit; r4p[2] += gnd

        # Coupling + bypass caps
        cin = skidl.Part("Device", "C", value=c_in); cin.ref = "C1"
        cin[1] += nin; cin[2] += nbase

        cout = skidl.Part("Device", "C", value=c_out); cout.ref = "C2"
        cout[1] += ncol; cout[2] += nout

        cemit = skidl.Part("Device", "C", value=c_emitter); cemit.ref = "C3"
        cemit[1] += nemit; cemit[2] += gnd

    return ckt


def circuit_to_spice_netlist(circuit: Any) -> str:
    """Emit SPICE .cir device lines from a skidl.Circuit.

    Walks circuit.parts; emits one SPICE line per resistor/capacitor/transistor.
    Power rails (+12V, -12V) become .GLOBAL nodes; GND becomes node 0
    (ngspice manual v46 §2.1.3.5 requires ground to be named '0').

    Power supply voltage sources (VCC/VEE) are emitted before the .GLOBAL
    declarations. The skidl.Circuit references +12V/-12V as Net names but
    does not declare voltage source Parts for them — without VCC/VEE sources
    the rails float, the transistor has no bias, and gain_db collapses to
    ~0 dB. Phase 204 fix.

    Args:
        circuit: Live skidl.Circuit (built via build_preamp_circuit or equivalent).

    Returns:
        SPICE netlist body as a string. No .END — caller (generate_ac_testbench)
        adds it.
    """
    # Power supply sources for the declared rails. Without these, ngspice
    # reports "singular matrix" and the bias network produces 0 V everywhere.
    supply_lines: list[str] = [
        "VCC +12V 0 DC 12",
        "VEE -12V 0 DC -12",
    ]
    lines: list[str] = supply_lines + [f".GLOBAL {rail}" for rail in _POWER_RAILS]

    for part in circuit.parts:
        first_letter = part.ref[0].upper()
        if first_letter not in _PIN_ORDER:
            continue  # skip power symbols / unknown part types

        node_names: list[str] = []
        for pin_key in _PIN_ORDER[first_letter]:
            pin = part[pin_key]
            # A pin can be on multiple nets; take the first named, non-NC.
            for net in pin.nets:
                nm = net.name
                if nm == "NC":
                    continue
                # GND → 0 per ngspice convention; other nets keep their name.
                node_names.append("0" if nm.upper() == "GND" else nm)
                break

        if first_letter == "Q":
            # Transistor: model name is part.value (e.g. "2N3904")
            line = f"{part.ref} {' '.join(node_names)} {part.value}"
        else:
            # Passive: value formatted via _sci (e.g. "4.7k", "10u")
            line = f"{part.ref} {' '.join(node_names)} {_sci(float(part.value))}"

        lines.append(line)

    return "\n".join(lines)


def _sci(v: float) -> str:
    """Format a float in SPICE engineering notation.

    ngspice scale factors (manual v46 §2.1.3.2):
        T=10^12, G=10^9, Meg=10^6, K/k=10^3, m/M=10^-3, u=10^-6,
        n=10^-9, p=10^-12, f=10^-15
    Note: 'F'/'f' = femto, NOT Farad. Use 'm' (milli) carefully (case-insensitive).
    We use Meg for mega to avoid ambiguity.
    """
    if v >= 1e12: return f"{v/1e12:g}T"
    if v >= 1e9:  return f"{v/1e9:g}G"
    if v >= 1e6:  return f"{v/1e6:g}Meg"
    if v >= 1e3:  return f"{v/1e3:g}k"
    if v >= 1:    return f"{v:g}"
    if v >= 1e-3: return f"{v*1e3:g}m"
    if v >= 1e-6: return f"{v*1e6:g}u"
    if v >= 1e-9: return f"{v*1e9:g}n"
    return f"{v*1e12:g}p"
