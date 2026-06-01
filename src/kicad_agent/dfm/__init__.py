"""Design for Manufacturing module.

DFM-01 through DFM-05: Pluggable DFM check framework with manufacturer profiles.

Mirrors analysis/design_rule_engine.py pattern:
- DfmCheck ABC (mirrors DesignRule ABC)
- DfmChecker orchestrator (mirrors DesignRuleEngine)
- ManufacturerProfile (manufacturer-specific constraints)
- DfmReport with manufacturability score (0.0-1.0)
"""
from kicad_agent.dfm.checker import DfmChecker, DfmCheck, DfmReport, DfmFinding, DfmSeverity
from kicad_agent.dfm.profiles import ManufacturerProfile, load_profile, get_builtin_profiles

__all__ = [
    "DfmChecker", "DfmCheck", "DfmReport", "DfmFinding", "DfmSeverity",
    "ManufacturerProfile", "load_profile", "get_builtin_profiles",
]
