"""Unified native ERC/DRC runner — orchestrates all checks.

Provides a single entry point that runs both ERC (schematic) and DRC (PCB)
checks, merges results, and produces a unified output compatible with the
existing kicad.post_check daemon handler.

This replaces kicad-cli for App Store sandboxed builds.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from kicad_agent.validation.native_erc import run_native_erc, NativeErcResult
from kicad_agent.validation.native_drc import run_native_drc, NativeDrcResult

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class UnifiedCheckResult:
    """Combined result of ERC + DRC + DFM checks."""
    decision: str  # "passed", "failed", "indeterminate"
    erc: dict[str, Any] | None
    drc: dict[str, Any] | None
    failures: list[str]
    total_errors: int
    total_warnings: int
    checks_run: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "decision": self.decision,
            "erc": self.erc,
            "drc": self.drc,
            "failures": self.failures,
            "total_errors": self.total_errors,
            "total_warnings": self.total_warnings,
            "checks_run": self.checks_run,
        }


def run_all_native_checks(
    sch_path: Path | None = None,
    pcb_path: Path | None = None,
    *,
    require_erc: bool = True,
    require_drc: bool = True,
) -> UnifiedCheckResult:
    """Run all applicable native checks.

    Args:
        sch_path: Path to .kicad_sch (None = skip ERC)
        pcb_path: Path to .kicad_pcb (None = skip DRC)
        require_erc: If False, missing ERC is not a failure
        require_drc: If False, missing DRC is not a failure

    Returns:
        UnifiedCheckResult with all violations.
    """
    erc_result: NativeErcResult | None = None
    drc_result: NativeDrcResult | None = None
    failures: list[str] = []
    checks_run: list[str] = []

    # Run ERC
    if sch_path and require_erc:
        try:
            erc_result = run_native_erc(sch_path)
            checks_run.extend(erc_result.checks_run)
            for v in erc_result.violations:
                if v.severity.value == "error":
                    failures.append(f"ERC: {v.description}")
        except Exception as e:
            logger.error(f"ERC failed: {e}")
            failures.append(f"ERC error: {e}")

    # Run DRC
    if pcb_path and require_drc:
        try:
            drc_result = run_native_drc(pcb_path)
            checks_run.extend(drc_result.checks_run)
            for v in drc_result.violations:
                if v.severity == "error":
                    failures.append(f"DRC: {v.description}")
        except Exception as e:
            logger.error(f"DRC failed: {e}")
            failures.append(f"DRC error: {e}")

    total_errors = (erc_result.error_count if erc_result else 0) + \
                   (drc_result.error_count if drc_result else 0)
    total_warnings = (erc_result.warning_count if erc_result else 0) + \
                     (drc_result.warning_count if drc_result else 0)

    if total_errors > 0:
        decision = "failed"
    elif checks_run:
        decision = "passed"
    else:
        decision = "indeterminate"

    return UnifiedCheckResult(
        decision=decision,
        erc=erc_result.to_dict() if erc_result else None,
        drc=drc_result.to_dict() if drc_result else None,
        failures=failures,
        total_errors=total_errors,
        total_warnings=total_warnings,
        checks_run=checks_run,
    )
