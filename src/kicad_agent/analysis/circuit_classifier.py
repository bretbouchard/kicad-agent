"""Rule-based subcircuit type classification.

Follows the same ordered-rule pattern as violation_classifier.py:
first matching rule wins. Rules match on IC lib_id + surrounding
component features.

DOMAIN-02: Subcircuit type classification for function recognition.

Usage:
    from kicad_agent.analysis.circuit_classifier import CircuitClassifier

    classifier = CircuitClassifier()
    result = classifier.classify(features)
    print(f"{result.type.value} (confidence={result.confidence:.2f})")
"""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Any, Union

from kicad_agent.analysis.subcircuit_detector import SubcircuitType

logger = logging.getLogger(__name__)


# Classification rules -- ordered list, first match wins.
# Each rule: (match_fn, subcircuit_type, confidence, description)
RuleTuple = tuple[
    callable,           # match function: (features: dict) -> bool
    SubcircuitType,     # classification
    float,              # confidence: 0.0 - 1.0
    str,                # description
]


# --- Match functions ---


def _is_compressor(features: dict) -> bool:
    """THAT4301/THAT2181 VCA with sidechain RC network."""
    lib_id = features.get("lib_id", "").upper()
    return (
        any(vca in lib_id for vca in ["THAT4301", "THAT2181"])
        and features.get("has_sidechain", False)
    )


def _is_vca(features: dict) -> bool:
    """THAT4301/THAT2181 without sidechain."""
    lib_id = features.get("lib_id", "").upper()
    return any(vca in lib_id for vca in ["THAT4301", "THAT2181"])


def _is_filter(features: dict) -> bool:
    """Op-amp with capacitors in feedback path."""
    comp_type = features.get("component_type", "")
    lib_id = features.get("lib_id", "").upper()
    return (
        comp_type == "ic"
        and any(op in lib_id for op in ["NE5532", "TL072", "LM358", "LM324", "OPA2134", "OP07", "OP27", "AD712"])
        and features.get("feedback_capacitor_count", 0) > 0
    )


def _is_preamplifier(features: dict) -> bool:
    """Op-amp with resistive feedback, no caps in feedback, at least 2 resistors."""
    comp_type = features.get("component_type", "")
    lib_id = features.get("lib_id", "").upper()
    return (
        comp_type == "ic"
        and any(op in lib_id for op in ["NE5532", "TL072", "LM358", "LM324", "OPA2134"])
        and features.get("resistor_count", 0) >= 2
        and features.get("feedback_resistor_count", 0) > 0
        and features.get("feedback_capacitor_count", 0) == 0
        and not features.get("has_multiple_inputs", False)
    )


def _is_mixer(features: dict) -> bool:
    """Op-amp with multiple input networks."""
    comp_type = features.get("component_type", "")
    lib_id = features.get("lib_id", "").upper()
    return (
        comp_type == "ic"
        and any(op in lib_id for op in ["NE5532", "TL072", "LM358", "LM324"])
        and features.get("has_multiple_inputs", False)
    )


def _is_output_stage(features: dict) -> bool:
    """Op-amp configured as output buffer/driver."""
    comp_type = features.get("component_type", "")
    lib_id = features.get("lib_id", "").upper()
    return (
        comp_type == "ic"
        and any(op in lib_id for op in ["NE5532", "TL072", "LM358"])
        and features.get("resistor_count", 0) <= 2
        and features.get("capacitor_count", 0) <= 2
        and features.get("feedback_resistor_count", 0) > 0
    )


def _is_lfo(features: dict) -> bool:
    """Oscillator with RC timing for low-frequency generation."""
    lib_id = features.get("lib_id", "").upper()
    return (
        "CD4060" in lib_id
        and features.get("capacitor_count", 0) >= 2
        and features.get("resistor_count", 0) >= 2
    )


def _is_oscillator(features: dict) -> bool:
    """CD4060 or crystal oscillator circuit."""
    lib_id = features.get("lib_id", "").upper()
    return (
        "CD4060" in lib_id
        or (features.get("has_crystal", False) and features.get("resistor_count", 0) <= 2)
    )


def _is_power_supply(features: dict) -> bool:
    """Voltage regulator with filter capacitors."""
    lib_id = features.get("lib_id", "").upper()
    return any(
        reg in lib_id
        for reg in ["LM7805", "LM7812", "LM317", "7912", "7805", "7812", "LM2931", "AMS1117"]
    )


def _is_digital_control(features: dict) -> bool:
    """MCU with crystal and decoupling."""
    lib_id = features.get("lib_id", "").upper()
    return any(mcu in lib_id for mcu in ["RP2040", "ATMEGA", "STM32", "ESP32", "TEENSY"])


