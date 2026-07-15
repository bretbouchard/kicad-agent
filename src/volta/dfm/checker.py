"""DFM checker orchestrator and schemas.

DFM-01: DfmChecker orchestrator mirrors DesignRuleEngine pattern.
DfmCheck ABC with check(spatial_model, profile, config) method.
DfmReport with manufacturability score (0.0-1.0).
"""
from __future__ import annotations

import logging
import time
from abc import ABC, abstractmethod
from enum import Enum
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from volta.spatial.pcb_model import PcbSpatialModel
    from volta.dfm.profiles import ManufacturerProfile

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class DfmSeverity(str, Enum):
    """DFM finding severity."""

    PASS = "PASS"
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"


class DfmFinding(BaseModel):
    """A single DFM finding from a manufacturability check.

    Attributes:
        check_id: Check identifier (e.g. "ANNULAR_RING_01").
        description: What was found and why it matters.
        severity: Finding severity level.
        location: Where in the design (component ref, pad number, or coordinate).
        suggestion: Concrete fix recommendation.
        affected_entities: Entity IDs involved.
        details: Additional context (dimensions, coordinates).
    """

    check_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Z][A-Z0-9_]*\d{2}$")
    description: str = Field(min_length=1, max_length=2000)
    severity: DfmSeverity
    location: str = Field(default="", max_length=512)
    suggestion: str = Field(default="", max_length=1000)
    affected_entities: tuple[str, ...] = Field(default_factory=tuple)
    details: dict[str, Any] = Field(default_factory=dict)


class DfmReport(BaseModel):
    """Aggregated DFM report with manufacturability score.

    Score formula: 1.0 - (critical * 0.1 + warning * 0.02 + info * 0.005)
    Clamped to [0.0, 1.0].

    Attributes:
        findings: All findings, sorted by severity (CRITICAL first).
        board_path: Path to the checked PCB file.
        profile_name: Manufacturer profile used for checks.
        checks_run: Number of checks executed.
        checks_passed: Number of checks with no findings.
        checks_failed: Number of checks with findings.
        manufacturability_score: 0.0 (unmanufacturable) to 1.0 (clean).
        summary: Count of findings per severity.
        elapsed_ms: Total execution time.
    """

    findings: tuple[DfmFinding, ...] = Field(default_factory=tuple, max_length=500)
    board_path: str = Field(default="")
    profile_name: str = Field(default="")
    checks_run: int = Field(default=0, ge=0)
    checks_passed: int = Field(default=0, ge=0)
    checks_failed: int = Field(default=0, ge=0)
    manufacturability_score: float = Field(default=1.0, ge=0.0, le=1.0)
    summary: dict[str, int] = Field(default_factory=dict)
    elapsed_ms: float = Field(default=0.0, ge=0.0)

    def model_post_init(self, __context: Any) -> None:
        """Compute summary counts and manufacturability score from findings."""
        counts = {s.value: 0 for s in DfmSeverity}
        for f in self.findings:
            counts[f.severity.value] += 1
        self.summary = counts

        # Score formula: 1.0 - weighted penalty, clamped to [0.0, 1.0]
        penalty = (
            counts[DfmSeverity.CRITICAL.value] * 0.1
            + counts[DfmSeverity.WARNING.value] * 0.02
            + counts[DfmSeverity.INFO.value] * 0.005
        )
        self.manufacturability_score = max(0.0, min(1.0, 1.0 - penalty))


class DfmCheck(ABC):
    """Abstract base class for DFM checks.

    Subclass this to create custom DFM checks. Register with
    DfmChecker to run them against PCB spatial models.

    Attributes:
        name: Check identifier (e.g. "ANNULAR_RING_01").
        description: What this check validates.
    """

    name: str
    description: str = ""

    @abstractmethod
    def check(
        self,
        spatial_model: Any,
        profile: Any,
        config: dict[str, Any] | None = None,
    ) -> list[DfmFinding]:
        """Check the PCB spatial model against manufacturer profile constraints.

        Args:
            spatial_model: PcbSpatialModel to check.
            profile: ManufacturerProfile with minimum constraints.
            config: Optional configuration overrides.

        Returns:
            List of findings. Empty list if no issues found.
        """
        ...


