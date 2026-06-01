"""TDD tests for YAML rule configuration loader.

DOMAIN-04: Per-project design rule configuration.

Tests cover:
- RuleConfigLoader loads valid YAML with enabled/disabled rules
- RuleConfigLoader rejects YAML with unknown rule names
- RuleConfigLoader applies custom thresholds to rule config
- RuleConfigLoader defaults to all rules enabled when no config file
- RuleConfigLoader handles missing config file gracefully
"""
from __future__ import annotations

import tempfile
from pathlib import Path

import pytest
import yaml


VALID_CONFIG = {
    "rules": {
        "BYPASS_CAP_01": {"enabled": True, "thresholds": {"max_distance_mm": 10.0}},
        "FEEDBACK_01": {"enabled": True},
        "IMPEDANCE_01": {"enabled": False},
        "THERMAL_01": {"enabled": True},
        "GROUND_01": {"enabled": True},
        "POWER_01": {"enabled": True, "thresholds": {"min_bulk_cap_pf": 1000}},
        "SIGNAL_01": {"enabled": True},
        "LAYOUT_01": {"enabled": True, "thresholds": {"max_components_per_net": 8}},
    }
}

INVALID_CONFIG_UNKNOWN_RULE = {
    "rules": {
        "FAKE_RULE_99": {"enabled": True},
    }
}

PARTIAL_CONFIG = {
    "rules": {
        "BYPASS_CAP_01": {"enabled": False},
        "THERMAL_01": {"enabled": True, "thresholds": {"max_power_w": 2.0}},
    }
}


def _write_yaml(tmp_dir: Path, data: dict, filename: str = "design-rules.yaml") -> Path:
    """Write a YAML config file and return its path."""
    path = tmp_dir / filename
    path.write_text(yaml.dump(data, default_flow_style=False))
    return path


class TestRuleConfigLoader:
    """Tests for RuleConfigLoader."""

    def test_load_valid_config(self, tmp_path: Path):
        """Load valid YAML with enabled/disabled rules."""
        from kicad_agent.analysis.rule_config import RuleConfigLoader

        config_path = _write_yaml(tmp_path, VALID_CONFIG)
        loader = RuleConfigLoader(config_path)
        config = loader.load()

        assert "IMPEDANCE_01" in config.disabled_rules
        assert "BYPASS_CAP_01" not in config.disabled_rules
        assert "FEEDBACK_01" not in config.disabled_rules

    def test_reject_unknown_rule_names(self, tmp_path: Path):
        """Unknown rule names in config raise ValueError."""
        from kicad_agent.analysis.rule_config import RuleConfigLoader

        config_path = _write_yaml(tmp_path, INVALID_CONFIG_UNKNOWN_RULE)
        loader = RuleConfigLoader(config_path)

        with pytest.raises(ValueError, match="Unknown rule name"):
            loader.load()

    def test_apply_custom_thresholds(self, tmp_path: Path):
        """Custom thresholds are parsed into rule_configs dict."""
        from kicad_agent.analysis.rule_config import RuleConfigLoader

        config_path = _write_yaml(tmp_path, VALID_CONFIG)
        loader = RuleConfigLoader(config_path)
        config = loader.load()

        assert config.rule_configs["BYPASS_CAP_01"]["max_distance_mm"] == 10.0
        assert config.rule_configs["POWER_01"]["min_bulk_cap_pf"] == 1000
        assert config.rule_configs["LAYOUT_01"]["max_components_per_net"] == 8

    def test_defaults_all_enabled_no_config(self):
        """No config path returns all rules enabled with empty overrides."""
        from kicad_agent.analysis.rule_config import RuleConfigLoader

        loader = RuleConfigLoader(None)
        config = loader.load()

        assert config.disabled_rules == set()
        assert config.rule_configs == {}

    def test_missing_config_file_returns_defaults(self, tmp_path: Path):
        """Missing config file returns defaults instead of raising."""
        from kicad_agent.analysis.rule_config import RuleConfigLoader

        fake_path = tmp_path / "nonexistent.yaml"
        loader = RuleConfigLoader(fake_path)
        config = loader.load()

        assert config.disabled_rules == set()
        assert config.rule_configs == {}

    def test_partial_config_only_specified_rules(self, tmp_path: Path):
        """Partial config only affects explicitly listed rules."""
        from kicad_agent.analysis.rule_config import RuleConfigLoader

        config_path = _write_yaml(tmp_path, PARTIAL_CONFIG)
        loader = RuleConfigLoader(config_path)
        config = loader.load()

        assert "BYPASS_CAP_01" in config.disabled_rules
        assert "THERMAL_01" not in config.disabled_rules
        assert config.rule_configs.get("THERMAL_01", {}).get("max_power_w") == 2.0

    def test_empty_yaml_returns_defaults(self, tmp_path: Path):
        """Empty YAML file returns defaults."""
        from kicad_agent.analysis.rule_config import RuleConfigLoader

        config_path = _write_yaml(tmp_path, {})
        loader = RuleConfigLoader(config_path)
        config = loader.load()

        assert config.disabled_rules == set()
        assert config.rule_configs == {}
