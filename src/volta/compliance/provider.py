"""Compliance provider protocol and registry for KiCad compliance checking.

This module defines the ComplianceProvider protocol that enables different
compliance checking engines to be plugged into the compliance system.
The registry allows for dynamic discovery and selection of compliance providers.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Set, Optional

# For now, using a generic type instead of specific Component model
# In a real implementation, we'd have a proper Component model
from typing import Any


class ComplianceCapability(str, Enum):
    """Capabilities that a compliance provider can offer."""
    LIFECYCLE_STATUS = "lifecycleStatus"
    ROHS = "rohs"
    SAFETY = "safety"
    QUALITY = "quality"
    ENVIRONMENTAL = "environmental"
    ELECTRICAL = "electrical"


class LifecycleStatus(str, Enum):
    """Lifecycle status of a component."""
    ACTIVE = "active"
    NOT_RECOMMENDED = "notRecommended"
    OBSOLETE = "obsolete"
    EOL = "eol"
    DISCONTINUED = "discontinued"


@dataclass(frozen=True)
class ComplianceReport:
    """Report from a compliance provider for a component."""
    
    component_data: Any
    """The component data this report is for."""
    
    lifecycle_status: Optional[LifecycleStatus] = None
    """Lifecycle status of the component."""
    
    rohs_compliant: Optional[bool] = None
    """Whether the component is RoHS compliant."""
    
    safety_certification: Optional[str] = None
    """Safety certification information."""
    
    quality_rating: Optional[str] = None
    """Quality rating of the component."""
    
    environmental_impact: Optional[str] = None
    """Environmental impact information."""
    
    electrical_specs: Optional[dict] = None
    """Electrical specifications."""
    
    warnings: Set[str] = None
    """Set of compliance warnings."""
    
    errors: Set[str] = None
    """Set of compliance errors."""
    
    def __post_init__(self):
        if self.warnings is None:
            object.__setattr__(self, 'warnings', set())
        if self.errors is None:
            object.__setattr__(self, 'errors', set())


class ComplianceProvider(ABC):
    """Protocol defining the interface for compliance providers.
    
    This protocol allows different compliance checking engines to be used
    interchangeably. All providers must implement these methods to be
    compatible with the compliance system.
    """
    
    @property
    @abstractmethod
    def name(self) -> str:
        """Get the name of this compliance provider."""
        ...
        
    @property
    @abstractmethod
    def capabilities(self) -> Set[ComplianceCapability]:
        """Get the set of compliance capabilities this provider offers."""
        ...
        
    @abstractmethod
    async def check_compliance(self, component_data: Any) -> ComplianceReport:
        """Check compliance for a component.
        
        Args:
            component_data: Component data to check
            
        Returns:
            ComplianceReport with results
            
        Raises:
            Exception: If compliance check fails
        """
        ...


class ComplianceProviderRegistry:
    """Registry for compliance providers.
    
    Maintains a collection of available compliance providers that can be dynamically
    discovered and selected at runtime.
    """
    
    _providers: dict[str, type[ComplianceProvider]] = {}
    _default_provider: Optional[str] = None
    
    @classmethod
    def register(cls, provider_type: str, provider_class: type[ComplianceProvider]) -> None:
        """Register a compliance provider.
        
        Args:
            provider_type: Unique identifier for the provider
            provider_class: Class implementing the ComplianceProvider protocol
        """
        cls._providers[provider_type] = provider_class
        
    @classmethod
    def unregister(cls, provider_type: str) -> None:
        """Unregister a compliance provider.
        
        Args:
            provider_type: Unique identifier for the provider to remove
        """
        if provider_type in cls._providers:
            del cls._providers[provider_type]
            
    @classmethod
    def get_provider(cls, provider_type: str) -> Optional[type[ComplianceProvider]]:
        """Get a registered provider class by type.
        
        Args:
            provider_type: Provider type identifier
            
        Returns:
            Provider class or None if not found
        """
        return cls._providers.get(provider_type)
        
    @classmethod
    def list_providers(cls) -> list[tuple[str, type[ComplianceProvider]]]:
        """List all registered providers.
        
        Returns:
            List of (provider_type, provider_class) tuples for all registered providers
        """
        return [(name, provider_cls) for name, provider_cls in cls._providers.items()]
        
    @classmethod
    def set_default_provider(cls, provider_type: str) -> None:
        """Set the default compliance provider.
        
        Args:
            provider_type: Provider type identifier to set as default
            
        Raises:
            ValueError: If the provider type is not registered
        """
        if provider_type not in cls._providers:
            raise ValueError(f"Provider '{provider_type}' is not registered")
        cls._default_provider = provider_type
        
    @classmethod
    def get_default_provider(cls) -> Optional[type[ComplianceProvider]]:
        """Get the default compliance provider.
        
        Returns:
            Default provider class or None if not set
        """
        if cls._default_provider is None:
            return None
        return cls._providers.get(cls._default_provider)
        
    @classmethod
    async def create_provider(cls, provider_type: str, **kwargs) -> ComplianceProvider:
        """Create an instance of a compliance provider.
        
        Args:
            provider_type: Provider type identifier
            **kwargs: Arguments to pass to the provider constructor
            
        Returns:
            Instance of the requested compliance provider
            
        Raises:
            ValueError: If the provider type is not registered
        """
        provider_class = cls.get_provider(provider_type)
        if provider_class is None:
            raise ValueError(f"Provider '{provider_type}' is not registered")
        return provider_class(**kwargs)
        
    @classmethod
    def is_provider_registered(cls, provider_type: str) -> bool:
        """Check if a provider type is registered.
        
        Args:
            provider_type: Provider type identifier
            
        Returns:
            True if the provider is registered, False otherwise
        """
        return provider_type in cls._providers