def _is_analog_switch(features: dict) -> bool:
    """CD4066 analog switch."""
    lib_id = features.get("lib_id", "").upper()
    return "CD4066" in lib_id


def _is_envelope(features: dict) -> bool:
    """RC envelope generator (ADSR-style)."""
    return (
        features.get("capacitor_count", 0) >= 3
        and features.get("resistor_count", 0) >= 3
        and features.get("diode_count", 0) >= 1
        and features.get("component_type", "") == "misc"
    )


def _is_protection(features: dict) -> bool:
    """Diode/transistor protection circuit."""
    return (
        features.get("diode_count", 0) >= 2
        and features.get("component_type", "") != "ic"
    )


# Ordered rules -- first match wins
_CLASSIFICATION_RULES: list[RuleTuple] = [
    (_is_compressor, SubcircuitType.COMPRESSOR, 0.9, "VCA with sidechain"),
    (_is_vca, SubcircuitType.VCA, 0.85, "VCA without sidechain"),
    (_is_filter, SubcircuitType.FILTER, 0.85, "Op-amp with capacitive feedback"),
    (_is_preamplifier, SubcircuitType.PREAMP, 0.8, "Op-amp with resistive feedback"),
    (_is_mixer, SubcircuitType.MIXER, 0.8, "Op-amp summing multiple inputs"),
    (_is_output_stage, SubcircuitType.OUTPUT_STAGE, 0.7, "Op-amp output buffer"),
    (_is_lfo, SubcircuitType.LFO, 0.85, "Low-frequency oscillator with RC timing"),
    (_is_oscillator, SubcircuitType.OSCILLATOR, 0.85, "Oscillator circuit"),
    (_is_power_supply, SubcircuitType.POWER_SUPPLY, 0.9, "Voltage regulator"),
    (_is_digital_control, SubcircuitType.DIGITAL_CONTROL, 0.9, "MCU with crystal"),
    (_is_analog_switch, SubcircuitType.ANALOG_SWITCH, 0.9, "Analog switch IC"),
    (_is_envelope, SubcircuitType.ENVELOPE, 0.7, "RC envelope generator"),
    (_is_protection, SubcircuitType.PROTECTION, 0.6, "Diode protection circuit"),
]


@dataclass(frozen=True)
class ClassificationResult:
    """Result of classifying a subcircuit."""

    subcircuit_type: SubcircuitType
    confidence: float
    matched_rule: str  # Description of the rule that matched
    feature_vector: dict | None = None  # Feature dict for audit/ML pipeline


class CircuitClassifier:
    """Rule-based subcircuit type classifier.

    Follows violation_classifier pattern: ordered rules, first match wins.
    Rules match on IC lib_id + surrounding component features.
    """

    def __init__(self, custom_rules: list[RuleTuple] | None = None):
        """Initialize with optional custom rules prepended before defaults.

        Args:
            custom_rules: Additional rules to check before default rules.
        """
        self._rules = (custom_rules or []) + _CLASSIFICATION_RULES

    def classify(
        self, features: dict[str, Any] | "SubcircuitFeatures",  # noqa: F821
    ) -> ClassificationResult:
        """Classify a subcircuit by its features.

        Accepts raw dict or SubcircuitFeatures. Converts SubcircuitFeatures
        to dict internally for rule matching.

        Args:
            features: Dict of subcircuit features or SubcircuitFeatures instance.

        Returns:
            ClassificationResult with type, confidence, matched rule, and
            optional feature_vector for low-confidence results.
        """
        from kicad_agent.analysis.feature_extraction import SubcircuitFeatures

        if isinstance(features, SubcircuitFeatures):
            feat_dict = features.to_dict()
        else:
            feat_dict = features

        for match_fn, sc_type, confidence, description in self._rules:
            if match_fn(feat_dict):
                return ClassificationResult(
                    subcircuit_type=sc_type,
                    confidence=confidence,
                    matched_rule=description,
                    feature_vector=feat_dict if confidence < 0.5 else None,
                )

        # No match -- log for ML training data
        logger.info(
            "Unknown subcircuit classification: features=%s",
            json.dumps(feat_dict, default=str),
        )
        return ClassificationResult(
            subcircuit_type=SubcircuitType.UNKNOWN,
            confidence=0.3,
            matched_rule="No rule matched",
            feature_vector=feat_dict,
        )

    def classify_batch(
        self,
        feature_list: list[dict[str, Any] | "SubcircuitFeatures"],  # noqa: F821
    ) -> list[ClassificationResult]:
        """Classify multiple subcircuits at once.

        Args:
            feature_list: List of feature dicts or SubcircuitFeatures instances.

        Returns:
            List of ClassificationResult, one per input.
        """
        return [self.classify(f) for f in feature_list]
