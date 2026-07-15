"""Phase 204 volta-5q8: Conversation Modes — Design/Review/Debug/Optimization/Manufacturing/Teaching.

Six modes that reframe the assistant's behavior. Each mode is a lens on
the same circuit/project — same data, different questions, different outputs.

Modes are PROMPT-LEVEL abstractions, not separate codepaths. Same underlying
engine (Phase 204 closed-box + Phase 158 SPICE + Phase 156 SKIDL). Each
mode selects: system prompt template, default tools, output formatter,
escalation policy.

This module ships the mode definitions + registry. Track D (Phase 173/175)
will wire a UI dropdown on top.

Usage:
    from volta.conversation import ModeRegistry, Mode, get_mode

    registry = ModeRegistry.default()
    design_mode = registry.get("design")
    system_prompt = design_mode.system_prompt_for(intent="20 dB preamp")

The LLM is invoked with this system prompt + the user's intent, producing
mode-appropriate output. Design generates schematics, Review audits,
Debug diagnoses, etc.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Callable


class ConversationMode(str, Enum):
    """All 6 conversation modes — same data, different lens."""

    DESIGN = "design"                  # "What are we building?"
    REVIEW = "review"                  # "What is wrong with this?"
    DEBUG = "debug"                    # "Why does this not work?"
    OPTIMIZATION = "optimization"      # "Make it cheaper / quieter / smaller / lower power"
    MANUFACTURING = "manufacturing"    # "Can this be built reliably?"
    TEACHING = "teaching"              # "Explain what you are doing as we go."


@dataclass(frozen=True)
class Mode:
    """Definition of a single conversation mode.

    Attributes:
        name: ConversationMode enum value (also the user-facing identifier).
        focus_question: The one-line question this mode asks. UI display.
        system_prompt: LLM system prompt template. May contain {intent}
            placeholder filled at runtime.
        enabled_tools: volta op_types this mode prefers. Tool routing
            layer (future Phase 165 extension) uses this to filter the 142+
            ops down to the relevant subset.
        output_format: Output formatter hint. "structured" (findings list),
            "narrative" (prose), "code" (executable op JSON), "tutorial"
            (annotated steps with explanations).
        escalation_policy: When to pause for user input. "always" (confirm
            every action), "destructive_only" (only on file deletes, etc.),
            "never" (autonomous), "uncertain" (pause on low-confidence).
        color_hint: Suggested UI color for the mode chip (for Track D).
    """

    name: ConversationMode
    focus_question: str
    system_prompt: str
    enabled_tools: tuple[str, ...] = ()
    output_format: str = "narrative"
    escalation_policy: str = "destructive_only"
    color_hint: str = "blue"

    def system_prompt_for(self, intent: str = "") -> str:
        """Render the system prompt with an optional user intent injected."""
        if "{intent}" in self.system_prompt:
            return self.system_prompt.replace("{intent}", intent)
        # Default: append intent if not templated.
        return f"{self.system_prompt}\n\nUser intent: {intent}" if intent else self.system_prompt


# ---------------------------------------------------------------------------
# Default mode definitions
# ---------------------------------------------------------------------------

_DESIGN_MODE = Mode(
    name=ConversationMode.DESIGN,
    focus_question="What are we building?",
    system_prompt="""You are a circuit design partner. The user wants to BUILD something.

Your job is forward-looking and generative. Ask clarifying questions,
propose topologies, suggest components. Default to action: emit a
schematic draft via volta ops rather than asking permission for
every step.

When the user's intent is ambiguous, ask ONE focused question (not three).
When the intent is clear, ship a v1 design immediately — the user can
iterate via Review/Debug modes.

User intent: {intent}

Output: schematics, BOM, intent graphs. Format as volta op JSON
when emitting mutations; prose when explaining choices.""",
    enabled_tools=(
        "add_component", "add_wire", "add_label", "add_power",
        "add_design_note", "build_preamp_circuit", "build_buffered_preamp_spice_netlist",
        "auto_layout_sch", "safe_annotate", "safe_sync_pcb_from_schematic",
    ),
    output_format="code",
    escalation_policy="destructive_only",
    color_hint="blue",
)

_REVIEW_MODE = Mode(
    name=ConversationMode.REVIEW,
    focus_question="What is wrong with this?",
    system_prompt="""You are a senior design reviewer. The user wants an AUDIT.

Critique the existing work — schematic, PCB, BOM, the lot. Run every
applicable check (ERC, DRC, SPICE sanity, IPC compliance). Flag issues
by severity: P0 (blocks ship), P1 (must fix), P2 (should fix), P3 (polish).

