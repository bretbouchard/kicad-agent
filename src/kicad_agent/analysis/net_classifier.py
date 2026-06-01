"""Rule-based net classification using naming patterns and topology context.

Follows the same ordered-rule pattern as violation_classifier.py:
first matching rule wins. Rules are applied in priority order:
1. Topology-based rules (if all connected pins are power pins -> POWER)
2. Exact name patterns (VCC -> POWER, GND -> GROUND)
3. Regex patterns (+\\d+V -> POWER, .*CLK.* -> CLOCK)
4. Fallback -> UNKNOWN

DOMAIN-01: Net classification for circuit topology.

Usage:
    from kicad_agent.analysis.net_classifier import NetClassifier

    classifier = NetClassifier()
    result = classifier.classify("VCC_AUDIO")
    assert result == NetClassification.POWER
"""

from __future__ import annotations

import re
from enum import Enum
from typing import Optional

from kicad_agent.analysis.types import NetClassification, PinRole


class SignalIntegrity(str, Enum):
    """Signal integrity classification for nets."""

    HIGH_SPEED = "HIGH_SPEED"           # Clocks, fast digital edges, SPI, I2C
    LOW_FREQUENCY = "LOW_FREQUENCY"     # Audio, slow analog, control voltages
    DC = "DC"                           # Static DC levels, bias voltages
    POWER_INTEGRITY = "POWER_INTEGRITY"  # Power rails, ground
    UNKNOWN = "UNKNOWN"


class NetImportance(str, Enum):
    """Importance ranking for nets."""

    CRITICAL = "CRITICAL"   # Power, clock -- failure causes system-wide issues
    HIGH = "HIGH"           # Feedback, control -- failure causes functional issues
    MEDIUM = "MEDIUM"       # Signal -- failure degrades performance
    LOW = "LOW"             # Unknown, test points -- failure is minor


# Classification rules -- ordered list, first match wins.
# Each rule: (match_fn, classification, description)
RuleTuple = tuple[
    callable,              # match function: (net_name, pin_roles) -> bool
    NetClassification,     # classification
    str,                   # description
]

# Signal integrity rules -- ordered list, first match wins.
SIRuleTuple = tuple[
    callable,              # match function: (net_name, pin_roles) -> bool
    SignalIntegrity,       # signal integrity classification
    str,                   # description
]

# Name patterns for classification
_POWER_NAMES = {"VCC", "VDD", "V+", "VEE", "VAA", "VCC_AUDIO", "VDD_DIGITAL"}
_POWER_PREFIXES = ["+3V3", "+5V", "+9V", "+12V", "-9V", "-12V", "+3.3V", "+5VA", "+15V", "-15V"]
_POWER_VOLTAGE_PATTERN = re.compile(r'^[+-]\d+\.?\d*V', re.IGNORECASE)
_GROUND_NAMES = {"GND", "VSS", "AGND", "PGND", "DGND", "CHASSIS", "EARTH", "GNDA"}
_CLOCK_PATTERNS = [re.compile(p, re.IGNORECASE) for p in [
    r"^CLK", r"MCLK", r"BCLK", r"LRCLK", r"SCK$", r"XTAL", r"OSC",
    r"_CLK$", r"CLOCK",
]]
_CONTROL_PATTERNS = [re.compile(p, re.IGNORECASE) for p in [
    r"^EN$", r"^CS$", r"^RST$", r"^RESET$", r"^WR$", r"^RD$",
    r"^SEL$", r"^SDA$", r"^SCL$", r"^TX$", r"^RX$", r"^MOSI$",
    r"^MISO$", r"^SS$", r"^MUTE$", r"^BYPASS$",
]]


def _is_power_by_name(name: str, _pin_roles: dict[str, PinRole]) -> bool:
    upper = name.upper()
    if upper in _POWER_NAMES:
        return True
    for prefix in _POWER_PREFIXES:
        if upper.startswith(prefix):
            return True
    if _POWER_VOLTAGE_PATTERN.match(upper):
        return True
    return False


def _is_ground_by_name(name: str, _pin_roles: dict[str, PinRole]) -> bool:
    return name.upper() in _GROUND_NAMES or name.upper().startswith("GND")


def _is_clock_by_name(name: str, _pin_roles: dict[str, PinRole]) -> bool:
    return any(p.search(name) for p in _CLOCK_PATTERNS)


def _is_control_by_name(name: str, _pin_roles: dict[str, PinRole]) -> bool:
    return any(p.search(name) for p in _CONTROL_PATTERNS)


def _is_power_by_topology(_name: str, pin_roles: dict[str, PinRole]) -> bool:
    """All connected pins are power pins -> this is a power net."""
    if not pin_roles:
        return False
    return all(role == PinRole.POWER for role in pin_roles.values())


