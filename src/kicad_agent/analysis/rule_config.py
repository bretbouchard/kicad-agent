"""YAML-based rule configuration loader.

DOMAIN-04: Per-project design rule configuration.

Config file format (design-rules.yaml):
```yaml
rules:
  BYPASS_CAP_01:
    enabled: true
    thresholds:
      max_distance_mm: 10.0
      min_capacitance_pf: 100
  FEEDBACK_01:
    enabled: true
  IMPEDANCE_01:
    enabled: false
```

Security:
  T-48-06: YAML config validated against known rule names.
  T-48-07: Threshold values validated as numeric with reasonable bounds.
  T-48-10: yaml.safe_load prevents arbitrary code execution.

Usage:
    from kicad_agent.analysis.rule_config import RuleConfigLoader

    loader = RuleConfigLoader("design-rules.yaml")
    config = loader.load()
    engine = DesignRuleEngine(
        rules=get_builtin_rules(),
        disabled_rules=config.disabled_rules,
        config=config.rule_configs,
    )
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from kicad_agent.analysis.builtin_rules import get_builtin_rules

logger = logging.getLogger(__name__)

_KNOWN_RULE_NAMES = frozenset(r.name for r in get_builtin_rules())

# Reasonable bounds for threshold validation (T-48-07)
_MAX_THRESHOLD_VALUE = 1_000_000.0
_MIN_THRESHOLD_VALUE = -1_000_000.0


class RuleConfig:
    """Parsed rule configuration.

    Attributes:
        disabled_rules: Set of rule names to disable.
        rule_configs: Per-rule config dict (thresholds, etc.).
    """

    def __init__(
        self,
        disabled_rules: set[str] | None = None,
        rule_configs: dict[str, dict[str, Any]] | None = None,
    ):
        self.disabled_rules: set[str] = disabled_rules or set()
        self.rule_configs: dict[str, dict[str, Any]] = rule_configs or {}


class RuleConfigLoader:
    """Loads and validates YAML rule configuration.

    Args:
        config_path: Path to YAML config file. None = all defaults.
    """

    def __init__(self, config_path: str | Path | None = None):
        self._path = Path(config_path) if config_path else None

    def load(self) -> RuleConfig:
        """Load and validate configuration from YAML file.

        Returns:
            RuleConfig with disabled rules and per-rule configs.

        Raises:
            ValueError: If config contains unknown rule names or
                invalid threshold values.
        """
        if self._path is None:
            return RuleConfig()

        if not self._path.exists():
            logger.warning(
                "Config file not found: %s -- using defaults", self._path,
            )
            return RuleConfig()

        import yaml

        with open(self._path) as f:
            raw = yaml.safe_load(f) or {}

        rules_section = raw.get("rules", {})
        disabled: set[str] = set()
        configs: dict[str, dict[str, Any]] = {}

        for rule_name, rule_conf in rules_section.items():
            if rule_name not in _KNOWN_RULE_NAMES:
                raise ValueError(
                    f"Unknown rule name in config: {rule_name!r}. "
                    f"Known rules: {sorted(_KNOWN_RULE_NAMES)}"
                )

            if not isinstance(rule_conf, dict):
                continue

            if not rule_conf.get("enabled", True):
                disabled.add(rule_name)

            thresholds = rule_conf.get("thresholds")
            if thresholds:
                if not isinstance(thresholds, dict):
                    raise ValueError(
                        f"Thresholds for {rule_name} must be a dict, "
                        f"got {type(thresholds).__name__}"
                    )
                self._validate_thresholds(rule_name, thresholds)
                configs[rule_name] = thresholds

        return RuleConfig(
            disabled_rules=disabled,
            rule_configs=configs,
        )

    @staticmethod
    def _validate_thresholds(rule_name: str, thresholds: dict[str, Any]) -> None:
        """Validate threshold values are numeric and within bounds.

        T-48-07: Prevents unreasonable threshold values that could
        cause DoS (e.g., extremely large iteration counts).

        Raises:
            ValueError: If any threshold value is not numeric or out of bounds.
        """
        for key, value in thresholds.items():
            if not isinstance(value, (int, float)):
                raise ValueError(
                    f"Threshold {key!r} for rule {rule_name} must be numeric, "
                    f"got {type(value).__name__}"
                )
            if value > _MAX_THRESHOLD_VALUE or value < _MIN_THRESHOLD_VALUE:
                raise ValueError(
                    f"Threshold {key!r} for rule {rule_name} value {value} "
                    f"is out of bounds "
                    f"[{_MIN_THRESHOLD_VALUE}, {_MAX_THRESHOLD_VALUE}]"
                )
