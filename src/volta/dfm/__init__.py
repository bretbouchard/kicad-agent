"""Design for Manufacturing module.

DFM-01 through DFM-05: Pluggable DFM check framework with manufacturer profiles,
multi-stage pipeline, panelization scoring, and assembly checks.

Mirrors analysis/design_rule_engine.py pattern:
- DfmCheck ABC (mirrors DesignRule ABC)
- DfmChecker orchestrator (mirrors DesignRuleEngine)
- ManufacturerProfile (manufacturer-specific constraints)
- DfmReport with manufacturability score (0.0-1.0)
- MultiStageDfmReport with 3-stage pipeline
- PanelizationScore for manufacturing readiness
- AssemblyCheckResult for pick-and-place validation
"""
from volta.dfm.checker import DfmChecker, DfmCheck, DfmReport, DfmFinding, DfmSeverity
from volta.dfm.profiles import ManufacturerProfile, load_profile, get_builtin_profiles
from volta.dfm.scoring import (
    PanelizationScore,
    AssemblyCheckResult,
    MultiStageDfmReport,
    run_multistage_dfm,
    score_panelization_readiness,
    run_assembly_checks,
)

__all__ = [
    "DfmChecker", "DfmCheck", "DfmReport", "DfmFinding", "DfmSeverity",
    "ManufacturerProfile", "load_profile", "get_builtin_profiles",
    "PanelizationScore", "AssemblyCheckResult", "MultiStageDfmReport",
    "run_multistage_dfm", "score_panelization_readiness", "run_assembly_checks",
]