# Ordered rules -- first match wins
_CLASSIFICATION_RULES: list[RuleTuple] = [
    (_is_power_by_name, NetClassification.POWER, "Named power rail"),
    (_is_ground_by_name, NetClassification.GROUND, "Named ground net"),
    (_is_clock_by_name, NetClassification.CLOCK, "Clock signal"),
    (_is_control_by_name, NetClassification.CONTROL, "Control signal"),
    (_is_power_by_topology, NetClassification.POWER, "All power pins"),
]

# Signal integrity rules -- ordered list, first match wins.
_SIGNAL_INTEGRITY_RULES: list[SIRuleTuple] = [
    # Clock patterns -> HIGH_SPEED
    (_is_clock_by_name, SignalIntegrity.HIGH_SPEED, "Clock signal"),
    # High-speed digital patterns -> HIGH_SPEED
    (_is_control_by_name, SignalIntegrity.HIGH_SPEED, "Digital control"),
    # Power by name -> POWER_INTEGRITY
    (_is_power_by_name, SignalIntegrity.POWER_INTEGRITY, "Power rail"),
    # Ground by name -> POWER_INTEGRITY
    (_is_ground_by_name, SignalIntegrity.POWER_INTEGRITY, "Ground net"),
    # Power by topology -> POWER_INTEGRITY
    (_is_power_by_topology, SignalIntegrity.POWER_INTEGRITY, "All power pins"),
    # Audio/analog signal patterns -> LOW_FREQUENCY
    (lambda name, _: bool(re.search(r"(SIG|AUDIO|IN|OUT|INPUT|OUTPUT)", name, re.IGNORECASE)),
     SignalIntegrity.LOW_FREQUENCY, "Analog signal"),
    # DC bias/reference patterns -> DC
    (lambda name, _: bool(re.search(r"(BIAS|REF|VREF|OFFSET)", name, re.IGNORECASE)),
     SignalIntegrity.DC, "DC reference"),
]

# Importance mapping from classification
_IMPORTANCE_MAP: dict[NetClassification, NetImportance] = {
    NetClassification.POWER: NetImportance.CRITICAL,
    NetClassification.GROUND: NetImportance.CRITICAL,
    NetClassification.CLOCK: NetImportance.CRITICAL,
    NetClassification.FEEDBACK: NetImportance.HIGH,
    NetClassification.CONTROL: NetImportance.HIGH,
    NetClassification.SIGNAL: NetImportance.MEDIUM,
    NetClassification.UNKNOWN: NetImportance.LOW,
}


class NetClassifier:
    """Rule-based net classifier using naming patterns and topology context.

    Follows violation_classifier pattern: ordered rules, first match wins.
    """

    def __init__(self, custom_rules: list[RuleTuple] | None = None):
        """Initialize with optional custom rules prepended before defaults.

        Args:
            custom_rules: Additional rules to check before default rules.
        """
        self._rules = (custom_rules or []) + _CLASSIFICATION_RULES
        self._si_rules = _SIGNAL_INTEGRITY_RULES
        self._importance_map = _IMPORTANCE_MAP

    def classify(self, net_name: str, pin_roles: dict[str, PinRole] | None = None) -> NetClassification:
        """Classify a net by name and topology context.

        Args:
            net_name: The net name to classify.
            pin_roles: Optional mapping of (ref, pin) -> PinRole for topology override.

        Returns:
            NetClassification for the net.
        """
        roles = pin_roles or {}
        for match_fn, classification, _desc in self._rules:
            if match_fn(net_name, roles):
                return classification
        return NetClassification.UNKNOWN

    def classify_many(self, nets: dict[str, dict[str, PinRole]]) -> dict[str, NetClassification]:
        """Classify multiple nets at once.

        Args:
            nets: Mapping of net_name -> {(ref, pin): PinRole}.

        Returns:
            Mapping of net_name -> NetClassification.
        """
        return {name: self.classify(name, roles) for name, roles in nets.items()}

    def classify_signal_integrity(self, net_name: str, pin_roles: dict[str, PinRole] | None = None) -> SignalIntegrity:
        """Classify signal integrity based on name and topology.

        Args:
            net_name: The net name to classify.
            pin_roles: Optional mapping of (ref, pin) -> PinRole for topology override.

        Returns:
            SignalIntegrity for the net.
        """
        roles = pin_roles or {}
        for match_fn, integrity, _desc in self._si_rules:
            if match_fn(net_name, roles):
                return integrity
        return SignalIntegrity.UNKNOWN

    def rank_importance(self, classification: NetClassification) -> NetImportance:
        """Map net classification to importance ranking.

        Args:
            classification: The NetClassification to rank.

        Returns:
            NetImportance for the classification.
        """
        return self._importance_map.get(classification, NetImportance.LOW)
