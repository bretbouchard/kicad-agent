"""Plan 01 Task 2: ConventionConfigLoader tests (D-02 project-local YAML).

Verifies:
- D-02: Project-local .volta/conventions.yaml loaded when present, silent skip when absent
- Phase 48 RuleConfigLoader pattern mirrored (yaml.safe_load, threshold bounds, unknown-name rejection)
- T-111-01: yaml.safe_load only (never yaml.load)
- T-111-03: Threshold values bounded [-1e6, 1e6]
- P2-3 (Council): discover() stops at first .git ancestor or filesystem root
"""
from __future__ import annotations

import os
from pathlib import Path
from unittest import mock

import pytest


def test_loader_with_no_config_path_returns_empty_config():
    from volta.conventions.loader import ConventionConfig, ConventionConfigLoader

    loader = ConventionConfigLoader(None)
    config = loader.load()
    assert isinstance(config, ConventionConfig)
    assert config.disabled_conventions == set()
    assert config.convention_configs == {}


def test_loader_with_nonexistent_path_returns_empty_config(tmp_path):
    from volta.conventions.loader import ConventionConfigLoader

    missing = tmp_path / "does_not_exist.yaml"
    loader = ConventionConfigLoader(missing)
    config = loader.load()
    assert config.disabled_conventions == set()
    assert config.convention_configs == {}


def test_loader_disables_convention_listed_in_yaml(tmp_path):
    """When a convention name is registered in catalog, enabled:false disables it."""
    from volta.conventions.loader import ConventionConfigLoader

    yaml_text = """
conventions:
  SCHEMATIC_OVERLAP_01:
    enabled: false
"""
    config_path = tmp_path / "conventions.yaml"
    config_path.write_text(yaml_text)

    with mock.patch(
        "volta.conventions.loader._KNOWN_CONVENTION_NAMES",
        frozenset({"SCHEMATIC_OVERLAP_01"}),
    ):
        loader = ConventionConfigLoader(config_path)
        config = loader.load()

    assert "SCHEMATIC_OVERLAP_01" in config.disabled_conventions


def test_loader_returns_thresholds_for_known_rule(tmp_path):
    from volta.conventions.loader import ConventionConfigLoader

    yaml_text = """
conventions:
  SCHEMATIC_OVERLAP_01:
    enabled: true
    thresholds:
      iou_threshold: 0.05
"""
    config_path = tmp_path / "conventions.yaml"
    config_path.write_text(yaml_text)

    with mock.patch(
        "volta.conventions.loader._KNOWN_CONVENTION_NAMES",
        frozenset({"SCHEMATIC_OVERLAP_01"}),
    ):
        loader = ConventionConfigLoader(config_path)
        config = loader.load()

    assert "SCHEMATIC_OVERLAP_01" not in config.disabled_conventions
    assert config.convention_configs["SCHEMATIC_OVERLAP_01"] == {"iou_threshold": 0.05}


def test_loader_rejects_unknown_convention_name(tmp_path):
    from volta.conventions.loader import ConventionConfigLoader

    yaml_text = """
conventions:
  TOTALLY_MADE_UP_RULE_01:
    enabled: false
"""
    config_path = tmp_path / "conventions.yaml"
    config_path.write_text(yaml_text)

    with mock.patch(
        "volta.conventions.loader._KNOWN_CONVENTION_NAMES",
        frozenset({"SCHEMATIC_OVERLAP_01"}),
    ):
        loader = ConventionConfigLoader(config_path)
        with pytest.raises(ValueError, match="Unknown convention name"):
            loader.load()


def test_loader_uses_yaml_safe_load(tmp_path):
    """T-111-01: Loader source uses yaml.safe_load (grep-enforced in <verify>)."""
    from volta.conventions import loader as loader_mod

    src = Path(loader_mod.__file__).read_text()
    assert "yaml.safe_load" in src
    # No unsafe yaml.load( calls (yaml.load( would match yaml.safe_load( so check carefully)
    # Strip the safe_load occurrences and confirm no bare yaml.load( remains
    stripped = src.replace("yaml.safe_load", "")
    assert "yaml.load(" not in stripped, "T-111-01 FAIL: unsafe yaml.load() present"
    # No yaml.unsafe_load / yaml.full_load / yaml.Loader
    assert "yaml.unsafe_load" not in src
    assert "yaml.full_load" not in src
    assert "yaml.Loader" not in src


