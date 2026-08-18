"""Local compliance provider implementation for KiCad compliance checking.

This module provides a compliance provider that checks component compliance
using local cached data rather than external API calls.
"""

import json
import os
import tempfile
from pathlib import Path
from typing import Set, Optional
from datetime import datetime, timedelta

from volta.compliance.provider import (
    ComplianceProvider, 
    ComplianceReport, 
    ComplianceCapability,
    LifecycleStatus
)


class LocalComplianceProvider(ComplianceProvider):
    """Compliance provider that uses local cached data for checking."""
    
    def __init__(self, cache_dir: Optional[Path] = None):
        """Initialize the local compliance provider.
        
        Args:
            cache_dir: Directory to store cached compliance data
        """
        self._name = "LocalComplianceProvider"
        self._capabilities = {
            ComplianceCapability.LIFECYCLE_STATUS,
            ComplianceCapability.ROHS
        }

        # Default cache directory
        if cache_dir is None:
            cache_dir = Path.home() / ".volta" / "cache" / "compliance"
        self._cache_dir = self._prepare_cache_dir(cache_dir)
        
        # Pre-load some sample data for demonstration purposes
        self._load_sample_data()
    
    @property
    def name(self) -> str:
        """Get the name of this compliance provider."""
        return self._name
    
    @property  
    def capabilities(self) -> Set[ComplianceCapability]:
        """Get the set of compliance capabilities this provider offers."""
        return self._capabilities
    
    async def check_compliance(self, component_data: dict) -> ComplianceReport:
        """Check compliance for a component using local data.
        
        Args:
            component_data: Component data to check
            
        Returns:
            ComplianceReport with results
        """
        # In a real implementation, this would check the actual cached data
        # For now, we'll simulate the compliance checks based on component data
        
        # Extract manufacturer part number for lookups
        mpn = component_data.get('mpn', '') if isinstance(component_data, dict) else ''
        
        # Simulate checking against cached data
        warnings = set()
        errors = set()
        
        # Determine lifecycle status based on some heuristics
        lifecycle_status = self._determine_lifecycle_status(component_data, mpn)
        
        # Check RoHS compliance (simple example)
        rohs_compliant = self._check_rohs_compliance(component_data, mpn)
        
        # Add any warnings or errors based on checks
        if lifecycle_status in [LifecycleStatus.OBSOLETE, LifecycleStatus.EOL, LifecycleStatus.DISCONTINUED]:
            errors.add(f"Component is {lifecycle_status.value.lower()}")
        elif lifecycle_status == LifecycleStatus.NOT_RECOMMENDED:
            warnings.add(f"Component is not recommended for new designs")
            
        return ComplianceReport(
            component_data=component_data,
            lifecycle_status=lifecycle_status,
            rohs_compliant=rohs_compliant,
            warnings=warnings,
            errors=errors
        )
    
    def _determine_lifecycle_status(self, component_data: dict, mpn: str) -> Optional[LifecycleStatus]:
        """Determine the lifecycle status for the component.
        
        In a real implementation, this would lookup the component in the local data.
        For demonstration, we'll use heuristics.
        
        Args:
            component_data: Component data to check
            mpn: Manufacturer part number
            
        Returns:
            Lifecycle status or None if undetermined
        """
        # Sample data - in a real implementation this would come from cache
        if "obsolete" in mpn.lower() or "eol" in mpn.lower():
            return LifecycleStatus.OBSOLETE
        elif "discontinued" in mpn.lower():
            return LifecycleStatus.DISCONTINUED
        elif "notrecommended" in mpn.lower():
            return LifecycleStatus.NOT_RECOMMENDED
        else:
            # Simulate random chance for demo purposes
            import random
            statuses = [LifecycleStatus.ACTIVE, LifecycleStatus.NOT_RECOMMENDED, 
                       LifecycleStatus.OBSOLETE, LifecycleStatus.EOL, LifecycleStatus.DISCONTINUED]
            return random.choice(statuses) if random.random() < 0.3 else LifecycleStatus.ACTIVE
    
    def _check_rohs_compliance(self, component_data: dict, mpn: str) -> Optional[bool]:
        """Check if component is RoHS compliant.
        
        Args:
            component_data: Component data to check
            mpn: Manufacturer part number
            
        Returns:
            True if RoHS compliant, False if not, None if unknown
        """
        # Sample RoHS data lookup
        if "rohs" in mpn.lower():
            return True
        elif "no-rohs" in mpn.lower() or "lead" in mpn.lower():
            return False
        elif "halogen" in mpn.lower() or "sgs" in mpn.lower():
            return False
        else:
            # Randomly determine for demo
            import random
            if random.random() < 0.1:
                return False  # 10% chance of non-compliant
            elif random.random() < 0.2:
                return True  # 10% chance of compliant 
            else:
                return None  # 80% chance unknown
    
    def _load_sample_data(self):
        """Load sample compliance data into cache for demonstration."""
        # This simulates loading data from a real cached database/file
        pass

    @staticmethod
    def _prepare_cache_dir(cache_dir: Path) -> Path:
        """Create a writable cache directory, falling back to temp if needed."""
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
            return cache_dir
        except PermissionError:
            fallback = Path(tempfile.gettempdir()) / "volta" / "cache" / "compliance"
            fallback.mkdir(parents=True, exist_ok=True)
            return fallback
