"""
Phase D: Multi-Task Inference Router

Routes user requests to the appropriate task handler based on intent classification.
Supports both prefix-mode (single combined adapter with task prefixes) and
adapter-swap-mode (multiple specialized adapters).

Architecture:
    User Input → IntentClassifier → Router → [Adapter/Prefix] → Model → Response

Intent categories:
    CODEGEN   — "Design a circuit", "Create an LED driver", "I need a preamp"
    THEORY    — "Why use decoupling?", "How do opamps work?", "What is impedance?"
    SPICE     — "Simulate this circuit", "Verify gain", "Run AC analysis"
    ANALYSIS  — "Analyze this PCB", "What's wrong with this layout?"
    GENERAL   — Everything else

Usage:
    from volta.llm.task_router import TaskRouter
    router = TaskRouter(adapter_path="/path/to/v5-mlx")
    response = router.route("Design an LED circuit on 5V")
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Optional


class TaskType(str, Enum):
    CODEGEN = "codegen"
    THEORY = "theory"
    SPICE = "spice"
    ANALYSIS = "analysis"
    GENERAL = "general"


@dataclass
class RoutingDecision:
    """The router's decision for a user request."""
    task_type: TaskType
    prefix: str
    system_prompt: str
    adapter_path: Optional[str] = None
    max_tokens: int = 1024
    confidence: float = 1.0
    matched_keywords: list[str] = field(default_factory=list)


# === Intent Classification Rules ===

CODEGEN_PATTERNS = [
    r"\b(design|create|build|make|generate)\b.*\b(circuit|board|pcb|schematic|breakout|driver|filter|amplifier|preamp|regulator|sensor|module)\b",
    r"\b(i need|we need|i want)\b.*\b(circuit|board|pcb|connector|interface)\b",
    r"\b(add|place|connect|wire)\b.*\b(resistor|capacitor|led|mosfet|opamp|mcu|esp32|stm32|crystal|connector)\b",
    r"\b(part|skidl|net|footprint|component)\b",
    r"\b(voltage divider|rc filter|lc filter|decoupling|h.bridge|current.limiter)\b",
    r"\b(breakout|shield|carrier|adapter board)\b",
    r"\b(esp32|stm32|rp2040|atmega|arduino|raspberry)\b.*\b(board|circuit|breakout)\b",
]

THEORY_PATTERNS = [
    r"\b(why|how|what|when|should|explain|difference between)\b.*\b(capacitor|resistor|inductor|diode|mosfet|opamp|ground|impedance|decoupling|pull.?up|pull.?down|trace|via|plane|emission|emi|emc|thermal|noise|bandwidth|slew|gain|feedback|stability)\b",
    r"\b(what is|what are|define)\b.*\b(esr|esl|srf|gbw|thd|snr|psrr|cmrr|isl|pdn|ddr|lvds|opamp|amplifier)\b",
    r"\b(ohm|kirchhoff|thevenin|norton|nyquist|bode|fourier)\b",
    r"\b(impedance matching|signal integrity|power integrity|ground loop|return path|crosstalk|reflection|termination)\b",
    r"\b(thermal|heatsink|junction temp|derating|power dissipation)\b",
    r"\b(buck|boost|ldo|switching.regulator|linear.regulator|flyback|charge.pump)\b.*\b(how|why|when|difference|versus|vs)\b",
    r"\b(difference|differences)\b.*\b(between|of)\b",
    r"\b(zener|schottky|tvz|esd|flyback.diode|crowbar)\b.*\b(how|why|when)\b",
    r"\b(how do|how does)\b.*\b(work|function|operate)\b",
    r"\bwhy\b.*\b(use|need|require)\b",
]

SPICE_PATTERNS = [
    r"\b(simulate|simulation|spice|ngspice|\.cir|netlist)\b",
    r"\b(verify|check|measure|test)\b.*\b(gain|bandwidth|cutoff|frequency response|bode|transient|noise|thd|phase.margin)\b",
    r"\b(ac analysis|dc sweep|transient analysis|noise analysis|monte carlo|worst.case)\b",
    r"\b(run.*analysis|plot.*response|frequency.sweep)\b",
    r"\b(-3db|3db.point|cutoff.frequency|corner.frequency|rolloff)\b.*\b(verify|check|measure|find)\b",
    r"\b(verify|check|measure|find)\b.*\b(-3db|3db.point|cutoff.frequency|corner.frequency|rolloff)\b",
    r"\b(simulate|simulation)\b.*\b(filter|circuit|amplifier|regulator)\b",
]

