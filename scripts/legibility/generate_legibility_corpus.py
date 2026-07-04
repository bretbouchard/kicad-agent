"""Generate a schematic test corpus spanning small/medium/large complexity.

Each generator builds a skidl.Circuit using the module-level skidl API
(skidl.Part / skidl.Net inside a `with circuit:` context). The harness
converts these to .kicad_sch and then runs the full autolayout pipeline.

Complexity tiers:
  S1  led_bringer        — 3 parts, 2 nets        (trivial)
  S2  rc_filter          — 2 parts, 1 net          (minimal)
  S3  opamp_preamp       — 5 parts, 4 nets         (small, signal flow + feedback)
  S4  audio_mixer        — 12 parts, 10 nets       (medium, opamp + passives)
  S5  esp32_breakout     — 25 parts, 30 nets       (medium-large, MCU + headers)
  S6  arduino_mega_real  — 161 parts               (existing fixture, large)
"""
from __future__ import annotations

import os
from pathlib import Path

import skidl

# Configure skidl to find the KiCad symbol libraries (pitfall: must set
# lib_search_paths, KICAD_SYMBOL_DIR alone is not enough for skidl 2.x).
_KICAD_SYMBOLS_DIR = "/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols"
skidl.lib_search_paths[skidl.KICAD] = [_KICAD_SYMBOLS_DIR]


def led_bringer() -> skidl.Circuit:
    """S1: LED + resistor + battery. Trivial."""
    c = skidl.Circuit(); c.name = "S1_led_bringer"
    with c:
        vcc, gnd = skidl.Net("VCC", stub=True), skidl.Net("GND", stub=True)
        r1 = skidl.Part("Device", "R", value="330"); r1.ref = "R1"
        led1 = skidl.Part("Device", "LED", value="red"); led1.ref = "LED1"
        r1[1] += vcc
        r1[2] += led1["A"]
        led1["K"] += gnd
    return c


def rc_filter() -> skidl.Circuit:
    """S2: RC lowpass filter. Minimal."""
    c = skidl.Circuit(); c.name = "S2_rc_filter"
    with c:
        vin, vout, gnd = skidl.Net("VIN"), skidl.Net("VOUT"), skidl.Net("GND", stub=True)
        r1 = skidl.Part("Device", "R", value="1k"); r1.ref = "R1"
        c1 = skidl.Part("Device", "C", value="1uF"); c1.ref = "C1"
        vin += r1[1]
        vout += r1[2], c1[1]
        gnd += c1[2]
    return c


def opamp_preamp() -> skidl.Circuit:
    """S3: Non-inverting opamp preamp with feedback. Small + feedback loop."""
    c = skidl.Circuit(); c.name = "S3_opamp_preamp"
    with c:
        vin, vout = skidl.Net("VIN"), skidl.Net("VOUT")
        vcc, gnd = skidl.Net("VCC", stub=True), skidl.Net("GND", stub=True)
        u1 = skidl.Part("Amplifier_Operational", "LM358", value="LM358"); u1.ref = "U1"
        r1 = skidl.Part("Device", "R", value="10k"); r1.ref = "R1"
        r2 = skidl.Part("Device", "R", value="100k"); r2.ref = "R2"
        # LM358 pin names: [3]=+, [2]=-, [1]=out, [8]=V+, [4]=V-
        u1[3] += vin              # non-inverting input
        u1[2] += r1[1], r2[1]     # inverting input
        vout += u1[1], r1[2]      # output + feedback
        r2[2] += gnd
        u1[8] += vcc              # V+
        u1[4] += gnd              # V-
    return c


