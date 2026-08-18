"""Compliance system for KiCad component compliance checking."""

from volta.compliance.provider import (
    ComplianceProvider,
    ComplianceReport,
    ComplianceCapability,
    LifecycleStatus,
    ComplianceProviderRegistry,
)
from volta.compliance.local_provider import LocalComplianceProvider
from volta.compliance.cad_provider import (
    CADModelProvider,
    CADModelImportResult,
    CADModelCapability,
    SnapMagicImportProvider,
)

__all__ = [
    "ComplianceProvider",
    "ComplianceReport", 
    "ComplianceCapability",
    "LifecycleStatus",
    "ComplianceProviderRegistry",
    "LocalComplianceProvider",
    "CADModelProvider",
    "CADModelImportResult",
    "CADModelCapability",
    "SnapMagicImportProvider",
]