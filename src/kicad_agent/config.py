"""Agent configuration loader (WORKFLOW-03).

Loads routing, model, and workflow settings from kicad-agent.yaml,
falling back to .kicad_pro project settings, then hardcoded defaults.

Config precedence: CLI args > kicad-agent.yaml > .kicad_pro > defaults

Usage:
    from kicad_agent.config import load_config

    config = load_config(Path("/path/to/project"))
    print(config.routing.target_route_pct)
    print(config.models.vision_model)
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

_CONFIG_FILENAME = "kicad-agent.yaml"


class RoutingConfig(BaseModel):
    """Routing workflow settings."""

    target_route_pct: float = Field(default=95.0, ge=0.0, le=100.0)
    max_iterations: int = Field(default=3, ge=1, le=3)
    strategy: str = "auto"

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> RoutingConfig:
        if not data:
            return cls()
        safe = {k: v for k, v in data.items() if k in cls.model_fields}
        return cls(**safe)


class ModelConfig(BaseModel):
    """Model selection settings."""

    vision_model: str = "gemma-4-12b"
    text_model: str = "qwen2.5-0.5b"
    use_ai: bool = True

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> ModelConfig:
        if not data:
            return cls()
        safe = {k: v for k, v in data.items() if k in cls.model_fields}
        return cls(**safe)


class AgentConfig(BaseModel):
    """Top-level agent configuration."""

    routing: RoutingConfig = Field(default_factory=RoutingConfig)
    models: ModelConfig = Field(default_factory=ModelConfig)

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> AgentConfig:
        if not data:
            return cls()
        return cls(
            routing=RoutingConfig.from_dict(data.get("routing")),
            models=ModelConfig.from_dict(data.get("models")),
        )


def _load_yaml(path: Path) -> dict[str, Any]:
    """Load a YAML file safely.

    Args:
        path: Path to the YAML file.

    Returns:
        Parsed dict, or empty dict if file missing/empty.
    """
    if not path.exists():
        return {}
    try:
        import yaml
        with open(path, encoding="utf-8") as f:
            raw = yaml.safe_load(f)
        return raw if isinstance(raw, dict) else {}
    except Exception as exc:
        logger.warning("Failed to load %s: %s", path, exc)
        return {}


def _extract_from_kicad_pro(project_dir: Path) -> dict[str, Any]:
    """Extract routing-relevant settings from .kicad_pro.

    Looks for a ``kicad_agent`` key in the .kicad_pro JSON, which boards
    can use to override defaults without a separate YAML file.

    Args:
        project_dir: Directory containing .kicad_pro.

    Returns:
        Dict with routing/model keys, or empty dict.
    """
    from kicad_agent.project.project_file import parse_project_file

    pro_path = project_dir / f"{project_dir.name}.kicad_pro"
    if not pro_path.exists():
        return {}
    try:
        proj = parse_project_file(pro_path)
        agent_section = proj.general.get("kicad_agent", {})
        return agent_section if isinstance(agent_section, dict) else {}
    except Exception as exc:
        logger.warning("Failed to read .kicad_pro: %s", exc)
        return {}


def load_config(
    project_dir: Path | str | None = None,
    config_path: Path | str | None = None,
) -> AgentConfig:
    """Load agent configuration with precedence.

    Precedence: config_path > project_dir/kicad-agent.yaml > .kicad_pro > defaults.

    Args:
        project_dir: Project directory to search for config files.
        config_path: Explicit path to a kicad-agent.yaml (overrides discovery).

    Returns:
        Merged AgentConfig.
    """
    # Layer 1: Explicit config file
    if config_path:
        config_path = Path(config_path)
        data = _load_yaml(config_path)
        if data:
            return AgentConfig.from_dict(data)

    # Layer 2: kicad-agent.yaml in project dir
    if project_dir:
        project_dir = Path(project_dir)
        yaml_path = project_dir / _CONFIG_FILENAME
        data = _load_yaml(yaml_path)
        if data:
            return AgentConfig.from_dict(data)

    # Layer 3: .kicad_pro kicad_agent section
    if project_dir:
        pro_data = _extract_from_kicad_pro(project_dir)
        if pro_data:
            return AgentConfig.from_dict(pro_data)

    # Layer 4: Defaults
    return AgentConfig()
