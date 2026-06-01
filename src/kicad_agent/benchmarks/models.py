"""Model wrappers for PCB MMLU benchmark evaluation.

Provides BenchmarkModel ABC and concrete implementations:
- BaselineRandom: Uniform random choice (~25% accuracy)
- BaselineHeuristic: Keyword-matching heuristic (>25% on relevant categories)

Only models with working implementations are included here.
Future model types (fine-tuned, API-based) will be added in later phases
when the training pipeline produces adapters or API endpoints are configured.
"""

from __future__ import annotations

import random
from abc import ABC, abstractmethod

from kicad_agent.benchmarks.schemas import BenchmarkQuestion


class BenchmarkModel(ABC):
    """Base class for benchmark evaluation models.

    Subclasses must implement predict() to return a choice index
    in the range [0, 3] for a given BenchmarkQuestion.
    """

    @abstractmethod
    def predict(self, question: BenchmarkQuestion) -> int:
        """Return predicted choice index (0-3) for the given question.

        Args:
            question: The benchmark question to answer.

        Returns:
            Integer index in [0, 3] corresponding to the predicted choice.

        Raises:
            ValueError: If the implementation returns an out-of-range index.
        """


class BaselineRandom(BenchmarkModel):
    """Random baseline -- uniform random choice among 4 options.

    Expected accuracy: ~25% (1 in 4) with standard deviation.
    Useful as a lower-bound baseline for benchmark comparison.
    """

    def predict(self, question: BenchmarkQuestion) -> int:
        """Return a random index in [0, 3].

        Args:
            question: Ignored -- prediction is purely random.

        Returns:
            Random integer in [0, 3].
        """
        return random.randint(0, 3)


class BaselineHeuristic(BenchmarkModel):
    """Keyword-matching heuristic baseline.

    Matches question text against category-specific keyword maps to find
    a choice containing the matching function name. Falls back to random
    when no keywords match the question text.

    Expected accuracy: >25% on categories with strong keyword signals
    (topology_recognition, troubleshooting). Falls back to ~25% on
    categories without keyword matches.
    """

    _KEYWORD_MAP: dict[str, dict[str, list[str]]] = {
        "topology_recognition": {
            "amplifier": ["amplif", "gain", "buffer", "opamp", "NE5532", "LM358",
                          "op-amp", "non-inverting", "inverting"],
            "filter": ["filter", "cutoff", "resonance", "pole", "Sallen", "Moog",
                        "low-pass", "high-pass", "bandpass", "notch"],
            "compressor": ["compress", "VCA", "THAT4301", "sidechain", "gain_reduction",
                           "limiter"],
            "oscillator": ["oscillator", "LFO", "CD4060", "frequency", "timing",
                           "sine", "square", "triangle", "sawtooth"],
            "power": ["regulator", "voltage", "supply", "LDO", "DC-DC", "boost",
                       "buck", "linear regulator"],
            "mixer": ["mixer", "summing", "pan", "crossfade", "combine"],
            "rectifier": ["rectif", "diode", "bridge", "AC", "DC conversion"],
            "comparator": ["compar", "threshold", "reference", "window"],
            "multiplexer": ["multiplex", "MUX", "selector", "switch", "CD4051",
                             "analog switch"],
        },
        "troubleshooting": {
            "short circuit": ["short", "bridge", "unintended connection"],
            "open circuit": ["open", "not connected", "floating", "no connection"],
            "wrong value": ["wrong value", "incorrect", "tolerance", "mismatch"],
            "missing component": ["missing", "omitted", "not installed", "DNP"],
            "reversed polarity": ["reversed", "polarity", "backwards", "installed wrong"],
            "EMI": ["EMI", "noise", "interference", "coupling", "crosstalk"],
        },
        "component_identification": {
            "resistor": ["resistor", "R", "resistance", "ohm", "potentiometer"],
            "capacitor": ["capacitor", "C", "capacitance", "farad", "ceramic", "electrolytic"],
            "inductor": ["inductor", "L", "choke", "ferrite", "coil"],
            "diode": ["diode", "LED", "Zener", "Schottky", "rectifier diode"],
            "transistor": ["transistor", "FET", "BJT", "MOSFET", "NPN", "PNP"],
            "IC": ["IC", "opamp", "op-amp", "microcontroller", "regulator"],
        },
        "signal_flow": {
            "input": ["input", "source", "signal in", "incoming"],
            "output": ["output", "load", "signal out", "outgoing"],
            "feedback": ["feedback", "loop", "return", "negative feedback"],
            "coupling": ["coupling", "AC coupling", "DC blocking", "coupled"],
        },
        "power_design": {
            "regulation": ["regulator", "LDO", "voltage regulation", "stabilize"],
            "filtering": ["decoupl", "bypass", "filter", "capacitor bank"],
            "protection": ["protection", "fuse", "TVS", "overvoltage", "reverse polarity"],
        },
        "pin_function": {
            "power pin": ["VCC", "VDD", "GND", "VSS", "power", "supply pin"],
            "input pin": ["input", "IN", "signal in", "receive"],
            "output pin": ["output", "OUT", "signal out", "drive"],
            "control pin": ["enable", "reset", "chip select", "CS", "EN"],
        },
        "net_purpose": {
            "power net": ["power", "VCC", "VDD", "supply", "rail"],
            "ground": ["ground", "GND", "VSS", "earth", "return"],
            "signal": ["signal", "data", "clock", "communication"],
            "analog": ["analog", "audio", "sensor", "measurement"],
        },
        "design_rules": {
            "clearance": ["clearance", "spacing", "creepage", "distance"],
            "trace width": ["trace width", "current", "ampacity", "conductor"],
            "thermal": ["thermal", "heat", "dissipation", "temperature", "via"],
        },
    }

    def predict(self, question: BenchmarkQuestion) -> int:
        """Return predicted choice index using keyword matching.

        For the question's category, checks if any keyword group matches
        the question text. If a match is found, returns the index of the
        choice that contains the function name. Falls back to random
        if no match is found.

        Args:
            question: The benchmark question to answer.

        Returns:
            Integer index in [0, 3] of the predicted choice.
        """
        category_map = self._KEYWORD_MAP.get(question.category, {})
        if not category_map:
            return random.randint(0, 3)

        question_lower = question.question.lower()
        choices_lower = [c.lower() for c in question.choices]

        # Check each function/keyword group
        for function_name, keywords in category_map.items():
            # Does the question text contain any keyword?
            if any(kw.lower() in question_lower for kw in keywords):
                # Try to find a choice matching the function name
                for i, choice_lower in enumerate(choices_lower):
                    if function_name.lower() in choice_lower:
                        return i

        # No keyword-function match found -- fall back to random
        return random.randint(0, 3)