ANALYSIS_PATTERNS = [
    r"\b(analyze|review|inspect|check|audit|diagnose|debug)\b.*\b(board|pcb|schematic|layout|design|circuit)\b",
    r"\b(what.s wrong|find.*error|fix.*issue|drc|erc.*error|violation)\b",
    r"\b(routing quality|placement|clearance|overlap|short circuit|open circuit)\b",
]


def classify_intent(user_input: str) -> RoutingDecision:
    """Classify user intent and return a routing decision.

    Uses keyword/pattern matching. Deterministic, no ML model needed.
    Can be upgraded to a learned classifier later.
    """
    text = user_input.lower().strip()

    # Score each task type
    scores: dict[TaskType, tuple[float, list[str]]] = {
        TaskType.CODEGEN: (0.0, []),
        TaskType.THEORY: (0.0, []),
        TaskType.SPICE: (0.0, []),
        TaskType.ANALYSIS: (0.0, []),
    }

    for pattern in CODEGEN_PATTERNS:
        match = re.search(pattern, text)
        if match:
            scores[TaskType.CODEGEN] = (
                scores[TaskType.CODEGEN][0] + 1.0,
                scores[TaskType.CODEGEN][1] + [match.group()],
            )

    for pattern in THEORY_PATTERNS:
        match = re.search(pattern, text)
        if match:
            scores[TaskType.THEORY] = (
                scores[TaskType.THEORY][0] + 1.0,
                scores[TaskType.THEORY][1] + [match.group()],
            )

    for pattern in SPICE_PATTERNS:
        match = re.search(pattern, text)
        if match:
            scores[TaskType.SPICE] = (
                scores[TaskType.SPICE][0] + 1.0,
                scores[TaskType.SPICE][1] + [match.group()],
            )

    for pattern in ANALYSIS_PATTERNS:
        match = re.search(pattern, text)
        if match:
            scores[TaskType.ANALYSIS] = (
                scores[TaskType.ANALYSIS][0] + 1.0,
                scores[TaskType.ANALYSIS][1] + [match.group()],
            )

    # Pick highest score
    best_task = max(scores, key=lambda t: scores[t][0])
    best_score, matched = scores[best_task]

    if best_score == 0:
        return _general_decision(user_input)

    # Build decision
    confidence = min(best_score / 3.0, 1.0)  # 3+ matches = high confidence

    return RoutingDecision(
        task_type=best_task,
        prefix=best_task.value.upper(),
        system_prompt=_system_prompt_for(best_task),
        confidence=confidence,
        matched_keywords=matched,
        max_tokens=_max_tokens_for(best_task),
    )


# === System Prompts per Task ===

SYSTEM_PROMPTS = {
    TaskType.CODEGEN: """\
You generate SKIDL Python code for circuits.

RULES:
1. Part() takes TWO positional args: Part("Library", "PartName", value=..., footprint=...)
   NEVER write Part("R", ...) — always include the library name.
   Common libs: Device, Connector, Connector_Generic, Switch, Diode, Regulator_Linear, Amplifier_Operational, MCU_RaspberryPi, RF_Module, Transistor_FET, Interface_USB.

2. Create Net variables ONCE, then connect pins with +=:
   vcc = Net("VCC")
   vcc += R1[1], U1["VDD"]

3. Use power() for supply nets: gnd = power("GND"), vcc = power("VCC")

4. Wrap in: def build_board() -> Circuit: with ckt = Circuit(): ... return ckt

Show your engineering calculations (Ohm's Law, RC formula, gain) before the code.""",

    TaskType.THEORY: """\
You are a circuit design expert. Answer questions about electronics, PCB design,
and circuit theory with precise, practical explanations. Reference specific formulas,
component values, and design rules when relevant.""",

    TaskType.SPICE: """\
You are a SPICE simulation expert. Given a circuit description, write the ngspice
netlist, choose the appropriate analysis (.ac, .tran, .noise, .dc, .tf), run the
simulation mentally, and report the key results with interpretation.""",

    TaskType.ANALYSIS: """\
You are a PCB design reviewer. Analyze the circuit/board provided and identify
issues with connectivity, placement, routing, signal integrity, power integrity,
thermal management, and manufacturability.""",

    TaskType.GENERAL: """\
You are an AI assistant for circuit design and PCB layout using KiCad and SKIDL.
Help the user design, analyze, simulate, and manufacture electronic circuits.""",
}