class DfmChecker:
    """Orchestrates DFM check execution.

    Loads checks, runs them against a PCB spatial model with a
    manufacturer profile, and produces a DfmReport with all findings
    and a manufacturability score.

    Mirrors DesignRuleEngine pattern from analysis/design_rule_engine.py.

    Args:
        checks: List of DfmCheck instances to run.
        disabled_checks: Set of check names to skip.
        config: Per-check configuration overrides.

    Usage:
        from volta.dfm.checks import get_builtin_dfm_checks

        checker = DfmChecker(checks=get_builtin_dfm_checks())
        report = checker.run(spatial_model, profile)
        for f in report.findings:
            print(f"[{f.severity.value}] {f.check_id}: {f.description}")
    """

    def __init__(
        self,
        checks: list[DfmCheck] | None = None,
        disabled_checks: set[str] | None = None,
        config: dict[str, dict[str, Any]] | None = None,
    ):
        self._checks = checks or []
        self._disabled = disabled_checks or set()
        self._config = config or {}

    def run(self, spatial_model: Any, profile: Any) -> DfmReport:
        """Run all enabled checks against the PCB spatial model.

        Algorithm:
        1. Filter out disabled checks
        2. For each enabled check, call check() with config
        3. Collect findings, handle errors gracefully
        4. Sort findings by severity (CRITICAL first)
        5. Build and return DfmReport

        Error handling: if a check raises an exception, log it
        and continue with remaining checks. Never let one broken
        check kill the entire run.

        Args:
            spatial_model: PcbSpatialModel to check.
            profile: ManufacturerProfile with minimum constraints.

        Returns:
            DfmReport with all findings, score, and summary.
        """
        start = time.monotonic()
        all_findings: list[DfmFinding] = []
        checks_run = 0
        checks_passed = 0
        checks_failed = 0

        for check in self._checks:
            if check.name in self._disabled:
                logger.debug("Skipping disabled check: %s", check.name)
                continue

            checks_run += 1
            check_config = self._config.get(check.name, {})

            try:
                findings = check.check(spatial_model, profile, config=check_config)
            except Exception as e:
                logger.error(
                    "Check %s raised exception: %s", check.name, e,
                    exc_info=True,
                )
                findings = [DfmFinding(
                    check_id="DFM_CHECKER_01",
                    description=f"Check execution failed ({check.name}): {e}",
                    severity=DfmSeverity.WARNING,
                    location="(dfm checker)",
                    suggestion=f"Report this as a bug: check {check.name} crashed",
                )]

            if findings:
                checks_failed += 1
                all_findings.extend(findings)
            else:
                checks_passed += 1

        # Sort: CRITICAL > WARNING > INFO > PASS
        severity_order = {
            DfmSeverity.CRITICAL: 0,
            DfmSeverity.WARNING: 1,
            DfmSeverity.INFO: 2,
            DfmSeverity.PASS: 3,
        }
        all_findings.sort(key=lambda f: severity_order[f.severity])

        elapsed = (time.monotonic() - start) * 1000

        profile_name = getattr(profile, "name", str(profile))
        board_path = getattr(spatial_model, "board_path", "")

        return DfmReport(
            findings=tuple(all_findings),
            board_path=board_path,
            profile_name=profile_name,
            checks_run=checks_run,
            checks_passed=checks_passed,
            checks_failed=checks_failed,
            elapsed_ms=elapsed,
        )

    def add_check(self, check: DfmCheck) -> None:
        """Add a check to the checker."""
        self._checks.append(check)

    def disable_check(self, check_name: str) -> None:
        """Disable a check by name."""
        self._disabled.add(check_name)

    def enable_check(self, check_name: str) -> None:
        """Re-enable a previously disabled check."""
        self._disabled.discard(check_name)

    @property
    def check_names(self) -> list[str]:
        """List all registered check names."""
        return [c.name for c in self._checks]