For each finding, give:
- File + line/refdes
- What's wrong (one sentence)
- Why it matters (one sentence)
- Suggested fix (as a volta op JSON when possible)

DO NOT apply fixes — that's Design Mode's job. You diagnose.

User intent: {intent}

Output: prioritized finding list with severity tags.""",
    enabled_tools=(
        "run_erc", "run_drc", "critique_sch", "compute_degradation",
        "run_simulation", "export_pdf", "list_violations",
    ),
    output_format="structured",
    escalation_policy="never",
    color_hint="orange",
)

_DEBUG_MODE = Mode(
    name=ConversationMode.DEBUG,
    focus_question="Why does this not work?",
    system_prompt="""You are a debug detective. The user has a SYMPTOM; find the ROOT CAUSE.

Methodology: symptom → hypothesis → test → confirm → fix. Iterate with
the user on reproduction steps. Use SPICE simulation to confirm hypotheses
before recommending fixes.

For each hypothesis:
- State it explicitly
- Predict what you'd see if it's true
- Run a sim or inspection to test
- Report the result (confirmed / ruled out / inconclusive)

Only recommend a fix when you have EVIDENCE the hypothesis is correct.
Multiple hypotheses may be in flight simultaneously.

User intent (symptom): {intent}

Output: causal chain, evidence, fix recommendation. Use structured
findings when confirmed; prose while investigating.""",
    enabled_tools=(
        "run_simulation", "trace_net", "get_node_voltages", "compute_degradation",
        "export_pdf", "run_erc", "run_drc", "list_violations",
    ),
    output_format="narrative",
    escalation_policy="uncertain",
    color_hint="red",
)

_OPTIMIZATION_MODE = Mode(
    name=ConversationMode.OPTIMIZATION,
    focus_question="Make it cheaper / quieter / smaller / lower power.",
    system_prompt="""You are an analog circuit optimizer. The user wants to TUNE.

Use the Phase 204 closed-box stack: Optuna GPSampler + ngspice. Sweep
E12 resistor/cap values against the user's objective (cost, noise, size,
current, THD, bandwidth). Surface the Pareto front when objectives conflict.

Default objective: minimize (gain_db - target)^2 + lambda * current.
Pareto objectives: gain vs current vs noise vs cost.

Always explain the tradeoff curve — don't just return "best" values.
The user picks the knee based on their priorities.

User intent: {intent}

Output: parameter sweeps, tradeoff curves, recommended values with rationale.
Format results as a markdown table.""",
    enabled_tools=(
        "optimize_preamp", "run_simulation", "compute_degradation",
        "build_buffered_preamp_spice_netlist",
    ),
    output_format="structured",
    escalation_policy="uncertain",
    color_hint="green",
)

_MANUFACTURING_MODE = Mode(
    name=ConversationMode.MANUFACTURING,
    focus_question="Can this be built reliably?",
    system_prompt="""You are a DFM/DFT/reliability engineer. The user wants to KNOW if
this will manufacture cleanly.

Check IPC standards (trace width vs current, annular rings, clearance),
component availability (LCSC stock, lead times), derating (capacitors
at 80% voltage, resistors at 60% power), and tolerance stackups.

Flag anything that would fail at JLC PCB, PCBWay, or Advanced Circuits.
Suggest panelization, test point coverage, and JTAG/boundary-scan where
appropriate.

Closes the IPC standards gap from docs/GAP_ANALYSIS.md — hobbyists
don't need this, professionals do.

User intent: {intent}

Output: DFM report with category-tagged findings (DFM/DFT/reliability/IPC).""",
    enabled_tools=(
        "run_drc", "list_violations", "export_gerbers", "export_drill",
        "export_pos", "search_components",
    ),
    output_format="structured",
    escalation_policy="never",
    color_hint="purple",
)

_TEACHING_MODE = Mode(
    name=ConversationMode.TEACHING,
    focus_question="Explain what you are doing as we go.",
    system_prompt="""You are a patient mentor. The user wants to LEARN.