MAX_TOKENS = {
    TaskType.CODEGEN: 1024,
    TaskType.THEORY: 800,
    TaskType.SPICE: 1024,
    TaskType.ANALYSIS: 800,
    TaskType.GENERAL: 600,
}


def _system_prompt_for(task: TaskType) -> str:
    return SYSTEM_PROMPTS.get(task, SYSTEM_PROMPTS[TaskType.GENERAL])


def _max_tokens_for(task: TaskType) -> int:
    return MAX_TOKENS.get(task, 600)


def _general_decision(user_input: str) -> RoutingDecision:
    return RoutingDecision(
        task_type=TaskType.GENERAL,
        prefix="",
        system_prompt=SYSTEM_PROMPTS[TaskType.GENERAL],
        confidence=0.5,
        max_tokens=600,
    )


# === Router (high-level API) ===

@dataclass
class AdapterConfig:
    """Configuration for adapter loading."""
    # Single combined adapter (prefix mode)
    combined_path: Optional[str] = None
    # Separate adapters (swap mode)
    codegen_path: Optional[str] = None
    theory_path: Optional[str] = None
    spice_path: Optional[str] = None
    analysis_path: Optional[str] = None

    @property
    def mode(self) -> str:
        """Return 'prefix' (combined) or 'swap' (separate adapters)."""
        if self.combined_path:
            return "prefix"
        return "swap"

    def adapter_for(self, task: TaskType) -> Optional[str]:
        """Get adapter path for a task type."""
        if self.mode == "prefix":
            return self.combined_path
        mapping = {
            TaskType.CODEGEN: self.codegen_path,
            TaskType.THEORY: self.theory_path,
            TaskType.SPICE: self.spice_path,
            TaskType.ANALYSIS: self.analysis_path,
            TaskType.GENERAL: self.codegen_path or self.combined_path,
        }
        return mapping.get(task)


class TaskRouter:
    """Routes user requests to the appropriate task handler.

    Supports two modes:
    - Prefix mode: single combined adapter, task type encoded in prompt prefix
    - Swap mode: multiple adapters, router selects which to load
    """

    def __init__(
        self,
        combined_adapter: Optional[str] = None,
        codegen_adapter: Optional[str] = None,
        theory_adapter: Optional[str] = None,
        spice_adapter: Optional[str] = None,
        analysis_adapter: Optional[str] = None,
    ):
        self.config = AdapterConfig(
            combined_path=combined_adapter,
            codegen_path=codegen_adapter,
            theory_path=theory_adapter,
            spice_path=spice_adapter,
            analysis_path=analysis_adapter,
        )

    def route(self, user_input: str) -> RoutingDecision:
        """Classify intent and return routing decision."""
        decision = classify_intent(user_input)

        # Attach adapter path based on mode
        decision.adapter_path = self.config.adapter_for(decision.task_type)

        return decision

    def prepare_prompt(self, user_input: str) -> tuple[str, str, int]:
        """Full routing: classify + format prompt for the model.

        Returns:
            (system_prompt, formatted_user_prompt, max_tokens)
        """
        decision = self.route(user_input)

        # In prefix mode, prepend task type to user input
        if self.config.mode == "prefix" and decision.prefix:
            formatted = f"[{decision.prefix}] {user_input}"
        else:
            formatted = user_input

        return decision.system_prompt, formatted, decision.max_tokens


# === Default Router Instance ===

DEFAULT_ADAPTER_PATH = "/Volumes/Storage/models/kicad-agent/adapters/gemma4-skidl-v5-mlx"

_default_router: Optional[TaskRouter] = None


def get_router() -> TaskRouter:
    """Get the default router instance (singleton)."""
    global _default_router
    if _default_router is None:
        adapter_path = DEFAULT_ADAPTER_PATH
        if Path(adapter_path).exists():
            _default_router = TaskRouter(combined_adapter=adapter_path)
        else:
            _default_router = TaskRouter()  # No adapter, general mode only
    return _default_router