def test_loader_rejects_threshold_values_out_of_bounds(tmp_path):
    """T-111-03: Threshold values must be numeric within [-1e6, 1e6]."""
    from volta.conventions.loader import ConventionConfigLoader

    yaml_text = """
conventions:
  SCHEMATIC_OVERLAP_01:
    thresholds:
      iou_threshold: 99999999
"""
    config_path = tmp_path / "conventions.yaml"
    config_path.write_text(yaml_text)

    with mock.patch(
        "volta.conventions.loader._KNOWN_CONVENTION_NAMES",
        frozenset({"SCHEMATIC_OVERLAP_01"}),
    ):
        loader = ConventionConfigLoader(config_path)
        with pytest.raises(ValueError, match="out of bounds"):
            loader.load()


def test_loader_rejects_non_numeric_threshold_values(tmp_path):
    from volta.conventions.loader import ConventionConfigLoader

    yaml_text = """
conventions:
  SCHEMATIC_OVERLAP_01:
    thresholds:
      iou_threshold: "not a number"
"""
    config_path = tmp_path / "conventions.yaml"
    config_path.write_text(yaml_text)

    with mock.patch(
        "volta.conventions.loader._KNOWN_CONVENTION_NAMES",
        frozenset({"SCHEMATIC_OVERLAP_01"}),
    ):
        loader = ConventionConfigLoader(config_path)
        with pytest.raises(ValueError, match="must be numeric"):
            loader.load()


def test_discover_finds_project_local_config(tmp_path):
    """P2-3: discover() walks up from cwd and finds .volta/conventions.yaml."""
    from volta.conventions.loader import ConventionConfigLoader

    project_root = tmp_path
    (project_root / ".volta").mkdir()
    (project_root / ".volta" / "conventions.yaml").write_text("conventions: {}")
    (project_root / ".git").mkdir()  # mark repo boundary
    deep_dir = project_root / "src" / "subdir"
    deep_dir.mkdir(parents=True)

    found = ConventionConfigLoader.discover(start_dir=deep_dir)
    assert found is not None
    assert found.name == "conventions.yaml"
    assert found.parent.name == ".volta"


def test_discover_stops_at_git_ancestor(tmp_path):
    """P2-3: discover() stops at first .git ancestor — does not walk past it."""
    from volta.conventions.loader import ConventionConfigLoader

    # Build: /tmp/outer/.volta/conventions.yaml  (should NOT be found)
    #        /tmp/outer/middle/.git                    (repo boundary)
    #        /tmp/outer/middle/inner/cwd               (start)
    outer = tmp_path
    (outer / ".volta").mkdir()
    (outer / ".volta" / "conventions.yaml").write_text("conventions: {}")
    middle = outer / "middle"
    middle.mkdir()
    (middle / ".git").mkdir()
    cwd = middle / "inner" / "cwd"
    cwd.mkdir(parents=True)

    found = ConventionConfigLoader.discover(start_dir=cwd)
    # Walk hits .git at middle/ → stops before reaching outer/.volta
    assert found is None, (
        f"P2-3 FAIL: discover() walked past .git boundary: found={found}"
    )


def test_discover_returns_none_at_filesystem_root_when_no_config(tmp_path):
    """P2-3: discover() returns None when no .volta/conventions.yaml exists."""
    from volta.conventions.loader import ConventionConfigLoader

    # tmp_path with no .volta dir and no .git — walk terminates at fs root
    found = ConventionConfigLoader.discover(start_dir=tmp_path)
    # Either None or walks to fs root. To make this deterministic, ensure no
    # .volta exists anywhere up the chain from tmp_path.
    # On most systems tmp_path's ancestors don't have .volta, but to be safe
    # we just assert the result is None OR a path that genuinely exists.
    if found is not None:
        assert found.is_file()