Slow down. Narrate your reasoning. Cite sources (datasheets, app notes,
textbooks like Horowitz & Hill, Williams' Analog Circuit Design).

For every action:
1. State what you're about to do (1 sentence)
2. Do it (emit the volta op)
3. Explain what happened (1-2 sentences)
4. Connect it to a broader concept (1 sentence)

Use analogies liberally. A CE preamp is "like a faucet controlled by
a thumb on the hose" — concrete > abstract.

User intent: {intent}

Output: annotated actions, links to references, concept glossary.
Markdown with embedded code blocks for op JSON.""",
    enabled_tools=(),  # teaching mode doesn't restrict tools — uses whatever the user is learning
    output_format="tutorial",
    escalation_policy="always",
    color_hint="yellow",
)


_ALL_MODES: tuple[Mode, ...] = (
    _DESIGN_MODE, _REVIEW_MODE, _DEBUG_MODE,
    _OPTIMIZATION_MODE, _MANUFACTURING_MODE, _TEACHING_MODE,
)


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------

class ModeRegistry:
    """Registry of conversation modes. Lookup by name, list all, default selection."""

    def __init__(self, modes: tuple[Mode, ...] = _ALL_MODES) -> None:
        self._modes: dict[str, Mode] = {m.name.value: m for m in modes}

    @classmethod
    def default(cls) -> "ModeRegistry":
        """Default registry with all 6 modes loaded."""
        return cls(_ALL_MODES)

    def get(self, name: str | ConversationMode) -> Mode:
        """Look up a mode by name. Raises KeyError if unknown."""
        key = name.value if isinstance(name, ConversationMode) else name.lower()
        if key not in self._modes:
            raise KeyError(
                f"Unknown conversation mode: {name!r}. "
                f"Available: {sorted(self._modes.keys())}"
            )
        return self._modes[key]

    def list(self) -> tuple[Mode, ...]:
        """All registered modes (in declaration order)."""
        return tuple(self._modes.values())

    def default_mode(self) -> Mode:
        """The default mode when none is specified — Design."""
        return self.get("design")

    def mode_for_intent(self, intent: str) -> Mode:
        """Heuristic mode selection from natural-language intent.

        Multi-keyword matching with priority order:
        1. Debug: symptom language (broken, fails, doesn't turn on, why doesn't)
        2. Manufacturing: DFM/IPC/production language (most specific — check first)
        3. Optimization: tuning language (smaller, cheaper, quieter, reduce, lower)
        4. Review: audit language (review, audit, what's wrong)
        5. Teaching: pedagogy language (explain, teach, learn, how does)
        6. Design: default — forward-looking, generative
        """
        i = intent.lower()

        # Manufacturing FIRST — most specific (DFM/IPC/jlc/production are
        # unambiguous signals; "DFM review" should be manufacturing not review).
        if any(k in i for k in (
            "manufacture", "dfm", "dft", "ipc", "build reliably", "production",
            "jlc pcb", "jlcpcb", "pcbway", "advanced circuits", "pass checks",
            "pass jlc", "manufacturing",
        )):
            return self.get("manufacturing")

        # Debug — symptom language.
        if any(k in i for k in (
            "broken", "not working", "doesn't work", "doesn't turn on",
            "doesn't turn", "doesn't power", "fails", "failure", "fail",
            "why doesn't", "why does it fail", "why is it", "no output",
            "no signal", "dead", "smoked", "burned", "hot to touch",
            "wrong value", "off by", "drift", "humming", "hums at",
            "oscillating", "ringing", "distorted",
        )):
            return self.get("debug")

        # Optimization — tuning language.
        if any(k in i for k in (
            "smaller", "cheaper", "quieter", "lower power", "lower noise",
            "optimize", "optimise", "improve", "reduce", "minimize", "minimise",
            "maximize", "maximise", "tune", "tuning", "sweep", "tradeoff",
            "trade-off", "pareto", "bom cost", "tighten",
        )):
            return self.get("optimization")

        # Review — audit language.
        if any(k in i for k in (
            "review", "audit", "what's wrong", "what is wrong", "check this",
            "critique", "find issues", "find problems",
        )):
            return self.get("review")

        # Teaching — pedagogy language.
        if any(k in i for k in (
            "explain", "teach", "learn", "how does", "how do", "what is a",
            "what is an", "walk me through", "show me how", "beginner",
        )):
            return self.get("teaching")

        return self.default_mode()


# ---------------------------------------------------------------------------
# Convenience module-level accessors
# ---------------------------------------------------------------------------

_DEFAULT_REGISTRY: ModeRegistry | None = None


def get_mode(name: str | ConversationMode) -> Mode:
    """Look up a mode via the default registry."""
    global _DEFAULT_REGISTRY
    if _DEFAULT_REGISTRY is None:
        _DEFAULT_REGISTRY = ModeRegistry.default()
    return _DEFAULT_REGISTRY.get(name)


def select_mode_for_intent(intent: str) -> Mode:
    """Heuristic mode selection via the default registry."""
    global _DEFAULT_REGISTRY
    if _DEFAULT_REGISTRY is None:
        _DEFAULT_REGISTRY = ModeRegistry.default()
    return _DEFAULT_REGISTRY.mode_for_intent(intent)
