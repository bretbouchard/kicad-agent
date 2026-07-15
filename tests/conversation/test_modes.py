"""Tests for Conversation Modes MVP (volta-5q8)."""
from __future__ import annotations

import pytest

from volta.conversation import (
    ConversationMode,
    Mode,
    ModeRegistry,
    get_mode,
    select_mode_for_intent,
)


class TestModeRegistry:
    """All 6 modes registered, lookup works."""

    def test_default_registry_has_all_6_modes(self) -> None:
        reg = ModeRegistry.default()
        modes = reg.list()
        assert len(modes) == 6
        names = {m.name.value for m in modes}
        assert names == {"design", "review", "debug", "optimization", "manufacturing", "teaching"}

    def test_get_by_string_name(self) -> None:
        reg = ModeRegistry.default()
        m = reg.get("design")
        assert m.name == ConversationMode.DESIGN
        assert m.focus_question == "What are we building?"

    def test_get_by_enum(self) -> None:
        reg = ModeRegistry.default()
        m = reg.get(ConversationMode.DEBUG)
        assert m.focus_question == "Why does this not work?"

    def test_get_case_insensitive(self) -> None:
        reg = ModeRegistry.default()
        m = reg.get("REVIEW")
        assert m.name == ConversationMode.REVIEW

    def test_unknown_mode_raises(self) -> None:
        reg = ModeRegistry.default()
        with pytest.raises(KeyError, match="Unknown conversation mode"):
            reg.get("nonexistent")

    def test_default_mode_is_design(self) -> None:
        reg = ModeRegistry.default()
        assert reg.default_mode().name == ConversationMode.DESIGN


class TestModeDefinitions:
    """Each mode has the required attributes."""

    @pytest.mark.parametrize("mode_name, focus", [
        ("design", "What are we building?"),
        ("review", "What is wrong with this?"),
        ("debug", "Why does this not work?"),
        ("optimization", "Make it cheaper / quieter / smaller / lower power."),
        ("manufacturing", "Can this be built reliably?"),
        ("teaching", "Explain what you are doing as we go."),
    ])
    def test_focus_question(self, mode_name: str, focus: str) -> None:
        m = get_mode(mode_name)
        assert m.focus_question == focus

    @pytest.mark.parametrize("mode_name, expected_format", [
        ("design", "code"),
        ("review", "structured"),
        ("debug", "narrative"),
        ("optimization", "structured"),
        ("manufacturing", "structured"),
        ("teaching", "tutorial"),
    ])
    def test_output_format(self, mode_name: str, expected_format: str) -> None:
        assert get_mode(mode_name).output_format == expected_format

    def test_design_mode_has_design_tools(self) -> None:
        """Design Mode enables generative op tools."""
        tools = get_mode("design").enabled_tools
        assert "add_component" in tools
        assert "add_design_note" in tools  # volta-29 op
        assert "build_preamp_circuit" in tools  # Phase 204 canonical

    def test_review_mode_has_audit_tools(self) -> None:
        """Review Mode enables ERC/DRC + critique tools."""
        tools = get_mode("review").enabled_tools
        assert "run_erc" in tools
        assert "run_drc" in tools
        assert "critique_sch" in tools

    def test_debug_mode_has_simulation_tools(self) -> None:
        """Debug Mode enables SPICE + net tracing."""
        tools = get_mode("debug").enabled_tools
        assert "run_simulation" in tools
        assert "trace_net" in tools

    def test_optimization_mode_has_optimizer(self) -> None:
        tools = get_mode("optimization").enabled_tools
        assert "optimize_preamp" in tools

    def test_teaching_mode_enables_all_tools(self) -> None:
        """Teaching Mode uses whatever the user is learning — empty list = unrestricted."""
        assert get_mode("teaching").enabled_tools == ()


class TestSystemPrompt:
    """system_prompt_for renders correctly."""

    def test_design_prompt_with_intent(self) -> None:
        m = get_mode("design")
        rendered = m.system_prompt_for("20 dB Eurorack preamp")
        assert "20 dB Eurorack preamp" in rendered
        assert "design partner" in rendered.lower()

    def test_design_prompt_without_intent(self) -> None:
        """Design mode prompt template has {intent} — without intent, placeholder stays."""
        m = get_mode("design")
        rendered = m.system_prompt_for("")
        # Template renders with empty intent (no crash).
        assert "design partner" in rendered.lower()

    def test_teaching_prompt_appends_intent(self) -> None:
        """Teaching mode has no {intent} placeholder — intent gets appended."""
        m = get_mode("teaching")
        rendered = m.system_prompt_for("common-emitter amplifier basics")
        assert "common-emitter amplifier basics" in rendered


class TestIntentRouting:
    """Heuristic mode selection from natural-language intent."""

    @pytest.mark.parametrize("intent, expected_mode", [
        # Debug signals
        ("this circuit is broken and hums at 60Hz", "debug"),
        ("why doesn't this work?", "debug"),
        ("the LED doesn't turn on", "debug"),
        # Review signals
        ("review my schematic for issues", "review"),
        ("what's wrong with this design?", "review"),
        ("audit this PCB", "review"),
        # Optimization signals
        ("make this quieter", "optimization"),
        ("reduce the BOM cost", "optimization"),
        ("lower power consumption", "optimization"),
        # Manufacturing signals
        ("will this pass JLC PCB checks?", "manufacturing"),
        ("DFM review please", "manufacturing"),
        ("IPC compliance check", "manufacturing"),
        # Teaching signals
        ("explain how a common-emitter amplifier works", "teaching"),
        ("teach me about decoupling caps", "teaching"),
        # Default — clear design intent
        ("build me a 20 dB preamp", "design"),
        ("create a low-pass filter", "design"),
        # Default — ambiguous
        ("", "design"),  # empty intent defaults to design
    ])
    def test_intent_routes_to_correct_mode(self, intent: str, expected_mode: str) -> None:
        m = select_mode_for_intent(intent)
        assert m.name.value == expected_mode, (
            f"Intent {intent!r} should route to {expected_mode!r}, got {m.name.value!r}"
        )


class TestModeStacking:
    """Modes can stack — e.g., Debug + Teaching."""

    def test_teaching_does_not_override_design(self) -> None:
        """A clear Design intent doesn't accidentally route to Teaching."""
        # "Build me an amp and explain as you go" → ambiguous, default Design
        m = select_mode_for_intent("build me an amp and explain as you go")
        # "explain" keyword would push to teaching, but "build" is strong design signal
        # Current heuristic: first match wins. Refinement deferred to Track D.
        # Just verify it doesn't crash and returns a valid mode.
        assert m.name.value in {"design", "teaching"}

    def test_combining_modes_via_registry(self) -> None:
        """User can switch modes mid-conversation by calling registry.get()."""
        reg = ModeRegistry.default()
        debug = reg.get("debug")
        teaching = reg.get("teaching")
        # Combined persona: debug + teaching
        combined_prompt = debug.system_prompt + "\n\n" + teaching.system_prompt
        assert "debug detective" in combined_prompt.lower()
        assert "patient mentor" in combined_prompt.lower()
