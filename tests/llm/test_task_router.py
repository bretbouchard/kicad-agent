"""Tests for the Phase D task router."""
import pytest
from kicad_agent.llm.task_router import (
    TaskRouter,
    TaskType,
    classify_intent,
    RoutingDecision,
    DEFAULT_ADAPTER_PATH,
)
from pathlib import Path


class TestIntentClassification:
    """Test the intent classifier with various user inputs."""

    @pytest.mark.parametrize("prompt", [
        "Design a circuit: An LED with a 220 ohm resistor on 5V",
        "I need an ESP32 breakout with USB-C power and I2C pull-ups",
        "Create an RC low-pass filter at 1kHz",
        "Build a non-inverting opamp amplifier with gain 10x",
        "Add a 10k pull-up resistor on the SDA line",
        "Generate a voltage divider producing 3.3V from 5V",
    ])
    def test_codegen_detection(self, prompt):
        decision = classify_intent(prompt)
        assert decision.task_type == TaskType.CODEGEN
        assert decision.prefix == "CODEGEN"
        assert decision.confidence > 0

    @pytest.mark.parametrize("prompt", [
        "Why use both 100nF and 10uF capacitors for decoupling?",
        "How do opamps work?",
        "What is impedance matching and when does it matter?",
        "Explain the difference between buck and LDO regulators",
        "What is ESR and why does it matter for capacitors?",
        "When should I use a pull-up vs pull-down resistor?",
    ])
    def test_theory_detection(self, prompt):
        decision = classify_intent(prompt)
        assert decision.task_type == TaskType.THEORY
        assert decision.prefix == "THEORY"

    @pytest.mark.parametrize("prompt", [
        "Simulate this RC filter at 1kHz cutoff",
        "Verify the gain of this opamp circuit",
        "Run AC analysis on this amplifier",
        "Check the -3dB point of this filter",
        "Measure the transient response of this LDO",
    ])
    def test_spice_detection(self, prompt):
        decision = classify_intent(prompt)
        assert decision.task_type == TaskType.SPICE
        assert decision.prefix == "SPICE"

    @pytest.mark.parametrize("prompt", [
        "Analyze this PCB layout for issues",
        "What's wrong with this schematic?",
        "Review my board for DRC violations",
        "Diagnose the routing quality of this design",
    ])
    def test_analysis_detection(self, prompt):
        decision = classify_intent(prompt)
        assert decision.task_type == TaskType.ANALYSIS

    def test_general_fallback(self):
        decision = classify_intent("Hello, how are you?")
        assert decision.task_type == TaskType.GENERAL
        assert decision.confidence == 0.5

    def test_empty_input(self):
        decision = classify_intent("")
        assert decision.task_type == TaskType.GENERAL

    def test_matched_keywords_populated(self):
        decision = classify_intent("Design an LED circuit with a resistor")
        assert len(decision.matched_keywords) > 0

    def test_confidence_increases_with_matches(self):
        single = classify_intent("Design a circuit")
        multi = classify_intent("Design a circuit with an ESP32 breakout board")
        assert multi.confidence >= single.confidence


class TestSystemPrompts:
    """Test that each task type gets the right system prompt."""

    def test_codegen_has_skidl_rules(self):
        decision = classify_intent("Design an LED circuit")
        assert "Part(" in decision.system_prompt
        assert "SKIDL" in decision.system_prompt or "skidl" in decision.system_prompt
        assert "build_board" in decision.system_prompt

    def test_theory_has_expert_role(self):
        decision = classify_intent("Why use decoupling capacitors?")
        assert "expert" in decision.system_prompt.lower() or "circuit" in decision.system_prompt.lower()

    def test_spice_has_ngspice(self):
        decision = classify_intent("Simulate this circuit")
        assert "ngspice" in decision.system_prompt.lower() or "spice" in decision.system_prompt.lower()

    def test_max_tokens_differ_by_task(self):
        codegen = classify_intent("Design a circuit")
        theory = classify_intent("Why use decoupling?")
        assert codegen.max_tokens >= 800
        assert theory.max_tokens >= 600


class TestTaskRouter:
    """Test the high-level TaskRouter class."""

    def test_prefix_mode_with_combined_adapter(self):
        router = TaskRouter(combined_adapter="/fake/path")
        assert router.config.mode == "prefix"

        decision = router.route("Design an LED circuit")
        assert decision.task_type == TaskType.CODEGEN
        assert decision.adapter_path == "/fake/path"

    def test_swap_mode_with_separate_adapters(self):
        router = TaskRouter(
            codegen_adapter="/codegen",
            theory_adapter="/theory",
            spice_adapter="/spice",
        )
        assert router.config.mode == "swap"

        codegen_decision = router.route("Design a circuit")
        assert codegen_decision.adapter_path == "/codegen"

        theory_decision = router.route("Why use decoupling?")
        assert theory_decision.adapter_path == "/theory"

    def test_prepare_prompt_adds_prefix_in_combined_mode(self):
        router = TaskRouter(combined_adapter="/fake")
        sys_prompt, user_prompt, max_tokens = router.prepare_prompt("Design an LED circuit")
        assert user_prompt.startswith("[CODEGEN]")
        assert "Part(" in sys_prompt
        assert max_tokens == 1024

    def test_prepare_prompt_no_prefix_in_swap_mode(self):
        router = TaskRouter(codegen_adapter="/codegen")
        sys_prompt, user_prompt, max_tokens = router.prepare_prompt("Design an LED circuit")
        assert not user_prompt.startswith("[")
        assert "Part(" in sys_prompt

    def test_general_fallback_no_prefix(self):
        router = TaskRouter(combined_adapter="/fake")
        sys_prompt, user_prompt, max_tokens = router.prepare_prompt("Hello there")
        assert not user_prompt.startswith("[")
        assert max_tokens == 600

    def test_default_router_exists(self):
        from kicad_agent.llm.task_router import get_router
        router = get_router()
        assert router is not None

    def test_adapter_path_resolves(self):
        """If the default adapter path exists, router should use it."""
        from kicad_agent.llm.task_router import get_router
        router = get_router()
        if Path(DEFAULT_ADAPTER_PATH).exists():
            decision = router.route("Design a circuit")
            assert decision.adapter_path == DEFAULT_ADAPTER_PATH
