"""ConventionConfigLoader (Plan 01 Task 2).

D-02 (CONTEXT): Project-local .kicad-agent/conventions.yaml loader. Mirrors
                Phase 48 RuleConfigLoader pattern.
T-111-01: yaml.safe_load only (never yaml.load) — security.
T-111-03: Threshold values bounded [-1e6, 1e6].
T-111-15 / P2-3 (Council): discover() upward walk stops at first .git ancestor
                           or filesystem root — never walks indefinitely.

_KNOWN_CONVENTION_NAMES is populated by the catalog module (Plan 02 Task 1).
Until then it's an empty frozenset — the loader rejects ALL rule names until
the catalog registers them. This is correct: Plan 01 has no catalog to
validate against.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Populated by Plan 02 Task 1 (catalog registers names via lazy import).
# Empty until then — loader rejects all rule names.
_KNOWN_CONVENTION_NAMES: frozenset[str] = frozenset()

# T-111-03: Reasonable bounds for threshold validation (mirrors Phase 48).
_MAX_THRESHOLD_VALUE = 1_000_000.0
_MIN_THRESHOLD_VALUE = -1_000_000.0

# D-02: project-local filename.
_PROJECT_LOCAL_FILENAME = ".kicad-agent/conventions.yaml"

# P2-3: stop marker — discover() halts at first ancestor containing this dir.
_STOP_MARKER = ".git"


def _refresh_known_convention_names() -> frozenset[str]:
    """Refresh _KNOWN_CONVENTION_NAMES from the catalog (Plan 02) if importable.

    The catalog registers Convention subclasses with class-level rule_id attrs
    (P0-3). We import lazily so Plan 01 tests pass before the catalog exists.
    On any import failure (catalog not yet shipped), return the current value.
    """
    global _KNOWN_CONVENTION_NAMES
    try:
        # Local import — avoids circular dependency at module load.
        from volta.conventions.catalog import get_v1_catalog  # type: ignore

        catalog = get_v1_catalog()
        names = frozenset(c.rule_id for c in catalog)
        if names:
            _KNOWN_CONVENTION_NAMES = names
    except Exception:  # noqa: BLE001 — catalog optional at Plan 01 ship time
        pass
    return _KNOWN_CONVENTION_NAMES


class ConventionConfig:
    """Parsed convention configuration.

    Attributes:
        disabled_conventions: Set of rule_id names to skip.
        convention_configs: Per-rule thresholds dict (rule_id -> {key: value}).
    """

    def __init__(
        self,
        disabled_conventions: set[str] | None = None,
        convention_configs: dict[str, dict[str, Any]] | None = None,
    ):
        self.disabled_conventions: set[str] = disabled_conventions or set()
        self.convention_configs: dict[str, dict[str, Any]] = convention_configs or {}


class ConventionConfigLoader:
    """Loads .kicad-agent/conventions.yaml per D-02.

    Mirrors Phase 48 RuleConfigLoader (yaml.safe_load, threshold validation,
    unknown-name rejection). Construction is cheap; load() does the I/O.
    """

    def __init__(self, config_path: str | Path | None = None):
        self._path = Path(config_path) if config_path else None

    @classmethod
    def discover(cls, start_dir: Path | None = None) -> Path | None:
        """Walk up from start_dir (default: cwd) looking for the project-local file.

        P2-3 (Council): STOPS at the first ancestor containing a `.git` directory
        or at the filesystem root. NEVER walks indefinitely. This prevents a
        planted .kicad-agent/conventions.yaml high in the filesystem from being
        reached when the user's cwd is inside any git project.

        Returns:
            Path to the discovered config, or None if not found within bounds.
        """
        current = (start_dir or Path.cwd()).resolve()
        # Check current dir, then walk parents. Stop at .git ancestor.
        candidates = [current, *current.parents]
        for idx, parent in enumerate(candidates):
            candidate = parent / _PROJECT_LOCAL_FILENAME
            if candidate.is_file():
                return candidate
            if (parent / _STOP_MARKER).exists():
                # P2-3: do not walk past the .git boundary
                return None
        return None  # filesystem root reached

    def load(self) -> ConventionConfig:
        """Load and validate YAML. Returns empty config if path is None or missing.

        Raises:
            ValueError: If config contains unknown convention names or invalid
                threshold values.
        """
        if self._path is None or not self._path.is_file():
            if self._path is not None:
                logger.debug(
                    "Convention config not found: %s — using defaults", self._path,
                )
            return ConventionConfig()

        # Refresh known names from catalog (no-op if catalog not shipped yet).
        known = _refresh_known_convention_names()

        import yaml  # local import keeps top-level lean

        with open(self._path) as f:
            raw = yaml.safe_load(f) or {}  # T-111-01: safe_load only

        conventions_section = raw.get("conventions", {})
        disabled: set[str] = set()
        configs: dict[str, dict[str, Any]] = {}

        for rule_name, rule_conf in conventions_section.items():
            # T-111-05: reject unknown rule names (catalog-aware).
            if known and rule_name not in known:
                raise ValueError(
                    f"Unknown convention name in config: {rule_name!r}. "
                    f"Known conventions: {sorted(known)}"
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

        return ConventionConfig(
            disabled_conventions=disabled,
            convention_configs=configs,
        )

    @staticmethod
    def _validate_thresholds(rule_name: str, thresholds: dict[str, Any]) -> None:
        """T-111-03: Validate threshold values are numeric within bounds."""
        for key, value in thresholds.items():
            if not isinstance(value, (int, float)) or isinstance(value, bool):
                raise ValueError(
                    f"Threshold {key!r} for convention {rule_name} must be numeric, "
                    f"got {type(value).__name__}"
                )
            if value > _MAX_THRESHOLD_VALUE or value < _MIN_THRESHOLD_VALUE:
                raise ValueError(
                    f"Threshold {key!r} for convention {rule_name} value {value} "
                    f"is out of bounds "
                    f"[{_MIN_THRESHOLD_VALUE}, {_MAX_THRESHOLD_VALUE}]"
                )