def audio_mixer() -> skidl.Circuit:
    """S4: 4-channel audio summing mixer. Medium."""
    c = skidl.Circuit(); c.name = "S4_audio_mixer"
    with c:
        gnd = skidl.Net("GND", stub=True)
        vcc = skidl.Net("VCC", stub=True)
        out = skidl.Net("MIX_OUT")
        u1 = skidl.Part("Amplifier_Operational", "TL072", value="TL072"); u1.ref = "U1"
        rf = skidl.Part("Device", "R", value="100k"); rf.ref = "RF"
        # TL072 pin names (dual opamp, use unit 1): [6]=-,[5]=+,[7]=out,[8]=V+,[4]=V-
        u1[6] += rf[1]
        out += u1[7], rf[2]
        for i in range(1, 5):
            r = skidl.Part("Device", "R", value="10k"); r.ref = f"R{i}"
            cap = skidl.Part("Device", "C", value="1uF"); cap.ref = f"C{i}"
            in_net = skidl.Net(f"CH{i}")
            in_net += cap[1]
            cap[2] += r[1]
            r[2] += u1[6]        # sum into inverting input
        u1[5] += gnd              # non-inverting to ground (virtual earth)
        u1[8] += vcc
        u1[4] += gnd
    return c


def esp32_breakout() -> skidl.Circuit:
    """S5: ESP32 + decoupling + LED + debug header. Medium-large."""
    c = skidl.Circuit(); c.name = "S5_esp32_breakout"
    with c:
        vcc33 = skidl.Net("+3V3", stub=True)
        gnd = skidl.Net("GND", stub=True)
        u1 = skidl.Part("RF_Module", "ESP32-WROOM-32", value="ESP32-WROOM-32"); u1.ref = "U1"
        u1[2] += vcc33           # VDD
        u1[1] += gnd             # GND
        for i in range(1, 4):
            cap = skidl.Part("Device", "C", value="100nF"); cap.ref = f"C{i}"
            vcc33 += cap[1]
            gnd += cap[2]
        ren = skidl.Part("Device", "R", value="10k"); ren.ref = "REN"
        vcc33 += ren[1]
        u1[3] += ren[2]          # EN pin
        for name, pin_num in [("BOOT", 25), ("RST", 3)]:   # IO0=25, EN=3
            sw = skidl.Part("Switch", "SW_Push", value=name); sw.ref = f"SW_{name}"
            sw[1] += gnd
            u1[pin_num] += sw[2]
        rled = skidl.Part("Device", "R", value="2k2"); rled.ref = "R_LED"
        led = skidl.Part("Device", "LED", value="blue"); led.ref = "LED1"
        vcc33 += rled[1]
        rled[2] += led["A"]
        led["K"] += u1[24]       # IO2 = pin 24
        j1 = skidl.Part("Connector_Generic", "Conn_01x15", value="HDR_L"); j1.ref = "J1"
        j2 = skidl.Part("Connector_Generic", "Conn_01x15", value="HDR_R"); j2.ref = "J2"
        left_pins = [25, 35, 24, 34, 26, 29, 14, 8, 9, 23, 27, 28, 30, 31, 33]
        for idx, pn in enumerate(left_pins, start=1):
            j1[idx] += u1[pn]
        right_pins = [36, 37, 10, 11, 12, 8, 9, 7, 6, 4, 5, 17, 3, 2, 1]
        right_nets = None
        for idx, pn in enumerate(right_pins, start=1):
            if pn == 2:
                j2[idx] += vcc33
            elif pn == 1:
                j2[idx] += gnd
            else:
                j2[idx] += u1[pn]
    return c


GENERATORS = {
    "S1_led_bringer": led_bringer,
    "S2_rc_filter": rc_filter,
    "S3_opamp_preamp": opamp_preamp,
    "S4_audio_mixer": audio_mixer,
    "S5_esp32_breakout": esp32_breakout,
}


def main() -> None:
    out_dir = Path("tests/fixtures/legibility")
    out_dir.mkdir(parents=True, exist_ok=True)

    from kicad_agent.circuit_ir import circuit_to_kicad_sch

    for name, gen in GENERATORS.items():
        try:
            circuit = gen()
            out_path = out_dir / f"{name}.kicad_sch"
            circuit_to_kicad_sch(circuit, out_path)
            n_parts = len(circuit.parts)
            n_nets = len(circuit.nets)
            size = out_path.stat().st_size
            print(f"OK   {name:25s} {n_parts:>3} parts  {n_nets:>3} nets  {size:>6} bytes")
        except Exception as e:
            import traceback
            print(f"FAIL {name:25s} {e}")
            traceback.print_exc()


if __name__ == "__main__":
    main()
