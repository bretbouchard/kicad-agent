"""Phase 160: NL→SKIDL circuit generation — the capstone.

Takes a natural-language circuit request and generates SKIDL Python code,
which then flows through ERC → SPICE → floor plan → PCB.

Best-of-N with gate feedback: generate K candidates, validate each through
the gate chain, first to pass wins.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class GenerationRequest:
    """A natural-language circuit generation request.

    Attributes:
        prompt: Natural language description of the desired circuit.
        spec_targets: Parsed spec targets (gain_db, bandwidth_hz, etc.).
        max_candidates: Maximum number of best-of-N candidates.
        max_retries: Maximum repair-loop retries per candidate.
    """
    prompt: str
    spec_targets: dict[str, float] = field(default_factory=dict)
    max_candidates: int = 3
    max_retries: int = 2


@dataclass
class GenerationResult:
    """Result of an NL→SKIDL generation attempt.

    Attributes:
        skidl_code: Generated SKIDL Python code (None if all candidates failed).
        passed_gates: Which gates the winning candidate passed.
        attempts: Total candidates generated.
        errors: List of error messages from failed attempts.
    """
    skidl_code: str | None
    passed_gates: list[str] = field(default_factory=list)
    attempts: int = 0
    errors: list[str] = field(default_factory=list)


def parse_spec_targets(prompt: str) -> dict[str, float]:
    """Extract spec targets from a natural-language prompt.

    Looks for patterns like "+18dB gain", "100kHz bandwidth", "-128dBu EIN".

    Args:
        prompt: Natural language circuit request.

    Returns:
        Dict of spec targets (e.g. {"gain_db": 18.0, "bandwidth_hz": 100000.0}).
    """
    import re

    targets: dict[str, float] = {}

    # Gain in dB: "+18dB", "gain of 20dB", "18 dB gain"
    gain_match = re.search(r'([+-]?\d+(?:\.\d+)?)\s*dB\s*(?:gain|amplification)', prompt, re.IGNORECASE)
    if not gain_match:
        gain_match = re.search(r'gain\s*(?:of\s*)?([+-]?\d+(?:\.\d+)?)\s*dB', prompt, re.IGNORECASE)
    if gain_match:
        targets["gain_db"] = float(gain_match.group(1))

    # Bandwidth: "100kHz", "bandwidth of 100kHz"
    bw_match = re.search(r'(\d+(?:\.\d+)?)\s*(kHz|MHz|Hz)\s*(?:bandwidth|BW)', prompt, re.IGNORECASE)
    if not bw_match:
        bw_match = re.search(r'bandwidth\s*(?:of\s*)?(\d+(?:\.\d+)?)\s*(kHz|MHz|Hz)', prompt, re.IGNORECASE)
    if bw_match:
        value = float(bw_match.group(1))
        unit = bw_match.group(2).lower()
        multiplier = {"hz": 1, "khz": 1e3, "mhz": 1e6}[unit]
        targets["bandwidth_hz"] = value * multiplier

    # EIN/Noise: "-128dBu", "EIN of -128dBu"
    ein_match = re.search(r'(-?\d+(?:\.\d+)?)\s*dBu\s*(?:EIN|noise)', prompt, re.IGNORECASE)
    if not ein_match:
        ein_match = re.search(r'EIN\s*(?:of\s*)?(-?\d+(?:\.\d+)?)\s*dBu', prompt, re.IGNORECASE)
    if ein_match:
        targets["ein_dbu"] = float(ein_match.group(1))

    # Voltage: "3.3V", "5V regulator", "±12V"
    voltage_match = re.search(r'([+-]?\d+(?:\.\d+)?)\s*V\b', prompt)
    if voltage_match:
        targets["voltage_v"] = float(voltage_match.group(1))

    return targets


def validate_skidl_code(code: str) -> tuple[bool, str]:
    """Validate that SKIDL code is syntactically correct Python.

    Args:
        code: SKIDL Python code string.

    Returns:
        Tuple of (is_valid, error_message).
    """
    try:
        compile(code, "generated.py", "exec")
        return True, ""
    except SyntaxError as e:
        return False, f"Syntax error: {e}"

    # Check for required imports.
    if "from skidl import" not in code and "import skidl" not in code:
        return False, "Missing skidl import"


def generate_circuit(
    request: GenerationRequest,
    llm_generate_fn=None,
) -> GenerationResult:
    """Generate a SKIDL circuit from natural language.

    Uses best-of-N: generates K candidates, validates each, returns
    the first that passes. If no candidates pass, returns the errors.

    Args:
        request: The generation request with NL prompt + spec targets.
        llm_generate_fn: Function that takes a prompt and returns SKIDL code.
            If None, uses a template-based fallback.

    Returns:
        GenerationResult with the winning SKIDL code or errors.
    """
    result = GenerationResult(skidl_code=None)

    for attempt in range(request.max_candidates):
        result.attempts += 1

        # Generate candidate.
        if llm_generate_fn:
            candidate = llm_generate_fn(request.prompt)
        else:
            candidate = _template_generate(request.prompt)

        if not candidate:
            result.errors.append(f"Attempt {attempt + 1}: empty output")
            continue

        # Validate syntax.
        valid, error = validate_skidl_code(candidate)
        if not valid:
            result.errors.append(f"Attempt {attempt + 1}: {error}")
            continue

        # Gate 1: SKIDL parse check.
        result.passed_gates.append("parse")
        logger.info("Candidate %d passed parse gate", attempt + 1)

        # Gate 2: ERC check (if skidl is available).
        try:
            from volta.circuit_ir import _ensure_skidl_env
            _ensure_skidl_env()
            exec_globals = {}
            exec(candidate, exec_globals)
            circuit = exec_globals.get("build_board")
            if circuit:
                ckt = circuit()
                erc_result = ckt.ERC()
                if erc_result is None or (isinstance(erc_result, tuple) and erc_result[0] == 0):
                    result.passed_gates.append("erc")
                    logger.info("Candidate %d passed ERC gate", attempt + 1)
                else:
                    errors = erc_result[0] if isinstance(erc_result, tuple) else "unknown"
                    result.errors.append(f"Attempt {attempt + 1}: ERC failed ({errors} errors)")
                    continue
        except Exception as e:
            result.errors.append(f"Attempt {attempt + 1}: execution/ERC error: {e}")
            continue

        # All gates passed — return this candidate.
        result.skidl_code = candidate
        logger.info("Candidate %d passed all gates", attempt + 1)
        return result

    return result


def _template_generate(prompt: str) -> str:
    """Fallback template-based generation when no LLM is available.

    Generates a minimal SKIDL circuit based on keywords in the prompt.
    """
    prompt_lower = prompt.lower()

    if "led" in prompt_lower:
        return '''#!/usr/bin/env python3
"""Generated LED circuit."""
import os
os.environ["KICAD_SYMBOL_DIR"] = "/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols"
from skidl import Part, Net, Circuit

def build_board() -> Circuit:
    ckt = Circuit()
    with ckt:
        led = Part("Device", "LED", value="Red")
        r = Part("Device", "R", value="330")
        vcc = Net("VCC")
        gnd = Net("GND")
        vcc += r[1]
        r[2] += led[1]
        led[2] += gnd
    return ckt
'''

    elif "opamp" in prompt_lower or "amplifier" in prompt_lower or "preamp" in prompt_lower:
        return '''#!/usr/bin/env python3
"""Generated opamp circuit."""
import os
os.environ["KICAD_SYMBOL_DIR"] = "/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols"
from skidl import Part, Net, Circuit

def build_board() -> Circuit:
    ckt = Circuit()
    with ckt:
        # NE5532 pinout: 1=OUT_A, 2=IN-_A, 3=IN+_A, 4=VEE, 5=IN+_B, 6=IN-_B, 7=OUT_B, 8=VCC
        opamp = Part("Amplifier_Operational", "NE5532", value="NE5532")
        r_in = Part("Device", "R", value="1k")
        r_fb = Part("Device", "R", value="10k")
        vin = Net("VIN")
        vout = Net("VOUT")
        vin += r_in[1]
        r_in[2] += opamp[2]  # IN- (pin 2)
        opamp[2] += r_fb[1]
        r_fb[2] += vout
        opamp[1] += vout  # OUT (pin 1)
    return ckt
'''

    else:
        # Generic RC filter.
        return '''#!/usr/bin/env python3
"""Generated RC lowpass filter circuit."""
import os
os.environ["KICAD_SYMBOL_DIR"] = "/Applications/KiCad/KiCad.app/Contents/SharedSupport/symbols"
from skidl import Part, Net, Circuit

def build_board() -> Circuit:
    ckt = Circuit()
    with ckt:
        r = Part("Device", "R", value="1k")
        c = Part("Device", "C", value="1u")
        vin = Net("VIN")
        vout = Net("VOUT")
        gnd = Net("GND")
        vin += r[1]
        r[2] += vout
        vout += c[1]
        c[2] += gnd
    return ckt
'''
