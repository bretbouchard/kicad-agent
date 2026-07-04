"""Phase 160: NL circuit generation + gate chain tests."""
from __future__ import annotations

import pytest

from kicad_agent.generation.nl_to_skidl import (
    GenerationRequest,
    parse_spec_targets,
    validate_skidl_code,
    generate_circuit,
    _template_generate,
)
from kicad_agent.generation.gate_chain import (
    run_gate_chain,
    GateName,
    GateStatus,
)


class TestParseSpecTargets:
    """Spec extraction from natural language."""

    def test_extracts_gain(self) -> None:
        targets = parse_spec_targets("I need a preamp with +18dB gain")
        assert "gain_db" in targets
        assert targets["gain_db"] == 18.0

    def test_extracts_bandwidth(self) -> None:
        targets = parse_spec_targets("bandwidth of 100kHz")
        assert "bandwidth_hz" in targets
        assert targets["bandwidth_hz"] == 100000.0

    def test_extracts_ein(self) -> None:
        targets = parse_spec_targets("EIN of -128dBu noise")
        assert "ein_dbu" in targets
        assert targets["ein_dbu"] == -128.0

    def test_no_targets_in_generic_prompt(self) -> None:
        targets = parse_spec_targets("build me a circuit")
        assert len(targets) == 0


class TestValidateSkidlCode:
    """SKIDL code validation."""

    def test_valid_code_passes(self) -> None:
        code = "x = 1 + 2\n"
        valid, _ = validate_skidl_code(code)
        assert valid

    def test_invalid_syntax_fails(self) -> None:
        code = "def broken(\n"
        valid, error = validate_skidl_code(code)
        assert not valid
        assert "Syntax" in error


class TestGenerateCircuit:
    """Circuit generation with template fallback."""

    def test_generates_led_circuit(self) -> None:
        request = GenerationRequest(prompt="I need an LED indicator circuit")
        result = generate_circuit(request)
        assert result.skidl_code is not None
        assert "LED" in result.skidl_code or "led" in result.skidl_code
        assert "parse" in result.passed_gates

    def test_generates_opamp_circuit(self) -> None:
        request = GenerationRequest(prompt="I need a preamp with 18dB gain")
        result = generate_circuit(request)
        assert result.skidl_code is not None
        assert "opamp" in result.skidl_code.lower() or "NE5532" in result.skidl_code

    def test_generates_rc_filter(self) -> None:
        request = GenerationRequest(prompt="I need a lowpass filter")
        result = generate_circuit(request)
        assert result.skidl_code is not None
        assert "Part(" in result.skidl_code

    def test_records_attempts(self) -> None:
        request = GenerationRequest(prompt="LED circuit", max_candidates=1)
        result = generate_circuit(request)
        assert result.attempts == 1


class TestGateChain:
    """Gate chain — validation pipeline."""

    def test_parse_gate_passes_on_valid_code(self) -> None:
        code = _template_generate("LED circuit")
        result = run_gate_chain(code)
        parse_gate = next(g for g in result.gates if g.gate_name == GateName.PARSE)
        assert parse_gate.status == GateStatus.PASSED

    def test_parse_gate_fails_on_invalid_code(self) -> None:
        result = run_gate_chain("def broken(")
        parse_gate = next(g for g in result.gates if g.gate_name == GateName.PARSE)
        assert parse_gate.status == GateStatus.FAILED

    def test_erc_gate_runs_on_valid_circuit(self) -> None:
        code = _template_generate("LED circuit")
        result = run_gate_chain(code)
        erc_gate = next(g for g in result.gates if g.gate_name == GateName.ERC)
        assert erc_gate.status in (GateStatus.PASSED, GateStatus.FAILED)

    def test_spice_gate_skipped_without_targets(self) -> None:
        code = _template_generate("LED circuit")
        result = run_gate_chain(code)  # No spec_targets
        spice_gate = next(g for g in result.gates if g.gate_name == GateName.SPICE)
        assert spice_gate.status == GateStatus.SKIPPED

    def test_pipeline_result_passed_property(self) -> None:
        code = _template_generate("LED circuit")
        result = run_gate_chain(code)
        assert isinstance(result.passed, bool)

    def test_failed_gate_identified(self) -> None:
        result = run_gate_chain("invalid syntax(")
        assert result.failed_gate is not None
        assert result.failed_gate.gate_name == GateName.PARSE
